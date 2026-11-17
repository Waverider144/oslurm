#include "oslurm_flight.h"
#include <limits.h>

static uint32_t ratio(uint64_t numerator, uint64_t denominator) {
    return numerator >= denominator ? 1000000U : static_cast<uint32_t>(numerator * 1000000U / denominator);
}

extern "C" OslurmDecision oslurm_decide(const OslurmRequest* request,
                                        const OslurmCandidate* candidates, uint32_t count) {
    OslurmDecision out{};
    out.action = OSLURM_INVALID;
    out.selected = UINT32_MAX;
    if (!request || !candidates || count == 0 || count > OSLURM_MAX_CANDIDATES) return out;
    const OslurmRequest& r = *request;
    if (!r.runtime_ms || !r.cpus || !r.ram_mb || r.reserve_soc_ppm > 1000000 ||
        r.thermal_limit_mc < 1000 || r.thermal_limit_mc > 2000000 || r.authority_mode > 2 ||
        r.ground_connected > 1 || r.allowed_actions > 7) return out;
    for (uint32_t i=0; i<count; ++i) {
        const auto& c = candidates[i];
        if (c.minimum_soc_ppm > 1000000 || c.peak_temperature_mc < -273150 ||
            c.peak_temperature_mc > 2000000 || c.is_local > 1 || c.busy > 1 || c.accelerator_ok > 1) return out;
    }
    out.action = OSLURM_REJECT;
    if ((r.authority_mode == 0 && !r.ground_connected) ||
        (r.authority_mode == 1 && r.now_ms > r.authority_until_ms)) return out;
    uint64_t best_duration=0, best_migration=0, best_energy=0;
    uint32_t best_margin=0;
    for (uint32_t i=0; i<count; ++i) {
        const auto& c = candidates[i];
        const uint64_t migration = c.is_local ? 0 : c.migration_ms;
        const uint64_t duration = r.runtime_ms + migration;
        uint32_t mask=0;
        if (c.cpus < r.cpus) mask |= OSLURM_CPU;
        if (c.ram_mb < r.ram_mb) mask |= OSLURM_RAM;
        if (c.minimum_soc_ppm < r.reserve_soc_ppm) mask |= OSLURM_POWER;
        if (c.peak_temperature_mc > r.thermal_limit_mc) mask |= OSLURM_THERMAL;
        if (c.window_ms < duration) mask |= OSLURM_WINDOW;
        if (r.deadline_ms < r.now_ms || r.deadline_ms - r.now_ms < duration) mask |= OSLURM_DEADLINE;
        if (!c.is_local && c.valid_until_ms < r.now_ms) mask |= OSLURM_STALE;
        if (c.busy) mask |= OSLURM_BUSY;
        if (!c.accelerator_ok) mask |= OSLURM_ACCELERATOR;
        out.rejected[i] = mask;
        if (mask) continue;
        uint32_t margin = ratio(r.deadline_ms - r.now_ms - duration, r.runtime_ms);
        const uint32_t energy_margin = ratio(c.minimum_soc_ppm - r.reserve_soc_ppm,
            1000000 - r.reserve_soc_ppm < 10000 ? 10000 : 1000000 - r.reserve_soc_ppm);
        const uint32_t thermal_margin = ratio(static_cast<uint32_t>(r.thermal_limit_mc - c.peak_temperature_mc), r.thermal_limit_mc);
        const uint32_t window_margin = ratio(c.window_ms - duration, duration);
        if (energy_margin < margin) margin = energy_margin;
        if (thermal_margin < margin) margin = thermal_margin;
        if (window_margin < margin) margin = window_margin;
        const uint64_t energy = static_cast<uint64_t>(r.runtime_ms) * (1000000 - c.minimum_soc_ppm);
        if (out.selected == UINT32_MAX || margin > best_margin ||
            (margin == best_margin && (duration < best_duration ||
             (duration == best_duration && (migration < best_migration ||
              (migration == best_migration && energy < best_energy)))))) {
            out.selected=i; best_margin=margin; best_duration=duration; best_migration=migration; best_energy=energy;
        }
    }
    if (out.selected == UINT32_MAX) { out.action = r.allowed_actions & 4 ? OSLURM_DEFER : OSLURM_REJECT; return out; }
    const bool local = candidates[out.selected].is_local != 0;
    out.action = (r.allowed_actions & (local ? 1 : 2)) ? (local ? OSLURM_LOCAL : OSLURM_REMOTE) : OSLURM_DEFER;
    out.worst_margin_ppm=static_cast<int32_t>(best_margin);
    return out;
}

extern "C" void oslurm_expire(OslurmLeaseTable* table, uint64_t now) {
    if (!table) return;
    for (auto& slot : table->slots) if (slot.state == 1 && now >= slot.expires_ms) slot.state=0;
}
extern "C" int oslurm_offer(OslurmLeaseTable* t, uint32_t source, uint32_t sequence, uint64_t offer,
                             uint64_t now, uint32_t lease) {
    if (!t || source >= OSLURM_MAX_CANDIDATES || !offer || !lease || sequence <= t->sequence[source] || UINT64_MAX-now < lease) return 0;
    oslurm_expire(t, now);
    for (const auto& slot : t->slots) if (slot.state && slot.offer_id == offer) return 0;
    for (auto& slot : t->slots) if (!slot.state) {
        slot={offer, now+lease, 1}; t->sequence[source]=sequence; return 1;
    }
    return 0;
}
extern "C" int oslurm_commit(OslurmLeaseTable* t, uint64_t offer, uint64_t now) {
    if (!t) return 0;
    oslurm_expire(t, now);
    for (auto& slot : t->slots) if (slot.offer_id == offer && slot.state == 1) { slot.state=2; return 1; }
    return 0;
}
extern "C" int oslurm_release(OslurmLeaseTable* t, uint64_t offer) {
    if (!t) return 0;
    for (auto& slot : t->slots) if (slot.offer_id == offer && slot.state == 2) { slot.state=0; return 1; }
    return 0;
}
extern "C" uint64_t oslurm_next_wake(const OslurmLeaseTable* t, uint64_t now) {
    uint64_t wake=UINT64_MAX;
    if (!t) return wake;
    for (const auto& slot : t->slots) if (slot.state == 1 && slot.expires_ms < wake) wake=slot.expires_ms;
    return wake < now ? now : wake;
}
