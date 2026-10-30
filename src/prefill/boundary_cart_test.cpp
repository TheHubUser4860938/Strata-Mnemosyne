// src/prefill/boundary_cart_test.cpp - the decision half of STRATA_BOUNDARY_CAPTURE (memory-core, 2026-10-29).
//
// Pure policy, no device and no file IO, so the rule that decides WHICH read donates its boundary rows -
// and which positions inside it - is checked without a GPU, the way the graft lever is
// (src/core/conversation_graft_test.cpp).  The environment is read by BoundaryCapture::process() at run time
// and is deliberately not exercised here: a static that caches the environment once per process cannot be
// re-asked inside one test binary, so the cases construct the struct and set the fields they test.
//
// What these checks protect, in one line each: the default path (nothing runs, nothing is printed), the
// skip-don't-fail rule that lets a probe sit beside a serving box's own traffic, the in-order rule that
// keeps two prompts' rows from landing in one file, and the byte arithmetic that the whole bank claim of
// include/strata/prefill/boundary_cart.hpp is built on.

#include "strata/prefill/boundary_cart.hpp"
#include "strata/core/geometry.hpp"

#include <algorithm>
#include <cstdio>
#include <cstdlib>

using strata::prefill::BoundaryCapture;
using strata::core::ModelGeometry;
using strata::core::is_qsa_layer;

namespace {
int checks = 0;
void check(bool value, const char* description) {
    ++checks;
    if (!value) { std::fprintf(stderr, "FAIL: %s\n", description); std::exit(1); }
}

// A capture as the probe would build it after reading its environment: on, boundary 12, one body to 4096
// positions - the shape the owner chose on 2026-10-29 (tuned, not faithful: "we running a different model
// than what he was testing").
BoundaryCapture probe() {
    BoundaryCapture c;
    c.on = true;
    c.dir = "/tmp/bndy-probe";
    return c;
}

const char* why(const BoundaryCapture& c, int64_t pos0, int64_t n, int64_t lb = 0, int64_t le = -1,
                bool pictures = false, bool* routine = nullptr) {
    return c.decline(pos0, n, lb, le, (int64_t) ModelGeometry{}.n_layers, pictures, routine);
}
}  // namespace

int main() {
    const BoundaryCapture off;   // nothing in the environment: this is every box that never heard of CUT3

    // C1 - the default-path guard.  Unset, the probe declines, and a run must not print or write a thing.
    // This is the check that fails the moment the hook is reached for unconditionally.
    check(!off.on, "an unset STRATA_BOUNDARY_CAPTURE leaves the probe off");
    check(why(off, 0, 1000) != nullptr, "off: the read declines");
    check(why(off, 0, 1000)[0] != '\0', "off: and the reason is a sentence, not an empty string");
    check(!off.wants(BoundaryCapture::kBoundaryLayerDefault), "off: no layer is ever wanted");

    const BoundaryCapture c = probe();

    // C2 - the shape the probe is for: a cold, whole-trunk, picture-free read of body length.
    check(why(c, 0, 1369) == nullptr, "a cold body-length read is captured");
    check(c.wants(12), "the tuned boundary (12) is the layer whose input is taken");
    check(!c.wants(11) && !c.wants(13), "and exactly one layer is: its neighbours are not");
    check(!c.wants(0), "layer 0 is not the boundary, so the embedding stage is never tapped");

    // C3 - skip, never fail: every ordinary thing a serve loop does must cost the request nothing but a
    // skipped file.  KVA's capture ERRORS on these; that is the difference this probe exists to remove.
    {
        bool routine = false;
        check(why(c, 500, 149, 0, -1, false, &routine) != nullptr && routine,
              "a continuation (pos0 != 0) is skipped as an everyday case");
        routine = false;
        check(why(c, 0, 13900, 0, -1, false, &routine) != nullptr && routine,
              "a chat turn carrying the standing text is longer than the window and is skipped");
        routine = false;
        check(why(c, 0, 1369, 4, -1, false, &routine) != nullptr && !routine,
              "a layer split is refused loudly: a stage that starts above the boundary has no rows to take");
        check(why(c, 0, 1369, 0, 24) != nullptr, "a stage that ends before the last layer declines too");
        check(why(c, 0, 1369, 0, -1, true) != nullptr, "a prompt with pictures declines (its rows are not the body's)");
        check(why(c, 0, 0) != nullptr, "an empty read declines");
    }

    // C4 - the in-order rule: two prompts must never share one file, and a chunk past the prompt's end is
    // the decode that followed it, not a corrupted row.
    {
        BoundaryCapture p = probe();
        p.begin_prompt();
        check(p.taken == 0 && p.next_pos == 0, "begin_prompt starts the position and the body over");
        check(p.take(0, 512, 1369), "chunk 1 (positions 0-511) is taken");
        check(p.take(512, 512, 1369), "chunk 2 continues in order");
        check(!p.take(1200, 169, 1369), "an out-of-order chunk is SKIPPED, not an error");
        check(p.next_pos == 1024 && p.taken == 1024, "and a skipped chunk moves nothing");
        check(p.take(1024, 345, 1369), "the in-order chunk after it is still taken");
        check(p.taken == 1369, "so the file holds exactly the prompt's positions");
        check(!p.take(1369, 1, 1369), "a decode step past the end of the prompt is not captured");
        p.begin_prompt();
        check(p.taken == 0 && p.next_pos == 0, "the next cold read starts over (one body per file)");
    }

    // C4b and C4c - the two shapes of the same defect, modelled the way the engine calls it: a read hands
    // over p0 = 0, then 512, then 1024... and the LAST chunk is partial (T = min(capacity, n - p0)). The bug
    // of 2026-10-30 was that prefill.cpp reset the tap per read and not the rule, so read 2 arrived offering
    // p0 = 0 against a stale next_pos, captured NOTHING, and the log went on printing the first body's count.
    // A probe that quietly stops measuring is worse than a missing one: it reads like a result.
    {
        // The caller, faithfully: positions start at 0 for every read, whether or not the probe was re-armed.
        auto run_read = [](BoundaryCapture& c, int64_t n, int64_t cap) {
            int64_t chunks = 0;
            for (int64_t p0 = 0; p0 < n; p0 += cap) {
                if (!c.take(p0, std::min(cap, n - p0), n)) break;
                ++chunks;
            }
            return chunks;
        };

        // C4b - the polite caller, which re-arms (what prefill.cpp does now).
        BoundaryCapture a = probe();
        check(run_read(a, 99, 512) == 1 && a.taken == 99, "read 1: one partial chunk covers a 99-position body");
        a.begin_prompt();
        check(run_read(a, 2319, 512) == 5 && a.taken == 2319,
              "read 2, re-armed: five chunks (four of 512, then a partial 271) cover 2319 positions");
        a.begin_prompt();
        check(a.taken == 0 && a.next_pos == 0, "begin_prompt clears both counters, so no read borrows another's count");

        // C4c - the FORGOTTEN re-arm, which is the bug as shipped: no begin_prompt between the two reads.
        // The self-arming rule in take() is what saves it, and this is the check that would catch its removal.
        BoundaryCapture b = probe();
        check(run_read(b, 99, 512) == 1 && b.taken == 99, "read 1 with no re-arm: still captured");
        const int64_t got = run_read(b, 2319, 512);
        check(got == 5 && b.taken == 2319,
              "read 2 with NO re-arm: the probe re-arms itself at position 0 instead of silently capturing nothing");

        // And the face-palm case the log showed: a smaller read must never report the previous, larger count.
        BoundaryCapture c2 = probe();
        run_read(c2, 99, 512);
        run_read(c2, 88, 512);
        check(c2.taken == 88, "a read of 88 positions reports 88 rows, never the 99 of the body before it (was \"99 of 88\")");
    }

    // C5 - the byte arithmetic every bank number in the header is built on.  Pinned to the compiled
    // geometry so a change to hc or n_embd is a change to this claim, and this test says so.
    {
        const ModelGeometry g;
        check(BoundaryCapture::row_bytes_bf16(g.hc, g.n_embd) == 20480,
              "one boundary row is hc x n_embd x bf16 = 20,480 B - the arithmetic of the 6x bank claim");
        check(BoundaryCapture::row_bytes_bf16(4, 2560) == 20480, "and it is spelled out for the reader, not derived");
    }

    // C6 - the architectural claim that makes a layer-boundary cut mean anything on this hybrid at all:
    // attention sits at 3, 7, 11 (and every 4th after), so a boundary at 12 leaves nine recurrent layers
    // and three attention layers below it.  If the interval or the phase moves, the tuned cut moves with
    // it and this check says so before the cart file is trusted.
    {
        const ModelGeometry g;
        check(is_qsa_layer(g, 3) && !is_qsa_layer(g, 0) && !is_qsa_layer(g, 2),
              "layer 3 is the FIRST full-attention layer (l % 4 == 3), which is why MAM's cut has a counterpart here");
        int64_t qsa_below = 0, gdn_below = 0;
        for (int64_t l = 0; l < BoundaryCapture::kBoundaryLayerDefault; ++l)
            (is_qsa_layer(g, l) ? qsa_below : gdn_below) += 1;
        check(qsa_below == 3 && gdn_below == 9,
              "boundary 12 leaves exactly 3 attention layers (their K/V) and 9 recurrent ones (their fixed state) below");
        check(BoundaryCapture::kBoundaryLayerDefault % g.qsa_interval == 0,
              "the boundary sits on a stage edge, so no layer is ever split across the cut");
        check(BoundaryCapture::kBoundaryLayerDefault > g.qsa_interval,
              "the tuned cut is above the faithful one (4): the owner chose tuned because this is not the model they measured");
    }

    std::printf("boundary_cart_test: %d checks passed\n", checks);
    return 0;
}
