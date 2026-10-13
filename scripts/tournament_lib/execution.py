"""Serial public-runner execution; recovery always checks original records."""
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time
from .storage import atomic_json, load_plan, locked, read_json, sha


def now():
    return datetime.now(timezone.utc).isoformat()


def command_to_logs(command, directory, prefix):
    """Separate runner session lets interruption stop it without signaling our shell."""
    with (directory/f'{prefix}.stdout.log').open('wb') as stdout, (directory/f'{prefix}.stderr.log').open('wb') as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, start_new_session=True)
        try:
            return process.wait()
        except BaseException:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            raise


def validate_match(root, plan, match, attempt):
    directory = attempt/'match'
    manifest = read_json(directory/'manifest.json')
    group = next(g for g in plan['groups'] if g['id'] == match['group'])
    ais = {ai['id']:ai for ai in plan['ais']}
    try:
        if manifest['status'] != 'complete' or manifest['seed'] != match['engine_seed'] or manifest['config'] != {'flag_respawn_min_turns':5,'flag_respawn_max_turns':15}:
            raise ValueError('seed/status/config')
        if sha(directory/'map.ron') != group['sha256'] or len(manifest['teams']) != len(match['slots']):
            raise ValueError('map/team count')
        for slot, aid in enumerate(match['slots']):
            team, ai = manifest['teams'][slot], ais[aid]
            if team['team_id'] != slot or team['library_sha256'] != ai['sha256'] or team['ai_seed'] != match['ai_seeds'][slot] or Path(team['library_path']).resolve() != (root/ai['path']).resolve():
                raise ValueError('team identity/library/AI seed')
    except (KeyError, TypeError, ValueError, OSError) as error:
        raise ValueError(f'{directory}: input mismatch: {error}') from error
    if command_to_logs([plan['runner']['path'],'verify',str(directory)],attempt,'verify') != 0:
        raise ValueError(f'{directory}: replay verification failed; see {attempt}/verify.stderr.log')
    summary = read_json(directory/'summary.json')
    if summary.get('complete') is not True or any(len(summary.get(k,[])) != group['players'] for k in ('scores','ai_failures','illegal_actions')):
        raise ValueError(f'{directory}: invalid completed summary')
    stats = [{'calls':0,'timeouts':0,'statuses':Counter(),'elapsed_histogram':Counter()} for _ in match['slots']]
    for path in sorted((directory/'frames').glob('*.json')):
        record = read_json(path)
        for call in record['calls']:
            item = stats[call['team_id']]
            item['calls'] += 1
            item['timeouts'] += int(call['status'] == 'timeout')
            item['statuses'][call['status']] += 1
            item['elapsed_histogram'][str(call['elapsed_us'])] += 1
    meta = read_json(attempt/'attempt.json')
    return {'match_id':match['id'],'group':match['group'],'block':match['block'],'slots':match['slots'],
            'engine_seed':match['engine_seed'],'ai_seeds':match['ai_seeds'],
            'summary':summary,'call_stats':stats,'directory':str(directory.relative_to(root)),
            'wall_seconds':meta.get('wall_seconds')}


def collect(root, plan):
    """Caller holds the output lock. Checkpoints are hints, never result authority."""
    root, rows = Path(root).resolve(), []
    for match in plan['matches']:
        parent = root/'matches'/match['id']
        adopted = []
        for attempt in sorted(parent.glob('attempt-*')):
            meta_path = attempt/'attempt.json'
            meta = read_json(meta_path) if meta_path.exists() else {'match_id':match['id'],'state':'running'}
            if meta.get('match_id') != match['id'] or meta.get('state') not in ('running','interrupted','complete','infra_error','invalid'):
                raise ValueError(f'{attempt}: invalid attempt metadata')
            if meta['state'] in ('infra_error','invalid'):
                raise ValueError(f'{attempt}: unresolved infrastructure error: {meta.get("error",meta["state"])}')
            manifest_path = attempt/'match/manifest.json'
            manifest = read_json(manifest_path) if manifest_path.exists() else {}
            complete = manifest.get('status') == 'complete'
            if meta['state'] == 'complete' and not complete:
                raise ValueError(f'{attempt}: completed attempt lost its complete records')
            if complete:
                # Recorder may finish just before orchestrator is killed; adopt after verification.
                if not meta_path.exists():
                    atomic_json(meta_path,meta)
                try:
                    row = validate_match(root,plan,match,attempt)
                except ValueError as error:
                    meta.update(state='invalid',error=str(error))
                    atomic_json(meta_path,meta)
                    raise
                if meta['state'] != 'complete':
                    meta.update(state='complete',recovered_utc=now())
                    atomic_json(meta_path,meta)
                adopted.append(row)
            elif meta['state'] != 'interrupted':
                meta.update(state='interrupted',recovered_utc=now())
                atomic_json(meta_path,meta)
        if len(adopted) > 1:
            raise ValueError(f'{parent}: multiple completed attempts; refusing ambiguous result')
        rows.extend(adopted)
    return rows


def checkpoint(root, plan, rows):
    atomic_json(root/'checkpoint.json',{'version':1,'plan_sha256':sha(root/'plan.json'),'updated_utc':now(),
                'completed':{row['match_id']:row['directory'] for row in rows},'planned':len(plan['matches'])})


def run(root, max_matches=None):
    root = Path(root).resolve()
    if max_matches is not None and (type(max_matches) is not int or max_matches < 1):
        raise ValueError('max-matches must be a positive integer')
    with locked(root):
        plan = load_plan(root)
        rows = collect(root,plan)
        completed = {row['match_id'] for row in rows}
        checkpoint(root,plan,rows)
        new_count = 0
        for match in plan['matches']:
            if match['id'] in completed:
                continue
            if max_matches is not None and new_count >= max_matches:
                break
            load_plan(root)  # Check binary and snapshot fingerprints before each match.
            parent = root/'matches'/match['id']
            parent.mkdir(parents=True,exist_ok=True)
            number = 0
            while (parent/f'attempt-{number:03d}').exists():
                number += 1
            attempt = parent/f'attempt-{number:03d}'
            attempt.mkdir()
            meta = {'match_id':match['id'],'state':'running','started_utc':now()}
            atomic_json(attempt/'attempt.json',meta)
            group = next(g for g in plan['groups'] if g['id'] == match['group'])
            ais = {ai['id']:ai for ai in plan['ais']}
            command = [plan['runner']['path'],'--map',str(root/group['path']),
                       '--out',str(attempt/'match'),'--seed',str(match['engine_seed'])]
            for aid, seed in zip(match['slots'],match['ai_seeds']):
                command += ['--ai',str(root/ais[aid]['path']),'--ai-seed',str(seed)]
            started = time.monotonic()
            try:
                code = command_to_logs(command,attempt,'runner')
                meta['wall_seconds'] = time.monotonic()-started
                atomic_json(attempt/'attempt.json',meta)
                if code:
                    raise ValueError(f'runner exited {code}; see {attempt}/runner.stderr.log')
                row = validate_match(root,plan,match,attempt)
                output = read_json(attempt/'runner.stdout.log')
                if output != row['summary']:
                    raise ValueError('runner stdout differs from recorded summary')
                load_plan(root)
            except KeyboardInterrupt:
                meta.update(state='interrupted',error='execution interrupted',wall_seconds=time.monotonic()-started)
                atomic_json(attempt/'attempt.json',meta)
                raise
            except (ValueError,OSError,KeyError,TypeError) as error:
                meta.update(state='infra_error',error=str(error),wall_seconds=time.monotonic()-started)
                atomic_json(attempt/'attempt.json',meta)
                raise ValueError(f'{attempt}: {error}') from error
            meta.update(state='complete',finished_utc=now())
            atomic_json(attempt/'attempt.json',meta)
            rows.append(row)
            completed.add(match['id'])
            new_count += 1
            checkpoint(root,plan,rows)
            print(f"{len(rows)}/{len(plan['matches'])} {match['id']}: scores={row['summary']['scores']} turns={row['summary']['turns']}",flush=True)
        return {'completed':len(rows),'planned':len(plan['matches']),'new_matches':new_count}
