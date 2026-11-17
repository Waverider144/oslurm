#include "oslurm_flight.h"
#include <limits.h>

extern "C" int oslurm_cg_advance(OslurmCgState* s, uint32_t budget) {
    if (!s || !s->x || !s->r || !s->p || !s->ap || s->dimension < 2 || s->dimension > OSLURM_CG_MAX_DIMENSION ||
        budget > OSLURM_CG_MAX_QUANTUM ||
        !__builtin_isfinite(s->rr) || s->rr < 0 || !__builtin_isfinite(s->bnorm2) || s->bnorm2 <= 0 ||
        !(s->tolerance > 0 && s->tolerance < 1) || budget > UINT32_MAX-s->iteration) return -1;
    for (uint32_t i=0; i<s->dimension; ++i)
        if (!__builtin_isfinite(s->x[i]) || !__builtin_isfinite(s->r[i]) || !__builtin_isfinite(s->p[i])) return -1;
    for (uint32_t k=0; k<budget && s->rr/s->bnorm2 > s->tolerance*s->tolerance; ++k) {
        double denominator=0;
        for (uint32_t i=0; i<s->dimension; ++i) {
            s->ap[i]=2.0001*s->p[i] - (i ? s->p[i-1] : 0) - (i+1<s->dimension ? s->p[i+1] : 0);
            denominator += s->p[i]*s->ap[i];
        }
        if (!__builtin_isfinite(denominator) || denominator <= 0) return -1;
        const double alpha=s->rr/denominator;
        double rr=0;
        for (uint32_t i=0; i<s->dimension; ++i) {
            s->x[i] += alpha*s->p[i]; s->r[i] -= alpha*s->ap[i]; rr += s->r[i]*s->r[i];
        }
        if (!__builtin_isfinite(rr)) return -1;
        const double beta=rr/s->rr;
        for (uint32_t i=0; i<s->dimension; ++i) s->p[i]=s->r[i]+beta*s->p[i];
        s->rr=rr; ++s->iteration;
    }
    return 0;
}
