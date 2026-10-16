"""Real worker preflight acceptance with small stateless C ABI fixtures."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
SOURCE=r'''
#include "ctf_ai.h"
#include <string.h>
#include <unistd.h>
uint32_t ctf_abi_version(void){return MODE==1?999:1;}
int32_t ctf_create(const CtfInit*init,void**out){(void)init;*out=0;return 0;}
int32_t ctf_decide(void*ctx,const CtfObservation*obs,CtfTeamAction*out){
(void)ctx;(void)obs;
if(MODE==2)_exit(7);
if(MODE==3){volatile unsigned long long value=0;for(;;)value++;}
memset(out,0,sizeof(*out));out->abi_version=1;out->struct_size=sizeof(*out);
for(unsigned i=0;i<3;i++)out->actions[i].unit_id=i;return 0;}
void ctf_destroy(void*ctx){(void)ctx;}
'''


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--bin-dir',type=Path,required=True)
    args=p.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=False);bins=args.bin_dir.resolve()
    source=out/'fixture.c';source.write_text(SOURCE);results=[]
    for mode,name,code,category in [(0,'wait',0,'ok'),(1,'bad-abi',1,'abi_or_symbols'),(2,'crash',1,'crash'),(3,'loop',1,'timeout')]:
        library=out/f'{name}.so'
        subprocess.run(['cc','-std=c11','-O2','-shared','-fPIC',f'-DMODE={mode}','-I',str(ROOT/'include'),str(source),'-o',str(library)],check=True)
        target=out/name
        command=[sys.executable,str(ROOT/'scripts/selftest.py'),'check','--runner',str(bins/'fff-runner'),
                 '--opponent',str(bins/'libfff_bot_baseline.so'),'--ai',str(library),'--out',str(target)]
        r=subprocess.run(command,capture_output=True,text=True,timeout=60)
        (out/f'{name}.stdout.log').write_text(r.stdout);(out/f'{name}.stderr.log').write_text(r.stderr)
        assert r.returncode==code,(name,r.returncode,r.stderr)
        d=json.loads((target/'diagnostics.json').read_text())
        assert d['stages'][0]['passed'],d
        assert d['stages'][1]['category']==category,(name,d)
        for manifest in target.glob('*/matches/*/attempt-*/match/manifest.json'):
            assert json.loads(manifest.read_text())['last_complete_turn']==2
        results.append({'case':name,'exit':r.returncode,'candidate_category':category})
    (out/'acceptance.json').write_text(json.dumps({'passed':True,'cases':results,'probe_games':8,'probe_turns':2},indent=2)+'\n')
    print(json.dumps({'passed':True,'cases':results,'probe_games':8}))


if __name__=='__main__':main()
