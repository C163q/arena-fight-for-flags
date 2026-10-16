"""Small participant tests and fixed-opponent version comparisons."""
import argparse
import json
from pathlib import Path
import signal
import sys
from contest_lib.common import read_json
from contest_lib.experiment import prepare_suite,resume_suite


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for name in ('run','compare'):
        p=sub.add_parser(name,help='new frozen development experiment (default: two games per version)')
        p.add_argument('--ai',action='append' if name=='compare' else 'store',required=name=='compare',default=None if name=='compare' else 'submission/libteam.so')
        p.add_argument('--map',dest='maps',type=Path,action='append')
        p.add_argument('--runner',type=Path);p.add_argument('--opponent',type=Path)
        p.add_argument('--out',type=Path,required=True);p.add_argument('--mode',choices=['quick','balanced'],default='quick')
        p.add_argument('--repeats',type=int,default=1);p.add_argument('--jobs',type=int,default=1)
        p.add_argument('--seed-file',type=Path);p.add_argument('--max-matches',type=int);p.add_argument('--match-limit',type=int,default=10000)
    p=sub.add_parser('resume',help='continue frozen inputs, preserving prior concurrency provenance')
    p.add_argument('root',type=Path);p.add_argument('--jobs',type=int,default=1);p.add_argument('--max-matches',type=int)
    args=parser.parse_args()
    def interrupted(_signum,_frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,interrupted)
    try:
        if args.jobs<1 or args.max_matches is not None and args.max_matches<1:raise ValueError('jobs/max-matches must be positive')
        if args.command=='resume':result=resume_suite(args.root,args.jobs,args.max_matches)
        else:
            if args.command=='run':versions=[('candidate',Path(args.ai))]
            else:
                if len(args.ai)<2:raise ValueError('compare requires at least two --ai NAME=PATH versions')
                versions=[]
                for value in args.ai:
                    if '=' not in value:raise ValueError('compare --ai requires NAME=PATH')
                    name,path=value.split('=',1);versions.append((name,Path(path)))
            suite=prepare_suite(versions,args.maps,args.opponent,args.runner,args.out,args.mode,args.repeats,
                                read_json(args.seed_file) if args.seed_file else None,args.match_limit)
            print(f"开发自测：{suite['planned_matches']} 场，{suite['mode']}，重复 {suite['repeats']}，jobs={args.jobs}；正式评测固定1。",flush=True)
            if args.jobs>1:print('并行自测可能增加超时并影响成绩；续跑保留并发来源。',file=sys.stderr,flush=True)
            result=resume_suite(args.out,args.jobs,args.max_matches)
        print(json.dumps({'completed':result['completed_matches'],'planned':result['planned_matches'],'execution':result['execution']},ensure_ascii=False))
        return 0
    except KeyboardInterrupt:
        print('自测已中断，现场保留；使用 selftest.py resume 原目录续跑。',file=sys.stderr);return 130
    except (ValueError,OSError,KeyError,TypeError) as error:
        print(f'自测失败：{error}',file=sys.stderr);return 2


if __name__=='__main__':sys.exit(main())
