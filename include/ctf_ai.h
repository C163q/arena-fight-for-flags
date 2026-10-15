#ifndef FFF_CTF_AI_H
#define FFF_CTF_AI_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
#define CTF_ABI_VERSION 1u
#define CTF_TEAM_SIZE 3u
#define CTF_MAX_HP 3u
#define CTF_SHOT_DAMAGE 1u
#define CTF_SHOT_RANGE_MANHATTAN 5u
#define CTF_WAIT 0u
#define CTF_MOVE 1u
#define CTF_SHOOT 2u
#define CTF_UP 0u
#define CTF_DOWN 1u
#define CTF_LEFT 2u
#define CTF_RIGHT 3u
/* cells: 0=floor, 1=wall. Flag state: 0=ground, 1=carried.
 * Borrowed arrays live for one decide call; never free or retain their pointers.
 * All structs use the platform's ordinary C alignment; do not pack them. */
typedef struct {
    uint32_t abi_version, struct_size, team_id, team_count, width, height;
    uint32_t max_turns, target_score, flag_respawn_min_turns, flag_respawn_max_turns;
    uint32_t first_turn, restart_count;
    uint64_t seed;
    /* decision_budget_us is the regular-turn budget (50000us).
     * Match observation.turn == 1 allows 250000us; restarts do not reset it.
     * first_turn is this worker's first served turn, not a new grace period. */
    uint32_t decision_budget_us, initial_flag_count, max_hp, shot_damage, shot_range, respawn_absent_turns;
} CtfInit;
typedef struct {uint32_t unit_id, kind, direction; int32_t target_x, target_y;} CtfAction;
typedef struct {uint32_t abi_version, struct_size; CtfAction actions[3];} CtfTeamAction;
typedef struct {
    uint32_t team_id, unit_id, alive, hp;
    int32_t x,y;
    uint32_t carrying, respawn_at_turn;
    uint64_t flag_id;
} CtfUnit;
typedef struct {
    uint64_t id;
    uint32_t site_id,state;
    int32_t x,y;
    uint32_t carrier_team,carrier_unit;
} CtfFlag;
typedef struct {uint32_t team_id;int32_t x,y;uint32_t width,height;} CtfHome;
typedef struct {uint32_t id;int32_t x,y;} CtfSite;
typedef struct {
    uint32_t abi_version,struct_size,turn,team_id,width,height;
    uint32_t team_count,unit_count,flag_count,site_count,cell_count,reserved;
    const uint8_t *cells;
    const CtfUnit *units;
    const CtfFlag *flags;
    const CtfHome *homes;
    const CtfSite *sites;
    const uint32_t *scores;
} CtfObservation;
uint32_t ctf_abi_version(void);
int32_t ctf_create(const CtfInit *init,void **context_out);
int32_t ctf_decide(void *context,const CtfObservation *observation,CtfTeamAction *output);
void ctf_destroy(void *context);
#ifdef __cplusplus
}
#endif
#endif
