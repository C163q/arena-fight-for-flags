"""Internal reproducible cross-match contention probe; never a formal AI ranking."""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import time
from tournament_lib.execution import command_to_logs
from tournament_lib.reporting import percentiles
from tournament_lib.storage import atomic_json

ROOT=Path(__file__).resolve().parents[1]


def assess_capacity(rows, levels, passes):
    if not levels or levels[0]!=1 or any(type(j) is not int or not 1<=j<=16 for j in levels):
        raise ValueError('probe jobs must include 1 and stay within 1..16 matches')
    indexed={(r['profile'],r['pass'],r['jobs']):r for r in rows}
    expected={(profile,p,j) for profile in ('baseline','cpu35') for p in range(passes) for j in levels}
    if len(indexed)!=len(rows) or set(indexed)!=expected:
        raise ValueError('missing or duplicate capacity measurements')
    output=[]
    for jobs in levels:
        reasons=[]
        for p in range(passes):
            for profile in ('baseline','cpu35'):
                row=indexed[profile,p,jobs]
                if row['faults'] or row['illegal_actions']:
                    reasons.append(f'{profile} pass{p}: faults or illegal actions')
            row,serial=indexed['cpu35',p,jobs],indexed['cpu35',p,1]
            for key,ratio in (('p95',1.10),('p99',1.20)):
                if row['regular_us'][key]>serial['regular_us'][key]*ratio:
                    reasons.append(f'cpu35 pass{p}: {key} exceeds serial x{ratio}')
        output.append({'jobs':jobs,'passed':not reasons,'reasons':reasons})
    maximum=None
    for row in output:
        if not row['passed']:
            break
        maximum=row['jobs']
    return {'measured_max_jobs':maximum,'levels':output,'criteria':{'extra_faults':0,'p95_serial_ratio':1.10,'p99_serial_ratio':1.20}}


def machine():
    data={'logical_cpus':os.cpu_count(),'affinity':sorted(os.sched_getaffinity(0)),
          'platform':platform.platform(),'loadavg':os.getloadavg(),'python':platform.python_version()}
    data['cpuinfo']=Path('/proc/cpuinfo').read_text().split('\n\n')[0]
    data['meminfo']=Path('/proc/meminfo').read_text()
    data['cgroup']=Path('/proc/self/cgroup').read_text()
    data['cpu_max']={str(p):p.read_text().strip() for p in Path('/sys/fs/cgroup').glob('**/cpu.max') if p.is_file()}
    return data


def measure(root, jobs, profile, pass_number, started):
    result=json.loads((root/'results.json').read_text())
    regular,first=Counter(),Counter()
    faults,timeouts,illegal,calls=0,0,0,0
    for row in result['matches']:
        faults+=sum(row['summary']['ai_failures'])
        illegal+=sum(row['summary']['illegal_actions'])
        for path in (root/row['directory']/'frames').glob('*.json'):
            frame=json.loads(path.read_text())
            for call in frame['calls']:
                calls+=1
                timeouts+=call['status']=='timeout'
                (first if frame['frame']['turn']==1 else regular)[str(call['elapsed_us'])]+=1
    return {'profile':profile,'pass':pass_number,'jobs':jobs,'matches':len(result['matches']),
            'wall_seconds':time.monotonic()-started,'faults':faults,'timeouts':timeouts,'illegal_actions':illegal,
            'calls':calls,'regular_calls':sum(regular.values()),'regular_us':percentiles(regular),
            'regular_histogram':dict(regular),'first_us':percentiles(first),'root':str(root)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--bin-dir',type=Path,default=ROOT/'target/release')
    parser.add_argument('--jobs',type=int,nargs='+',default=[1,2,4,6,8,10,12,16])
    parser.add_argument('--passes',type=int,default=2)
    parser.add_argument('--turns',type=int,default=24)
    args=parser.parse_args()
    levels=sorted(set(args.jobs))
    if not levels or levels[0]!=1 or any(j>16 for j in levels) or args.passes<1 or args.turns<2:
        parser.error('include jobs 1, limited to 1..16 matches; positive passes and turns >=2 required')
    out,bins=args.out.resolve(),args.bin_dir.resolve()
    out.mkdir(parents=True,exist_ok=False)
    before=machine()
    fixture=out/'fixtures';fixture.mkdir()
    probe=fixture/'cpu35.so'
    subprocess.run(['cc','-std=c11','-O2','-shared','-fPIC','-Werror','-I',str(ROOT/'include'),
                    str(ROOT/'tests/fixtures/ctf_cpu_probe.c'),'-o',str(probe)],check=True)
    source=(ROOT/'maps/arena_8p.ron').read_text()
    source,count=re.subn(r'max_turns: \d+',f'max_turns: {args.turns}',source)
    if count!=1:raise ValueError('expected one match limit')
    map_path=fixture/'probe_8p.ron';map_path.write_text(source)
    configs={}
    for profile,library in [('baseline',bins/'libfff_bot_baseline.so'),('cpu35',probe)]:
        cfg={'version':1,'runner':str(bins/'fff-runner'),'mode':'quick','repeats':2,
             'ais':[{'id':f'bot{i}','library':str(library)} for i in range(8)],
             'lineups':[{'id':'probe','players':8,'map':str(map_path),'ais':[f'bot{i}' for i in range(8)]}]}
        configs[profile]=fixture/f'{profile}.json';atomic_json(configs[profile],cfg)
    rows=[]
    started=time.monotonic()
    for p in range(args.passes):
        for jobs in (levels if p%2==0 else list(reversed(levels))):
            for profile in ('baseline','cpu35'):
                directory=out/f'pass{p}-{profile}-j{jobs}';directory.mkdir()
                root=directory/'tournament'
                plan=[os.sys.executable,str(ROOT/'scripts/tournament.py'),'plan','--config',str(configs[profile]),'--out',str(root)]
                if command_to_logs(plan,directory,'plan'):
                    raise ValueError(f'{directory}: plan failed')
                tick=time.monotonic()
                command=[os.sys.executable,str(ROOT/'scripts/tournament.py'),'run',str(root),'--jobs',str(jobs)]
                if command_to_logs(command,directory,'run'):
                    raise ValueError(f'{directory}: execution failed')
                row=measure(root,jobs,profile,p,tick);rows.append(row)
                atomic_json(out/'measurements.json',{'before':before,'rows':rows})
                print(json.dumps({k:v for k,v in row.items() if k not in ('regular_histogram','root')}),flush=True)
    result={'before':before,'after':machine(),'rows':rows,'assessment':assess_capacity(rows,levels,args.passes),
            'total_seconds':time.monotonic()-started,'turns':args.turns,'passes':args.passes,
            'probe_cpu_ns':35000000,'formal_jobs':1}
    atomic_json(out/'acceptance.json',result)
    print(json.dumps(result['assessment']),flush=True)


if __name__=='__main__':
    main()
