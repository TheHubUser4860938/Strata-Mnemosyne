// src/core/adapt_predict_test.cpp - the vote-led admission order (boot 4), its cap, and its ties.  No GPU:
// strata::core::rank_admission is a pure function over the tier's candidate list, the same shape
// pcie_share_rule.hpp is tested in.  Build: cmake --build build --target adapt_predict_test && ./build/adapt_predict_test
#include "strata/core/adapt_predict.hpp"

#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

namespace {

int fails = 0;

void CHECK(bool ok, const std::string& what) {
    if (!ok) {
        std::printf("  FAIL: %s\n", what.c_str());
        ++fails;
    }
}

using Cand = std::vector<std::pair<float, int32_t>>;

std::string order(const Cand& c) {
    std::string s;
    for (const auto& p : c) {
        if (!s.empty()) s += ",";
        s += std::to_string(p.second);
    }
    return s;
}

}  // namespace

int main() {
    // The live rule's shape: (decayed count, expert).  Counts descend as the tier's own sort leaves them.
    Cand c{{9.0f, 10}, {7.0f, 11}, {5.0f, 12}, {4.0f, 13}, {3.0f, 14}, {2.0f, 15}};

    // 1. cap 0: today's order, byte for byte.
    {
        Cand v = c;
        const uint8_t mask[16] = {0};
        strata::core::rank_admission(v, mask, 0);
        CHECK(order(v) == "10,11,12,13,14,15", "cap 0 keeps the count order, got " + order(v));
    }
    {
        Cand v = c;
        strata::core::rank_admission(v, nullptr, 16);
        CHECK(order(v) == "10,11,12,13,14,15", "no mask keeps the count order, got " + order(v));
    }

    // 2. The votes lead, and keep the count's order among themselves (a stable partition, not a re-rank).
    {
        Cand v = c;
        std::vector<uint8_t> m(16, 0);
        m[13] = 1; m[15] = 1;                       // the two coldest experts are what the near future routes
        strata::core::rank_admission(v, m.data(), 16);
        CHECK(order(v) == "13,15,10,11,12,14", "votes lead in count order, got " + order(v));
    }

    // 3. An unsorted candidate list is normalised first: the tier sorts by count, the votes go in front of that.
    {
        Cand v{{3.0f, 14}, {9.0f, 10}, {5.0f, 12}};
        std::vector<uint8_t> m(16, 0);
        m[14] = 1;
        strata::core::rank_admission(v, m.data(), 2);
        CHECK(order(v) == "14,10,12", "count-normalised then vote-led, got " + order(v));
    }

    // 4. Past the cap, the extra voted experts rejoin the count order instead of crowding out steady workers.
    {
        Cand v = c;
        std::vector<uint8_t> m(16, 0);
        m[10] = 1; m[12] = 1; m[15] = 1;             // three voted, cap 2: 10 and 12 lead, 15 falls back to last
        strata::core::rank_admission(v, m.data(), 2);
        CHECK(order(v) == "10,12,11,13,14,15", "the cap holds and the tail is count order, got " + order(v));
    }

    // 5. A voted set larger than the list: everything is voted, so the cap is the whole list and the count order
    //    inside each group is all that is left.
    {
        Cand v = c;
        std::vector<uint8_t> m(16, 1);
        strata::core::rank_admission(v, m.data(), 3);
        CHECK(order(v) == "10,11,12,13,14,15", "all-voted with cap 3 is the count order, got " + order(v));
    }

    // 6. Nothing is filtered: the tier's own bar decides, the rule only orders.
    {
        Cand v = c;
        std::vector<uint8_t> m(16, 0);
        m[11] = 1;
        strata::core::rank_admission(v, m.data(), 1);
        CHECK(v.size() == c.size(), "the ranking never drops a candidate");
    }

    // 7. The ledger counts the leaders only, up to the pairs the tier will actually consider.
    {
        Cand v = c;
        std::vector<uint8_t> m(16, 0);
        m[13] = 1; m[15] = 1;
        strata::core::rank_admission(v, m.data(), 16);
        CHECK(strata::core::count_voted(v, m.data(), 2) == 2, "two votes lead the first two pairs");
        CHECK(strata::core::count_voted(v, m.data(), 4) == 2, "the tail is the count rule's");
        CHECK(strata::core::count_voted(v, nullptr, 4) == 0, "no mask, no votes counted");
    }

    if (fails == 0) std::printf("adapt_predict_test: ok\n");
    return fails == 0 ? 0 : 1;
}
