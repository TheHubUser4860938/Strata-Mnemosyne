// src/core/proj_form_test.cpp - WHICH kernel reads a dense projection row, decided from the row's own metadata.
//
// WHY THIS EXISTS.  Three dispatchers asked that question as `w->native_data != nullptr` and all three got it
// wrong in the same direction: a pack row kept UNQUANTIZED is not a MISSING tensor, it is a different FORM, and
// reading it as missing made the engine blame a flag that was on the whole time.  The boot that triggered this:
//
//     strata generate: prefill: blk.0.attn_gate.weight has no native GGUF blocks (run with --native)
//
// on trubisky's Swift 1.5 Flash Next Heretic v2, whose card says layer 0's attention gate is "a giant outlier
// (the most sensitive tensor family in the model) - kept uncompressed".  It is the only one of the model's 36
// gates that is: the other 35 are Q8_0, which is why no other quant on this box ever reached that line.
//
// The two row shapes below are not invented.  They are the `blk.0.attn_gate.weight` rows of the two packs on
// the dev box, read out of `index.txt` with the 19-field order `src/core/weights.cpp` parses:
//
//     huihui  UD-Q4_K_XL   kind 0 (Verbatim)  pool 0 B          code_bits 8  -> the GGUF's blocks serve it
//     heretic IQ4_NL       kind 4 (BF16)      pool 31,457,280 B code_bits 0  -> the pack's own 16-bit bytes
//
// (`kind` 4/5 are `tools/iq_pack.py`'s plan v0.3 P6 forms, which the loader maps to Bf16InF32/F16InF32 with
// `raw16`; 2560 x 6144 x 2 B = 31,457,280, exactly the pool span the pack records for the row.)
//
// Pure policy: no device, no file IO, so no GPU and no model.
#include "strata/core/weights.hpp"

#include <cstdio>
#include <cstdlib>

using strata::core::WeightKind;
using strata::core::WeightRef;
using ProjForm = WeightRef::ProjForm;

namespace {
int checks = 0;
void check(ProjForm got, ProjForm want, const char* description) {
    ++checks;
    if (got != want) {
        std::fprintf(stderr, "FAIL: %s (got form %d, want %d)\n", description, (int) got, (int) want);
        std::exit(1);
    }
}

// The row a pack writes when the GGUF's block form serves the tensor: no bytes in the pool, the metadata kept,
// and NativeDense publishes the binding at load (`src/core/native_dense.cpp` sets native_data/native_type).
WeightRef native_row() {
    WeightRef r;
    r.kind = WeightKind::Verbatim;
    r.code_bits = 8;
    r.group_elems = 32;
    r.resident = false;      // plan v0.3 P1: the loader skipped the canonical bytes, another form serves them
    r.ne0 = 2560;
    r.ne1 = 6144;
    r.native_data = (const void*) 0x1000;   // any non-null binding: this policy reads presence, never the bytes
    r.native_type = 8;
    return r;
}

// The row a pack writes when the GGUF keeps the tensor unquantized: the 16-bit bytes ARE the pack payload, and
// nothing binds blocks under them, because `native_mmvq` reads blocks and a 16-bit matrix has none.
WeightRef bf16_row() {
    WeightRef r;
    r.kind = WeightKind::Bf16InF32;         // what index kind 4 becomes in the engine's form
    r.code_bits = 0;                        // not quantized at all: this is the whole point
    r.resident = true;
    r.data = (const void*) 0x2000;
    r.bytes = 2560ull * 6144ull * 2ull;     // 31,457,280 B, the pool span the pack records for the row
    r.ne0 = 2560;
    r.ne1 = 6144;
    return r;
}
}  // namespace

int main() {
    // P1 - the two real rows land on the two different readers, and neither is called missing.
    check(native_row().proj_form(), ProjForm::Native, "a bound block row is read from the GGUF blocks (huihui)");
    check(bf16_row().proj_form(), ProjForm::Bf16, "an unquantized 16-bit row is read by the BF16 GEMVs (heretic)");

    // P2 - THE BUG THIS FILE EXISTS FOR.  The old test was `native_data != nullptr`, which answered "nothing
    // serves this" for the row above.  If this check ever fails, a dispatcher is back to saying "run with
    // --native" at a launch that had it on.
    {
        const WeightRef r = bf16_row();
        check(r.proj_form() == ProjForm::None ? ProjForm::None : ProjForm::Bf16, ProjForm::Bf16,
              "an unbound row is not an absent row");
    }

    // P3 - adding the fallback must not move a row that already works: whenever the binding is there, the block
    // read wins, whatever else the row looks like.  This is the byte-identical guarantee for every model running
    // today (huihui has no BF16 dense matrix at all: its 300 eligible matrices are the same 300 names, all
    // block-quantized).
    {
        WeightRef r = bf16_row();
        r.native_data = (const void*) 0x1000;
        r.native_type = 8;
        check(r.proj_form(), ProjForm::Native, "a binding outranks the 16-bit form: no existing model changes path");
    }

    // P4 - a quantized pack row stays with the S-form readers.  Routing one to the BF16 GEMVs would read codes
    // as values and produce a plausible wrong answer, which is the worst kind.
    {
        WeightRef r;
        r.kind = WeightKind::Verbatim;
        r.code_bits = 8;
        r.group_elems = 32;
        r.data = (const void*) 0x3000;
        r.bytes = 16711680;
        r.codes_bytes = 15728640;
        r.scales_bytes = 983040;
        check(r.proj_form(), ProjForm::None, "a resident quantized row is the planes' business, not the BF16 read's");
    }

    // P5 - FP16 is NOT BF16.  Index kind 5 arrives as F16InF32; the BF16 GEMVs would read its bits as BF16 and
    // be wrong by construction, so the decision refuses it until something is wired for it.  Naming that here
    // keeps a future F16 quant from assuming the fallback covers every 16-bit form.
    {
        WeightRef r = bf16_row();
        r.kind = WeightKind::F16InF32;
        check(r.proj_form(), ProjForm::None, "an FP16 row is refused rather than read as if it were BF16");
    }

    // P6 - the STRATA_HC_Q8 trap: that row keeps kind Bf16InF32 while `data` holds INT8 codes with one fp32 scale
    // per 32 values, so "16-bit matrix" is false about it.  Its own entry expands the codes before any GEMV.
    {
        WeightRef r = bf16_row();
        r.q8_scale = (const float*) 0x4000;
        check(r.proj_form(), ProjForm::None, "a q8_scale row's data is int8 codes, so it is not a 16-bit matrix");
    }

    // P7 - a 16-bit form with no bytes behind it is still absent: the fallback must not invent a pointer.
    {
        WeightRef r = bf16_row();
        r.data = nullptr;
        r.resident = false;
        check(r.proj_form(), ProjForm::None, "no bytes, no projection - the honest error still fires");
    }

    // P8 - a row that claims a code width is quantized, whatever its kind says; the two attributes must agree
    // before the 16-bit read takes it.
    {
        WeightRef r = bf16_row();
        r.code_bits = 4;
        check(r.proj_form(), ProjForm::None, "code_bits set means the S-form owns the row");
    }

    std::printf("proj_form_test: ALL PASS (%d checks)\n", checks);
    return 0;
}
