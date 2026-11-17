#include "oslurm_flight.h"
#include <assert.h>
#include <stdint.h>
#include <stdlib.h>
#include <new>
void* operator new(size_t) { abort(); }
void* operator new[](size_t) { abort(); }
void operator delete(void*) noexcept {}
void operator delete[](void*) noexcept {}
void operator delete(void*, size_t) noexcept {}
void operator delete[](void*, size_t) noexcept {}
int main() {
    OslurmRequest r{100, 10000, 10000, 1000, 1, 32, 300000, 70000, 1, 0, 7};
    OslurmCandidate c[2]{{10000, 10000, 1, 64, 800000, 40000, 0, 1, 0, 1},
                          {10000, 10000, 1, 64, 900000, 30000, 100, 0, 0, 1}};
    assert(oslurm_decide(&r,c,2).action == OSLURM_REMOTE);
    c[1].minimum_soc_ppm=200000;
    assert(oslurm_decide(&r,c,2).action == OSLURM_LOCAL);
    c[0].peak_temperature_mc=80000;
    assert(oslurm_decide(&r,c,2).action == OSLURM_DEFER);
    r.authority_until_ms=99;
    assert(oslurm_decide(&r,c,2).action == OSLURM_REJECT);
    assert(oslurm_decide(&r,c,17).action == OSLURM_INVALID);
    OslurmLeaseTable table{};
    assert(oslurm_next_wake(&table,0)==UINT64_MAX);
    for (uint32_t i=0;i<8;++i) assert(oslurm_offer(&table,i,1,i+1,0,100));
    assert(oslurm_next_wake(&table,0)==100);
    assert(!oslurm_offer(&table,8,1,99,0,100));
    assert(oslurm_commit(&table,1,99));
    assert(!oslurm_commit(&table,1,99));
    assert(!oslurm_commit(&table,2,100));
    assert(oslurm_release(&table,1));
    assert(!oslurm_offer(&table,0,1,1,100,100));
    assert(oslurm_offer(&table,0,2,9,100,100));
    assert(!oslurm_offer(&table,0,3,10,UINT64_MAX-1,100));
    double x[2]{}, p[2]{1,1}, residual[2]{1,1}, ap[2]{};
    OslurmCgState state{x,residual,p,ap,2,0,2,2,1e-8};
    assert(oslurm_cg_advance(&state,2)==0);
    assert(state.iteration==1);
    assert(x[0]>0.999 && x[0]<1);
}
