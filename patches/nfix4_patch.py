#!/usr/bin/env python3
"""NFIX4: retention-aware lane selection + LRU retained eviction.
Default target /opt/ninfer/src; pass a tree root as argv[1] to patch elsewhere."""
import sys
ROOT = sys.argv[1] if len(sys.argv) > 1 else "/opt/ninfer/src"
F = ROOT + "/src/runtime/engine/concurrent_executor.h"
s = open(F).read()
if "lane_admit_stamps_" in s:
    print("already patched"); sys.exit(0)

old_a = """    [[nodiscard]] std::optional<LaneChoice>
    find_admission_lane(const std::shared_ptr<Request>& request) {
        std::optional<LaneChoice> selected;
        std::uint32_t selected_reuse = 0;
        for (std::uint32_t lane = 0; lane < max_concurrency_; ++lane) {
            if (slots_[lane] != nullptr) { continue; }
            ensure_lane_plan(request, lane);
            const Plan& plan          = *request->lane_plans[lane];
            const std::uint32_t reuse = plan.summary().reusable_prompt_tokens;
            if (instance_.program->can_admit_lane(lane, plan) &&
                (!selected || reuse > selected_reuse)) {
                selected       = LaneChoice{.lane = lane};
                selected_reuse = reuse;
            }
        }
        if (selected) { return selected; }

        for (std::uint32_t lane = 0; lane < max_concurrency_; ++lane) {
            if (slots_[lane] != nullptr) { continue; }
            ensure_lane_plan(request, lane);
            const Plan& plan          = *request->lane_plans[lane];
            const std::uint32_t reuse = plan.summary().reusable_prompt_tokens;
            if (instance_.program->can_admit_lane_after_retained_eviction(lane, plan) &&
                (!selected || reuse > selected_reuse)) {
                selected = LaneChoice{
                    .lane           = lane,
                    .evict_retained = true,
                };
                selected_reuse = reuse;
            }
        }
        return selected;
    }"""
assert s.count(old_a) == 1, "anchor A"
new_a = """    // Retention-aware lane preference. A zero-reuse request must not trample a lane whose
    // retained conversation another client is still extending: order candidate lanes by most
    // reusable tokens, then lanes holding no retained sequence, then the least-recently
    // admitted resident, then lane index for determinism.
    [[nodiscard]] bool prefer_lane(std::uint32_t lane, std::uint32_t reuse,
                                   const std::optional<LaneChoice>& current,
                                   std::uint32_t current_reuse) const noexcept {
        if (!current) { return true; }
        if (reuse != current_reuse) { return reuse > current_reuse; }
        const bool lane_retained    = instance_.program->has_retained_lane(lane);
        const bool current_retained = instance_.program->has_retained_lane(current->lane);
        if (lane_retained != current_retained) { return !lane_retained; }
        if (lane_retained && lane_admit_stamps_[lane] != lane_admit_stamps_[current->lane]) {
            return lane_admit_stamps_[lane] < lane_admit_stamps_[current->lane];
        }
        return false;
    }

    [[nodiscard]] std::optional<LaneChoice>
    find_admission_lane(const std::shared_ptr<Request>& request) {
        std::optional<LaneChoice> selected;
        std::uint32_t selected_reuse = 0;
        for (std::uint32_t lane = 0; lane < max_concurrency_; ++lane) {
            if (slots_[lane] != nullptr) { continue; }
            ensure_lane_plan(request, lane);
            const Plan& plan          = *request->lane_plans[lane];
            const std::uint32_t reuse = plan.summary().reusable_prompt_tokens;
            if (instance_.program->can_admit_lane(lane, plan) &&
                prefer_lane(lane, reuse, selected, selected_reuse)) {
                selected       = LaneChoice{.lane = lane};
                selected_reuse = reuse;
            }
        }
        if (selected) { return selected; }

        for (std::uint32_t lane = 0; lane < max_concurrency_; ++lane) {
            if (slots_[lane] != nullptr) { continue; }
            ensure_lane_plan(request, lane);
            const Plan& plan          = *request->lane_plans[lane];
            const std::uint32_t reuse = plan.summary().reusable_prompt_tokens;
            if (instance_.program->can_admit_lane_after_retained_eviction(lane, plan) &&
                prefer_lane(lane, reuse, selected, selected_reuse)) {
                selected = LaneChoice{
                    .lane           = lane,
                    .evict_retained = true,
                };
                selected_reuse = reuse;
            }
        }
        return selected;
    }"""
s = s.replace(old_a, new_a, 1)

old_b = """        if (choice.evict_retained) {
            for (std::uint32_t retained_lane = 0;
                 retained_lane < max_concurrency_ &&
                 !instance_.program->can_admit_lane(lane, *request->lane_plans[lane]);
                 ++retained_lane) {
                if (retained_lane != lane && slots_[retained_lane] == nullptr &&
                    instance_.program->has_retained_lane(retained_lane)) {
                    instance_.program->evict_retained_lane(retained_lane);
                    invalidate_lane_plans(retained_lane);
                }
            }"""
assert s.count(old_b) == 1, "anchor B"
new_b = """        if (choice.evict_retained) {
            // Reclaim retained lanes least-recently-admitted first, so the most recently
            // active conversation survives the longest.
            while (!instance_.program->can_admit_lane(lane, *request->lane_plans[lane])) {
                std::optional<std::uint32_t> victim;
                for (std::uint32_t retained_lane = 0; retained_lane < max_concurrency_;
                     ++retained_lane) {
                    if (retained_lane == lane || slots_[retained_lane] != nullptr ||
                        !instance_.program->has_retained_lane(retained_lane)) {
                        continue;
                    }
                    if (!victim ||
                        lane_admit_stamps_[retained_lane] < lane_admit_stamps_[*victim]) {
                        victim = retained_lane;
                    }
                }
                if (!victim) { break; }
                instance_.program->evict_retained_lane(*victim);
                invalidate_lane_plans(*victim);
            }"""
s = s.replace(old_b, new_b, 1)

old_c = "    std::array<std::uint64_t, kMaximumConcurrency> lane_plan_versions_{};\n"
assert s.count(old_c) == 1, "anchor C"
s = s.replace(old_c, old_c + "    std::array<std::uint64_t, kMaximumConcurrency> lane_admit_stamps_{};\n    std::uint64_t admit_counter_ = 0;\n", 1)

old_d = """            slots_[lane]                    = request;
            invalidate_lane_plans(lane);"""
assert s.count(old_d) == 1, "anchor D"
s = s.replace(old_d, """            slots_[lane]                    = request;
            lane_admit_stamps_[lane]        = ++admit_counter_;
            invalidate_lane_plans(lane);""", 1)

open(F, "w").write(s)
print("NFIX4_PATCH_OK")
