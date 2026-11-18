"""Offline DFlash2 block-size sweep on OUR target: how many tokens per round does a wider drafted
window buy, measured on this box's own quantized model?

    python tools/dflash2/sweep_blocks.py --pack <file.pack> --taps <tap-file>
                                         [--blocks 4,8,12,16,20,24] [--shard <...00008-of-00008.gguf>]
                                         [--work <dir>] [--threads N] [--seq NAME] [--json OUT]

The Linux side of the experiment the Windows-pathed scripts (run_eval.py, orch.py) started: same
torch reference (dflash2_ref.py), same walk, no hard-coded C:\ paths, and it reads the drafter
straight out of the shipped .pack instead of a pre-staged drafter.safetensors.

What it does:
  1. unpacks the pack (q4_0 / f32 blocks dequantized exactly as the engine reads them, so the
     numbers are the SHIPPED drafter's, not the bf16 original's) and writes a safetensors + the
     config.json the reference wants, both derived from the pack's own cfg lines;
  2. dequantizes the target's token_embd.weight and output.weight from the GGUF shard (Q8_0 here);
  3. splits the STRATA_TAP_FILE dump into sequences (a position run that restarts near 0 is a new
     conversation - the engine appends every request to one file);
  4. walks each sequence the way the verify loop does: the row at position s is the anchor, the
     drafter proposes b-1 tokens, the engine's own tokens are the truth, the leading matches are
     accepted plus one bonus token, and s moves on. Reports tokens per round and the acceptance at
     each block position, per block size.

Needs torch (CPU is enough) and safetensors in the venv.
"""
import argparse
import json
import os
import struct
import sys
import time
from pathlib import Path

import numpy as np
import safetensors.torch as stt
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import dflash2_ref as R  # noqa: E402  (the torch port of z-lab's DFlash2DraftModel)

DTYPES = {"q4_0": R.gguf.GGMLQuantizationType.Q4_0,
          "q8_0": R.gguf.GGMLQuantizationType.Q8_0,
          "f32": None}

# pack cfg key -> config.json key. The reference reads the HF names; the pack carries short ones.
CFG_MAP = {"hidden": "hidden_size", "layers": "num_hidden_layers", "heads": "num_attention_heads",
           "kv_heads": "num_key_value_heads", "head_dim": "head_dim", "inter": "intermediate_size",
           "window": "sliding_window", "eps": "rms_norm_eps"}
DC_MAP = {"conv_group": "conv_group_size", "conv_kernel": "conv_kernel_size",
          "mask_token": "mask_token_id", "top_k": "selector_top_k", "taps": "target_layer_ids"}


def read_pack(path):
    """(cfg, tensors) from a .pack: cfg is {key: value}, tensors is [(name, dtype, rows, cols, offset, nbytes)]."""
    with open(path, "rb") as fh:
        magic, version, idxlen = struct.unpack("<4sII", fh.read(12))
        assert magic == b"DF2P" and version == 1, (magic, version)
        index = fh.read(idxlen).decode("ascii", "replace")
    cfg, tensors = {}, []
    for line in index.splitlines():
        f = line.split()
        if not f:
            continue
        if f[0] == "cfg":
            cfg[f[1]] = f[2]
        elif f[0] == "t":
            name, dtype, rows, cols, offset, nbytes = f[1], f[2], int(f[3]), int(f[4]), int(f[5]), int(f[6])
            tensors.append((name, dtype, rows, cols, offset, nbytes))
        elif f[0] == "end":
            break
    return cfg, tensors


def unpack(path, work):
    """Dequantize every pack tensor into one safetensors, and write the config.json the reference loads."""
    cfg, tensors = read_pack(path)
    work.mkdir(parents=True, exist_ok=True)
    raw = Path(path).read_bytes()
    out, tmp = {}, work / "tensor.bin"
    for name, dtype, rows, cols, offset, nbytes in tensors:
        block = raw[offset:offset + nbytes]
        if DTYPES[dtype] is None:                                    # f32: the bytes are the values
            arr = np.frombuffer(block, np.float32).reshape(rows, cols)
        else:                                                        # a ggml quant: the tested path
            tmp.write_bytes(block)
            arr = R.load_dequant(str(tmp), rows, cols, DTYPES[dtype]).numpy()
        if name.endswith("base_kernel"):           # the pack flattens (prepare, finish) x kernel x H into rows x H;
            arr = arr.reshape(2, int(cfg.get("conv_kernel", 2)), cols)   # the reference indexes [which][o]
        out[name] = arr.reshape(rows) if cols == 1 else arr               # a 1-D norm is stored as (N, 1)
    st = work / "drafter.safetensors"
    stt.save_file({k: torch.from_numpy(v) for k, v in out.items()}, str(st))

    conf = {}
    for k, v in CFG_MAP.items():
        if k in cfg:
            conf[v] = float(cfg[k]) if k == "eps" else int(cfg[k])
    conf["rope_parameters"] = {"rope_theta": float(cfg.get("rope_theta", 10000))}
    conf["dflash_config"] = {}
    for k, v in DC_MAP.items():
        if k not in cfg:
            continue
        conf["dflash_config"][v] = [int(x) for x in cfg[k].split(",")] if k == "taps" else (
            float(cfg[k]) if k == "eps" else int(cfg[k]))
    conf["dflash_config"].setdefault("target_layer_ids", [5, 15, 25, 35, 45])
    cj = work / "drafter_config.json"
    cj.write_text(json.dumps(conf, indent=1))
    print("pack: %d tensors, %s -> %s (%.0f MB) | block %s, window %s, taps %s"
          % (len(out), Path(path).name, st.name, st.stat().st_size / 1e6,
             cfg.get("block"), cfg.get("window"), conf["dflash_config"]["target_layer_ids"]), flush=True)
    return st, cj, cfg


def target_tables(shard, work):
    """The target's embedding and head, dequantized to fp32 - the two tensors the drafter reads
    through (it embeds its own block rows and scores them with the target's head)."""
    rd = R.gguf.GGUFReader(str(shard))
    by = {t.name: t for t in rd.tensors}
    tables = {}
    for key, name in (("embed", "token_embd.weight"), ("head", "output.weight")):
        t = by.get(name)
        if t is None:
            sys.exit("%s has no %s (the drafter needs the target's embedding and head)" % (shard, name))
        p = work / ("%s.bin" % key)
        p.write_bytes(np.asarray(t.data).tobytes())
        q = t.tensor_type.name.lower()
        cols, rows = [int(x) for x in t.shape]                   # ggml shape is [n_embd, vocab]
        print("%s: %s %s %dx%d -> dequantizing ..." % (key, name, q, rows, cols), flush=True)
        t0 = time.time()
        tables[key] = R.load_dequant(str(p), rows, cols, DTYPES[q])
        print("%s: %.2f GB fp32 in %.0f s" % (key, tables[key].numel() * 4 / 1e9, time.time() - t0), flush=True)
    return tables["embed"], tables["head"]


def sequences(tapfile):
    """The tap dump split into conversations: a position run that restarts near 0 begins a new one."""
    layers, pos, tok, taps = R.read_taps(str(tapfile))
    runs, start = [], 0
    for i in range(1, len(pos)):
        if pos[i] <= pos[i - 1]:
            runs.append((start, i))
            start = i
    if len(pos):
        runs.append((start, len(pos)))
    return layers, [(pos[a:b], tok[a:b], taps[a:b]) for a, b in runs]


def walk(drafter, seq, feats, b):
    """One block size over one sequence, the way the verify loop runs it. Returns (rounds, tau,
    per-position conditional acceptance)."""
    n = len(seq)
    drafter.set_context(torch.from_numpy(feats))
    s, rounds, cond_ok, cond_n = 0, [], np.zeros(max(b - 1, 1)), np.zeros(max(b - 1, 1))
    with torch.no_grad():
        while s + 1 < n:
            room = min(b - 1, n - s - 1)
            if room < 1:
                break
            path = drafter.draft(s, seq[s], b)[0]
            truth = seq[s + 1:s + 1 + room]
            a = 0
            while a < room and int(path[a]) == int(truth[a]):
                a += 1
            for i in range(room):
                if i <= a:
                    cond_n[i] += 1
                    cond_ok[i] += (i < a)
            rounds.append(a + 1)
            s += a + 1
    return rounds, float(np.mean(rounds)), (cond_ok / np.maximum(cond_n, 1)).round(3).tolist()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pack", required=True, help="the shipped drafter .pack")
    ap.add_argument("--taps", required=True, help="a STRATA_TAP_FILE dump")
    ap.add_argument("--blocks", default="4,8,12,16,20,24", help="comma list of block widths (rows = 1 anchor + b-1 masks)")
    ap.add_argument("--shard", default="/home/eugene/Strata-data/models/heretic-IQ4_NL/"
                                      "Swift-1.5-Qwen3.8-Flash-Next-Heretic-V2-IQ4_NL-00008-of-00008.gguf",
                    help="the GGUF shard that carries token_embd.weight and output.weight")
    ap.add_argument("--work", default="/home/eugene/Strata-data/dflash2/sweep")
    ap.add_argument("--threads", type=int, default=max(1, (os.cpu_count() or 8) - 2))
    ap.add_argument("--seq", type=int, default=0, help="which conversation in the dump to walk (-1: all)")
    ap.add_argument("--json", default="", help="write the results here")
    a = ap.parse_args()

    torch.set_num_threads(a.threads)
    work = Path(a.work)
    st, cj, pcfg = unpack(a.pack, work)
    embed, head = target_tables(Path(a.shard), work)
    d = R.Drafter(str(st), str(cj), embed, head, threads=a.threads)

    layers, runs = sequences(Path(a.taps))
    if not runs:
        sys.exit("%s has no tap records" % a.taps)
    print("taps: layers %s, %d conversation(s): %s"
          % (",".join(map(str, layers)), len(runs), ", ".join("%d rows" % len(r[0]) for r in runs)), flush=True)
    want = range(len(runs)) if a.seq < 0 else [min(a.seq, len(runs) - 1)]
    blocks = [int(x) for x in a.blocks.split(",")]
    results = {"pack": str(a.pack), "blocks": blocks, "taps": str(a.taps), "layers": list(layers), "runs": {}}

    for ri in want:
        pos, tok, taps = runs[ri]
        n = int(pos.max()) + 1
        feats = np.zeros((n, taps.shape[1]), np.float32)
        seen = np.zeros(n, bool)
        for i in range(len(pos)):                     # the last record of a position wins
            feats[pos[i]] = taps[i]
            seen[pos[i]] = True
        seq = np.zeros(n, np.int64)
        seq[pos] = tok
        if not seen[0] and n > 1:
            feats[0] = feats[1]                       # row 0 rides the batched prefill: the next row stands in
            seen[0] = True
        miss = np.flatnonzero(~seen)
        if len(miss):
            print("run %d: %d positions missing taps (%s...), walking the covered prefix"
                  % (ri, len(miss), miss[:3]), flush=True)
            n = int(miss.min())
            feats, seq = feats[:n], seq[:n]
        print("\nrun %d: %d tokens" % (ri, n), flush=True)
        per = {}
        for b in blocks:
            t0 = time.time()
            rounds, tau, cond = walk(d, seq, feats, b)
            per[b] = {"rounds": len(rounds), "tokens_per_round": round(tau, 3), "cond_accept": cond,
                      "hist": np.bincount(rounds, minlength=b + 1).tolist()}
            print("  block %2d: %5d rounds, %.3f tokens/round, pos-accept %s  (%.0f s)"
                  % (b, len(rounds), tau, cond, time.time() - t0), flush=True)
        results["runs"]["run%d" % ri] = {"tokens": n, "blocks": per}

    if a.json:
        Path(a.json).write_text(json.dumps(results, indent=1))
        print("\nwrote %s" % a.json, flush=True)


if __name__ == "__main__":
    main()
