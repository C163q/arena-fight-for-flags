"""Candidate-only rankings and equal-map aggregation of complete repetitions."""
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from fractions import Fraction
import io
import random
from .reporting import BOOTSTRAP_SEED, SCORE_SCALE, display_score, md, percentiles, points, score_fields
from .storage import atomic_json, atomic_text, sha


def interval(values):
    if len(values)<5:
        return None
    rng = random.Random(BOOTSTRAP_SEED)
    samples = sorted(sum(values[rng.randrange(len(values))] for _ in values)/len(values) for _ in range(2000))
    return [samples[(len(samples)-1)*25//1000],samples[(len(samples)-1)*975//1000]]


def rank(items, keys):
    # Fractions preserve mathematical ties rather than float addition order.
    items.sort(key=lambda x:(tuple(-v for v in keys[x['id']]),x['id']))
    for i,item in enumerate(items):
        item['rank'] = items[i-1]['rank'] if i and keys[item['id']]==keys[items[i-1]['id']] else i+1


def summarize(aid, name, n, rows, bids):
    games = [(r,r['slots'].index(aid)) for r in rows if aid in r['slots']]
    count = len(games)
    if not count:
        raise ValueError(f'complete block lacks participant {aid}')
    hist,statuses = Counter(),Counter()
    for r,s in games:
        hist.update(r['call_stats'][s]['elapsed_histogram'])
        statuses.update(r['call_stats'][s]['statuses'])
    score_sum = sum(r['summary']['scores'][s] for r,s in games)
    point_sum = sum(points(r['summary']['scores'],s) for r,s in games)
    sole = sum(r['summary']['outcome']['winners']==[s] for r,s in games)
    by_block = {}
    for bid in bids:
        local = [(r,s) for r,s in games if r['block']==bid]
        p = sum(points(r['summary']['scores'],s) for r,s in local)
        by_block[bid] = {'points':p,'denominator':len(local)*2*(n-1),'matches':len(local)}
    item = {'id':aid,'name':name,'matches':count,'complete_blocks':len(bids),
            'rank_score':point_sum/(count*2*(n-1)),'mean_rank':n-point_sum/(count*2),
            'mean_score':score_sum/count,'sole_wins':sole,'sole_win_rate':sole/count,
            'joint_firsts':sum(s in r['summary']['outcome']['winners'] and len(r['summary']['outcome']['winners'])>1 for r,s in games),
            'first_credit':sum(1/len(r['summary']['outcome']['winners']) if s in r['summary']['outcome']['winners'] else 0 for r,s in games)/count,
            'mean_score_difference':sum(r['summary']['scores'][s]-max(v for i,v in enumerate(r['summary']['scores']) if i!=s) for r,s in games)/count,
            'ai_failures':sum(r['summary']['ai_failures'][s] for r,s in games),
            'timeouts':sum(r['call_stats'][s]['timeouts'] for r,s in games),
            'illegal_actions':sum(r['summary']['illegal_actions'][s] for r,s in games),
            'calls':sum(r['call_stats'][s]['calls'] for r,s in games),
            'call_statuses':dict(statuses),'elapsed_us':percentiles(hist),'by_block':by_block,
            'rank_score_ci95':interval([v['points']/v['denominator'] for v in by_block.values()]),'by_slot':[]}
    item['joint_first_rate'] = item['joint_firsts']/count
    for numerator,field,denominator in [('ai_failures','failure_rate',item['calls']),('timeouts','timeout_rate',item['calls']),
                                       ('illegal_actions','illegal_action_rate',3*item['calls'])]:
        item[field] = item[numerator]/denominator if denominator else 0
    for slot in range(n):
        local = [(r,s) for r,s in games if s==slot]
        item['by_slot'].append({'slot':slot,'matches':len(local),
            'mean_score':sum(r['summary']['scores'][s] for r,s in local)/len(local),
            'rank_score':sum(points(r['summary']['scores'],s) for r,s in local)/(len(local)*2*(n-1)),
            'score':display_score(Fraction(sum(points(r['summary']['scores'],s) for r,s in local),len(local)*2*(n-1)))})
    key = (Fraction(point_sum,count*2*(n-1)),Fraction(score_sum,count),Fraction(sole,count))
    item.update(score_fields(key[0],item['rank_score_ci95']))
    return item,key


def build_results(plan, rows):
    if plan.get('version') != 2 or plan.get('kind') != 'league':
        raise ValueError('league report requires a version=2 league plan')
    expected = {m['id']:m for m in plan['matches']}
    seen = set()
    for row in rows:
        mid = row['match_id']
        if mid not in expected or mid in seen or any(row[k]!=expected[mid][k] for k in ('group','block','slots')):
            raise ValueError('duplicate or mismatched match result')
        if type(row.get('execution_jobs',1)) is not int or row.get('execution_jobs',1)<1:
            raise ValueError('invalid execution jobs')
        seen.add(mid)
    jobs = sorted({r.get('execution_jobs',1) for r in rows})
    by_block = defaultdict(set)
    for m in plan['matches']:
        by_block[m['block']].add(m['id'])
    complete = {bid for bid,mids in by_block.items() if mids<=seen}
    names = {a['id']:a['name'] for a in plan['ais']}
    participants = plan['participants']
    result = {'version':2,'kind':'league','score_scale':SCORE_SCALE,'generated_utc':datetime.now(timezone.utc).isoformat(),
        'execution':{'jobs_used':jobs,'classification':'parallel_self_test' if any(j>1 for j in jobs) else 'serial','formal_jobs':1},
        'environment':plan['environment'],'completed_matches':len(rows),'planned_matches':len(plan['matches']),
        'bootstrap':{'seed':BOOTSTRAP_SEED,'resamples':2000,'minimum_blocks':5,'unit':'complete map block / complete all-map repetition'},
        'groups':[],'matches':rows}
    global_repeats = [i for i in range(plan['repeats']) if all(
        any(b['group']==g['id'] and b['repeat']==i and b['id'] in complete for b in plan['blocks']) for g in plan['groups'])]
    for g in plan['groups']:
        blocks = [b for b in plan['blocks'] if b['group']==g['id']]
        bids = [b['id'] for b in blocks if b['id'] in complete]
        ranked = [r for r in rows if r['group']==g['id'] and r['block'] in complete]
        output = {'id':g['id'],'players':g['players'],'participants':participants,'map_sha256':g['sha256'],
            'complete_blocks':len(bids),'planned_blocks':len(blocks),'ranked_matches':len(ranked),
            'verified_matches':sum(r['group']==g['id'] for r in rows),'pending_blocks':[b['id'] for b in blocks if b['id'] not in complete],
            'coverage_by_block':{b['id']:b['coverage'] for b in blocks},'standings':[],'pairwise':{},
            'mean_turns':sum(r['summary']['turns'] for r in ranked)/len(ranked) if ranked else None,
            'ending_reasons':dict(Counter(r['summary']['outcome']['reason'] for r in ranked))}
        keys = {}
        for aid in participants if ranked else []:
            item,keys[aid] = summarize(aid,names[aid],g['players'],ranked,bids)
            output['standings'].append(item)
            output['pairwise'][aid] = {}
            for other in participants:
                if aid==other:
                    continue
                meetings = [r for r in ranked if aid in r['slots'] and other in r['slots']]
                differences = [r['summary']['scores'][r['slots'].index(aid)]-r['summary']['scores'][r['slots'].index(other)] for r in meetings]
                output['pairwise'][aid][other] = {'wins':sum(d>0 for d in differences),'ties':sum(d==0 for d in differences),
                    'losses':sum(d<0 for d in differences),'matches':len(meetings)}
        rank(output['standings'],keys)
        result['groups'].append(output)
    overall = {'complete_repeats':global_repeats,'planned_repeats':plan['repeats'],
               'pending_repeats':[i for i in range(plan['repeats']) if i not in global_repeats],
               'map_weighting':'equal','standings':[]}
    keys = {}
    for aid in participants if global_repeats else []:
        values,by_map,by_map_score,matches = [],{},{},0
        for g,output in zip(plan['groups'],result['groups']):
            item = next(x for x in output['standings'] if x['id']==aid)
            selected = [b for b in plan['blocks'] if b['group']==g['id'] and b['repeat'] in global_repeats]
            local = [item['by_block'][b['id']] for b in selected]
            score = sum((Fraction(v['points'],v['denominator']) for v in local),Fraction())/len(local)
            by_map[g['id']] = float(score)
            by_map_score[g['id']] = display_score(score)
            matches += sum(v['matches'] for v in local)
        for repeat in global_repeats:
            local = []
            for g,output in zip(plan['groups'],result['groups']):
                bid = next(b['id'] for b in plan['blocks'] if b['group']==g['id'] and b['repeat']==repeat)
                v = next(x for x in output['standings'] if x['id']==aid)['by_block'][bid]
                local.append(Fraction(v['points'],v['denominator']))
            values.append(sum(local,Fraction())/len(local))
        value = sum(values,Fraction())/len(values)
        keys[aid] = (value,)
        ci = interval([float(v) for v in values])
        overall['standings'].append({'id':aid,'name':names[aid],'matches':matches,'rank_score':float(value),
            'by_map':by_map,'by_map_score':by_map_score,'complete_repeats':len(global_repeats),'rank_score_ci95':ci,
            **score_fields(value,ci)})
    rank(overall['standings'],keys)
    result['overall'] = overall
    return result


def write_reports(root, plan, rows):
    result = build_results(plan,rows)
    result['plan_sha256'] = sha(root/'plan.json')
    atomic_json(root/'results.json',result)
    classification = result['execution']['classification']
    jobs = ','.join(map(str,result['execution']['jobs_used']))
    lines = ['# 多 AI、多地图测评结果','',f"已验证 {len(rows)}/{len(plan['matches'])} 场；执行：{classification}；jobs：{jobs or '尚无场次'}。",
        '正式评测固定 --jobs 1；含并行场次（包括不完整组）的报告均为自测，串行续跑不清除标记。',
        f"计划 SHA-256：`{result['plan_sha256']}`。",'',
        '主指标为归一化名次分：战胜对手计 1、同分计 0.5，再除以场内对手数，含填充对手。填充队不入榜。',
        '积分与区间采用千分制（满分 1000），四舍五入到整数；排序使用未取整值，显示同分不一定并列。平均夺旗分不缩放。',
        '总榜各地图等权，仅采用所有指定地图均完整的重复组；每图榜可使用该图的其他完整块。两两均衡不保证三方组合公平。',
        '少于 5 个完整统计单位不提供区间；区间为按完整块/全图组重采样的描述性 95% 区间，不保证普适显著性。','']
    stream = io.StringIO(newline='')
    fields = ['execution_classification','execution_jobs_used','scope','group','players','rank','id','name','matches',
              'complete_blocks','complete_repeats','score','rank_score','mean_score','sole_win_rate','ai_failures','timeouts','illegal_actions']
    writer = csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
    writer.writeheader()
    def table(items,scope,group='',players=''):
        if not items:
            lines.extend(['暂无正式排名：尚无完整统计单位。',''])
            return
        lines.extend(['| 名次 | AI | 出场数 | 积分（千分制）| 95% 区间 |','| --- | --- | --- | --- | --- |'])
        for x in items:
            ci = x['score_ci95']
            label = f'{ci[0]}–{ci[1]}' if ci else '完整单位不足 5'
            lines.append(f"| {x['rank']} | {md(x['name'])} (`{x['id']}`) | {x['matches']} | {x['score']} | {label} |")
            writer.writerow(dict(x,scope=scope,group=group,players=players,
                                 execution_classification=classification,execution_jobs_used=jobs))
        lines.append('')
    lines.extend(['## 等权总榜','',f"完整全图重复组：{result['overall']['complete_repeats']}；待完成：{result['overall']['pending_repeats']}。",''])
    table(result['overall']['standings'],'overall')
    for g in result['groups']:
        lines.extend([f"## {g['id']}：{g['players']} 队",'',
            f"完整块 {g['complete_blocks']}/{g['planned_blocks']}；验证 {g['verified_matches']} 场；排名采用 {g['ranked_matches']} 场。",''])
        table(g['standings'],'map',g['id'],g['players'])
        lines.extend(['| AI | 平均游戏分 | 独胜 / 并列第一 | AI 故障 / 超时 / 非法动作 | P50/P95/P99 µs |',
                      '| --- | --- | --- | --- | --- |'])
        for x in g['standings']:
            timing = '/'.join(str(x['elapsed_us'][p]) for p in ('p50','p95','p99'))
            lines.append(f"| `{x['id']}` | {x['mean_score']:.3f} | {x['sole_wins']} / {x['joint_firsts']} | {x['ai_failures']} / {x['timeouts']} / {x['illegal_actions']} | {timing} |")
        lines.extend(['','出生位成绩（team_id：千分制积分 / 场数）：',''])
        for x in g['standings']:
            lines.append(f"- `{x['id']}`："+'，'.join(f"{s['slot']}：{s['score']} / {s['matches']}" for s in x['by_slot']))
        lines.extend(['','混战两两成绩（胜/平/负，括号为同场样本数），不是独立 1v1 胜率：','',
            '| AI | '+' | '.join(f'`{a}`' for a in plan['participants'])+' |',
            '| --- | '+' | '.join('---' for _ in plan['participants'])+' |'])
        for a,pairs in g['pairwise'].items():
            cells = []
            for b in plan['participants']:
                p = pairs.get(b)
                cells.append(f"{p['wins']}/{p['ties']}/{p['losses']} ({p['matches']})" if p else '—')
            lines.append(f'| `{a}` | '+' | '.join(cells)+' |')
        lines.extend(['','精确均衡检查（按完整计划，不代表全部已执行）：','',
            '| 块 | 场数 | 每队出场 | 每位置 | 每候选对同场 | 每有序位置对 |',
            '| --- | --- | --- | --- | --- | --- |'])
        for bid,c in g['coverage_by_block'].items():
            lines.append(f"| {bid} | {c['matches']} | {c['appearances_min']} | {c['seat_min']} | {c['pair_min']} | {c['pair_seat_min']} |")
        lines.append('')
    lines.extend(['## 回放索引','','未完整块仍保留明细，但不参与正式排名。用 viewer/export.py 导出所需比赛。','',
        '| 场次 | 出生位队伍 | 比分 | 比赛目录 |','| --- | --- | --- | --- |'])
    for r in rows:
        lines.append(f"| {r['match_id']} | {', '.join(r['slots'])} | {r['summary']['scores']} | [{r['directory']}]({r['directory']}/) |")
    lines.extend(['','JSON 另存完整调用统计、出生位成绩、地图权重和重复组状态；CSV 同时含地图榜与总榜。超时属于 AI 故障的子集。',''])
    atomic_text(root/'standings.csv',stream.getvalue())
    atomic_text(root/'report.md','\n'.join(lines))
    return result
