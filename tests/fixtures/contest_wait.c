/* Test-only ABI implementation. Never shipped in participant materials. */
#include "ctf_ai.h"
#include <stddef.h>
_Static_assert(sizeof(CtfInit)==80 && _Alignof(CtfInit)==8, "init layout");
_Static_assert(sizeof(CtfAction)==20 && _Alignof(CtfAction)==4, "action layout");
_Static_assert(sizeof(CtfTeamAction)==68 && _Alignof(CtfTeamAction)==4, "team action layout");
_Static_assert(sizeof(CtfUnit)==40 && _Alignof(CtfUnit)==8, "unit layout");
_Static_assert(sizeof(CtfFlag)==32 && _Alignof(CtfFlag)==8, "flag layout");
_Static_assert(sizeof(CtfHome)==20 && _Alignof(CtfHome)==4, "home layout");
_Static_assert(sizeof(CtfSite)==12 && _Alignof(CtfSite)==4, "site layout");
_Static_assert(sizeof(CtfObservation)==96 && offsetof(CtfObservation,cells)==48, "observation layout");
uint32_t ctf_abi_version(void) { return CTF_ABI_VERSION; }
int32_t ctf_create(const CtfInit *init, void **out) {
    if (!init || !out || init->struct_size != sizeof(*init)) return 1;
    *out = NULL; return 0;
}
int32_t ctf_decide(void *ctx, const CtfObservation *obs, CtfTeamAction *out) {
    (void)ctx;
    if (!obs || !out || obs->struct_size != sizeof(*obs) || obs->unit_count != obs->team_count*3) return 1;
    *out = (CtfTeamAction){.abi_version=1,.struct_size=sizeof(*out)};
    for (uint32_t i=0;i<3;i++) out->actions[i].unit_id=i;
    return 0;
}
void ctf_destroy(void *ctx) { (void)ctx; }
