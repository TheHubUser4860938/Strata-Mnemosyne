#pragma once
// Boot 4 (2026-11-14): the adapt tier's admission order when the router look-ahead has a vote on the layer.
// The live rule admits the non-resident expert with the highest decayed routing count, which over-represents the
// steady workers; a routing-trace replay (bench/p1/cache_ceiling_2026-11-14.py, 3,630 windows, 4,923 slots) put
// that rule at 0.7220 of the miss stream against Belady's 0.8924, and the arms that moved it were all on the
// INCOMING side: protect the residents the look-ahead expects +0.5 pts, order the victims by next use +0.8,
// pure LRU victims -1.6, and admit what the next window routes **+10.0 pts** at a 16-swap-per-layer cap
// (saturating there: cap 2 +1.9, 4 +6.1, 8 +8.9, 16 +10.0, 32/64/128 +10.2).  So the knob is admission order,
// and its cost is copies: 47 -> 132 swaps/window, 113 -> 318 MiB/window on this box.
//
// The votes are the look-ahead's cross-token consensus for the layer (the arm the stats line reports as
// "votes top12: covers 0.471 of the misses, precision 0.557" on this box tonight) - a near-future signal, not
// clairvoyance, so the offline gain is an upper bound on what the engine can collect.
//
// Pure: the test needs no GPU.  `--adapt-predict 0` (the default) keeps today's order exactly.
#include <algorithm>
#include <cstdint>
#include <utility>
#include <vector>

namespace strata::core {

/// The candidates for one layer, in the order the tier should admit them: the ones the look-ahead voted for
/// first (nearest future use), each group in the live rule's descending-count order, and at most `cap` voted
/// experts in front - the rest fall back into the count order, so a layer with a long vote list keeps the
/// count rule's judgement about the tail.
///
/// `voted[expert]` is non-zero for a voted expert (n_expert bytes, built by the caller from the published
/// list).  `cap` 0 or `voted == nullptr`: the caller's order stands (the live rule).
inline void rank_admission(std::vector<std::pair<float, int32_t>>& cand, const uint8_t* voted, int cap) {
    if (voted == nullptr || cap <= 0 || cand.empty()) return;
    // The live rule's order first, so a stable partition keeps ties as they are.
    std::stable_sort(cand.begin(), cand.end(),
                     [](const std::pair<float, int32_t>& a, const std::pair<float, int32_t>& b) { return a.first > b.first; });
    const auto is_voted = [&](const std::pair<float, int32_t>& c) { return voted[c.second] != 0; };
    const auto mid = std::stable_partition(cand.begin(), cand.end(), is_voted);
    const int n_voted = (int) std::distance(cand.begin(), mid);
    if (n_voted <= cap) return;                       // the whole vote list fits in the front
    // Past the cap, the extra voted experts rejoin the count order rather than crowding out the layer's
    // steady workers: rebuild the tail as (voted[cap:] + non-voted) in descending count.
    std::vector<std::pair<float, int32_t>> tail(cand.begin() + cap, cand.end());
    std::stable_sort(tail.begin(), tail.end(),
                     [](const std::pair<float, int32_t>& a, const std::pair<float, int32_t>& b) { return a.first > b.first; });
    std::move(tail.begin(), tail.end(), cand.begin() + cap);
}

/// How many of the layer's admissions the votes are driving (the round's ledger line, so a sweep is readable
/// in the log without a profiler).
inline int count_voted(const std::vector<std::pair<float, int32_t>>& cand, const uint8_t* voted, int n) {
    if (voted == nullptr) return 0;
    int v = 0;
    for (int i = 0; i < n && i < (int) cand.size(); ++i)
        if (voted[cand[(size_t) i].second] != 0) ++v;
    return v;
}

}  // namespace strata::core
