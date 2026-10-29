#pragma once

// include/strata/prefill/cut3.hpp - STRATA_CUT3_CAPTURE: the rows a MAM cartridge is made of
// (memory-core research, 2026-10-29).  Pure policy - no device, no file IO - so the whole rule is
// testable the way the graft lever is (src/core/conversation_graft_test.cpp).
//
// WHY.  A CUT3 cartridge (AKBASCORE Silicon Hippocampus, TEST815 doi 10.5281/zenodo.23736317) is not
// a KV cache and not text: it is the frozen model's own residual-stream rows for a source body, taken
// at ONE layer boundary, plus the state of the layers below it.  At read time those rows are injected
// AT the boundary with zero input embeddings and the layers above rebuild the memory - "no source
// text enters the prompt".  The first thing to learn on this architecture is what those rows cost, so
// this step captures them and measures; it mounts nothing.
//
// THE CUT, and why the number is 12.  This trunk is a hybrid: `is_qsa_layer(g, l) = l % 4 == 3`
// (include/strata/core/geometry.hpp:75-77), so full attention runs at 3, 7, 11, ... 47 - 12 of 48 -
// and the rest are recurrent with a fixed-size state (about 3.27 MB per layer, position-independent).
// MAM cuts after block 3 on a dense 80-layer Qwen2.5-72B, which leaves three recurrent-equivalent
// layers plus one attention layer below the cut.  The tuned counterpart here is boundary 12: below it
// sit nine GDN layers and three attention layers (K/V of 3, 7, 11), and 36 of 48 layers rebuild above
// it instead of 44 of 48.  The owner chose tuned over faithful on 2026-10-29 because the model is not
// the one they measured ("we running a different model than what he was testing so go with tuned").
//
// THE COST, arithmetic on compiled constants (not yet a measurement, and it must become one): the
// residual is the hyper-connection multi-stream `R`, hc=4 x n_embd=2560 = 10,240 floats per position
// (include/strata/core/geometry.hpp:23,49-50; src/prefill/prefill.cpp:172) = 20,480 B in bf16.  A
// 1,369-token body is therefore ~28 MB of rows - and the cart that holds the same body as a whole
// session state measures 257 MB today, because 117.7 MB of it is 36 fixed-size GDN states that a
// boundary-12 cart leaves behind (only nine ride along).  The bank claim lives or dies on that
// difference, which is the number T1 exists to check.
//
// THE RULE, in one sentence: capture the rows ENTERING layer `boundary` for the positions of one cold,
// in-range, whole-trunk read, and SKIP anything else - never fail it.  That last clause is the whole
// difference from STRATA_KVA_CAPTURE, which treats an out-of-order write as an error (prefill.cpp's
// KvaTap::write) and so can only ever run alone on a quiet box; a serve loop answers continuations
// (pos0 != 0) and chat turns far longer than a body, and a cart probe must be able to sit beside them.
//
// The rows are written by the same plumbing (KvaTap, prefill.cpp), so the file is
// `<dir>/L<boundary>.bin`: bf16 records in position order, a reader seeks straight to a position.

#include <cstdint>
#include <cstdlib>
#include <string>

namespace strata::prefill {

struct Cut3Capture {
    /// First layer that does NOT run for captured positions, i.e. rows are taken as they enter it.  Tuned
    /// for this hybrid, not faithful to the paper: see C6 in src/prefill/cut3_test.cpp for what sits below it.
    static constexpr int64_t kCut3BoundaryDefault = 12;
    /// Reads longer than this are skipped by default: an ordinary chat turn on a cartridge box carries the
    /// standing text (measured ~13.9k tokens on this box), and its rows are not a body we asked for.
    static constexpr int64_t kCut3MaxPromptDefault = 4096;

    bool on = false;              ///< STRATA_CUT3_CAPTURE=<dir>; unset or empty: nothing here runs
    int64_t boundary = kCut3BoundaryDefault;   ///< STRATA_CUT3_BOUNDARY
    int64_t min_prompt = 1;       ///< STRATA_CUT3_MIN_PROMPT: shorter reads are not worth a file
    int64_t max_prompt = kCut3MaxPromptDefault;
    std::string dir;

    // Bookkeeping for the in-order rule, per captured read:
    int64_t next_pos = 0;         ///< where the next record must start
    int64_t taken = 0;            ///< positions captured for the current read (what the probe reports)

    /// Why this read takes no capture, or nullptr when it does.  `routine` marks the everyday reasons
    /// (a continuation, a length outside the window) that are not worth a log line - the KVA style.
    const char* decline(int64_t pos0, int64_t n, int64_t lb, int64_t le, int64_t n_layers,
                        bool pictures, bool* routine = nullptr) const {
        if (routine != nullptr) *routine = false;
        if (!on) return "off (STRATA_CUT3_CAPTURE is not set)";
        if (pos0 != 0) {
            if (routine != nullptr) *routine = true;
            return "not a cold read (pos0 != 0)";
        }
        if (lb != 0 || (le >= 0 && le != n_layers)) return "a layer split (not the whole trunk)";
        if (pictures) return "a prompt with pictures";
        if (n < min_prompt) {
            if (routine != nullptr) *routine = true;
            return "shorter than STRATA_CUT3_MIN_PROMPT";
        }
        if (n > max_prompt) {
            if (routine != nullptr) *routine = true;
            return "longer than STRATA_CUT3_MAX_PROMPT";
        }
        return nullptr;
    }

    bool wants(int64_t layer) const { return on && layer == boundary; }

    /// A new captured read starts: one read per file, so the position counter and the body reset.
    void begin_prompt() { next_pos = 0; taken = 0; }

    /// Accept this chunk?  Anything out of order, empty, or past the end of the prompt is SKIPPED and
    /// the run continues: a probe must never be the reason a request fails.
    bool take(int64_t p0, int64_t T, int64_t n) {
        if (!on || p0 != next_pos || T <= 0 || p0 + T > n) return false;
        next_pos += T;
        taken += T;
        return true;
    }

    /// Bytes the rows of one position cost in bf16 - the number the bank arithmetic is made of.
    static constexpr int64_t row_bytes_bf16(int64_t hc, int64_t n_embd) { return hc * n_embd * 2; }

    /// Read once per process, the way KVA does it: the environment does not change under a running
    /// server, and a knob that could would make a measured run unreproducible.
    static const Cut3Capture& process() {
        static const Cut3Capture c = [] {
            Cut3Capture k;
            const char* d = std::getenv("STRATA_CUT3_CAPTURE");
            if (d == nullptr || *d == '\0') return k;
            k.on = true;
            k.dir = d;
            const auto num = [](const char* name, int64_t dflt) {
                const char* v = std::getenv(name);
                if (v == nullptr || *v == '\0') return dflt;
                char* end = nullptr;
                const long long x = std::strtoll(v, &end, 10);
                return (end == nullptr || *end != '\0' || x < 0) ? dflt : (int64_t) x;
            };
            k.boundary = num("STRATA_CUT3_BOUNDARY", kCut3BoundaryDefault);
            k.min_prompt = num("STRATA_CUT3_MIN_PROMPT", 1);
            k.max_prompt = num("STRATA_CUT3_MAX_PROMPT", kCut3MaxPromptDefault);
            return k;
        }();
        return c;
    }
};

}  // namespace strata::prefill
