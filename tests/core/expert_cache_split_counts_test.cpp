// R4.2g-3: a weighted split on a SIZED cache is a SIZING decision.  `open_sized` lays the slots out in layer
// order - `quota` copies of each layer's own blob - so a band that is not the count the table was built from
// puts a wide layer's blob in a narrow slot, the copy overruns the stride, and long prompts come back with
// non-finite logits (#879, measured 2026-11-15 on the heretic IQ4_NL boot with STRATA_EXPERT_CACHE_SPLIT set).
// Needs a CUDA device (exits 77 without one).
#include "strata/core/expert_cache.hpp"

#include <cuda_runtime.h>

#include <cmath>
#include <cstdio>
#include <cstdint>
#include <string>
#include <vector>

int main() {
    int n = 0;
    if (cudaGetDeviceCount(&n) != cudaSuccess || n == 0) {
        std::puts("no CUDA device: skipped");
        return 77;
    }

    // 1. the spec: a short list repeats its last weight, a long one is cut, the weights average 1
    {
        const auto w = strata::core::ExpertCache::parse_split("1.4,1.4,1.4,1", 8);
        if (w.size() != 8) {
            std::fprintf(stderr, "parse: %zu weights for 8 layers\n", w.size());
            return 1;
        }
        double tot = 0.0;
        for (double x : w) tot += x;
        if (std::fabs(tot - 8.0) > 1e-9) {
            std::fprintf(stderr, "parse: the weights sum to %f, want 8 (mean 1)\n", tot);
            return 1;
        }
        if (!(w[0] > w[7])) {
            std::fprintf(stderr, "parse: 1.4 did not come out heavier than 1\n");
            return 1;
        }
        if (!strata::core::ExpertCache::parse_split("0,abc", 4).empty()) {
            std::fprintf(stderr, "parse: a spec of nothing usable should give no weights\n");
            return 1;
        }
    }

    // 2. the bands: the counts the table was built from, contiguous, and every slot in a band holds that
    //    layer's blob size (a fill and a read-back is the only proof the stride covers it)
    {
        const int64_t sizes[3] = {1024, 2048, 4096};
        const int64_t counts[3] = {4, 2, 2};
        std::vector<int64_t> bytes;
        for (int64_t l = 0; l < 3; ++l)
            for (int64_t s = 0; s < counts[l]; ++s) bytes.push_back(sizes[l]);

        strata::core::ExpertCache cache;
        std::string err;
        if (!cache.open_sized(bytes, 3, 4, err)) {
            // the card is shared with a running host: no room is the device test's skip condition
            std::printf("open_sized: %s\n", err.c_str());
            return 77;
        }
        cache.set_per_layer_admission(true);
        cache.set_layer_counts(std::vector<int64_t>(counts, counts + 3));

        const int64_t want_lo[3] = {0, 4, 6}, want_hi[3] = {4, 6, 8};
        std::vector<uint8_t> blob(4096);
        for (int64_t l = 0; l < 3; ++l) {
            int64_t lo = 0, hi = 0;
            cache.layer_slot_range(l, lo, hi);
            if (lo != want_lo[l] || hi != want_hi[l]) {
                std::fprintf(stderr, "layer %lld: band %lld..%lld, want %lld..%lld\n", (long long) l,
                             (long long) lo, (long long) hi - 1, (long long) want_lo[l],
                             (long long) want_hi[l] - 1);
                return 1;
            }
            for (int64_t e = 0; e < counts[l]; ++e) {
                const int32_t slot = cache.admit(l, e);
                if (slot < (int32_t) lo || slot >= (int32_t) hi) {
                    std::fprintf(stderr, "layer %lld expert %lld admitted slot %d outside its band\n",
                                 (long long) l, (long long) e, slot);
                    return 1;
                }
                std::fill(blob.begin(), blob.end(), (uint8_t) (l * 31 + e + 1));
                if (!cache.fill_slot_blocking(slot, blob.data(), err, sizes[l]) ||
                    !cache.verify_slot(slot, blob.data(), err, sizes[l])) {
                    std::fprintf(stderr, "slot %d (layer %lld, %lld B): %s\n", slot, (long long) l,
                                 (long long) sizes[l], err.c_str());
                    return 1;
                }
            }
        }
    }
    std::puts("expert cache split counts: the spec, the bands and the blob sizes held");
    return 0;
}
