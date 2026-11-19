#include "strata/core/conversation_graft.hpp"

#include <cstdio>
#include <string_view>
#include <cstdlib>
#include <vector>

using namespace strata::core;

namespace {
int checks = 0;
void check(bool value, const char* description) {
    ++checks;
    if (!value) { std::fprintf(stderr, "FAIL: %s\n", description); std::exit(1); }
}
std::vector<int32_t> ids(std::initializer_list<int32_t> v) { return std::vector<int32_t>(v); }
// Names are std::string_view on the call site (the serve loop holds a std::string); the test writes
// them as views so a swapped argument list cannot hide behind an implicit conversion.
constexpr std::string_view NAME = "cart.bin";
}

int main() {
    const auto g = ids({10, 11, 12, 13});

    // C6 - the instrument check: no key on the wire, and the graft is never consulted.  This fails the
    // moment the serve loop reaches for the file unconditionally, so it is the default-path guard.
    {
        const auto d = graft_decide(ids({7, 8, 9}), false, std::string_view{}, g, 0, true);
        check(!d.consulted(), "no graft name leaves the decision exactly as today");
    }
    // C1 - a name is the key: `graft=` with nothing after it is a refusal, never a silent no-op.
    {
        const auto d = graft_decide(ids({7, 8, 9}), true, std::string_view{}, g, 0, true);
        check(d.refused(), "an empty graft name refuses rather than doing nothing");
    }
    // C2 - no vault, no graft: the engine never guesses where the file lives.
    {
        const auto d = graft_decide(ids({7, 8, 9}), true, NAME, g, 0, false);
        check(d.refused(), "a graft without --slot-save-path refuses");
    }
    // C4 - the arm itself: a prompt that does not begin with the graft ids continues it, so the file's
    // ids ride as a virtual prefix and the read starts at the graft's length.
    {
        const auto d = graft_decide(ids({7, 8, 9}), true, NAME, g, 0, true);
        check(d.applies() && d.prepend && d.resume == 4,
              "a disjoint prompt grafts: ids prepended, resume at the graft length");
    }
    // C3 - a client that re-sends the source pays the SAME window, not a doubled one.
    {
        const auto d = graft_decide(ids({10, 11, 12, 13, 7, 8}), true, NAME, g, 0, true);
        check(d.applies() && !d.prepend && d.resume == 4,
              "a prompt already carrying the graft ids grafts without prepending them");
    }
    // C5 - the cache outranks the file: a proven resume deeper than the graft wins, unread.
    {
        const auto d = graft_decide(ids({10, 11, 12, 13, 7, 8, 9}), true, NAME, g, 6, true);
        check(!d.consulted(), "a proven resume deeper than the graft beats the file");
    }
    // An empty file cannot graft: there is no virtual prefix to speak of.
    {
        const auto d = graft_decide(ids({7, 8, 9}), true, NAME, std::vector<int32_t>{}, 0, true);
        check(d.refused(), "a graft file with no ids refuses");
    }
    // The equal-length case: a re-sent source with nothing new still rides the grafted state.
    {
        const auto d = graft_decide(g, true, NAME, g, 0, true);
        check(d.applies() && !d.prepend && d.resume == 4, "a prompt equal to the graft ids grafts once");
    }
    // A shallower cache hit does not block a deeper graft - the graft may still be the better start.
    {
        const auto d = graft_decide(ids({7, 8, 9}), true, NAME, g, 2, true);
        check(d.applies() && d.resume == 4, "a resume shallower than the graft does not beat it");
    }

    // C7 - the LIFECYCLE of a stage (2026-10-29), which is where the lever actually died.  The server writes
    // GRAFT and its GEN in one FIFO turn, so a stage is always young when the guard runs; dropping it there
    // unconditionally is what made "state without text" unmeasurable, and these checks are the reason the bug
    // cannot come back quietly.
    {
        // The exchange that must work: staged this turn, asked this turn, RAM proved nothing of its own.
        const auto live = graft_lifecycle(true, true, false, 0);
        check(live.keep_staged && !live.clear_wanted && !live.report_not_used,
              "a stage that is seconds old survives the guard so its request can consume it (the bug)");
        // RAM already has a start: the graft is moot, and it must SAY so - the silence here hid the bug a day.
        const auto moot = graft_lifecycle(true, true, false, 13610);
        check(!moot.keep_staged && moot.clear_wanted && moot.report_not_used,
              "a deeper RAM start drops the stage and reports it");
        // Never held over: staged, and the request that followed did not ask.
        const auto orphan = graft_lifecycle(false, true, false, 0);
        check(!orphan.keep_staged && orphan.clear_wanted,
              "a stage nobody asked for is dropped, so no later conversation inherits it");
        // The no-stage case stays loud: asked, nothing staged, a cold request.
        const auto missing = graft_lifecycle(true, false, false, 0);
        check(!missing.keep_staged && !missing.clear_wanted,
              "an ask with nothing staged is left to the branch below, which reports it - never silenced");
        // A leftover ask from an earlier exchange is still a leftover after this fix.
        const auto leftover = graft_lifecycle(false, false, true, 7);
        check(leftover.clear_wanted && leftover.report_not_used,
              "an unconsumed ask from an earlier request is cleared, not carried");
    }

    std::printf("conversation_graft_test: ALL PASS (%d checks)\n", checks);
    return 0;
}
