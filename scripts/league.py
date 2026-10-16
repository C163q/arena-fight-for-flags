"""Plan, run/resume and report exact balanced multi-AI, multi-map leagues."""
import argparse
import json
from pathlib import Path
import signal
import sys
from tournament_lib.execution import collect, run
from tournament_lib.league_storage import create_league_plan
from tournament_lib.storage import load_plan, locked


def report(root):
    from tournament_lib.league_reporting import write_reports
    with locked(root) as lock_fd:
        plan = load_plan(root)
        return write_reports(root,plan,collect(root,plan,lock_fd))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    plan = sub.add_parser('plan',help='inspect maps, freeze inputs and print exact schedule size; does not run AI')
    plan.add_argument('--config',type=Path,required=True)
    plan.add_argument('--out',type=Path,required=True)
    plan.add_argument('--repeats',type=int)
    plan.add_argument('--only',nargs='+',help='select map IDs')
    plan.add_argument('--match-limit',type=int,default=10000,help='reject larger exact schedules, never truncate (default: 10000)')
    execute = sub.add_parser('run',help='run/resume; formal evaluation uses jobs=1')
    execute.add_argument('root',type=Path)
    execute.add_argument('--jobs',type=int,default=1)
    execute.add_argument('--max-matches',type=int)
    show = sub.add_parser('report',help='verify original records and rebuild reports')
    show.add_argument('root',type=Path)
    args = parser.parse_args()
    def interrupted(_signum,_frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupted)
    try:
        if args.command == 'plan':
            value = create_league_plan(args.config,args.out,args.repeats,args.only,args.match_limit)
            print(json.dumps({'planned_matches':len(value['matches']),'repeats':value['repeats'],
                'blocks':[{'id':b['id'],**b['coverage']} for b in value['blocks']]},ensure_ascii=False,indent=2))
        else:
            args.root = args.root.resolve()
            if load_plan(args.root)['version'] != 2:
                raise ValueError('use tournament.py for version=1 fixed-roster plans')
            if args.command == 'run':
                if args.jobs > 1:
                    print('并行自测：资源争抢可能增加 AI 超时并改变成绩；正式评测固定 --jobs 1。',file=sys.stderr,flush=True)
                status = run(args.root,args.max_matches,args.jobs)
                print(json.dumps(status))
            value = report(args.root)
            print(f"Report: {args.root}/report.md ({value['completed_matches']}/{value['planned_matches']})")
    except KeyboardInterrupt:
        print('测评已中断，现场已保留；重新运行同一 run 命令可续跑。',file=sys.stderr)
        return 130
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(f'测评失败：{error}',file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
