"""Build an immutable league plan from candidate libraries and selected RON maps."""
import ctypes
from datetime import datetime, timezone
import errno
import json
import os
from pathlib import Path
import platform
import random
import secrets
import shutil
import subprocess
import tempfile
from .league_schedule import schedule, coverage
from .storage import atomic_json, atomic_text, identifier, read_json, sha, source_file


def publish(stage, out):
    # Never replace even an empty output directory created concurrently.
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.renameat2(-100,os.fsencode(stage),-100,os.fsencode(out),1) != 0:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise ValueError(f'output already exists: {out}')
        raise OSError(code,os.strerror(code),str(out))


def create_league_plan(config_path, out, repeats=None, only=None, match_limit=10000):
    config_path, out = Path(config_path).resolve(), Path(out).absolute()
    cfg = read_json(config_path)
    if not isinstance(cfg,dict) or type(cfg.get('version')) is not int or cfg['version'] != 2:
        raise ValueError('league configuration version must be 2')
    repeats = cfg.get('repeats',1) if repeats is None else repeats
    if type(repeats) is not int or repeats < 1 or type(match_limit) is not int or match_limit < 1:
        raise ValueError('repeats and match limit must be positive integers')
    base = config_path.parent
    runner = source_file(base,cfg.get('runner'),executable=True)
    worker = source_file(runner.parent,'fff-ai-worker',executable=True)
    def item(value, role):
        if not isinstance(value,dict):
            raise ValueError(f'{role} must be an object')
        aid = identifier(value.get('id'))
        name = value.get('name',aid)
        if not isinstance(name,str) or not name:
            raise ValueError('AI name must be nonempty')
        return {'id':aid,'name':name,'source':str(source_file(base,value.get('library'))),
                'path':f'inputs/ais/{aid}.so','role':role}
    if not isinstance(cfg.get('participants'),list) or not cfg['participants']:
        raise ValueError('participants must be a nonempty array')
    ais = [item(v,'participant') for v in cfg['participants']]
    ids = [v['id'] for v in ais]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate participant ID')
    if not isinstance(cfg.get('maps'),list) or not cfg['maps']:
        raise ValueError('maps must be a nonempty array')
    groups = []
    for value in cfg['maps']:
        if not isinstance(value,dict):
            raise ValueError('map entry must be an object')
        gid = identifier(value.get('id'))
        if any(g['id'] == gid for g in groups):
            raise ValueError('duplicate map ID')
        groups.append({'id':gid,'source':str(source_file(base,value.get('map'))), 'path':f'inputs/maps/{gid}.ron'})
    if only is not None:
        if not only or len(set(only)) != len(only) or not set(only) <= {g['id'] for g in groups}:
            raise ValueError('unknown or duplicate map in --only')
        groups = [g for g in groups if g['id'] in only]
    if os.path.lexists(out):
        raise ValueError(f'output already exists: {out}')
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.league-',dir=out.parent) as temporary:
        stage = Path(temporary)/'plan'
        (stage/'inputs/maps').mkdir(parents=True)
        (stage/'inputs/ais').mkdir()
        fingerprints = {key:{'path':str(path),'sha256':sha(path)} for key,path in (('runner',runner),('worker',worker))}
        for g in groups:
            shutil.copyfile(g['source'],stage/g['path'])
            g['sha256'] = sha(stage/g['path'])
            try:
                result = subprocess.run([str(runner),'inspect-map',str(stage/g['path'])],
                                        capture_output=True,text=True,timeout=10,check=False)
                if result.returncode:
                    raise ValueError(result.stderr.strip())
                inspected = json.loads(result.stdout)
                n = inspected['players']
            except (ValueError,KeyError,TypeError,subprocess.TimeoutExpired) as error:
                raise ValueError(f"{g['source']}: map inspection failed: {error}; rebuild release runner if inspect-map is unavailable") from error
            if type(n) is not int or not 2 <= n <= 8:
                raise ValueError('inspected map players must be 2..8')
            g.update(players=n,ais=ids[:])
        missing = max(max(0,g['players']-len(ids)) for g in groups)
        filler_ids = []
        if missing:
            filler = cfg.get('filler')
            if not isinstance(filler,dict):
                raise ValueError('filler library is required when candidates do not fill a map')
            for index in range(missing):
                aid = f'fill-{index}'
                while aid in ids or aid in filler_ids:
                    aid = 'x'+aid
                if len(aid)>64:
                    raise ValueError('unable to allocate filler ID')
                ai = item({**filler,'id':aid},'filler')
                ais.append(ai)
                filler_ids.append(aid)
        designs, total = {}, 0
        for g in groups:
            g['ais'] += filler_ids[:max(0,g['players']-len(ids))]
            rows, method = schedule(len(ids),g['players'],max_rows=match_limit)
            total += len(rows)*repeats
            if total > match_limit:
                raise ValueError(f'league needs at least {total} matches, above limit {match_limit}; increase --match-limit')
            designs[g['id']] = rows
            g['method'] = method
        for a in ais:
            shutil.copyfile(a['source'],stage/a['path'])
            a['sha256'] = sha(stage/a['path'])
        roots = {kind:secrets.randbits(256) for kind in ('engine','ai','schedule')}
        rngs = {kind:random.Random(seed) for kind,seed in roots.items()}
        used = {'engine':set(),'ai':set()}
        def fresh(kind):
            while True:
                seed = rngs[kind].getrandbits(64)
                if seed not in used[kind]:
                    used[kind].add(seed)
                    return seed
        blocks, matches = [],[]
        # Round-major execution lets each completed all-map repetition be usable.
        for repeat in range(repeats):
            for g in groups:
                n = g['players']
                bid = f"{g['id']}-b{repeat:03d}"
                labels, seats = ids[:],list(range(n))
                rngs['schedule'].shuffle(labels)
                labels += g['ais'][len(ids):]
                rngs['schedule'].shuffle(seats)
                block = {'id':bid,'group':g['id'],'repeat':repeat,'engine_seed':fresh('engine'),
                         'ai_seeds':{a:fresh('ai') for a in g['ais']}}
                rows = list(designs[g['id']])
                rngs['schedule'].shuffle(rows)
                realized = []
                for number,row in enumerate(rows):
                    slots = [None]*n
                    for s,a in enumerate(row):
                        slots[seats[s]] = labels[a]
                    realized.append(tuple(g['ais'].index(a) for a in slots))
                    matches.append({'id':f'{bid}-m{number:05d}','group':g['id'],'block':bid,
                                    'slots':slots,'engine_seed':block['engine_seed'],
                                    'ai_seeds':[block['ai_seeds'][a] for a in slots]})
                block['coverage'] = coverage(realized,len(ids),n)
                blocks.append(block)
        for info in fingerprints.values():
            if sha(info['path']) != info['sha256']:
                raise ValueError('runner/worker changed during plan creation')
        plan = {'version':2,'kind':'league','created_utc':datetime.now(timezone.utc).isoformat(),
                **fingerprints,'participants':ids,'ais':ais,'groups':groups,'blocks':blocks,'matches':matches,
                'mode':'balanced','repeats':repeats,'seed_roots':roots,'config':cfg,
                'environment':{'platform':platform.platform(),'logical_cpus':os.cpu_count(),'python':platform.python_version()}}
        atomic_json(stage/'plan.json',plan)
        atomic_text(stage/'plan.sha256',sha(stage/'plan.json')+'\n')
        publish(stage,out)
        return plan
