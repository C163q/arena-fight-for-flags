"""Short real-worker control/candidate checks, never an AI loader in the controller."""
import json
from pathlib import Path
from tournament_lib.execution import run,collect
from tournament_lib.seeds import make_seed_spec
from tournament_lib.storage import atomic_json,atomic_text,create_plan,load_plan,locked,sha,staged_directory
from .common import ROOT,freeze,inspect_map,log_text,read_json,regular,resolve_runner,resolve_opponent


def probe_ron(data):
    def structures(items,fields):
        return '['+','.join('('+','.join(f'{key}: {item[key]}' for key in fields)+')' for item in items)+']'
    return '\n'.join(['(format_version: 1,',f'id: {json.dumps(data["id"])}, players: {data["players"]},',
        f'width: {data["width"]}, height: {data["height"]},',
        f'match_limits: (target_score: {data["match_limits"]["target_score"]}, max_turns: 2),',
        'terrain: ['+','.join(json.dumps(row) for row in data['terrain'])+'],',
        'spawn_regions: '+structures(data['spawn_regions'],['team_id','x','y','width','height'])+',',
        'flag_points: '+structures(data['flag_points'],['id','x','y'])+',)'])+'\n'


def category(phase,statuses,errors):
    text=' '.join(errors).lower()
    if phase=='environment' and any(s in text for s in ['operation not permitted','permission denied','eperm']):
        return 'environment_permissions'
    for status,result in [('timeout','timeout'),('crash','crash'),('protocol_error','protocol'),('ai_error','ai_return_error')]:
        if status in statuses:return result
    if any(s in text for s in ['abi','symbol']):return 'abi_or_symbols'
    if any(s in text for s in ['elf','shared object','permission']):return 'library_load'
    return 'initialization_or_load'


def _check_phase(root,phase):
    plan_root=root/('control' if phase=='environment' else 'candidate')
    try:
        run(plan_root,max_matches=1,jobs=1)
        plan=load_plan(plan_root)
        with locked(plan_root) as fd:row=collect(plan_root,plan,fd)[0]
        team=row['slots'].index('candidate')
        chosen=list(range(len(row['slots']))) if phase=='environment' else [team]
        records=[];directory=plan_root/row['directory']
        for path in sorted((directory/'frames').glob('*.json')):
            records.extend(read_json(path)['calls'][i] for i in chosen)
        statuses=sorted({c['status'] for c in records})
        errors=list(dict.fromkeys(c['error'] for c in records if c.get('error')))
        stderr=log_text(directory.parent/'runner.stderr.log')
        if stderr:errors.append(stderr)
        passed=bool(records) and statuses==['ok']
        opponent_failure=phase=='candidate' and any(row['summary']['ai_failures'][i] for i in range(len(row['slots'])) if i!=team)
        kind='ok' if passed else category(phase,statuses,errors)
        if opponent_failure:passed=False;kind='opponent_failure'
        return {'phase':phase,'passed':passed,'category':kind,'statuses':statuses,'errors':errors,
                'illegal_actions':sum(row['summary']['illegal_actions'][i] for i in chosen),
                'calls':len(records),'max_elapsed_us':max((c['elapsed_us'] for c in records),default=0),
                'match':str(directory.relative_to(root))}
    except (ValueError,OSError,KeyError,TypeError) as error:
        errors=[str(error)]
        for path in sorted(plan_root.glob('matches/*/attempt-*/runner.stderr.log')):
            detail=log_text(path)
            if detail:errors.append(detail)
        kind=category(phase,[],errors)
        return {'phase':phase,'passed':False,'category':kind if kind=='environment_permissions' else 'infrastructure','statuses':[],'errors':errors,
                'illegal_actions':0,'calls':0}


def check_ai(ai,runner,baseline,map_path,out):
    runner=resolve_runner(runner);baseline=resolve_opponent(baseline,runner);ai=regular(ai)
    map_path=map_path or ROOT/'maps/arena_2p.ron'
    out=Path(out).absolute()
    with staged_directory(out) as stage:
        original=stage/'original.ron';freeze(map_path,original);data=inspect_map(runner,original)
        probe=stage/'probe.ron';probe.write_text(probe_ron(data));data=inspect_map(runner,probe)
        if data['match_limits']['max_turns']!=2:raise ValueError('probe map must have exactly two turns')
        base=stage/'frozen/baseline.so';base_info=freeze(baseline,base)
        candidate=stage/'frozen/candidate.so';ai_info=freeze(ai,candidate)
        mid=data['id'];n=data['players']
        seeds=make_seed_spec([{'id':mid,'players':n,'sha256':sha(probe)}],1)
        for name,library in [('control',base),('candidate',candidate)]:
            ais=[{'id':'candidate','name':name,'library':str(library)}]
            ais += [{'id':f'opponent_{i}','library':str(base)} for i in range(1,n)]
            cfg={'version':1,'runner':str(runner),'repeats':1,'mode':'quick','ais':ais,
                 'lineups':[{'id':mid,'players':n,'map':str(probe),'ais':[a['id'] for a in ais]}]}
            path=stage/f'{name}.json';atomic_json(path,cfg);plan_root=stage/name
            plan=create_plan(path,plan_root,seed_spec=seeds)
            for a in plan['ais']:a['source']=str(ai if name=='candidate' and a['id']=='candidate' else baseline)
            plan['groups'][0]['source']=str(out/'probe.ron')
            atomic_json(plan_root/'plan.json',plan);atomic_text(plan_root/'plan.sha256',sha(plan_root/'plan.json')+'\n')
        atomic_json(stage/'inputs.json',{'candidate':ai_info,'baseline':base_info,'original_map':str(Path(map_path).resolve()),'probe_turns':2})
    with locked(out):
        stages=[_check_phase(out,'environment')]
        if stages[0]['passed']:stages.append(_check_phase(out,'candidate'))
        result={'format':'fff-preflight','version':1,'passed':len(stages)==2 and all(s['passed'] for s in stages),
                'stages':stages,'strength_test':False}
        atomic_json(out/'diagnostics.json',result)
        lines=['# 运行环境与 AI 接入预检','','仅验证私有两回合局面，不是强度成绩，不保证其他局面必不超时。','']
        for stage in stages:
            lines.extend([f"## {stage['phase']}: {stage['category']}",'',
                          f"通过：{stage['passed']}；调用：{stage['calls']}；游戏非法动作：{stage['illegal_actions']}。",''])
            lines.extend('    '+line for error in stage['errors'] for line in error.splitlines())
            lines.append('')
        if stages[0]['category']=='environment_permissions':
            lines.extend(['当前环境可能不允许所需的 worker/IPC/信号操作，请场外人员检查隔离配置；本工具不会自动扩大权限。',''])
        atomic_text(out/'report.md','\n'.join(lines))
    return result
