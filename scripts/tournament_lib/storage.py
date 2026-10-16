"""Validated configuration, immutable inputs, atomic metadata and output locking."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re
import secrets
import shutil
import tempfile
from .schedule import permutations_for, coverage


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise ValueError(f'{path}: {error}') from error


def atomic_text(path, text):
    path = Path(path)
    with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, prefix='.'+path.name, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path, value):
    atomic_text(path, json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for part in iter(lambda: stream.read(1024*1024), b''):
            digest.update(part)
    return digest.hexdigest()


@contextmanager
def locked(root):
    with (Path(root)/'.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError(f'{root}: tournament is locked by another process') from error
        # Close our descriptor on exit, rather than explicitly unlocking the
        # shared open-file description: an inherited child may still be alive.
        yield stream.fileno()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', value):
        raise ValueError('ID must contain 1..64 ASCII letters/digits/underscore/hyphen')
    return value


def source_file(base, value, executable=False):
    if not isinstance(value, str) or not value:
        raise ValueError('file path must be a nonempty string')
    path = (base/value).resolve()
    if not path.is_file() or (executable and not os.access(path, os.X_OK)):
        raise ValueError(f'file missing or not executable: {path}')
    return path


def snapshot_path(root, value):
    path = (Path(root)/value).resolve()
    if not path.is_relative_to(Path(root).resolve()):
        raise ValueError('snapshot path escapes output directory')
    return path


def create_plan(config_path, out, mode=None, repeats=None, only=None):
    config_path, out = Path(config_path).resolve(), Path(out).resolve()
    cfg = read_json(config_path)
    if not isinstance(cfg, dict) or type(cfg.get('version')) is not int or cfg['version'] != 1:
        raise ValueError('configuration version must be 1')
    mode = cfg.get('mode', 'balanced') if mode is None else mode
    repeats = cfg.get('repeats', 5) if repeats is None else repeats
    if mode not in ('balanced', 'quick') or type(repeats) is not int or repeats < 1:
        raise ValueError('mode must be balanced/quick and repeats a positive integer')
    if not isinstance(cfg.get('ais'), list) or not cfg['ais'] or not isinstance(cfg.get('lineups'), list) or not cfg['lineups']:
        raise ValueError('ais and lineups must be nonempty arrays')
    base = config_path.parent
    runner = source_file(base, cfg.get('runner'), executable=True)
    worker = source_file(runner.parent, 'fff-ai-worker', executable=True)
    ais, groups = [], []
    for item in cfg['ais']:
        if not isinstance(item, dict):
            raise ValueError('AI must be an object')
        aid = identifier(item.get('id'))
        if any(ai['id'] == aid for ai in ais):
            raise ValueError(f'duplicate AI ID: {aid}')
        name = item.get('name', aid)
        if not isinstance(name, str) or not name:
            raise ValueError('AI display name must be a nonempty string')
        ais.append({'id':aid, 'name':name, 'source':str(source_file(base, item.get('library'))), 'path':f'inputs/ais/{aid}.so'})
    ids = {a['id'] for a in ais}
    for item in cfg['lineups']:
        if not isinstance(item, dict):
            raise ValueError('lineup must be an object')
        gid = identifier(item.get('id'))
        n, roster = item.get('players'), item.get('ais')
        if any(g['id'] == gid for g in groups):
            raise ValueError(f'duplicate lineup ID: {gid}')
        if type(n) is not int or not 2 <= n <= 8:
            raise ValueError('lineup players must be an integer in 2..8')
        if not isinstance(roster, list) or len(roster) != n or any(not isinstance(a, str) or a not in ids for a in roster) or len(set(roster)) != n:
            raise ValueError('lineup needs N distinct, known AI IDs')
        groups.append({'id':gid, 'players':n, 'ais':roster, 'source':str(source_file(base,item.get('map'))), 'path':f'inputs/maps/{gid}.ron'})
    if only:
        if len(set(only)) != len(only) or not set(only) <= {g['id'] for g in groups}:
            raise ValueError('unknown or duplicate lineup in --only')
        groups = [g for g in groups if g['id'] in only]
    used = {a for g in groups for a in g['ais']}
    ais = [a for a in ais if a['id'] in used]
    if out.exists():
        raise ValueError(f'output already exists: {out}')
    out.mkdir(parents=True)
    (out/'inputs/ais').mkdir(parents=True)
    (out/'inputs/maps').mkdir(parents=True)
    for item in ais + groups:
        shutil.copyfile(item['source'], out/item['path'])
        item['sha256'] = sha(out/item['path'])
    roots = {kind:secrets.randbits(256) for kind in ('engine','ai','schedule')}
    rngs = {kind:random.Random(seed) for kind,seed in roots.items()}
    blocks, matches = [], []
    used_seeds = {'engine':set(), 'ai':set()}

    def fresh(kind):
        while True:
            value = rngs[kind].getrandbits(64)
            if value not in used_seeds[kind]:
                used_seeds[kind].add(value)
                return value

    for group in groups:
        n = group['players']
        for index in range(repeats):
            bid = f"{group['id']}-b{index:03d}"
            block = {'id':bid,'group':group['id'],'engine_seed':fresh('engine'),
                     'ai_seeds':{a:fresh('ai') for a in group['ais']}}
            ai_labels, slot_labels = group['ais'][:], list(range(n))
            rngs['schedule'].shuffle(ai_labels)
            rngs['schedule'].shuffle(slot_labels)
            rows = permutations_for(n, mode)
            rngs['schedule'].shuffle(rows)
            realized = []
            for number, row in enumerate(rows):
                slots = [None]*n
                for i, slot in enumerate(row):
                    slots[slot_labels[slot]] = ai_labels[i]
                realized.append(tuple(slots.index(a) for a in group['ais']))
                matches.append({'id':f'{bid}-m{number:03d}','group':group['id'],'block':bid,
                                'slots':slots,'engine_seed':block['engine_seed'],
                                'ai_seeds':[block['ai_seeds'][a] for a in slots]})
            block['coverage'] = coverage(realized)
            if block['coverage']['single_min'] != block['coverage']['single_max'] or (mode == 'balanced' and (block['coverage']['pair_min'] == 0 or block['coverage']['pair_min'] != block['coverage']['pair_max'])):
                raise ValueError('generated schedule failed balance check')
            blocks.append(block)
    plan = {'version':1,'created_utc':datetime.now(timezone.utc).isoformat(), 'mode':mode,'repeats':repeats,
            'seed_roots':roots,'runner':{'path':str(runner),'sha256':sha(runner)},
            'worker':{'path':str(worker),'sha256':sha(worker)},'ais':ais,'groups':groups,
            'blocks':blocks,'matches':matches,'environment':{'platform':platform.platform(),'logical_cpus':os.cpu_count(),
            'cpu':next((line.split(':',1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')),platform.machine()),
            'python':platform.python_version()},'config':cfg}
    atomic_json(out/'plan.json', plan)
    atomic_text(out/'plan.sha256', sha(out/'plan.json')+'\n')
    return plan


def load_plan(root):
    root = Path(root)
    try:
        if sha(root/'plan.json') != (root/'plan.sha256').read_text().strip():
            raise ValueError('plan fingerprint mismatch')
        plan = read_json(root/'plan.json')
        if plan['version'] not in (1, 2) or (plan['version'] == 2 and plan.get('kind') != 'league'):
            raise ValueError('unsupported plan version')
        for item in plan['ais'] + plan['groups']:
            if sha(snapshot_path(root,item['path'])) != item['sha256']:
                raise ValueError(f"input fingerprint mismatch: {item['path']}")
        for key in ('runner','worker'):
            if sha(plan[key]['path']) != plan[key]['sha256']:
                raise ValueError(f'{key} fingerprint mismatch')
        return plan
    except (OSError, KeyError, TypeError) as error:
        raise ValueError(f'{root}: invalid plan/input: {error}') from error
