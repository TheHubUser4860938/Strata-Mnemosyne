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
        const auto d = graft_decide(ids({7, 8, 9}), true, NAME, {}, 0, true);
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

    std::printf("conversation_graft_test: ALL PASS (%d checks)\n", checks);
    return 0;
}
