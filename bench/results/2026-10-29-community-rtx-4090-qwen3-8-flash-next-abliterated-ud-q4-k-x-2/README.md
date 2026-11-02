# Community benchmark on NVIDIA GeForce RTX 4090

Measured on 2026-10-29 with `tools/strata_bench.py` (suite 1, 3 runs per test, medians with ranges). Speeds are the engine's own timings; first-token times are measured by the client over HTTP. Speed only: no correctness check was run.

## Hardware and software

- GPU and VRAM: NVIDIA GeForce RTX 4090, 24 GiB VRAM
- CPU: AMD Ryzen 7 9800X3D 8-Core Processor (8 cores, 16 threads); installed RAM: 125.4 GiB; storage: sda     WDC WD101FZBX-00ATAA0   sata; sdb     WDC WD101FZBX-00ATAA0   sata; sdc     USB DISK 3.0            usb; sr0     USB DISK 3.0            usb; zram0; nvme0n1 Samsung SSD 990 PRO 4TB nvme; nvme1n1 WD_BLACK SN850X 1000GB  nvme
- OS: Linux 7.3.0-5-cachyos; GPU driver: 615.78.08; CUDA (driver supports up to): 13.4
- Strata: project 0.1.54, commit 1da72f3a; engine 0.1.54
- GPU detail (after the run, near idle): power_limit_w=650.00, power_draw_w=338.15, pcie=gen4 x16, pstate=P0, temp_c=42
- Background workloads: not recorded (GPU power limit/draw read above)

## Model and configuration

- Model and quantization: qwen3.8-flash-next-abliterated-ud-q4_k_xl
- Context: 524288 tokens; parallel slots: 1
- Settings: the install's own configuration, unchanged; thinking off for the suite; temperature 0

## Method

Run by `python tools/strata_bench.py --long` against the HTTP API of a Strata server (already running); model loading is not timed. One warm-up chat and a 1K prompt are discarded first. Every prompt starts with a unique tag, so the conversation cache cannot help the fresh-prompt tests.

- short chat: the three questions of `tools/ab_engine.py`, up to 100 new tokens, 3 runs
- 4K / 16K prompts: generated word lists sized by a calibration request, 24 new tokens, 3 fresh prompts each
- agent session: system prompt and four tools, then 5 turns that each add about 1500 words of a project file and continue from the model's own earlier answers (the way agent clients resend a conversation), 64 new tokens per turn, 3 sessions; the cache numbers come from the answer's usage (`cached_tokens`) and timings (`prompt_n`)
- concurrency (when run): N requests sent at the same moment, total tokens over the wall time of the burst, latency over all requests

## Results

| Configuration | Actual prompt tokens | Reused tokens | Generated tokens | Runs | Prompt tok/s median and range | Decode tok/s median and range | TTFT seconds median and range |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- |
| short chat | 10278 (10204-11045) | 0 | 100 (3-194) | 9 | not measured | 79.2 (73.6-97.3) | 0.97 (0.88-1.22) |
| 4K prompt, fresh | 10363 (10363-10410) | 10033 (10033-10033) | 24 cap | 3 | 389.2 (368.9-417.2) | not measured | 1.06 (1.01-1.07) |
| 16K prompt, fresh | 16062 (16005-16062) | 10033 (10033-10033) | 24 cap | 3 | 1954.0 (1666.6-1957.8) | not measured | 3.24 (3.21-3.80) |
| 32K prompt, fresh | 31479 (31424-31499) | 10033 (0-10033) | 24 cap | 3 | 4948.5 (3510.5-5046.7) | not measured | 4.50 (4.42-58.21) |
| agent session, follow-up turns | 23938 (23896-23942) at the last turn | see below | up to 64 | 3 | see below | 91.7 (82.0-111.6) | 3.43 (2.99-4.25) |

Ranges are the lowest and highest of the runs; `Runs` counts requests that returned a token.

### Agent session (conversation cache)

Cache hit over the follow-up turns: 55.2 % (55.2-55.3); earlier-turn tokens read again per session: 29167 (29076-29172) (earlier turns that the cache did not hold; the 12999 (12999-13000) new tokens of the files are read once); first turn (nothing cached) first token: 3.92 s (3.90-4.54).

| Turn (run 1) | Prompt tokens | Reused | Read | Prompt tok/s | First token (s) | Decode tok/s |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 10664 | 0 | 10664 | 2464.1 | 4.539 | 93.5 |
| 1 | 14115 | 10396 | 3719 | 965.5 | 4.099 | 84.1 |
| 2 | 15803 | 10396 | 5407 | 1505.2 | 3.836 | 82.4 |
| 3 | 19119 | 10396 | 8723 | 2260.5 | 4.109 | 90.7 |
| 4 | 21176 | 10396 | 10780 | 2951.0 | 3.863 | 105.5 |
| 5 | 23938 | 10396 | 13542 | 3377.0 | 4.247 | 105.1 |

Per-request data: `results.json`. Engine log lines from the start: `engine-log-excerpt.txt` (when this run started the server).

## Correctness and limitations

Not measured: this is a speed suite. The conversation uses the model's own replies, so token counts differ a little between runs. Machine details come from the server, `nvidia-smi`/`rocm-smi` and the OS; background load is not recorded. Total time of the suite: 237 s.
