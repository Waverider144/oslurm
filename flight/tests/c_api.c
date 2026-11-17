#include "oslurm_flight.h"
int main(void) {
    OslurmRequest request = {0};
    OslurmCandidate candidate = {0};
    OslurmDecision result = oslurm_decide(&request, &candidate, 1);
    return result.action == OSLURM_INVALID ? 0 : 1;
}
