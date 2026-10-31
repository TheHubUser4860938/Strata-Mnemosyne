# Set up Strata for a user

Use this guide when a user asks an AI agent to install Strata (version 0.2.7). There are two release routes. Pick
one; do not start from a source checkout.

- **The Terminal and `strata launch`** (below). This is the route for an agent that has a shell.
- **The desktop app.** One installer per system: `Strata-0.2.8-windows-x64-setup.exe`,
  `Strata-0.2.8-linux-x86_64.AppImage`, `Strata-0.2.8-macos-arm64.dmg`, from the
  [latest release](https://github.com/Niko1221/Strata/releases/latest). The Windows and Linux installers carry no
  engine: on first start the app shows the engine for the user's graphics card and downloads it, or installs a file the
  user already has ("I already have the file"). Details: [INSTALL.md](INSTALL.md).

On **this fork's `memory-core` branch** two things differ from upstream, and both matter to an agent: the server
serves an OpenAI- and Anthropic-compatible API on `http://127.0.0.1:8005` (upstream installs use 8080/8095), and the
source route (§8) is the one that carries the built-in memory system, Strata Mnemosyne - the released installers
come from upstream and do not have it. The memory is ON by default there; §5b says what to check.

Model availability, provider preference and API details are in [AI_REFERENCE.md](AI_REFERENCE.md).

## 1. Check the computer and the requested model

- Check OS, CPU architecture, graphics cards, driver, available RAM/VRAM and free disk space.
- Use the [hardware guides](INSTALL.md#what-you-need). Linux and Windows packages are x86-64; Mac packages are
  Apple Silicon and need macOS 15 or newer. Older GPUs, Intel Arc and low-memory machines have specific limits.
- Model support is separate from hardware support. Qwen3.6 currently uses CUDA or HIP; it is not a Metal/SYCL model.
  DeepSeekV4.1-Flash-1017 (`--family deepseek41`) runs in the app and in the Terminal, on NVIDIA RTX 30, 40 and 50
  (Windows and Linux) and on the AMD Radeon AI PRO R9700 under Linux. It has three sets: 1.75 bpw (239 GB of disk),
  2.00 bpw (257 GB) and 2.25 bpw (274 GB), and for a 12 GB card it needs 46 to 64 GB of RAM. The context is 8K.
  `--speed faster|full` (or `--full-quality`) chooses how many experts it uses per word; Faster is the default on a
  PC with 16 GB of graphics memory or less. Print the plan first:
  `strata launch --plan --family deepseek41 --model ist-das-2.00bpw`.
- Check the **chosen pack's** memory and disk needs. Do not reuse a Flash-Next estimate for every family.
  Unified memory is one pool, not RAM plus VRAM. A completed download does not establish that a model can run.
- Keep the default local-only access. Share the server over a network only when the user asks; recommend an API key
  beyond localhost and explain any deliberate use of `--no-api-key`.
- Explain substantial downloads and follow the user's existing authorization and network/storage constraints.
  Do not install drivers or system build tools as an unannounced side effect of a normal Terminal install.

## 2. Install the Terminal

The installer downloads a private Python runtime and Control, verifies the release checksums and signed feed, and
installs into the user's home folder. The engine and model are acquired during launch.

**Linux / Mac:**

```sh
curl -fsSL https://github.com/Niko1221/Strata/releases/latest/download/install.sh -o install.sh && sh install.sh
```

**Windows PowerShell:**

```powershell
irm https://github.com/Niko1221/Strata/releases/latest/download/install.ps1 | iex
```

Open a new terminal on Windows. On Linux and Mac, use the full executable path printed by the installer if
`~/.local/bin` is not on PATH. Confirm with `strata --version` and `strata launch --help`.
Do not search for `START-HERE.bat` in the installed app or Terminal: it is not part of them.

## 3. Select a compatible pack and inspect the plan

Keep the user's model and provider choice. Otherwise prefer **ISTA-DASLab → Unsloth → Gyro → others**, when a pack
fits the selected model and computer. This is the maintainer's recommendation policy; current executable defaults
can differ. Gyro is a memory-saving fallback, currently slower, not a general speed recommendation.

| Choice | Explicit launch selection |
| --- | --- |
| ISTA-DASLab Flash-Next | `--family qwen --model q2_0` (or a compatible IQ2_XS / IQ3_XXS / IQ3_S pack) |
| ISTA-DASLab Coder | `--family coder --model IQ1_M` |
| Unsloth Flash-Next | `--family unsloth --model UD-Q4_K_XL` (check the pack's backend limits) |
| Gyro Flash-Next | `--family gyro --model Gyro-S` |
| Unsloth Qwen3.6 | `--family qwen36 --model UD-Q4_K_XL` |

These are choices, not an instruction to install every row. The full list and memory estimates are in
[MODELS.md](MODELS.md). Source setup on this fork's branch additionally offers `dau` and `daureg` (DavidAU's
Turbo-Brilliance re-quants, which the reason modes ride) and `huihui` (huihui-ai's abliterated re-quants, the same
Unsloth Dynamic sizes, plain template) and `heretic` (trubisky's quants of jeffpeng3's heretic v2 of Swift 1.5 — three
sizes, 85 to 109 GB, the reason modes ride its template and the optional Q8_0 n-gram table applies to it). For example,
inspect the ISTA-DASLab Q2_0 plan:

```sh
strata launch --family qwen --model q2_0 --context 32k --plan --output json
```

Check the resolved family, model, storage folder, context, picture reader and missing downloads. If the plan names
an unavailable backend, do not continue as though compatibility were confirmed. Intel Arc has a released Linux
engine, but model preparation still has special requirements: [INTEL_ARC.md](INTEL_ARC.md).

## 4. Start it

After the plan matches the user's computer and requested setup:

```sh
strata launch --family qwen --model q2_0 --context 32k --yes --no-tui
```

`--no-tui` prints the address and returns after startup while the server continues in the background. Keep the
launch process alive during model acquisition; large downloads and preparation can take a long time. Poll progress
and logs rather than promising a universal startup time. Repeating an interrupted launch resumes completed work.

Useful options:

| Option | Meaning |
| --- | --- |
| `--model-path PATH` | Use existing supported model files; a matching filename alone does not prove compatibility |
| `--data-dir PATH` | Folder for new downloads; existing files stay put unless `--move-data` is also given |
| `--vision on\|off\|gpu\|cpu` | Picture reading, subject to model and packaged-reader support |
| `--gpu 0,1` | Selected GPUs; do not use source setup's `--gpus` spelling here |
| `--parallel N` | Requested concurrent slots, 1–8; check what actually fits and starts |
| `--save-preset NAME` | Keep these launch choices for later |
| `--open` | Open the server's browser page after it starts |
| `--restart` | Replace an already running launch with different settings; interrupts active answers |

`--yes` does not authorize a restart by itself. When a model is already running, inspect its state before using
`--restart` or `--stop`. Use `strata launch --help` for the installed release's full list.

## 5. Verify the running service

```sh
strata launch --status
strata doctor --live
```

Check the printed address and model, then query `/health` and `/v1/models` at that address. With this fork's
default port (8005; a mainline install uses 8080):

**Linux / Mac:**

```sh
curl -fsS http://127.0.0.1:8005/health
curl -fsS http://127.0.0.1:8005/v1/models
```

**Windows PowerShell:**

```powershell
Invoke-RestMethod http://127.0.0.1:8005/health
Invoke-RestMethod http://127.0.0.1:8005/v1/models
```

Use the configured credential for protected endpoints. Confirm the model is loaded, then send a real request or
run the relevant tool check below. **Exit code 0 alone is insufficient:** launch can finish after downloading a model
without starting it when no usable engine is available. Report that as downloaded, not installed and verified.

## 5b. The memory (memory-core branch only) - ON by default

This branch ships Strata Mnemosyne, the built-in memory store, **on by default** (the user's
decision, 2026-10-16: "if someone doesn't want the built-in memory system they won't be using
our fork to begin with"). Setup writes the `"memory"` block into the engine config and fetches
the embedder it ships with (`BAAI/bge-small-en-v1.5`, MIT, pinned by SHA-256, ~130 MB, CPU-only -
it never touches the GPU your model owns); a server started with no `"memory"` key at all also
turns the store on, with a default directory and the embedder auto-detected when present. To
turn it OFF, set `"memory": { "enabled": false }` (or `"memory": false`) - every path then
returns to upstream Strata, byte for byte. `--memory DIR` still forces the store on at a given
directory. Tuning (all optional): `"recall_limit"`, `"max_block_chars"`, `"per_turn"`,
`"turn_recall_limit"`, `"turn_block_chars"`, `"encrypt"`, `"tool"`, `"auto_shelve"`,
`"embedder"`, `"cartridges"`, `"soul"`; setup bundles the store at the dev-verified budgets
(96 notes under a 48,000-char cap, per-turn 12 notes under 24,000, unlimited tool rounds), writes
`"slot_save_path": "<data folder>/sessions"` with `"slot_retain": 6` (slot
save/restore, and the directory the cartridges need), and ships the tier-2 cartridges ON only when
the PC keeps at least 8 GB of system RAM free of the model's all-in need (an IQ3_S box with 64 GB
gets no cartridges; a 128 GB box does) - the knobs measured and shipped off (`floor_cosine`,
`block_min_score`, exposure decay, `route_shelves`) stay one config key away. Without the embedder
files recall stays lexical and the banner
says so out loud - the degrade is visible, never a silent no-op.

- verify before reporting done: the boot banner must print `[strata] memory core on: ...` (the
  banner is the check - a silent no-op config is the failure mode), and
  `http://127.0.0.1:<port>/memory-ui` must answer; on a DavidAU-family install the banner must
  also print `[strata] reason modes on: ...` and `http://127.0.0.1:<port>/reason` must answer
  (setup writes `reason_modes: true` and the autonomous default for that family - a DAU install
  without those lines did not get the fork's config);
- never expose `/memory` beyond `127.0.0.1` without `--api-key` — the store holds what the server
  remembers about the user.

## 6. Connect a tool

```sh
strata connect
strata connect opencode
strata connect opencode --check --output json
```

The first command lists adapters; the second prints settings; the third sends a prompt and tool-call check. Use the
adapter the user actually needs. `--write` changes that tool's configuration and keeps a backup; use it within the
user's authorization. Printed configuration and a previous vendor test are not a successful current-server check.

- OpenAI-compatible clients: use the printed server address plus `/v1`.
- Anthropic-compatible clients: use the server root; the client adds `/v1/messages`.
- Use the actual API key when enabled. Tool identifiers and limits: [connection guide](TERMINAL_LAUNCH.md#connect-your-apps-strata-connect).
- Flash-Next's template defaults to thinking on with `xhigh` effort; `high` maps to `xhigh`. Requests, shared Chat
  settings and run-config settings can override defaults. Do not assert a sampling configuration without inspecting it.

## 7. Handoff, update or stop

Tell the user which model is running, where its files are, its address, how the tool check went, and any limitations.

```sh
strata launch --preset NAME
strata launch --status
strata launch --stop
strata update --check
```

Stop active models before `strata update`. Very old Terminals require rerunning the installer; see
[updating](INSTALL.md#updating). Show credentials only to the intended user; redact them from shared logs and reports.

## 8. Source-only and unsupported setups

A source build is a separate workflow: [SOURCE_INSTALL.md](SOURCE_INSTALL.md). `START-HERE.bat`, `SETUP.bat`,
`UPDATE.bat`, `setup.sh` and generated `run-<model>` scripts belong to that workflow. Do not pass their flags to
`strata launch`, promise a source build will support an unknown model, or describe a source-only command as an
installed-app command. If a required backend or artifact is missing, say exactly what is missing.

On **this fork**, the source clone is the fork itself - the `memory-core` branch is the route with the built-in
memory system and the reason modes (its setup writes the memory block, the slot keys and the DavidAU families by
itself, §5b), and it serves on port **8005** where mainline uses 8080/8095:

```sh
git clone -b memory-core https://github.com/TheHubUser4860938/Strata-Mnemosyne.git
```
