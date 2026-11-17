#ifndef OSLURM_FLIGHT_H
#define OSLURM_FLIGHT_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif

#define OSLURM_MAX_CANDIDATES 16
#define OSLURM_LEASE_SLOTS 8
#define OSLURM_CG_MAX_QUANTUM 256
#define OSLURM_CG_MAX_DIMENSION 1048576
enum OslurmAction { OSLURM_LOCAL, OSLURM_REMOTE, OSLURM_DEFER, OSLURM_REJECT, OSLURM_INVALID };
enum OslurmReject { OSLURM_CPU=1, OSLURM_RAM=2, OSLURM_POWER=4, OSLURM_THERMAL=8,
    OSLURM_WINDOW=16, OSLURM_DEADLINE=32, OSLURM_STALE=64, OSLURM_BUSY=128, OSLURM_ACCELERATOR=256 };
typedef struct {
    uint64_t now_ms, deadline_ms, authority_until_ms;
    uint32_t runtime_ms, cpus, ram_mb, reserve_soc_ppm;
    int32_t thermal_limit_mc;
    uint32_t authority_mode, ground_connected, allowed_actions;
} OslurmRequest;
typedef struct {
    uint64_t window_ms, valid_until_ms;
    uint32_t cpus, ram_mb, minimum_soc_ppm;
    int32_t peak_temperature_mc;
    uint32_t migration_ms, is_local, busy, accelerator_ok;
} OslurmCandidate;
typedef struct {
    uint32_t action, selected, rejected[OSLURM_MAX_CANDIDATES];
    int32_t worst_margin_ppm;
} OslurmDecision;
/* Candidates must be sorted by stable node ID. No allocation or OS calls. */
OslurmDecision oslurm_decide(const OslurmRequest*, const OslurmCandidate*, uint32_t count);

typedef struct { uint64_t offer_id, expires_ms; uint32_t state; } OslurmLease;
typedef struct { OslurmLease slots[OSLURM_LEASE_SLOTS]; uint32_t sequence[OSLURM_MAX_CANDIDATES]; } OslurmLeaseTable;
/* Zero initialize the table. source is a provisioned index, sequence strictly increases. */
int oslurm_offer(OslurmLeaseTable*, uint32_t source, uint32_t sequence, uint64_t offer,
                 uint64_t now_ms, uint32_t lease_ms);
int oslurm_commit(OslurmLeaseTable*, uint64_t offer, uint64_t now_ms);
int oslurm_release(OslurmLeaseTable*, uint64_t offer);
void oslurm_expire(OslurmLeaseTable*, uint64_t now_ms);
/* UINT64_MAX means no lease timer is armed; caller may sleep until an event. */
uint64_t oslurm_next_wake(const OslurmLeaseTable*, uint64_t now_ms);

/* Caller owns all five dimension-sized float64 vectors. A=tridiag(-1,2.0001,-1). */
typedef struct {
    double *x, *r, *p, *ap;
    uint32_t dimension, iteration;
    double rr, bnorm2, tolerance;
} OslurmCgState;
/* Returns 0 for a valid step, -1 for invalid/numerically unsafe state. */
int oslurm_cg_advance(OslurmCgState*, uint32_t iteration_budget);
#ifdef __cplusplus
}
#endif
#endif
