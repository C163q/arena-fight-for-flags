"""Streaming public replay metrics; canonical verification precedes analysis."""
from collections import Counter
import hashlib
import os
from pathlib import Path
import stat
import sys
from tournament_lib.reporting import percentiles,md,build_results
from tournament_lib.storage import atomic_json,atomic_text,staged_directory
from .common import ROOT,invoke,log_text,read_object,resolve_runner

sys.path.insert(0,str(ROOT))
from viewer.schema import Validator,integer

MAX_JSON=16*1024*1024
MAX_TOTAL=512*1024*1024
MAX_FRAMES=25000


def file_stat(path):
    st=Path(path).stat(follow_symlinks=False)
    if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1:raise ValueError(f'single-link regular file required: {path}')
    return st


def tree_bytes(root):
    total=0
    for base,dirs,files in os.walk(root,followlinks=False):
        for name in dirs:
            if (Path(base)/name).is_symlink():raise ValueError('symlink directory in records')
        for name in files:total+=file_stat(Path(base)/name).st_size
    return total


def record_inventory(path):
    path=Path(path)
    if path.is_symlink():raise ValueError('symlink record root')
    root=path.resolve(strict=True)
    manifest=read_object(root/'manifest.json',MAX_JSON)
    if manifest.get('format_version')!=1 or manifest.get('status')!='complete':raise ValueError('complete replay required')
    last=integer(manifest.get('last_complete_turn'),1,MAX_FRAMES,'last_complete_turn')
    if (root/'frames').is_symlink():raise ValueError('symlink frames directory')
    expected={f'{i:06d}.json' for i in range(1,last+1)}
    if {p.name for p in (root/'frames').glob('*.json')}!=expected:raise ValueError('missing/extra replay frames')
    frames=[root/'frames'/f'{i:06d}.json' for i in range(1,last+1)]
    files=[root/n for n in ['manifest.json','map.ron','map.json','initial.json','initial.txt','summary.json']]
    for frame in frames:files.extend([frame,frame.with_suffix('.txt')])
    total=0;digest=hashlib.sha256()
    for file in files:
        st=file_stat(file)
        if st.st_size>MAX_JSON:raise ValueError(f'record size limit: {file}')
        if file.suffix=='.json':total+=st.st_size
        digest.update(f'{file.relative_to(root)}:{st.st_dev}:{st.st_ino}:{st.st_size}:{st.st_mtime_ns}:{st.st_ctime_ns}\n'.encode())
    if total>MAX_TOTAL:raise ValueError('replay JSON total size limit')
    return {'root':root,'manifest':manifest,'frames':frames,'files':files,'fingerprint':digest.hexdigest(),'disk_bytes':tree_bytes(root)}


def verify_match(path,runner,logdir):
    inventory=record_inventory(path)
    if invoke([runner,'verify',inventory['root']],logdir,'verify'):
        raise ValueError('replay verification failed: '+log_text(Path(logdir)/'verify.stderr.log'))
    if record_inventory(path)['fingerprint']!=inventory['fingerprint']:raise ValueError('records changed during verification')
    return inventory


def _team(team,label):
    return {'team_id':team,'name':label,'calls':0,'call_statuses':Counter(),'_latency':Counter(),
            'actions':Counter(),'shooting':Counter(),'health':Counter(),
            'flags':{'ground_pickups':0,'spawn_pickups':0,'returns':0},'movement':Counter(),
            'invalid_reasons':Counter(),'examples':{}}


def summarize_match(path,runner,logdir):
    runner=resolve_runner(runner);inventory=verify_match(path,runner,logdir);root=inventory['root']
    game_map=read_object(root/'map.json',MAX_JSON);validator=Validator(game_map);n=validator.players
    initial_record=read_object(root/'initial.json',MAX_JSON)
    if initial_record.get('format_version')!=1:raise ValueError('invalid initial version')
    initial=validator.state(initial_record.get('state'),0,'initial')
    manifest=inventory['manifest'];labels=manifest.get('teams')
    if not isinstance(labels,list) or len(labels)!=n:raise ValueError('manifest team count')
    teams=[_team(i,labels[i].get('name',str(i))) for i in range(n)]
    def example(team,key,turn,event):
        if len(event['event_id'])>256:raise ValueError('event ID too long')
        values=team['examples'].setdefault(key,[])
        if len(values)<3:values.append({'match':str(root),'turn':turn,'event_id':event['event_id']})
    for turn,file in enumerate(inventory['frames'],1):
        try:
            record=read_object(file,MAX_JSON);frame=record.get('frame',{})
            if not isinstance(frame,dict):raise ValueError('expected frame object')
            if record.get('format_version')!=1 or record.get('call_order')!=list(range(n)) or frame.get('turn')!=turn:
                raise ValueError('invalid frame metadata')
            start=validator.state(frame.get('start'),turn,'start');end=validator.state(frame.get('end'),turn,'end')
            calls=record.get('calls')
            if not isinstance(calls,list) or len(calls)!=n:raise ValueError('call count')
            for i,call in enumerate(calls):
                if call.get('team_id')!=i or call.get('turn')!=turn or call.get('status') not in ('ok','timeout','crash','load_error','protocol_error','ai_error'):
                    raise ValueError('invalid call metadata')
                elapsed=integer(call.get('elapsed_us'),0,2**64-1,'elapsed_us')
                teams[i]['calls']+=1;teams[i]['call_statuses'][call['status']]+=1;teams[i]['_latency'][str(elapsed)]+=1
            requested=frame.get('requested')
            if not isinstance(requested,list) or len(requested)!=n:raise ValueError('requested team count')
            for i,row in enumerate(requested):
                if not isinstance(row,list) or len(row)!=3:raise ValueError('requested unit count')
                for u,action in enumerate(row):
                    if not isinstance(action,dict) or not isinstance(action.get('kind'),str):raise ValueError('invalid action object')
                    kind=action['kind'];teams[i]['actions'][kind if kind in ('move','shoot','wait') else 'invalid']+=1
                    if kind=='wait':teams[i]['actions']['alive_wait' if start['units'][i*3+u]['position'] is not None else 'dead_wait']+=1
            events=frame.get('events')
            if not isinstance(events,list) or len(events)>10000:raise ValueError('invalid event count')
            seen=set()
            for index,e in enumerate(events):
                validator.event(e,f'event {index}')
                if e['event_id'] in seen:raise ValueError('duplicate event ID')
                seen.add(e['event_id']);kind=e['type']
                who=e.get('shooter') if kind=='shot' else e.get('unit')
                if who is None:continue  # No private flag scheduler/RNG information is emitted.
                team=teams[who['team_id']]
                if kind=='shot':
                    team['shooting']['attempted']+=1
                    if e['validation']!='ok':
                        team['shooting']['illegal']+=1;team['invalid_reasons'][e['validation']]+=1;key='shot_illegal'
                    else:
                        team['shooting']['legal']+=1;team['shooting'][e['result']]+=1;key='shot_'+e['result']
                        team['shooting']['nominal_damage']+=e['damage']
                        if e.get('hit_unit') is not None and e['hit_unit']['team_id']==who['team_id']:
                            team['shooting']['friendly_hits']+=1
                    example(team,key,turn,e)
                elif kind=='hp_change':
                    if e['after']>e['before']:raise ValueError('hp_change increases HP')
                    team['health']['damage_taken']+=e['before']-e['after']
                elif kind=='death':
                    team['health']['deaths']+=1
                    if start['units'][who['team_id']*3+who['unit_id']]['carrying'] is not None:team['health']['carrying_deaths']+=1
                    example(team,'death',turn,e)
                elif kind=='carry_change' and e['reason'] in ('ground_pickup','spawn_pickup'):
                    team['flags']['ground_pickups' if e['reason']=='ground_pickup' else 'spawn_pickups']+=1
                    example(team,e['reason'],turn,e)
                elif kind=='score':
                    if e['after']<e['before']:raise ValueError('negative score change')
                    team['flags']['returns']+=e['after']-e['before'];example(team,'return',turn,e)
                elif kind=='move':
                    team['movement']['attempted']+=1
                    if e.get('validation')!='ok':
                        key='illegal';team['invalid_reasons'][e.get('validation','unknown')]+=1
                    elif e['result']=='moved':key='moved'
                    elif e['reason'] in ('contested','occupied_or_cycle','killed_before_move'):key=e['reason']
                    else:key='other'
                    team['movement'][key]+=1;example(team,'move_'+key,turn,e)
                elif kind=='action_invalid':
                    team['invalid_reasons'][e.get('reason','invalid_action')]+=1;example(team,'action_invalid',turn,e)
        except (ValueError,KeyError,TypeError,IndexError) as error:
            raise ValueError(f'{file}: {error}') from error
    final=read_object(root/'summary.json',MAX_JSON)
    if final.get('complete') is not True or final.get('turns')!=len(inventory['frames']) or final.get('scores')!=end['scores']:
        raise ValueError('summary differs from final state')
    if record_inventory(root)['fingerprint']!=inventory['fingerprint']:raise ValueError('records changed during analysis')
    for i,team in enumerate(teams):
        hist=team.pop('_latency');team['elapsed_us']={**percentiles(hist),'max':max(map(int,hist),default=0)}
        for key in ('move','shoot','wait','invalid','alive_wait','dead_wait'):team['actions'].setdefault(key,0)
        for key in ('attempted','legal','hit','miss','blocked','illegal','nominal_damage','friendly_hits'):team['shooting'].setdefault(key,0)
        for key in ('damage_taken','deaths','carrying_deaths'):team['health'].setdefault(key,0)
        for key in ('attempted','moved','contested','occupied_or_cycle','killed_before_move','illegal','other'):team['movement'].setdefault(key,0)
        team['shooting']['hit_rate']=team['shooting']['hit']/team['shooting']['legal'] if team['shooting']['legal'] else None
        team['movement']['success_rate']=team['movement']['moved']/team['movement']['attempted'] if team['movement']['attempted'] else None
        team['game_score']=final['scores'][i];team['ai_failures']=sum(v for k,v in team['call_statuses'].items() if k!='ok')
    return {'format':'fff-match-analysis','version':1,'source':str(root),'map_id':game_map['id'],'turns':len(inventory['frames']),
            'verified':True,'teams':teams,'disk_bytes':inventory['disk_bytes']}


def aggregate_candidates(analyses,data):
    result=[]
    for version in data:
        report=build_results(version['plan'],version['rows'])
        for group in report['groups']:
            local=[a for a in analyses if a.get('version_id')==version['id'] and a['map_id']==group['id']]
            if not local:continue
            selected=[a['teams'][a['candidate_team']] for a in local]
            totals=_team(0,version['id']);totals.pop('team_id')
            totals['calls']=sum(t['calls'] for t in selected)
            for key in ('actions','shooting','health','flags','movement','invalid_reasons','call_statuses'):
                merged=Counter()
                for t in selected:merged.update({k:v for k,v in t[key].items() if not k.endswith('_rate')})
                totals[key]=dict(merged)
            hist=Counter()
            for row in version['rows']:
                if row['group']==group['id']:hist.update(row['call_stats'][row['slots'].index('candidate')]['elapsed_histogram'])
            totals.pop('_latency');totals['elapsed_us']={**percentiles(hist),'max':max(map(int,hist),default=0)}
            totals['shooting']['hit_rate']=totals['shooting']['hit']/totals['shooting']['legal'] if totals['shooting']['legal'] else None
            totals['movement']['success_rate']=totals['movement']['moved']/totals['movement']['attempted'] if totals['movement']['attempted'] else None
            for team in selected:
                for key,examples in team['examples'].items():
                    values=totals['examples'].setdefault(key,[]);values.extend(examples[:max(0,3-len(values))])
            ranking=next((x for x in group['standings'] if x['id']=='candidate'),None)
            result.append({'version_id':version['id'],'map_id':group['id'],'role':'candidate','matches':len(local),
                           'complete_blocks':group['complete_blocks'],'ranked_matches':group['ranked_matches'],
                           'score':ranking['score'] if ranking else None,'rank_score':ranking['rank_score'] if ranking else None,
                           'mean_score':sum(t['game_score'] for t in selected)/len(selected),'metrics':totals})
    return result


def write_summary(source,out,runner=None,estimate_matches=None):
    source=Path(source).resolve(strict=True);out=Path(out).absolute()
    if out.resolve().is_relative_to(source):raise ValueError('analysis output must be outside source records')
    if estimate_matches is not None and (type(estimate_matches) is not int or estimate_matches<1):raise ValueError('estimate-matches must be positive')
    runner=resolve_runner(runner)
    with staged_directory(out) as stage:
        analyses=[];scenarios=[];data=[]
        if (source/'suite.json').is_file():
            from .experiment import suite_rows
            data=suite_rows(source,precheck=record_inventory)
            for version in data:
                for row in version['rows']:
                    result=summarize_match(version['root']/row['directory'],runner,stage/f'logs/{version["id"]}/{row["match_id"]}')
                    result['version_id']=version['id'];result['candidate_team']=row['slots'].index('candidate');analyses.append(result)
                scenarios.extend((g['id'],sum(m['group']==g['id'] for m in version['plan']['matches'])) for g in version['plan']['groups'])
        else:analyses=[summarize_match(source,runner,stage/'logs')]
        maps={a['map_id'] for a in analyses}
        if estimate_matches is not None and len(maps)>1:raise ValueError('explicit match estimate requires one map; do not extrapolate across maps')
        bytes_used=tree_bytes(source);records_bytes=sum(a['disk_bytes'] for a in analyses);overhead=max(0,bytes_used-records_bytes)
        estimates={};estimated=overhead
        for mid in maps:
            local=[a for a in analyses if a['map_id']==mid];wanted=estimate_matches or sum(n for m,n in scenarios if m==mid) or len(local)
            size=sum(a['disk_bytes'] for a in local);projected=size*wanted//len(local)
            estimates[mid]={'sample_matches':len(local),'estimated_matches':wanted,'estimated_bytes':projected,'sample_small':len(local)<2}
            estimated+=projected
        missing=sorted({m for m,_ in scenarios}-maps)
        disk={'bytes':bytes_used,'sample_matches':len(analyses),'sample_turns':sum(a['turns'] for a in analyses),
              'mean_bytes_per_match':records_bytes/len(analyses) if analyses else None,
              'mean_bytes_per_turn':records_bytes/sum(a['turns'] for a in analyses) if analyses else None,
              'estimated_matches':estimate_matches or sum(n for _,n in scenarios) or len(analyses),
              'estimated_bytes':estimated if analyses and not missing else None,'by_map':estimates,'missing_sample_maps':missing,
              'note':'同地图样本粗估；算法、局长、事件数量和背景环境不同会改变数据量，不是上界或压缩率承诺。'}
        result={'format':'fff-public-analysis','version':1,'matches':analyses,'candidates':aggregate_candidates(analyses,data),'disk':disk,
                'definitions':{'hit_rate':'合法射击中的命中比例','movement_success_rate':'移动事件中实际移动成功的比例',
                               'nominal_damage':'命中次数对应的名义伤害，包含过量伤害，不是实际扣血或独占击杀',
                               'damage_taken':'hp_change 的 before-after；死亡记受害者，携旗死亡按回合开始携旗状态',
                               'actions':'请求动作包含死棋等待；alive_wait/dead_wait 分列，取消或受阻不等于非法',
                               'flags':'每次拾取/生成即拾取各计一次，重复拾同一面旗也重复计；交回按 score 事件增量',
                               'aggregation':'实验按 candidate 角色汇总，不按出生位编号混入对手；各比率由总分子除总分母'}}
        atomic_json(stage/'summary.json',result)
        lines=['# 公开行为摘要','','仅来自验证通过的完整比赛。未完成换位块可以展示行为统计，但不生成正式排名。',
               '名义命中伤害包含过量伤害；实际承受扣血另列。移动受阻或先死亡取消不算非法。','',
               '| 比赛/版本 | 队伍 | 夺旗分 | 拾旗/生成即携旗/交回 | 命中/名义伤害 | 承受扣血/死亡/携旗死亡 | 移动成功/争格/占格/先死/非法 |','| --- | --- | --- | --- | --- | --- | --- |']
        if result['candidates']:
            lines.extend([''])
            for c in result['candidates']:
                lines.append(f"候选 {c['version_id']} / {c['map_id']}：{c['matches']} 场，完整块 {c['complete_blocks']}，千分制积分 {c['score']}，平均夺旗分 {c['mean_score']:.2f}。")
            lines.append('')
        for a in analyses:
            for t in a['teams']:
                f=t['flags'];s=t['shooting'];h=t['health'];m=t['movement']
                lines.append(f"| {md(a.get('version_id',Path(a['source']).name))} | {t['team_id']} | {t['game_score']} | {f['ground_pickups']}/{f['spawn_pickups']}/{f['returns']} | {s['hit']}/{s['nominal_damage']} | {h['damage_taken']}/{h['deaths']}/{h['carrying_deaths']} | {m['moved']}/{m['contested']}/{m['occupied_or_cycle']}/{m['killed_before_move']}/{m['illegal']} |")
        lines.extend(['',f"当前 {disk['bytes']} 字节，样本 {disk['sample_matches']} 场，粗估 {disk['estimated_matches']} 场：{disk['estimated_bytes']} 字节。",disk['note'],'JSON 含有界代表事件引用和明确的比率分母；样本少于两场时标记 sample_small。',''])
        atomic_text(stage/'summary.md','\n'.join(lines))
    return result
