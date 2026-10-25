# Strata Mnemosyne — Strata with built-in long-term memory (Still in development not ready for everyday use yet) 

An 180-billion-parameter model running on a normal PC — one graphics card, some system RAM —
that **remembers**. Not in the client, not per-app: the memory lives at the inference server
itself, so every client (OpenCode, Claude Code, Codex, the web app) shares one store, and no
harness ever has to re-send history. The server remembers, and it remembers the same way no
matter which app is knocking.

This fork is based on upstream Strata 0.2.5 — app, Terminal and Control at 0.2.5 / 0.1.50, and every
engine package (Qwen and DeepSeek) rebuilt at 0.1.50 for this release, so a Qwen install now has a
newer engine to take. Upstream's own headline list for this round: **one installer per system**
(Windows and Linux no longer carry an engine — the first start names the one for your card and offers a
Download button, or "I already have the file" for offline), **DeepSeek V4.1-Flash in the app**, and a
**Speed choice** for DeepSeek — Faster uses 5 of the model's 6 experts per word and is the default on
16 GB of graphics memory or less and on shared-memory PCs (upstream measured +16% decode on an
RTX 5070 and +11 to 13% on Strix Halo, with no quality difference found on an MI325X). DeepSeek got the
bulk of the work: the RAM store can now hold every expert (it stopped at 48 GB; 12.6 → 21.4 tokens/s on
one R9700 with 251 GB), the CPU starts on experts it already has (+13.5% on an RTX 5070), and prompts
now always take the same path for the same length, which is what made answers drift between runs before.
**For the Qwen path there is one engine change:** on a single CUDA card with all experts in RAM, the
engine tries the asynchronous tier itself, measures it over 64 windows and keeps it only if it is not
more than 2% slower. The 0.2.3 round's Strix Halo gains, Intel Arc package, DFlash2 drafter,
full-context agent chat, OS certificates (#3722) and the CPU worker, VRAM and conversation-cache
defaults (#3493) all still stand. This fork adds the memory system and the reason-mode steering
described below.

## The two names, and they are not decoration

The project is **Strata**. Its built-in memory system is **Strata Mnemosyne** — Mnemosyne being
the Titaness of memory, mother of the Muses, and the literal root of the word *mnemonic*: the
store is named after memory itself. The assistant that recalls it — in the chat window, and in
the coding agent's tool calls — is **Clio** (KLEE-oh), the Muse of history: the one who decides
what gets recorded and what gets repeated. The split is architectural, not mythological
window dressing: storage is passive and curated; recall is the part with rules, budgets and
judgement. The mythology *is* the spec — a store that never forgets, and a retriever with
taste.

## Try it: Strata with memory

**Windows:** double-click `START-HERE.bat`. **Linux:** `./setup.sh`. Run it from a clone of
**this** repository's `memory-core` branch — the installer checks your PC, picks the model size
that fits your RAM, downloads it, and starts the server at `http://127.0.0.1:8005`:

```
git clone -b memory-core https://github.com/TheHubUser4860938/Strata-Mnemosyne.git
cd Strata
```

- **Runs on a gaming PC.** 32 GB of RAM and graphics memory together is enough to start.
- **Works with your tools.** Claude Code, Codex CLI, OpenCode and other agents connect through the OpenAI and Anthropic APIs.
- **Reads pictures**, on by default.
- **Free and private.** MIT license, no account, no cloud, no telemetry ([what it downloads and when](docs/SAFETY.md)).

<img width="1877" height="638" alt="image" src="https://github.com/user-attachments/assets/5cae0570-fb69-4665-a59d-92a1c0eff5f7" />

<img width="1278" height="263" alt="image" src="https://github.com/user-attachments/assets/f6f63206-afdb-439a-a9d4-d58ce0ee054a" />

Version 0.2.4.2 (Terminal and Control 0.1.49.2) · Qwen engine 0.1.48 · app 0.2.3

<img width="1879" height="434" alt="image" src="https://github.com/user-attachments/assets/1643c829-dc1b-43f5-9952-0d5c4f67f924" />

Two things arrive switched **on**, and everything else stays byte-identical to upstream Strata:

- **Memory.** On by default in this fork — someone who does not want the built-in memory
  system would not be using this fork to begin with. Setup writes the block below (paths into
  the one data folder beside the install, or wherever `--data-dir` put it) and fetches the
  embedder it ships with, so hybrid recall works out of the box. To turn it off, set
  `"memory": { "enabled": false }` — every path then returns to upstream Strata, byte for byte:

  ```json
  "memory": { "dir": "Strata-data/memory",
              "embedder": { "name": "bge-small-en-v1.5",
                            "dir": "Strata-data/embeddings/bge-small-en-v1.5" } }
  ```

  (`name` picks the model class — the only one shipped in the default setup is bge-small; the
  dev box runs `embeddinggemma-2` behind the same block, and an unknown name **raises** rather
  than quietly falling back. Changing `name`/`dir` means re-embedding the store:
  `python -m serve.reembed --store DIR --dir EMBDIR`.)

  or start the server with `--memory Strata-data/memory`. When it is live the boot banner
  prints `[strata] memory core on: ...`, and `http://127.0.0.1:8005/memory-ui` is the store's
  own page — stats, search, forget. The embedder (pinned by SHA-256, MIT, ~130 MB, CPU-only —
  it never touches the GPU your model owns) is what lets recall understand paraphrase;
  without it recall stays lexical and everything else still works. The dev box's store
  switched the same way to `embeddinggemma-2` (Apache-2.0, 768-d, 8K context, 314 MB q8) on
  2026-10-24; every banked venue number still carries its *bge-small era* label until a
  venue day re-records it.

- **Reason modes** (DavidAU model families — see below): 41 framings, pairs, thinking levels
  and an autonomous picker — the server boots already knowing how to consult its own cast
  list. The banner prints `reason modes on: ...`; `http://127.0.0.1:8005/reason` is the live
  view.

This fork listens on **port 8005** where upstream uses 8080/8095, so a mainline Strata install
and a memory install can run side by side on the same PC.

**At least 32 GB of memory: RAM and graphics memory (VRAM) together.** On a Mac or a Ryzen AI Max that is the unified
memory. A 32 GB PC with a 12-16 GB card runs the smaller sizes, and 64 GB runs every size.

| Works on | Guide |
| --- | --- |
| **NVIDIA** GeForce RTX 20, 30, 40 and 50 series, 12 GB or more | [Install](#install) |
| **AMD** Radeon RX 6800 and newer, Radeon AI PRO R9700 | [AMD cards](docs/AMD_HIP.md) |
| **Intel** Arc | [Intel Arc](docs/INTEL_ARC.md) |
| **Apple Silicon Mac**, M1 or newer, macOS 15 or newer | [Mac](docs/MAC.md) |
| **AMD Ryzen AI Max (Strix Halo)** and other unified-memory PCs | [Strix Halo](docs/STRIX_HALO.md) |
| Older cards and processors | [Older GPUs](docs/OLDER_GPUS.md) |

You also need about 80 GB of free disk (an SSD), Windows 10 / 11, Linux or macOS, and a current graphics driver. Two or
three cards of the same make can share a model ([multi-GPU](docs/MULTI_GPU.md)).

## Install

### 1. The Strata app (easiest)

Download the file for your computer, open it, and press install on the model it recommends.

**Windows 10 / 11**

[![Windows](https://img.shields.io/badge/Windows-10%20%2F%2011-0078D4?style=for-the-badge&logo=windows&logoColor=white)](https://github.com/Niko1221/Strata/releases/latest/download/Strata-0.2.5-windows-x64-setup.exe)

**Linux**

[![Linux](https://img.shields.io/badge/Linux-AppImage-FCC624?style=for-the-badge&logo=linux&logoColor=black)](https://github.com/Niko1221/Strata/releases/latest/download/Strata-0.2.5-linux-x86_64.AppImage)

**Mac** (Apple Silicon, macOS 15 or newer)

[![Mac, Apple Silicon](https://img.shields.io/badge/Mac-Apple%20Silicon-333333?style=for-the-badge&logo=apple&logoColor=white)](https://github.com/Niko1221/Strata/releases/latest/download/Strata-0.2.5-macos-arm64.dmg)

The app picks the right engine for your graphics card by itself. All files are on the [releases page](https://github.com/Niko1221/Strata/releases/latest).

| First start | What to do |
| --- | --- |
| **Windows** | Run the `.exe`. No administrator rights needed. If Windows says "Windows protected your PC", choose **More info**, then **Run anyway**. |
| **Linux** | `chmod +x` the file and start it. It needs FUSE 2: `sudo apt install libfuse2t64` (Ubuntu 24.04 and newer) or `libfuse2` (22.04). |
| **Mac** | Open the `.dmg` and drag Strata onto Applications. |

The model download is big (40-70 GB). If it stops, it continues where it left off.

### 2. The Terminal (one line)

The `strata` command, for scripts, servers and AI agents. It is also the way to run DeepSeek.

Linux and Mac:

```sh
curl -fsSL https://github.com/Niko1221/Strata/releases/latest/download/install.sh -o install.sh && sh install.sh
```

Windows (PowerShell):

```powershell
irm https://github.com/Niko1221/Strata/releases/latest/download/install.ps1 | iex
```

Then start it. It asks one question at a time (model, context, pictures, who may connect), downloads what it needs and
starts serving:

```sh
strata launch
```

No admin rights needed. The install checks the SHA-256 of everything it downloads. On Windows, open a new terminal window
after the install. All screens and flags: [docs/TERMINAL_LAUNCH.md](docs/TERMINAL_LAUNCH.md).

### 3. Let your AI set it up

Paste this into Claude Code, Cursor, Codex, GitHub Copilot or another coding assistant:

```text
Set up Strata with its built-in memory (Strata Mnemosyne) on this PC for me:
https://github.com/TheHubUser4860938/Strata-Mnemosyne - use the memory-core branch, follow
docs/AI_SETUP.md in that repository. The memory is ON by default on that branch, and setup
fetches its embedder as part of the install.
Before reporting done, verify the boot banner says "memory core on" (and, on a DavidAU
install, "reason modes on"), and /memory-ui answers.
```

The agent can also drive install/start/stop through Strata's [MCP server](docs/MCP_SERVER.md).

## What's new — the thinking, on a dial

DavidAU's re-quant of Qwen3.8-Flash-Next ships with a chat template that answers to a
`{REASON:name}` tag, and the cast list reads like a convention badge rather than a config
file: **DevOracle**, an architect who cannot resist proposing a refactor; **House**, who
diagnoses first and is pleasant later; **Curie**, lab notebook before opinions; **Socrates**,
who would rather ask you a better question than answer this one; **Every Joe**, who never met
a jargon term he didn't translate; **007**, whose licence to improvise expires when the task
is done; and **einstein+pkd**, who suspects the cartridge is a simulation — a reasonable
paranoia, given the research below.

The abliterated family's ancestry, because credits belong in the story: it descends from
[SC117](https://huggingface.co/SC117/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-GGUF)'s abliterated GSQ-RCO
build — the refusal direction removed by tensor transplant, copying [orcarouter](https://huggingface.co/orcarouter/Qwen3.8-Flash-Next-Uncensored-GGUF)'s
abliterated weights into ISTA-DASLab's already-learned quantization without recomputing a single value —
and DavidAU's build is assembled on that file.

Forty-one framings in all, and this fork turned the tag
that summons them into a steering system:

- **Pairs.** `joe+comedy` thinks like the first and answers like the second; `stark+coder`
  draws the architecture and ships the files. The server splices both constructs mechanically,
  so the grammar works through any door: a client tag, the `reason_mode` tool (agents steer
  themselves mid-task), or the Settings menu — which applies live, no restart.
- **Autonomous mode — the default.** `auto` picks the construct per request, scored against
  the template author's own use-case map: the map that says `curie+teacher` for explanations
  and `musk+business` for physics-first strategy. No confident match, no pick — it never
  guesses. A conversation can pin a mode over it, a client tag outranks everything, and
  `GET /reason` shows what actually framed each conversation, including when a tag overruled
  the picker.
- **Honest about what it can claim.** Three sweeps over the published suites (GSM-Symbolic,
  MATH-500, HumanEval, five BIG-Bench Hard tasks, GPQA-diamond) — 3,168 generations, twelve
  arms, at temperature 0 and at the model's recommended 1.0 — found **no mode beats the
  default on accuracy beyond the ±0.05 band**; coder alone measurably *costs* it (−0.07), the
  reasoning-family arms land inside the noise (einstein's 0.95 best observed), and the dial
  steers voice, structure and behaviour — never performance (full record: docs/MEMORY_CORE.md).
  For the model itself: on the full 198-question GPQA-diamond set it scores **0.843** (physics
  0.93, chemistry 0.78, biology 0.74; no framing, temp 0) — ISTA's card claims 0.929 for the
  stock IQ3_S on their harness; the free-agent run, the model unrestrained with search and
  memory in hand, will say how much of that gap is dress, harness, or nothing.
- **Tuned on live traffic, the same day it shipped.** The first evening of autonomous mode
  produced a transcript audit: two turns rode a stale frame because the *agent* pinned a mode
  and forgot to re-check — and a cold replay of the picker scored the right construct 2-for-2
  on the misses. So pins now say what they freeze, pair splices carry a wrapper-arbitration
  bridge, and the internal machinery (curation loop, benchmark harness) got its own opt-out
  tag — measured, it had been carrying 2,227 tokens of persona block per prompt. The cast is
  for the user; the staff room stays professional.

  And if you want to hear the cast at full volume: the staff room wrote a second README —
  **[docs/README_MASHUP.md](docs/README_MASHUP.md)** — neo thinking, House diagnosing, Vader
  commanding. Same numbers, different clothes; it is the fastest way to see what the dial
  actually does to the voice.

**Where it stands, read from the store's own stats on 2026-10-23:** **966** live rows across 138
shelves (one row still unclassified), 1,521 retired rows behind them, 2,508 journaled turns, and
the invariant holds — the embedder reports 966 vectors for 966 live rows. The store now runs on
**native PostgreSQL** (ADR-002, the owner's decision 2026-10-16): psycopg 3, no SQLite backend, no
dialect shim, no dual-backend matrix. The measurements that justified it are on the record —
1.6 ms a query at 2,707 rows, a fresh test database in 3 ms, the whole live store loaded in 0.03 s —
and the encrypted `pg_dump` backup round-trips (1.7 s, restore byte-verified by identical lexical
rankings). Encryption at rest is the honest shape for a server database: a 0700 data directory plus
a key file, so a running store is readable by whoever owns the machine and a stopped one is only as
private as that directory. The persona layer has its own constitution (`soul.md`, V4) and its own
budget gate — 14,000 characters, the owner's numbers, raised from 6,000 on 2026-10-20 and to 14,000
on 2026-10-21 — and it fails closed to the plain path when it overflows.

## How it works today

**Tier 3 — curated text memory (live).** ~930 facts on 134 subject shelves (plus 24 index
cartridges cataloging the map), recalled server-side and injected as one hidden system block
that rides all three dialects (OpenAI, Anthropic, Responses). A journal feeds itself from
conversations; a curation loop classifies, dedups and consolidates with human-gated merge
review, and relabels the index cartridges every 30 minutes; a budget speaks before it's full;
`?since=`/`?until=` windows answer when-said questions; a CPU-only embedder (pinned by SHA-256,
MIT, ~130 MB) makes recall understand paraphrase. Opt-in: the model browses its own store
mid-answer with a `memory_search` tool the server runs itself — one tool, three verbs: search
with words, ask for the card map of the shelves (counts, dates, curated labels), or walk a
shelf newest-first — no client wiring.

**Measured head-to-head (2026-10-24 venue, same fixture, same judge):** browsed **0.682** vs
served **0.666** — browsing wins the judgment classes (abstention +0.20, multi-session +0.12),
being served wins the summaries (preference 0.69 -> 0.20 when the model must fetch what the
block used to digest), and the countersigned ruling is HYBRID: block default, verbs as the
escalation path. One sentence of honesty ships with it: when the block is off, the server SAYS
so, because a hidden store that never announces itself buys free "idk"s — two revisions of that
sentence moved the 20-question pilot 0.25 -> 0.70.

**Reviewed line by line (2026-10-24):** an outside model's read of this branch was checked against
the code rather than the prose, and ten fixes came out of it — the router's demote arm now honours
the shelf-boundary law instead of `startswith`, the `hits` ledger counts the lines a model actually
read instead of every candidate a search returned, an address that names no shelf stops quietly
widening to the whole store, the long-scope and deep-call-number columns stop being cut in half
inside the vector matrix, and the standing cartridge re-installs its prefix when the engine process
behind the slot changes instead of reporting a warm prefix no slot holds. Receipts, with the numbers
and the two doc claims the review got wrong: `docs/MEMORY_CORE.md`, "The 2026-10-24 review round".

**What it measures like, on LongMemEval-V1 (oracle, 500 questions × 3 repeats):** the built-in
memory answers **0.72** correctly at the shipped budget. The control line is the one to trust:
with memory muted, **98.4–98.7% of answers are `idk`** and gold leaks 2 in 1,500 — the model is
recalling, not confabulating. Recall splits honestly: single-session 0.91–0.95, preferences
0.90, knowledge-update 0.75, multi-session 0.74, abstention 0.78, temporal arithmetic 0.43 —
and the one intervention ever measured to move that weak spot (writing facts with absolute
dates) gained **+0.207** on the same 127 questions, McNemar p ≤ 1.2e-12, and it ships in the
curation loop. Full protocol and records: `docs/MEMORY_CORE.md`.

**Tier 2 — KV cartridges (built, and riding on a big-RAM box).** The standing texts are seeded once
as an engine session file and stand in the slot ahead of the traffic that continues them: restore
**81 ms** for 247 MB, the pin law **refuses foreign files** by config fingerprint, and the knowledge
delta is real — warm 3/3 correct, cold 3/3 `idk`, wrong-cartridge control 0 leaks. The RAM gate is
met on this box now: 125 GB since 2026-10-22. What rides live since 2026-10-24 is the five-file
static cart — the soul plus agent/skill/user/always, 237 MB, `MEM-CRG-22c49c0c.bin`, standing in
the slot (`kv_standing` true at the 19:37 boot); the 63-fact soul+facts cart it replaced restored
285 MB in **150.3 ms** (the engine's own line: read+check 142.0 ms).
What is *not* claimed: prefill skipped for strangers (engine resume extends one conversation, not
across them — measured, and the docs say so). The venue re-record that would settle its economics
is unblocked and queued.

**Phase 2 — state-without-text (open research).** Porting the *AKBASCORE MAM / NIRVANA
cognitive cartridge* idea — knowledge stored as model-produced K/V and read back with no source
text in the prompt. Upstream:
[ceceli33/titan-cognitive-core-v2](https://github.com/ceceli33/titan-cognitive-core-v2)
(records I–III: 7B, Mistral parity, and Qwen2.5-72B on one A100, K/V bitwise-stable under
appends; Zenodo DOIs [23127434](https://doi.org/10.5281/zenodo.23127434),
[23143605](https://doi.org/10.5281/zenodo.23143605),
[23146475](https://doi.org/10.5281/zenodo.23146475),
[23311350](https://doi.org/10.5281/zenodo.23311350),
[23381336](https://doi.org/10.5281/zenodo.23381336),
[23434686](https://doi.org/10.5281/zenodo.23434686)). The authors' own boundary governs how we
read it: semantic transfer is **not** claimed, and the open question they raise — extension to
"architectures with substantially different attention mechanisms" — is exactly this fork's
blocker: on the 180B MoE here (125B of language model plus 51B of n-gram embedding plus 4B of MTP —
the three numbers you see floating around the cards are the same model counted three ways; 512
experts, 10 active per token; 36 Gated DeltaNet layers + 12 sparse-attention layers, quantized
KV), state-without-text is research, not a result. Positive *and* negative results land in
`docs/MEMORY_CORE.md`.

Setup checks your graphics card, RAM and disk, picks the model that fits, installs and starts it, and tells you how to
connect your apps.

Where your PC has RAM to spare, setup no longer locks the n-gram table into RAM by itself: it asks. Locked in RAM
(`--ple-io ram`) a fresh 4K prompt arrives about 18% sooner on a fast card (measured) — at the table's own size in RAM
the experts cannot use; read from the SSD (the engine's default) only the rows each batch needs come off the drive and
the RAM stays free. Either answer is recorded as your own option in the model's config (`user_args`), so no later
setup run rewrites it by formula; `--ple-io ram|ssd` on the command line answers for you.

And a second model, or a setup rerun on the first, no longer resets the memory system: the box's memory block — the
store's folder, the recall budgets, the embedder, the measured knobs you turned on — is carried into the new config.
Only the tier-2 cartridge gate re-decides, for the new model's RAM.

Prefer to build it yourself? See [Build from source](#build-from-source).

## Models

The app and `strata launch` recommend a size for your memory. Smaller sizes are faster, larger sizes are a bit smarter.

### Low on memory? Start with Gyro

[Gyro](https://huggingface.co/agentionai/Qwen3.8-Flash-Next-Gyro-GGUF) by agentionai is the smallest way to run
Qwen3.8-Flash-Next. It runs on NVIDIA, AMD, Intel Arc and Apple Silicon.

| Size | Memory it needs (RAM + VRAM) | Download | Good for |
| --- | ---: | ---: | --- |
| **Gyro-S** | 27.6 GB | 58.5 GB | PCs that fit nothing else. 9 tokens/s on a 32 GB Mac mini. |
| **Gyro-M** | 35 GB | 92.0 GB | About IQ3_XXS quality with 20% less GPU memory. |

Start it with `strata launch --model gyro-s`. Details: [docs/GYRO.md](docs/GYRO.md).

### Qwen3.8-Flash-Next sizes

| Your memory (RAM + VRAM) | Take | Why |
| --- | --- | --- |
| **32 GB** | **Gyro-S**, or the **[Coder](docs/MODELS.md#coder)** for code | The Coder keeps the experts that code uses |
| **40 GB** | **[Swift 1.5](docs/MODELS.md#swift-15)** IQ2_XS (39.2 GB) or **Gyro-M** | Swift thinks for a shorter time before it answers |
| **48 GB** | **IQ3_XXS** (47.0 GB) | Slower, better |
| **64 GB** | **IQ3_S** (54.8 GB) | Matches the full model on the published tests |
| **96 GB or more** | Unsloth's **UD-IQ4_XS** to **Q8_0** | Closest to the full model |

Less RAM than a row says can still work, only slower: Strata switches to its
[low-RAM mode](docs/MODELS.md#a-big-graphics-card-and-little-ram) by itself. Also available:
[NVFP4](docs/NVFP4.md) for NVIDIA cards, [Qwen3.6-35B-A3B](docs/QWEN36.md) (smaller, several requests at once) and
[OrcaRouter's Uncensored IQ3_XXS](docs/MODELS.md#orcarouter-uncensored-iq3_xxs). Every size and what fits where:
[docs/MODELS.md](docs/MODELS.md).

And three this fork added to setup's menu (`--family ...`), in the order the menu shows them — qwen, swift, coder, dau, daureg, unsloth, huihui, gyro, nvfp4, qwen36:

- **Turbo-Brilliance, abliterated** ([DavidAU](https://huggingface.co/DavidAU/Qwen3.8-Flash-Next-Abliterated-Uncensored-Turbo-Brilliance-50x-Reasoning-Instruct-GSQ-RCO-GGUF), `--family dau`) is the IQ3_S that answers the `{REASON:}` dial described above: 41 framings, pairs, thinking levels and an autonomous picker. It is DavidAU's build on [SC117](https://huggingface.co/SC117/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-GGUF)'s abliterated GSQ-RCO quant — his shard sizes agree with SC117's plus the transplant's signature, so it is a derivative of that file, not the original quant. Same size and speed as IQ3_S. Apache-2.0 on DavidAU's release, Qwen Community License 1.0 underneath.
- **Turbo-Brilliance, regular** ([DavidAU](https://huggingface.co/DavidAU/Qwen3.8-Flash-Next-Turbo-Brilliance-50x-Reasoning-Instruct-GSQ-RCO-GGUF), `--family daureg`) is his re-quant of the original IQ3_S without the refusal-shaping removal: the same dial, the same size and speed as IQ3_S, the same licenses.
- **Huihui, abliterated** ([huihui-ai](https://huggingface.co/huihui-ai/Huihui-Qwen3.8-Flash-Next-abliterated-v2-GGUF), `--family huihui`) is their re-quant of their own abliterated model in the Unsloth Dynamic sizes (94 to 188 GB of download): it answers plainly where the original declines. The dial does not ride it — its chat template is the stock one, and the server says so with a banner at boot — but the memory system and the picture reader work as usual. Qwen Community License 1.0.

Every size, download and what fits where: [docs/MODELS.md](docs/MODELS.md).

### The n-gram table: a bigger one is optional

Every file of this model carries its n-gram lookup table at IQ4_NL: measured against the model's own
BF16 table it misremembers rows at 0.076, where the Q8_0 table sits at 0.0053 — fourteen times truer
(the labs' numbers, cross-checked against each other's quants). The table is one trained tensor, the
same in every quantization of a family tree, and Q8_0 takes no imatrix, so one 54.4 GB file per tree
serves every quant of it on your PC. Setup offers it as **`--ple-q8 on`** (an interactive setup asks;
`--yes` and the app take the bundled table, as always):

- On the two-file GSQ-RCO families (qwen, coder, dau, daureg) the Q8_0 downloads **as the model's second
  file, in that file's place and name** — the IQ4_NL file is never fetched, so the table costs 54.4 GB
  instead of 28.8 and nothing else changes. This is the shape the fork's own 125 GB box has run since
  2026-10-09.
- On the four-file Unsloth families (unsloth, huihui) every file stays: the table rides beside them and
  is read by `--ple-gguf`, with all four shards enumerated as dense projections — without that the
  engine refuses an outside table ("additional shard must match the architecture-validated first
  shard's split metadata"), measured on this fork's box 2026-10-23.
- One file per tree, pinned by size and SHA-256 (sleepyeldrazi's for the GSQ-RCO tree, mduca771's for
  the Unsloth one — his IQ4_NL sibling is the families' own bundled shard 2 byte for byte, which is what
  makes the same-table-better-precision claim checkable). A PC that already owns a table of the pinned
  size links it instead of downloading it twice, and a swapped slot is checked against the table's own
  pin — a swap you made by hand included, so it survives every later setup run.

Swift, Gyro and NVFP4 bring their own tables and are never asked.

For swift models you can run them with the Q8 PLE N-gram table adjust your .json file to look like this.

  "--native",
  
  "Strata-data/models/swift-IQ3_S/Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf",
  
  "--native-dense-gguf",
  
  "Strata-data/models/swift-IQ3_S/Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00001-of-00002.gguf",
  
  "--native-dense-gguf",
  
  "Strata-data/models/swift-IQ3_S/Swift-Qwen3.8-Flash-Next-GSQ-RCO-IQ3_S-00002-of-00002.gguf",
  
  "--ple-gguf",
  
  "/Strata-data/models/IQ3_S/Qwen3.8-Flash-Next-Q8PLETable.gguf", 
  Change to the name of the Q8 PLE table.

### DeepSeek V4.1-Flash (Terminal, from 0.2.4)

[DeepSeek V4.1-Flash](https://huggingface.co/ISTA-DASLab/DeepSeek-V4.1-Flash-1017-GSQ-RCO-GGUF) is a different, much bigger model. ISTA-DASLab made the three sets below. Strata runs them on a PC with one 12 GB graphics card and 46 to 64 GB of RAM, and reads the rest from your SSD. It runs on NVIDIA RTX 30 to 50 cards and on the Radeon AI PRO R9700. It uses its own engine package, `strata-dsv41`, which `strata launch` downloads when you pick DeepSeek. The desktop app does not offer it yet.

| Set | Download | Quality | Writes code at |
| --- | ---: | --- | --- |
| **IQ1_M** (1.75 bits) | 239 GB | The smallest; weaker on plain prose | not measured on a PC yet |
| **IQ2_XXS** (2.00 bits) | 257 GB | Good balance | 10 tokens/s (RTX 3060), 5 (RTX 5070), 48 (4x R9700) |
| **IQ2_XS** (2.25 bits) | 274 GB | Closest to the original | 15 tokens/s (one R9700), 80 (4x R9700) |
| **IQ4_NL** (Engram table) | in every download above | The lookup table all three sets share | |

Start it with `strata launch --model ist-das-2.00bpw` (or `ist-das-1.75bpw`, `ist-das-2.25bpw`). Quality numbers, speeds
per PC and the manual install: [docs/DEEPSEEK41.md](docs/DEEPSEEK41.md).

## How fast is it?

Based on a 12 GB graphics card (RTX 5070, 64 GB RAM). Results from other cards:
[speed of each model](docs/MODELS.md#how-fast-is-each-size) and [community results](docs/COMMUNITY_BENCHMARKS.md).

| Model | Answers appear at | Reads your prompt at |
| --- | --- | --- |
| **Q2_0** | `████████████` 94 tokens/s | `████████████` 2,650 tokens/s |
| **IQ2_XS** | `██████████░░` 79 tokens/s | `█████████░░░` 2,090 tokens/s |
| **IQ3_XXS** | `████████░░░░` 62 tokens/s | `████████░░░░` 1,750 tokens/s |
| **IQ3_S** | `███████░░░░░` 53 tokens/s | `███████░░░░░` 1,620 tokens/s |
| **Coder** | `███████░░░░░` 55 tokens/s | `██████████░░` 2,180 tokens/s |

On a 16 GB AMD card (RX 9070 XT, 47 GB RAM):

| Model | Answers appear at | Reads your prompt at |
| --- | --- | --- |
| **Q2_0** | `████████░░░░` 60 tokens/s | `█████░░░░░░░` 1,160 tokens/s |
| **IQ2_XS** | `███████░░░░░` 52 tokens/s | `█████░░░░░░░` 1,110 tokens/s |
| **Coder** | `██████░░░░░░` 44 tokens/s | `██████░░░░░░` 1,420 tokens/s |

A token is about ¾ of a word, so 60 tokens per second is faster than you can read. "Reads your prompt" is how fast Strata
takes in a long document, code or chat history.

## Status — beta-1 (Linux)

The claim list, what each measurement was run on, and what beta-1 refuses to claim:
[`docs/BETA1.md`](docs/BETA1.md). The engine-heavy queue — benchmark re-record on the current
weights, cartridges — was waiting on the RAM upgrade, and the RAM upgrade landed on 2026-10-22:
this box now has **125 GB**, KV streaming is on (`--kv-resident 32768`), and the engine's own
counters moved — expert cache 5,709 → 7,236 slots, decode-cache hit rate 87.0-87.4% → 93.3%,
traffic served over PCIe 3.4-3.6% → 1.5%. No speed number is claimed from that: mixed traffic, no
repeats, and the protocol is temperature 0.8/1.0 with at least three repeats before anything is
said. Huge pages were tested and reverted the same day — the reservation ate the page cache, and
the arena was already running on 2 MiB pages through transparent huge pages. The
memory-and-tooling line shipped six releases on October 17 alone: pairs, thinking levels,
autonomous mode, the Settings menu, auto-pick observability and the store purge above. The
full-size intelligence run — five published suites at full size, 21,336 generations, temperature
1.0, three repeats — was launched on 2026-10-22 and has not landed a number yet. The server's own
test suite — 1,163 tests under this repo's runner, no GPU and no downloads needed — passes clean on
this box: measured 2026-10-24, `python -m pytest serve/` gives 1,163 passed, 20 skipped, 10,856
subtests in 6 m 06 s. The note this sentence carried for a week — two environmental timing tests,
the `test_lifeline` watcher and `test_keepawake` inside a full run — did not reproduce that day, so
it is now recorded as what it is: a flake on a loaded box, not a fixture of the suite. The suite also
leaks one 2 GB Postgres cluster per test process into `$TMPDIR` (its atexit cleanup stopped the
cluster and never deleted the directory); 48 of them filled this box's 63 GiB `/tmp` to 100% and
killed a run with `psycopg.errors.DiskFull`. Fixed 2026-10-24: the fixture now stops the cluster and
deletes the directory, and the box came back from 11 MB free to 61 GB.

Engine and server changes live on the `memory-core` branch; `main` stays a near-mirror of
[upstream Strata](https://github.com/Niko1221/Strata) (MIT, by Niko1221). MAM-derived code
carries the attribution and license terms of the AkbasCore repository (Copyright © 2026
Mustafa Akbaş).

**Who wrote this code:** most of it was typed by AI coding agents under a human's direction.
The human picks the direction, owns the claims, and runs every measurement on real hardware
(RTX 4090, Ryzen 7 9800X3D — 62 GB RAM class through 2026-10-21, 125 GB since 2026-10-22, so
every number before that date was measured on the smaller box); each number in
this fork links to the script and raw output that produced it, so anyone can re-check it
whether or not an AI typed the driver.

---

### In the app

Chat, a **Monitor** of the model and your GPU, CPU and RAM, a **Models** page and **Settings**. The chat can work in a
folder on your PC. In **Manual** mode it asks before it changes a file or runs a command. It can search the web
(DuckDuckGo or Bing, no account); the search words are the one thing that leaves your PC.

<p align="center"><img src="docs/media/app-chat.png" width="900" alt="The Strata app: a chat where the agent built a small voxel pagoda garden, with the page open in the preview on the right"><br>
<sub>The agent wrote a voxel pagoda garden as one HTML file, and the page opens in the preview next to the chat</sub></p>

### In the Terminal

<p align="center"><img src="docs/media/terminal-monitor.png" width="900" alt="The Strata Terminal monitor overview while the model writes a reply"><br>
<sub><code>strata monitor</code> while the model writes a reply: speed, GPU, memory and the recent requests</sub></p>

```sh
strata launch                              # guided: model, context, pictures, access, then serve
strata launch --model q2_0 --yes --no-tui  # no questions: serve and print the address
strata launch --status                     # what is being served now
strata launch --stop                       # stop it
strata monitor                             # watch speed, GPU, memory and requests
strata update                              # get the newest engine
strata doctor                              # check the installed files
```

To reach Strata from your phone or another PC, use `strata launch --access lan`. It makes an API key for you.
`strata --help` lists everything, and [docs/TERMINAL.md](docs/TERMINAL.md) explains it.

### With AI agents and other apps

An agent installs Strata with the one-line command above and runs `strata launch --model NAME --yes --no-tui`. Steps,
flags and exit codes: [docs/AI_SETUP.md](docs/AI_SETUP.md). Repository rules for agents: [AGENTS.md](AGENTS.md).

| Your app speaks | Base URL |
| --- | --- |
| OpenAI API (most apps and agents) | `http://127.0.0.1:8080/v1` (any API key, any model name) |
| Anthropic API (Claude Code) | `http://127.0.0.1:8080`, without `/v1`. Claude Code: `ANTHROPIC_BASE_URL=http://127.0.0.1:8080` |
| OpenAI Responses API (Codex CLI) | `http://127.0.0.1:8080/v1/responses` ([setup](docs/DETAILS.md#the-responses-api-and-codex-cli)) |

`strata connect` prints the exact settings for OpenCode, Codex CLI, Claude Code, oh-my-pi, pi, Hermes Agent and OpenClaw,
and `strata connect opencode --write` writes them for you (with a backup).

### Good to know

- **Pictures** are on for every model that can read them. Attach or paste one in the chat, or send it from your app. Details: [docs/IMAGES.md](docs/IMAGES.md).
- **Thinking** can be off, low, medium or high, in the chat menu or your app's "reasoning effort". Off is fastest.
- **The first message** of a chat is read in full, about 1 minute per 30,000 tokens. Follow-ups start in seconds.
- **One request at a time** by default. For more, use `--parallel N` ([BATCHING.md](docs/BATCHING.md)). On a 12 GB card each answer gets slower.

## Build from source

<details>
<summary>Windows, Linux and Mac from the repository</summary>

[Download Strata](https://github.com/Niko1221/Strata/archive/refs/heads/main.zip) and unzip it, or `git clone` it.
**Windows:** double-click `START-HERE.bat`. **Linux:** run `./setup.sh` in the Strata folder.

**Mac (Apple Silicon, macOS 15 or newer):** install Apple's Command Line Tools once with `xcode-select --install`
(Xcode itself is not needed). Open Terminal in the Strata folder and run `./setup.sh`. It builds the Mac engine on your
Mac (about 7 minutes), asks the same questions, downloads the model and starts it. Next time, `./setup.sh` starts it
right away. Which size fits your Mac: [docs/MAC.md](docs/MAC.md).

The installer finds your card and sets up the right engine. It asks which model and size, how much context (how much text
the model keeps in mind) and whether it should read pictures. Press Enter for the recommended answer. Then it downloads the
model (about 70 GB) and starts it. If the download stops, run it again and it continues. Your browser opens the Strata
page at `http://127.0.0.1:8080`.

> While the model starts, your PC can be slow or stop responding for 1-3 minutes (longest the first time). Strata loads
> 35-55 GB into your RAM and locks part of it for the graphics card. Wait, and don't close the window.

Next time, run `START-HERE.bat` (or `./setup.sh`) again. It starts right away and downloads nothing twice. Close its
window to stop the model. `UPDATE.bat` (`./update.sh`) updates Strata without starting it. Updating, Docker, several cards,
where the files go and every option: [docs/INSTALL.md](docs/INSTALL.md).

To measure your PC, run `BENCH.bat` (`./bench.sh`). It takes 5-10 minutes and writes a report you can share
([how](docs/COMMUNITY_BENCHMARKS.md#run-the-benchmark)).

**Optional: more speed on one card when the whole model fits in RAM.** Two opt-in settings by RubenTorney (#1904, #1905).
They help when you run one graphics card and your RAM holds every expert, for example Q2_0 or IQ3_XXS on a 64 GB PC. Open
`strata-<model>.json` in the Strata data folder ([where](docs/INSTALL.md#where-things-are-stored)) and add:

- `"--adapt-async", "1"` to the `"args"` list. The expert cache then updates on a helper thread instead of pausing the
  answer. Measured on an RTX 5070 (Windows, Q2_0): +4-5% decode, +7-10% on code and long documents. Answers can differ
  slightly from the default and stay the same from run to run.
- `"STRATA_PIN_BY_NEED": "1"` in the `"env"` block (Windows). Windows can lock only about half the RAM for the graphics
  card, and this locks the experts the card needs first. Measured on the RTX 5070: +4.4% prompt reading.

```json
"args": [ ..., "--adapt-async", "1" ],
"env": { "STRATA_PIN_BY_NEED": "1" }
```

Restart Strata after the change. To undo, remove the two entries.

</details>

## How does it work?

Models like this one usually run on servers with hundreds of gigabytes of graphics memory. Your graphics card has
12-24 GB. Strata makes the model fit by sharing the work across your whole PC. Picture a library.

- The model is a team of 24,576 small specialists ("experts"), like 24,576 reference books. Each word needs only 10 of them.
- **Your graphics card is the desk.** It is small and fast. The roughly 4,000 books used most often lie open on it.
- **Your RAM is the shelves in the reading room.** All 24,576 books are there. When a word needs a book that is not on the
  desk, your processor reads it from the shelf at once, while the card keeps working.
- **Your SSD is the archive.** It holds a 29 GB lookup table. The model reads a few rows of it per word, so it does not
  need to sit in RAM.

<p align="center"><img src="docs/media/how-it-works.svg" width="860" alt="The model's 24,576 experts: the busiest on the graphics card, all of them in RAM, a lookup table on the SSD"></p>

A small helper also guesses the next few words. The big model checks all of them at once and keeps the right ones. You get
the same answer, 1.6-1.8x sooner. Long texts are read in big pieces, up to 8,192 tokens at a time, at over 1,000 tokens
per second.

<p align="center"><img src="docs/media/guess-and-check.svg" width="860" alt="A small helper guesses the next words; the big model checks them all at once and keeps the right ones"></p>

The longer explanation: [docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md). Every part and its numbers:
[the details](docs/DETAILS.md#how-it-works) and the [paper](docs/paper/Strata-Paper.pdf).

## Something went wrong?

- **My PC froze the first time Strata started.** It loads the model into RAM. Wait, and don't close the window. Still
  frozen after 10 minutes? Restart the PC, close other programs and try again, or pick a smaller size.
- **It stopped while downloading or installing.** Start the app or `strata launch` again. It continues where it stopped.
- **It is very slow, or it says "the engine stopped unexpectedly".** Your PC is short on free RAM. Close other programs
  (browsers use a lot), or pick a smaller size such as Q2_0 or IQ2_XS.
- **It says there is no engine for this PC.** In the app, open **Settings, Engine** and press **Update engine**. In the
  Terminal, run `strata update`.
- **It says port 8080 is already in use.** Strata is already running. Look for its window.

More fixes: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md). Still stuck? Open an
[issue](https://github.com/Niko1221/Strata/issues) and attach the logs: in the app from **Settings, Engine, Diagnostics,
Save logs**, in the Terminal the output of `strata doctor`. For a security problem, report it privately: [SECURITY.md](SECURITY.md).

## Credits and license

The model is [Qwen3.8-Flash-Next](https://huggingface.co/Qwen/Qwen3.8-Flash-Next) by the Qwen team. It was
compressed by [ISTA-DASLab](https://huggingface.co/ISTA-DASLab/Qwen3.8-Flash-Next-GSQ-RCO-GGUF), UkisAI (Swift 1.5),
agentionai (Gyro), Unsloth, and [DavidAU](https://huggingface.co/DavidAU) — whose Turbo-Brilliance reason-mode re-quants,
[regular](https://huggingface.co/DavidAU/Qwen3.8-Flash-Next-Turbo-Brilliance-50x-Reasoning-Instruct-GSQ-RCO-GGUF)
and [abliterated](https://huggingface.co/DavidAU/Qwen3.8-Flash-Next-Abliterated-Uncensored-Turbo-Brilliance-50x-Reasoning-Instruct-GSQ-RCO-GGUF)
(the abliterated one built on [SC117](https://huggingface.co/SC117/Qwen3.8-Flash-Next-GSQ-RCO-abliterated-GGUF)'s
abliterated GSQ-RCO transplant, which carries [orcarouter](https://huggingface.co/orcarouter/Qwen3.8-Flash-Next-Uncensored-GGUF)'s
abliterated weights),
are the models this fork's reason modes ride and both of which the installer offers.
ISTA-DASLab also made the DeepSeek V4.1-Flash sets. Strata uses parts of [llama.cpp / ggml](https://github.com/ggml-org/llama.cpp). All credits:
[docs/HOW_IT_WORKS.md](docs/HOW_IT_WORKS.md#credits). Strata is open source under the [MIT License](LICENSE). A few
parts and every model have their own licenses ([which ones](docs/HOW_IT_WORKS.md#license)).

## Contributing

Found a bug, or want to send a change or a benchmark? Read [CONTRIBUTING.md](CONTRIBUTING.md) first. It says what to
include so that others can check your work.

## Support Strata

Strata is free and MIT-licensed. I build it and test it on whatever hardware I can get. If it runs well on your PC, a coffee helps
me keep testing new cards and fixing what you report. No pressure. Using it and reporting what you find helps just as much.

<a href="https://buymeacoffee.com/strataengine"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" height="50"></a>

Interested in sponsoring Strata? Contact me via [GitHub](https://github.com/Niko1221).
