"""Small, frozen candidate-vs-opponent experiments and controlled version comparisons."""
from contextlib import contextmanager,ExitStack
import json
import os
from pathlib import Path
from tournament_lib.execution import run,collect
from tournament_lib.reporting import write_reports,md
from tournament_lib.schedule import permutations_for
from tournament_lib.seeds import make_seed_spec,validate_seed_spec
from tournament_lib.storage import atomic_json,atomic_text,create_plan,identifier,load_plan,locked,sha,snapshot_path,staged_directory
from .common import ROOT,freeze,inspect_map,regular,resolve_runner,resolve_opponent,read_json


def prepare_suite(versions,maps,opponent,runner,out,mode='quick',repeats=1,seed_spec=None,match_limit=10000):
    if mode not in ('quick','balanced') or type(repeats) is not int or repeats<1:
        raise ValueError('invalid mode/repeats')
    if type(match_limit) is not int or match_limit<1:raise ValueError('match-limit must be positive')
    if not versions or len({v[0] for v in versions})!=len(versions):raise ValueError('versions must be nonempty and unique')
    versions=[(identifier(name),regular(path)) for name,path in versions]
    maps=maps or [ROOT/'maps/arena_2p.ron']
    runner=resolve_runner(runner);worker=regular(runner.parent/'fff-ai-worker',True)
    opponent=resolve_opponent(opponent,runner)
    programs={'runner':{'path':str(runner),'sha256':sha(runner)},'worker':{'path':str(worker),'sha256':sha(worker)}}
    with staged_directory(out) as stage:
        frozen=[];map_entries=[];sources={};seen=set()
        foe=stage/'inputs/opponent.so';info=freeze(opponent,foe);frozen.append({'path':str(foe.relative_to(stage)),**info})
        for index,path in enumerate(maps):
            copied=stage/f'inputs/maps/map-{index}.ron';info=freeze(path,copied);data=inspect_map(runner,copied)
            mid=data['id']
            if mid in seen:raise ValueError(f'duplicate map ID: {mid}')
            seen.add(mid);sources[mid]=info['source']
            map_entries.append({'id':mid,'players':data['players'],'sha256':info['sha256'],'path':str(copied.relative_to(stage))})
            frozen.append({'path':str(copied.relative_to(stage)),**info})
        planned=sum(len(permutations_for(m['players'],mode))*repeats for m in map_entries)*len(versions)
        if planned>match_limit:raise ValueError(f'{planned} matches exceeds match-limit {match_limit}')
        seeds=make_seed_spec(map_entries,repeats) if seed_spec is None else seed_spec
        validate_seed_spec(seeds,map_entries,repeats)
        atomic_json(stage/'seeds.json',seeds)
        entries=[]
        for name,source in versions:
            copied=stage/f'inputs/versions/{name}.so';info=freeze(source,copied)
            frozen.append({'path':str(copied.relative_to(stage)),**info})
            ais=[{'id':'candidate','name':name,'library':str(copied)}]
            ais += [{'id':f'opponent_{i}','name':f'固定对手 {i}','library':str(foe)} for i in range(1,max(m['players'] for m in map_entries))]
            groups=[{'id':m['id'],'players':m['players'],'map':str(stage/m['path']),
                     'ais':['candidate']+[f'opponent_{i}' for i in range(1,m['players'])]} for m in map_entries]
            config={'version':1,'runner':str(runner),'mode':mode,'repeats':repeats,'ais':ais,'lineups':groups}
            cfg=stage/f'config-{name}.json';atomic_json(cfg,config)
            plan_root=stage/f'versions/{name}'
            plan=create_plan(cfg,plan_root,seed_spec=seeds)
            # Correct provenance before the immutable suite is published; runtime uses snapshots.
            for ai in plan['ais']:ai['source']=str(source if ai['id']=='candidate' else opponent)
            for group in plan['groups']:group['source']=sources[group['id']]
            for ai in config['ais']:ai['library']=str(source if ai['id']=='candidate' else opponent)
            for group in config['lineups']:group['map']=sources[group['id']]
            plan['config']=config;atomic_json(cfg,config)
            atomic_json(plan_root/'plan.json',plan);atomic_text(plan_root/'plan.sha256',sha(plan_root/'plan.json')+'\n')
            entries.append({'id':name,'plan':f'versions/{name}','library_sha256':info['sha256'],'source':str(source)})
        if sha(runner)!=programs['runner']['sha256'] or sha(worker)!=programs['worker']['sha256']:
            raise ValueError('runner/worker changed during preparation')
        suite={'format':'fff-selftest','version':1,'purpose':'development_self_test','versions':entries,'maps':map_entries,
               'mode':mode,'repeats':repeats,'planned_matches':planned,'frozen_inputs':frozen,**programs}
        atomic_json(stage/'suite.json',suite);atomic_text(stage/'suite.sha256',sha(stage/'suite.json')+'\n')
    return suite


def load_suite(root):
    root=Path(root).resolve(strict=True)
    if sha(root/'suite.json')!=(root/'suite.sha256').read_text().strip():raise ValueError('suite fingerprint mismatch')
    suite=read_json(root/'suite.json')
    if suite.get('format')!='fff-selftest' or type(suite.get('version')) is not int or suite['version']!=1:
        raise ValueError('unsupported selftest suite')
    for entry in suite['frozen_inputs']:
        if sha(snapshot_path(root,entry['path']))!=entry['sha256']:raise ValueError('suite input fingerprint mismatch')
    names=set()
    for entry in suite['versions']:
        identifier(entry['id'])
        if entry['id'] in names:raise ValueError('duplicate suite version')
        names.add(entry['id']);load_plan(snapshot_path(root,entry['plan']))
    if not names:raise ValueError('empty suite')
    return suite


@contextmanager
def locked_suite(root):
    """Archive/analysis holds every inner lock, including after a controller dies."""
    root=Path(root).resolve()
    with ExitStack() as stack:
        stack.enter_context(locked(root));suite=load_suite(root);fds={}
        for version in suite['versions']:
            fds[version['id']]=stack.enter_context(locked(snapshot_path(root,version['plan'])))
        yield suite,fds


def suite_rows(root):
    root=Path(root).resolve()
    with locked_suite(root) as (suite,fds):
        return [{'id':v['id'],'root':snapshot_path(root,v['plan']),'plan':load_plan(snapshot_path(root,v['plan'])),
                 'rows':collect(snapshot_path(root,v['plan']),load_plan(snapshot_path(root,v['plan'])),fds[v['id']])} for v in suite['versions']]


def _write_suite_report(root,suite,data):
    jobs=sorted({r['execution_jobs'] for v in data for r in v['rows']})
    result={'format':'fff-selftest-results','version':1,'purpose':'development_self_test',
            'planned_matches':suite['planned_matches'],'completed_matches':sum(len(v['rows']) for v in data),
            'execution':{'jobs_used':jobs,'classification':'parallel_self_test' if any(j>1 for j in jobs) else 'serial'},'versions':[]}
    lines=['# 开发自测版本对照','','各版本分别面对固定对手；这不是正式同场排名。积分采用千分制，平均夺旗分不缩放。',
           f'并发来源 jobs：{jobs}；正式评测固定 jobs=1。','',
           '| 版本 | 地图 | 完整块 | 已验证场次 | 积分 | 平均夺旗分 | 故障/超时/非法 |','| --- | --- | --- | --- | --- | --- | --- |']
    for v in data:
        report=write_reports(v['root'],v['plan'],v['rows'])
        result['versions'].append({'id':v['id'],'completed_matches':len(v['rows']),'planned_matches':len(v['plan']['matches']),'groups':report['groups']})
        for g in report['groups']:
            candidate=next((x for x in g['standings'] if x['id']=='candidate'),None)
            fields=[str(candidate['score']),f"{candidate['mean_score']:.2f}",f"{candidate['ai_failures']}/{candidate['timeouts']}/{candidate['illegal_actions']}"] if candidate else ['未完整块','—','—']
            lines.append(f"| {md(v['id'])} | {g['id']} | {g['complete_blocks']}/{g['planned_blocks']} | {g['verified_matches']} | "+' | '.join(fields)+' |')
    atomic_json(root/'results.json',result);atomic_text(root/'report.md','\n'.join(lines)+'\n')
    return result


def resume_suite(root,jobs=1,max_matches=None):
    root=Path(root).resolve()
    if type(jobs) is not int or jobs<1:raise ValueError('jobs must be positive')
    if max_matches is not None and (type(max_matches) is not int or max_matches<1):raise ValueError('max-matches must be positive')
    with locked(root):
        suite=load_suite(root)
        # Never bypass an active inner cleanup just because the outer controller died.
        for version in suite['versions']:
            with locked(snapshot_path(root,version['plan'])):pass
        remaining=max_matches
        for version in suite['versions']:
            if remaining==0:break
            status=run(snapshot_path(root,version['plan']),remaining,jobs)
            if remaining is not None:remaining-=status['new_matches']
        data=[]
        for version in suite['versions']:
            plan_root=snapshot_path(root,version['plan']);plan=load_plan(plan_root)
            with locked(plan_root) as fd:rows=collect(plan_root,plan,fd)
            data.append({'id':version['id'],'root':plan_root,'plan':plan,'rows':rows})
        return _write_suite_report(root,suite,data)
