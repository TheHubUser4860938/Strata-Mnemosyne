#pragma once

// The DECISION half of the graft lever (memory-core, 2026-10-28): may this request start on the state
// stored in a session FILE, and where does its own text begin?  Pure policy - no device, no file IO -
// so the whole rule is testable the way the cart fence is (src/core/conversation_cache_test.cpp).
//
// WHY a lever at all: state reuse in the serve loop is provable only by TOKEN-PREFIX EQUALITY
// (starts_with, src/program/generate.cpp:13949; conversation_prefix,
// include/strata/core/conversation_cache.hpp:233-245).  Nothing on the wire can say "this new
// conversation begins at this saved state", so the one file lever that exists - the out-of-band
// RESTORE <path> command (generate.cpp:13462) - REPLACES the live session (13668) and is then zeroed
// by the first prefix-mismatched chat (`if (resume == 0) session_zero(...)`, 14486-14494).  Measured on
// this box 2026-10-28: after a save and restore of a 1,073-token conversation, a fresh one-question
// conversation paid prompt=13,095 at cached=0.  The state was there and unreachable - which is exactly
// the "state without text" question the MAM cartridges raise, unmeasurable from the harness.
//
// THE RULE, in one sentence: a graft is a VIRTUAL PREFIX - the file's ids stand before the request's
// own ids and the read begins at the graft's length - consulted only when nothing already in RAM beats
// it, so a request that carries no graft key behaves exactly as it does today.
//
// The wire shape follows `cart=1` (2026-10-28): the GEN line already skips unknown keys
// (generate.cpp:13795, "the ids start at the first token without '='"), so `graft=<name>` is safe in
// both directions - a new server against an old engine degrades to "no graft", and an old server
// against a new engine changes nothing.  The value is a plain file name (the server's own alphabet:
// serve/server.py:4463-4480 forbids `/ \ : * ? " < > |`, a leading dot, >200 bytes) and the no-separator
// rule is load-bearing, not cosmetic: a space in the name would end the key list and swallow the ids.

#include <cstdint>
#include <string_view>
#include <vector>

namespace strata::core {

enum class GraftStatus : uint8_t {
    none,     // no key on the wire: the request decides its start exactly as before
    refused,  // a key was given and cannot be honoured - the caller refuses the request, never shrugs
    apply,    // graft this file as the request's virtual prefix
};

struct graft_decision {
    GraftStatus status = GraftStatus::none;
    bool prepend = false;   // stand the file's ids in front of the request's ids
    int64_t resume = 0;     // tokens already in the state when the request's own text begins
    const char* reason = "";

    bool consulted() const { return status != GraftStatus::none; }
    bool applies() const { return status == GraftStatus::apply; }
    bool refused() const { return status == GraftStatus::refused; }
};

// Decide whether `graft_name` should carry this request, given the request's ids, the graft file's ids
// and the best resume the caller has ALREADY proven from RAM (live ids, checkpoints, batch slots, the
// parked cache - the caller owns that ranking; this function only says whether the file can beat it).
//
// slot_path_known says the engine was started with --slot-save-path: the graft reads from that same
// vault, so a file the /slots route saved is a file a request can graft.  Without it the engine does
// not guess a directory, it refuses.
//
// A name is REQUIRED (an empty value is a refusal, not a silent no-op: a request that asked for a
// cartridge and got none must not answer as though it had).  An empty file is likewise a refusal -
// there is no virtual prefix in a file with no ids.
//
// Both id vectors are deduced, not fixed to one integer type: the serve loop counts a prompt in
// int64_t (generate.cpp:13871) while a session file stores int32_t (conversation_file.cpp's grammar),
// and the rule is about token EQUALITY, not about a width. Forcing one type would mean a copy of every
// prompt or a narrowing cast on every file - and a narrowing cast in a memory system is how you get a
// silent wrong answer instead of a loud one.
//
// Equal resume is NOT enough to skip the file: a prefix match of the same length proves the same
// TOKENS, not the same STATE (two conversations can share tokens and differ in their recurrent state),
// so only a strictly deeper resume beats a graft.
// A std::string_view for the name, not const char*: the wire hands the serve loop a std::string, and
// a const char* parameter would let a std::string convert silently into the WRONG slot of an argument
// list (a vector<int32_t> converts to int64_t via size(), so a swapped call even compiles and answers
// confidently - this signature was caught by that exact mistake).  `name_given` is a parameter and NOT
// inferred from emptiness, because the serve loop can tell "no graft= key" from "graft= with nothing
// after it" (req_cart-style parse flags) and must: the first is today's behaviour, the second is a
// refusal.  Both arrive as an empty view here, so the flag is the only honest signal.
template <typename PromptIds, typename GraftIds>
graft_decision graft_decide(const PromptIds& prompt, bool name_given, std::string_view graft_name,
                            const GraftIds& graft_ids, int64_t resume, bool slot_path_known) {
    graft_decision d;
    if (!name_given) return d;
    // A key with no value asked for a cartridge and got none: refuse, do not answer as though it had.
    if (graft_name.empty()) {
        d.status = GraftStatus::refused;
        d.reason = "graft= names no file";
        return d;
    }
    if (!slot_path_known) {
        d.status = GraftStatus::refused;
        d.reason = "graft needs --slot-save-path";
        return d;
    }
    if (graft_ids.empty()) {
        d.status = GraftStatus::refused;
        d.reason = "graft file carries no conversation";
        return d;
    }
    const int64_t glen = (int64_t) graft_ids.size();
    if (resume > glen) {   // RAM already proves a deeper start than this file can offer
        d.resume = resume;
        return d;
    }
    d.status = GraftStatus::apply;
    d.resume = glen;
    // A client that re-sends the source pays the SAME window, not a doubled one: prepend only when the
    // prompt does not already open with the graft's tokens.
    const bool already = (int64_t) prompt.size() >= glen;
    bool starts = already;
    for (int64_t i = 0; starts && i < glen; ++i)
        if (prompt[(size_t) i] != graft_ids[(size_t) i]) starts = false;
    d.prepend = !starts;
    return d;
}

/// The LIFECYCLE half of the lever, decided per request (2026-10-29, from a measured failure).
///
/// `graft_decide` answers "may this request start on the file"; this answers the question the serve loop has to
/// answer one step earlier: "is the staged file still mine to use?"  The rule is `one exchange, one graft` - a
/// stage is dropped, never held over, so a later conversation can never start on a graft it did not ask for.
///
/// WHY this is a function and not four lines in the loop: those four lines were wrong where they were written,
/// and no test could see it.  The server writes `GRAFT <path>` and `GEN ... graft=1` in the SAME FIFO turn, so
/// the stage lands a moment BEFORE the block that guarded it ran; clearing unconditionally there wiped a stage
/// that was seconds old and the request answered "asked for a graft and none is staged".  Measured on this box
/// 2026-10-29: `graft staged ... MEM-CART-e8228bae.bin: 149 tokens ... device untouched (81.3 ms)` and then that
/// refusal - the lever had never once fired, in any path, because the older declines (`resume != 0`) were silent
/// and hid it.
struct GraftLifecycle {
    bool keep_staged = false;      ///< the stage survives to the branch below, which consumes or reports it
    bool clear_wanted = true;      ///< this request's ask is finished with
    bool report_not_used = false;  ///< say so: RAM already proved a start, so the graft is moot
};

/// `staged`: a file is waiting from a `GRAFT` command.  `wanted`: an earlier request asked and did not consume
/// it (the leftover the drop exists for).  `req_graft`: THIS request's `graft=` key.  `resume`: what RAM gave it.
inline GraftLifecycle graft_lifecycle(bool req_graft, bool staged, bool wanted, int64_t resume) {
    GraftLifecycle d;
    const bool asks = req_graft || wanted;
    if (!asks) {
        d.keep_staged = false;                       // nobody asked: a stage of an older exchange goes now
        d.clear_wanted = true;
        return d;
    }
    if (resume != 0) {                               // RAM already gave this request a deeper-or-equal start
        d.keep_staged = false;
        d.clear_wanted = true;
        d.report_not_used = true;
        return d;
    }
    d.keep_staged = staged;                          // consumed below, or reported as missing - never dropped here
    d.clear_wanted = false;                          // the branch below finishes with the ask, and says why
    return d;
}

}  // namespace strata::core
