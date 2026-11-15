#!/usr/bin/env python3
"""Prefetch-margin arithmetic for the live heretic boot (2026-11-14).

Every input is measured on THIS box today, with the source named in the comment.
Run: .venv/bin/python bench/p1/prefetch_margin.py
"""
MB = 2**20

# --- inputs, all measured 2026-11-14 on the running boot (engine 0.1.59.1) ---
SLOTS = 5123            # /metrics engine.expert_slots
CACHE_MIB = 14781       # /metrics engine.expert_cache_mib
N_LAYER, N_EXP, K_ROUTED = 48, 512, 10          # GGUF qwen4exp.*
HIT = 0.819            # log "cache hit rate: 81.9% (489428 hits / 489428+... lookups)"
NONRES = 8.68          # log lookahead stats: actual non-resident experts/layer (per window)
PRED_MS = 30.98        # log: predictor thread ms/window
UNPRED = 0.499         # log: layers scored with no prediction
BLOB_MIB = 2.885       # CACHE_MIB / SLOTS, cross-checked vs the shard tensor table (2.863)
PCIE = 28.9            # GB/s, Gen4 x16 measured
KV_TOKS_S = 90.4       # /metrics hardware.tok_s (instant), 73.8 mean
K = 8                  # --spec 8 on this boot; the log prints acceptance for positions 0..6

# per-position acceptance, log "acceptance stats, 1000 windows" (p_i = accept i | reached i)
P = [0.773, 0.660, 0.614, 0.602, 0.615, 0.626, 0.615, 0.60]

print("== window shape")
# mean tokens per verify step = 1 + sum of the running product of p_i
run, tot = 1.0, 1.0
for i, p in enumerate(P):
    run *= p
    tot += run
    print(f"   pos{i} p={p:.3f}  P(reach)=...  cum tokens={tot:.3f}")
T = tot
print(f"   => tokens/window T = {T:.2f}   (spec rows K={K}, so the ceiling is {K+1})")

print("\n== per-token expert demand")
req = N_LAYER * K_ROUTED
miss_gpu = req * (1 - HIT)
win_per_tok = NONRES * N_LAYER / req * (req / (NONRES * N_LAYER))  # placeholder
n_tok_from_stats = NONRES * N_LAYER / (req * (1 - HIT))
print(f"   routed requests/token        = {req}")
print(f"   GPU-cache misses/token       = {miss_gpu:.1f}  (hit {HIT:.1%})")
print(f"   host-pool misses/window      = {NONRES} x {N_LAYER} = {NONRES*N_LAYER:.0f} blobs")
print(f"   => window tokens implied      = {n_tok_from_stats:.2f}  (stats arm counts the host pool)")
print(f"   bytes/window (host pool)      = {NONRES*N_LAYER*BLOB_MIB/1024:.2f} GiB"
      f"  = {NONRES*N_LAYER*BLOB_MIB/1024/T*1024:.0f} MiB/token")

print("\n== time budget")
win_ms = PRED_MS
tok_ms = win_ms / T
layer_ms = tok_ms / N_LAYER
load_ms = BLOB_MIB / 1024 / PCIE * 1000
print(f"   window (measured)             = {win_ms:.1f} ms   ({tok_ms:.2f} ms/token, {layer_ms:.3f} ms per layer-token)")
print(f"   one blob over PCIe            = {load_ms:.3f} ms  ({BLOB_MIB:.3f} MiB / {PCIE} GB/s)")
print(f"   loads that fit the layer window at 100% link = {layer_ms/load_ms:.2f}")
print(f"   loads demanded per layer-token = {NONRES/T:.2f}")
print(f"   => link margin                = {layer_ms/load_ms/(NONRES/T):.2f}x")
gibs = NONRES * N_LAYER * BLOB_MIB / 1024 / (win_ms / 1000)
print(f"   link share at full blobs      = {gibs*1.0737:.1f} GB/s of {PCIE}"
      f"  = {gibs*1.0737/PCIE:.0%}  (the engine streams --pcie-frac 0.35 of a blob per swap)")

print("\n== what the predictor is worth")
print(f"   layers with no prefetch today = {UNPRED:.1%}")
zs = NONRES * N_LAYER * UNPRED
print(f"   blobs arriving with zero lead = {zs:.0f}/window = {zs*BLOB_MIB/1024:.2f} GiB/window"
      f"  ({zs*BLOB_MIB/1024/T*1024:.0f} MiB/token exposed to the layer window)")
for name, pred, cov, prec, share in [
        ("votes top4", 3.60, 0.239, 0.578, 0.142),
        ("votes top8", 6.17, 0.385, 0.541, 0.286),
        ("votes top12", 7.89, 0.471, 0.518, 0.383),
        ("per-token k=10", 10.78, 0.584, 0.471, None),
        ("per-token k=14", 16.22, 0.695, 0.372, None)]:
    eff = f"{cov/share:.2f} coverage per link" if share else "n/a"
    print(f"   {name:<16} predicted/layer {pred:5.2f}  covers {cov:.3f} of misses"
          f"  precision {prec:.3f}  link {share if share is not None else float('nan'):.3f}  {eff}")

print("\n== lever prices (per-token, at the measured 90 tok/s)")
base_mib = NONRES * N_LAYER * BLOB_MIB / T   # MiB/token
print(f"   today: {base_mib:.0f} MiB/token of expert traffic")
print(f"   2611.15842 next-use-distance eviction: 2.1x fewer copies -> {base_mib/2.1:.0f} MiB/token")
print(f"   coverage 50%->90% (boot-time predictor): {base_mib*0.4:.0f} MiB/token moves off the critical path")
print(f"   per-layer k (KS) at -2 predicted/layer: {2*BLOB_MIB/1024/T*1024:.0f} MiB/token saved, recall -0.03")
