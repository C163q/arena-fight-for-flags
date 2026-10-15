/* Internal timing probe, not an AI strategy or participant example. */
#define _POSIX_C_SOURCE 200809L
#include "ctf_ai.h"
#include <stdint.h>
#include <time.h>
#ifndef PROBE_CPU_NS
#define PROBE_CPU_NS 35000000ULL
#endif
static uint64_t cpu_ns(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &t)) return UINT64_MAX;
    return (uint64_t)t.tv_sec*1000000000ULL+(uint64_t)t.tv_nsec;
}
uint32_t ctf_abi_version(void) { return CTF_ABI_VERSION; }
int32_t ctf_create(const CtfInit *init, void **out) {
    if (!init || !out || init->struct_size != sizeof(*init)) return 1;
    *out = 0; return 0;
}
int32_t ctf_decide(void *ctx, const CtfObservation *obs, CtfTeamAction *out) {
    (void)ctx;
    if (!obs || !out || obs->struct_size != sizeof(*obs)) return 1;
    uint64_t start=cpu_ns();
    if (start==UINT64_MAX) return 2;
    volatile uint64_t work=1;
    for (;;) {
        for (int i=0;i<1024;i++) work=work*1664525ULL+1013904223ULL;
        uint64_t current=cpu_ns();
        if (current==UINT64_MAX) return 2;
        if (current-start>=PROBE_CPU_NS) break;
    }
    *out=(CtfTeamAction){.abi_version=CTF_ABI_VERSION,.struct_size=sizeof(*out)};
    for (uint32_t i=0;i<3;i++) out->actions[i].unit_id=i;
    return 0;
}
void ctf_destroy(void *ctx) { (void)ctx; }
