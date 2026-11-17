#include "oslurm_flight.h"

/* Call only on telemetry/neighbor/intent updates or the returned lease timer.
 * Board code owns wakeup, clock, resource forecasts and checkpoint transport. */
static OslurmLeaseTable leases;
OslurmDecision flight_on_event(const OslurmRequest* request,
                               const OslurmCandidate* candidates, uint32_t count) {
    oslurm_expire(&leases, request->now_ms);
    return oslurm_decide(request, candidates, count);
}
uint64_t flight_timer_deadline(uint64_t now_ms) {
    return oslurm_next_wake(&leases, now_ms);
}
