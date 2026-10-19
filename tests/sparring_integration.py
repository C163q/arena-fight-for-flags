#!/usr/bin/env python3
"""Real-worker maximum-map and regular-turn cold-restart acceptance for sparring AI."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from contest_lib.preflight import probe_ron

SHIM = r'''
#include "ctf_ai.h"
#include <dlfcn.h>
#include <stdlib.h>
#include <unistd.h>
typedef int32_t (*Create)(const CtfInit *, void **);
typedef int32_t (*Decide)(void *, const CtfObservation *, CtfTeamAction *);
typedef void (*Destroy)(void *);
typedef struct { void *lib; void *inner; Decide decide; Destroy destroy; uint32_t restarts; } Context;
uint32_t ctf_abi_version(void) { return CTF_ABI_VERSION; }
int32_t ctf_create(const CtfInit *init, void **output) {
    Context *c = calloc(1, sizeof(*c));
    if (!c) return 1;
    c->lib = dlopen(BOT_LIBRARY, RTLD_NOW | RTLD_LOCAL);
    if (!c->lib) { free(c); return 1; }
    Create create = (Create)dlsym(c->lib, "ctf_create");
    c->decide = (Decide)dlsym(c->lib, "ctf_decide");
    c->destroy = (Destroy)dlsym(c->lib, "ctf_destroy");
    if (!create || !c->decide || !c->destroy || create(init, &c->inner)) {
        dlclose(c->lib); free(c); return 1;
    }
    c->restarts = init->restart_count;
    *output = c; return 0;
}
int32_t ctf_decide(void *context, const CtfObservation *o, CtfTeamAction *out) {
    Context *c = context;
    if (o->turn == 2 && c->restarts == 0) _exit(86);
    return c->decide(c->inner, o, out);
}
void ctf_destroy(void *context) {
    Context *c = context;
    if (c) { c->destroy(c->inner); dlclose(c->lib); free(c); }
}
'''


def maximum_map():
    coordinates = [(52, 52), (56, 52), (60, 52), (52, 56),
                   (60, 56), (52, 60), (56, 60), (60, 60)]
    homes = [dict(team_id=i, x=x, y=y, width=3, height=3)
             for i, (x, y) in enumerate(coordinates)]
    points = []
    for y in range(53, 63):
        for x in range(53, 63):
            if any(h['x'] <= x < h['x']+3 and h['y'] <= y < h['y']+3 for h in homes):
                continue
            if len(points) < 32:
                points.append(dict(id=len(points), x=x, y=y))
    return dict(id='sparring_maximum', players=8, width=128, height=128,
                match_limits=dict(target_score=20, max_turns=6),
                terrain=['#'*128]+['#'+'.'*126+'#']*126+['#'*128],
                spawn_regions=homes, flag_points=points)


def checked(command, out, label):
    with (out / (label+'.stdout')).open('w') as stdout, (out / (label+'.stderr')).open('w') as stderr:
        result = subprocess.run([str(x) for x in command], stdout=stdout, stderr=stderr, timeout=90)
    if result.returncode:
        raise RuntimeError(f'{label} exited {result.returncode}: '+(out/(label+'.stderr')).read_text()[-2000:])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bin-dir', type=Path, default=ROOT/'target/release')
    parser.add_argument('--library', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    binary = args.bin_dir.resolve()
    library = (args.library or binary/'libfff_bot_sparring.so').resolve(strict=True)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    data = maximum_map()
    map_path = out/'maximum.ron'
    map_path.write_text(probe_ron(data).replace('max_turns: 2', 'max_turns: 6'))
    source = out/'restart_shim.c'
    source.write_text('#define BOT_LIBRARY '+json.dumps(str(library))+'\n'+SHIM)
    wrapper = out/'restart_shim.so'
    checked(['cc', '-std=c11', '-O2', '-shared', '-fPIC', '-I', ROOT/'include', source, '-ldl', '-o', wrapper], out, 'compile')
    results = {}
    for phase, ai in [('normal', library), ('restart', wrapper)]:
        match = out/phase
        command = [binary/'fff-runner', '--map', map_path, '--seed', '91003', '--out', match]
        for team in range(8):
            command += ['--ai', ai, '--ai-seed', str(83100+team)]
        checked(command, out, phase)
        checked([binary/'fff-runner', 'verify', match], out, phase+'-verify')
        calls = [call for f in sorted((match/'frames').glob('*.json'))
                 for call in json.loads(f.read_text())['calls']]
        unexpected = [c for c in calls if c['status'] != ('crash' if phase=='restart' and c['turn']==2 else 'ok')]
        summary = json.loads((match/'summary.json').read_text())
        assert not unexpected, (phase, unexpected)
        assert not any(summary['illegal_actions']), summary
        assert summary['ai_failures'] == [1 if phase=='restart' else 0]*8, summary
        recovered = [c for c in calls if c['turn']==3]
        if phase=='restart':
            assert len(recovered)==8 and all(c['restart_count']==1 for c in recovered), recovered
        regular = sorted(c['elapsed_us'] for c in calls if c['turn']>1 and c['status']=='ok')
        results[phase] = dict(calls=len(calls), regular_max_us=max(regular),
                              regular_p99_us=regular[math.ceil(len(regular)*.99)-1],
                              first_max_us=max(c['elapsed_us'] for c in calls if c['turn']==1),
                              cold_restart_max_us=max(c['elapsed_us'] for c in recovered) if phase=='restart' else None)
    (out/'acceptance.json').write_text(json.dumps(results, indent=2)+'\n')
    print(json.dumps(results))


if __name__ == '__main__':
    main()
