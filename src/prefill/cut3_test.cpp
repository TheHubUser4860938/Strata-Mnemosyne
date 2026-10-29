// src/prefill/cut3_test.cpp - the decision half of STRATA_CUT3_CAPTURE (memory-core, 2026-10-29).
//
// Pure policy, no device and no file IO, so the rule that decides WHICH read donates its boundary rows -
// and which positions inside it - is checked without a GPU, the way the graft lever is
// (src/core/conversation_graft_test.cpp).  The environment is read by Cut3Capture::process() at run time
// and is deliberately not exercised here: a static that caches the environment once per process cannot be
// re-asked inside one test binary, so the cases construct the struct and set the fields they test.
//
// What these checks protect, in one line each: the default path (nothing runs, nothing is printed), the
// skip-don't-fail rule that lets a probe sit beside a serving box's own traffic, the in-order rule that
// keeps two prompts' rows from landing in one file, and the byte arithmetic that the whole bank claim of
// include/strata/prefill/cut3.hpp is built on.

#include "strata/prefill/cut3.hpp"
#include "strata/core/geometry.hpp"

#include <cstdio>
#include <cstdlib>

using strata::prefill::Cut3Capture;
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
Cut3Capture probe() {
    Cut3Capture c;
    c.on = true;
    c.dir = "/tmp/cut3-probe";
    return c;
}

const char* why(const Cut3Capture& c, int64_t pos0, int64_t n, int64_t lb = 0, int64_t le = -1,
                bool pictures = false, bool* routine = nullptr) {
    return c.decline(pos0, n, lb, le, (int64_t) ModelGeometry{}.n_layers, pictures, routine);
}
}  // namespace

int main() {
    const Cut3Capture off;   // nothing in the environment: this is every box that never heard of CUT3

    // C1 - the default-path guard.  Unset, the probe declines, and a run must not print or write a thing.
    // This is the check that fails the moment the hook is reached for unconditionally.
    check(!off.on, "an unset STRATA_CUT3_CAPTURE leaves the probe off");
    check(why(off, 0, 1000) != nullptr, "off: the read declines");
    check(why(off, 0, 1000)[0] != '\0', "off: and the reason is a sentence, not an empty string");
    check(!off.wants(Cut3Capture::kCut3BoundaryDefault), "off: no layer is ever wanted");

    const Cut3Capture c = probe();

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
        Cut3Capture p = probe();
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

    // C5 - the byte arithmetic every bank number in the header is built on.  Pinned to the compiled
    // geometry so a change to hc or n_embd is a change to this claim, and this test says so.
    {
        const ModelGeometry g;
        check(Cut3Capture::row_bytes_bf16(g.hc, g.n_embd) == 20480,
              "one boundary row is hc x n_embd x bf16 = 20,480 B - the arithmetic of the 6x bank claim");
        check(Cut3Capture::row_bytes_bf16(4, 2560) == 20480, "and it is spelled out for the reader, not derived");
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
        for (int64_t l = 0; l < Cut3Capture::kCut3BoundaryDefault; ++l)
            (is_qsa_layer(g, l) ? qsa_below : gdn_below) += 1;
        check(qsa_below == 3 && gdn_below == 9,
              "boundary 12 leaves exactly 3 attention layers (their K/V) and 9 recurrent ones (their fixed state) below");
        check(Cut3Capture::kCut3BoundaryDefault % g.qsa_interval == 0,
              "the boundary sits on a stage edge, so no layer is ever split across the cut");
        check(Cut3Capture::kCut3BoundaryDefault > g.qsa_interval,
              "the tuned cut is above the faithful one (4): the owner chose tuned because this is not the model they measured");
    }

    std::printf("cut3_test: %d checks passed\n", checks);
    return 0;
}
