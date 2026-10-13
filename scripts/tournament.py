"""Plan, run/resume and report balanced 2–8-team AI tournaments."""
import argparse
import json
from pathlib import Path
import signal
import sys
from tournament_lib.execution import collect, run
from tournament_lib.reporting import write_reports
from tournament_lib.storage import create_plan, load_plan, locked


def report(root):
    with locked(root) as lock_fd:
        plan = load_plan(root)
        return write_reports(root,plan,collect(root,plan,lock_fd))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command',required=True)
    plan = sub.add_parser('plan',help='freeze inputs and generate schedule without running AI')
    plan.add_argument('--config',type=Path,required=True)
    plan.add_argument('--out',type=Path,required=True)
    plan.add_argument('--mode',choices=['balanced','quick'])
    plan.add_argument('--repeats',type=int)
    plan.add_argument('--only',nargs='+',help='select lineup IDs from config')
    execute = sub.add_parser('run',help='run or resume a saved plan serially')
    execute.add_argument('root',type=Path)
    execute.add_argument('--max-matches',type=int,help='stop normally after this many new matches; partial blocks remain unranked')
    show = sub.add_parser('report',help='verify saved matches and rebuild reports without running AI')
    show.add_argument('root',type=Path)
    args = parser.parse_args()
    if hasattr(args,'root'):
        args.root = args.root.resolve()
    def interrupted(_signum, _frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupted)
    try:
        if args.command == 'plan':
            plan = create_plan(args.config,args.out,args.mode,args.repeats,args.only)
            print(json.dumps({'planned_matches':len(plan['matches']),'mode':plan['mode'],'repeats':plan['repeats'],
                             'output':str(args.out.resolve()),'blocks':[{'id':b['id'],**b['coverage']} for b in plan['blocks']]},ensure_ascii=False,indent=2))
        elif args.command == 'run':
            status = run(args.root,args.max_matches)
            report(args.root)
            print(json.dumps(status))
            print(f'Report: {args.root}/report.md')
        else:
            result = report(args.root)
            print(json.dumps({'completed':result['completed_matches'],'planned':result['planned_matches']}))
            print(f'Report: {args.root}/report.md')
    except KeyboardInterrupt:
        print('测评已中断，比赛现场已保留；重新执行同一 run 命令可续跑。',file=sys.stderr)
        return 130
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(f'测评失败：{error}',file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
