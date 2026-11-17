#include "oslurm_flight.h"
#include <chrono>
#include <stdio.h>
int main() {
    OslurmRequest r{0,1000000,1000000,120000,1,512,300000,70000,1,0,7};
    OslurmCandidate c[16]{};
    for (unsigned i=0;i<16;++i) c[i]={900000,1000000,1,512,800000,40000,i*1000,i==0,0,1};
    const auto start=std::chrono::steady_clock::now();
    uint32_t checksum=0;
    for (unsigned i=0;i<100000;++i) { r.now_ms=i; checksum+=oslurm_decide(&r,c,16).action; }
    const auto ns=std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count();
    printf("{\"platform\":\"host only; not RISC-V WCET/power\",\"decisions\":100000,\"mean_ns\":%lld,\"workspace_bytes\":%zu,\"checksum\":%u}\n",
           static_cast<long long>(ns/100000), sizeof(r)+sizeof(c)+sizeof(OslurmDecision)+sizeof(OslurmLeaseTable), checksum);
}
