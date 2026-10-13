"""Per-lineup statistics using only complete, verified rotation blocks."""
from collections import Counter, defaultdict
import csv
import html
from datetime import datetime, timezone
import io
import random
import re
from .storage import atomic_json, atomic_text, sha

BOOTSTRAP_SEED = 0xFFF20261013


def percentiles(histogram):
    ordered = sorted((int(value),count) for value,count in histogram.items())
    total = sum(count for _,count in ordered)
    result = {}
    for label, percent in [('p50',50),('p95',95),('p99',99)]:
        target, seen, answer = (total-1)*percent//100, 0, None
        for value,count in ordered:
            seen += count
            if seen > target:
                answer = value
                break
        result[label] = answer
    return result


def points(scores, slot):
    value = scores[slot]
    return sum(2 if value > other else 1 if value == other else 0 for i,other in enumerate(scores) if i != slot)


def build_results(plan, rows):
    expected = {m['id']:m for m in plan['matches']}
    seen = set()
    for row in rows:
        mid = row['match_id']
        if mid not in expected or mid in seen or any(row[key] != expected[mid][key] for key in ('group','block','slots')):
            raise ValueError('duplicate or mismatched match result')
        seen.add(mid)
    by_block = defaultdict(list)
    for match in plan['matches']:
        by_block[match['block']].append(match['id'])
    complete = {bid for bid,mids in by_block.items() if set(mids) <= seen}
    names = {a['id']:a['name'] for a in plan['ais']}
    result = {'version':1,'generated_utc':datetime.now(timezone.utc).isoformat(),
              'mode':plan['mode'],'environment':plan['environment'],'bootstrap':{'seed':BOOTSTRAP_SEED,'resamples':2000,'unit':'complete repetition block','minimum_blocks':5},
              'completed_matches':len(rows),'planned_matches':len(plan['matches']), 'groups':[],'matches':rows}
    for group in plan['groups']:
        n, roster = group['players'],group['ais']
        group_rows = [r for r in rows if r['group'] == group['id']]
        ranked = [r for r in group_rows if r['block'] in complete]
        blocks = [b for b in plan['blocks'] if b['group'] == group['id']]
        complete_ids = [b['id'] for b in blocks if b['id'] in complete]
        # Resample whole blocks, with paired indices shared by all AIs.
        block_samples = []
        if len(complete_ids) >= 5:
            rng = random.Random(BOOTSTRAP_SEED)
            block_samples = [[rng.randrange(len(complete_ids)) for _ in complete_ids] for _ in range(2000)]
        output = {'id':group['id'],'players':n,'ais':roster,'map_sha256':group['sha256'],
                  'complete_blocks':len(complete_ids),'planned_blocks':len(blocks),'verified_matches':len(group_rows),
                  'ranked_matches':len(ranked),'pending_blocks':[b['id'] for b in blocks if b['id'] not in complete],
                  'coverage_by_block':{b['id']:b['coverage'] for b in blocks},
                  'ending_reasons':dict(Counter(r['summary']['outcome']['reason'] for r in ranked)),
                  'mean_turns':sum(r['summary']['turns'] for r in ranked)/len(ranked) if ranked else None,
                  'standings':[],'pairwise':{}}
        for aid in roster if ranked else []:
            appearances = [(r,r['slots'].index(aid)) for r in ranked]
            scores = [r['summary']['scores'][slot] for r,slot in appearances]
            point_sum = sum(points(r['summary']['scores'],slot) for r,slot in appearances)
            games = len(appearances)
            sole = sum(r['summary']['outcome']['winners'] == [slot] for r,slot in appearances)
            joint = sum(slot in r['summary']['outcome']['winners'] and len(r['summary']['outcome']['winners']) > 1 for r,slot in appearances)
            hist, statuses = Counter(),Counter()
            for r,slot in appearances:
                hist.update(r['call_stats'][slot]['elapsed_histogram'])
                statuses.update(r['call_stats'][slot]['statuses'])
            block_means = []
            for bid in complete_ids:
                block_pairs = [(r,s) for r,s in appearances if r['block'] == bid]
                block_means.append(sum(points(r['summary']['scores'],s) for r,s in block_pairs)/(len(block_pairs)*2*(n-1)))
            boot = sorted(sum(block_means[i] for i in indices)/len(indices) for indices in block_samples)
            item = {'id':aid,'name':names[aid],'matches':games,'complete_blocks':len(complete_ids),
                    'rank_score':point_sum/(games*2*(n-1)), 'mean_rank':n-point_sum/(games*2),
                    'mean_score':sum(scores)/games,
                    'mean_score_difference':sum(r['summary']['scores'][slot]-max(v for i,v in enumerate(r['summary']['scores']) if i!=slot) for r,slot in appearances)/games,
                    'sole_wins':sole,'sole_win_rate':sole/games,'joint_firsts':joint,'joint_first_rate':joint/games,
                    'first_credit':sum(1/len(r['summary']['outcome']['winners']) if slot in r['summary']['outcome']['winners'] else 0 for r,slot in appearances)/games,
                    'ai_failures':sum(r['summary']['ai_failures'][slot] for r,slot in appearances),
                    'illegal_actions':sum(r['summary']['illegal_actions'][slot] for r,slot in appearances),
                    'calls':sum(r['call_stats'][slot]['calls'] for r,slot in appearances),
                    'timeouts':sum(r['call_stats'][slot]['timeouts'] for r,slot in appearances),
                    'call_statuses':dict(statuses),'elapsed_us':percentiles(hist),
                    'rank_score_ci95':[boot[(len(boot)-1)*25//1000],boot[(len(boot)-1)*975//1000]] if boot else None,
                    'by_slot':[]}
            item['failure_rate'] = item['ai_failures']/item['calls'] if item['calls'] else 0
            item['timeout_rate'] = item['timeouts']/item['calls'] if item['calls'] else 0
            item['illegal_action_rate'] = item['illegal_actions']/(3*item['calls']) if item['calls'] else 0
            for s in range(n):
                local = [(r,slot) for r,slot in appearances if slot == s]
                item['by_slot'].append({'slot':s,'matches':len(local),
                    'mean_score':sum(r['summary']['scores'][s] for r,_ in local)/len(local),
                    'rank_score':sum(points(r['summary']['scores'],s) for r,_ in local)/(len(local)*2*(n-1))})
            output['standings'].append(item)
            output['pairwise'][aid] = {}
            for opponent in roster:
                if opponent == aid:
                    continue
                wins = sum(r['summary']['scores'][s] > r['summary']['scores'][r['slots'].index(opponent)] for r,s in appearances)
                ties = sum(r['summary']['scores'][s] == r['summary']['scores'][r['slots'].index(opponent)] for r,s in appearances)
                output['pairwise'][aid][opponent] = {'wins':wins,'ties':ties,'losses':games-wins-ties}
        standings = output['standings']
        def key(item):
            return (item['rank_score'],item['mean_score'],item['sole_wins'])
        standings.sort(key=lambda item:(-item['rank_score'],-item['mean_score'],-item['sole_wins'],item['id']))
        for index,item in enumerate(standings):
            item['rank'] = standings[index-1]['rank'] if index and key(item)==key(standings[index-1]) else index+1
        result['groups'].append(output)
    return result


def md(value):
    text = html.escape(str(value), quote=False).replace('\r',' ').replace('\n',' ')
    return re.sub(r'([\\`*_{}\[\]()#+.!|~\-])', r'\\\1', text)


def write_reports(root, plan, rows):
    result = build_results(plan,rows)
    result['plan_sha256'] = sha(root/'plan.json')
    atomic_json(root/'results.json',result)
    stream = io.StringIO(newline='')
    fields = ['group','players','rank','id','name','matches','complete_blocks','rank_score','mean_rank','mean_score',
              'mean_score_difference','sole_wins','sole_win_rate','joint_firsts','joint_first_rate','first_credit',
              'ai_failures','timeouts','illegal_actions','failure_rate','timeout_rate','illegal_action_rate']
    writer = csv.DictWriter(stream,fieldnames=fields,extrasaction='ignore')
    writer.writeheader()
    lines = ['# 自动测评结果','',f"模式：{result['mode']}；已验证 {len(rows)}/{len(plan['matches'])} 场。只使用完整换位块排名。",
             f"报告时间：{result['generated_utc']}；计划 SHA-256：`{result['plan_sha256']}`。",'',
             '名次分为战胜对手比例，同分对手计半分；先按平均名次分，再按平均得分、独胜率排序。完全相同则并列。各名单分别比较，不合成全局排名。',
             '两两均衡不能消除三方以上的组合影响。快速模式仅保证单队位置均衡。至少五个完整块才给出按块重采样的描述性 95% 区间；样本较少，不能据此承诺普适显著性。','']
    for group in result['groups']:
        lines += [f"## {group['id']}：{group['players']} 队",'',
                  f"完整块 {group['complete_blocks']}/{group['planned_blocks']}；验证 {group['verified_matches']} 场，排名采用 {group['ranked_matches']} 场。",'']
        if not group['standings']:
            lines += ['暂无正式排名，至少完成一个换位块。','']
            continue
        lines += ['| 名次 | AI | 场次 | 名次分 / 95% 区间 | 平均分 | 平均名次 | 独胜 / 并列第一 | AI 故障 / 超时 / 非法动作 | P50/P95/P99 µs |',
                  '| --- | --- | --- | --- | --- | --- | --- | --- | --- |']
        for item in group['standings']:
            writer.writerow(dict(item,group=group['id'],players=group['players']))
            ci = item['rank_score_ci95']
            interval = f'{ci[0]:.3f}–{ci[1]:.3f}' if ci else '完整块不足 5'
            timing = '/'.join(str(item['elapsed_us'][p]) for p in ('p50','p95','p99'))
            lines.append(f"| {item['rank']} | {md(item['name'])} (`{item['id']}`) | {item['matches']} | {item['rank_score']:.3f} / {interval} | {item['mean_score']:.2f} | {item['mean_rank']:.2f} | {item['sole_wins']} / {item['joint_firsts']} | {item['ai_failures']} / {item['timeouts']} / {item['illegal_actions']} | {timing} |")
        lines += ['', '各出生位平均得分（team_id 顺序）：','']
        for item in group['standings']:
            lines.append(f"- {md(item['name'])}："+'，'.join(f"{s['slot']}位 {s['mean_score']:.2f}分/{s['matches']}场" for s in item['by_slot']))
        lines += ['','混战中的两两成绩：胜/同分/负，以本场最终得分比较，不能解释为单独 1v1 胜率。','',
                  '| AI | '+' | '.join(f'`{aid}`' for aid in group['ais'])+' |',
                  '| --- | '+' | '.join('---' for _ in group['ais'])+' |']
        for aid in group['ais']:
            cells=[]
            for other in group['ais']:
                pair=group['pairwise'][aid].get(other)
                cells.append('/'.join(str(pair[k]) for k in ('wins','ties','losses')) if pair else '—')
            lines.append(f'| `{aid}` | '+' | '.join(cells)+' |')
        lines += ['',f"平均回合：{group['mean_turns']:.1f}；结束原因：`{json_counts(group['ending_reasons'])}`。",'']
    lines += ['## 回放索引','', '完整比赛保存在以下目录；使用项目 `viewer/export.py` 可生成播放器。未完整块的比赛仍列出，但不计入正式排名。','',
              '| 场次 | 块 | 出生位顺序 | 比分 | 比赛目录 |','| --- | --- | --- | --- | --- |']
    for row in rows:
        lines.append(f"| {row['match_id']} | {row['block']} | {', '.join(row['slots'])} | {row['summary']['scores']} | [{row['directory']}]({row['directory']}/) |")
    lines += ['','JSON 保存逐场结果、完整位置覆盖、调用状态与耗时直方图；CSV 为逐名单排名。超时属于 AI 故障的子集，不能把二者相加。非法动作率分母为调用次数乘三。',
              '耗时为裁判侧墙钟时间，包含恢复与 IPC；初始化另计。比赛及各队调用均串行，但系统其他程序仍可能影响耗时。','']
    atomic_text(root/'standings.csv',stream.getvalue())
    atomic_text(root/'report.md','\n'.join(lines))
    return result


def json_counts(counts):
    return ', '.join(f'{key}: {value}' for key,value in sorted(counts.items()))
