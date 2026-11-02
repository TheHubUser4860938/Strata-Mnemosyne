# Community benchmark on NVIDIA GeForce RTX 4090

Measured on 2026-10-29 with `tools/strata_bench.py` (suite 1, 3 runs per test, medians with ranges). Speeds are the engine's own timings; first-token times are measured by the client over HTTP. Speed only: no correctness check was run.

## Hardware and software

- GPU and VRAM: NVIDIA GeForce RTX 4090, 24 GiB VRAM
- CPU: AMD Ryzen 7 9800X3D 8-Core Processor (8 cores, 16 threads); installed RAM: 125.4 GiB; storage: sda     WDC WD101FZBX-00ATAA0   sata; sdb     WDC WD101FZBX-00ATAA0   sata; sdc     USB DISK 3.0            usb; sr0     USB DISK 3.0            usb; zram0; nvme0n1 Samsung SSD 990 PRO 4TB nvme; nvme1n1 WD_BLACK SN850X 1000GB  nvme
- OS: Linux 7.3.0-5-cachyos; GPU driver: 615.78.08; CUDA (driver supports up to): 13.4
- Strata: project 0.1.54, commit 1da72f3a; engine 0.1.54
- GPU detail (after the run, near idle): power_limit_w=650.00, power_draw_w=306.98, pcie=gen4 x16, pstate=P0, temp_c=42
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
| short chat | 10281 (10204-10467) | 0 | 100 (15-100) | 9 | not measured | 77.1 (72.2-89.2) | 1.00 (0.94-1.24) |
| 4K prompt, fresh | 10386 (10363-10410) | 10033 (10033-10033) | 24 cap | 3 | 395.3 (357.3-397.9) | not measured | 1.10 (1.05-1.11) |
| 16K prompt, fresh | 16060 (16005-16087) | 10033 (10033-10033) | 24 cap | 3 | 1949.5 (1911.3-1952.5) | not measured | 3.24 (3.21-3.33) |
| 32K prompt, fresh | 31472 (31471-31502) | 10033 (0-10033) | 24 cap | 3 | 4854.5 (4074.5-4882.0) | not measured | 4.58 (4.56-7.90) |
| agent session, follow-up turns | 23942 (23942-23947) at the last turn | see below | up to 64 | 3 | see below | 90.4 (70.1-107.3) | 3.46 (2.99-4.08) |

Ranges are the lowest and highest of the runs; `Runs` counts requests that returned a token.

### Agent session (conversation cache)

Cache hit over the follow-up turns: 55.2 % (55.2-55.2); earlier-turn tokens read again per session: 29167 (29167-29192) (earlier turns that the cache did not hold; the 13000 (13000-13000) new tokens of the files are read once); first turn (nothing cached) first token: 3.97 s (3.95-4.29).

| Turn (run 1) | Prompt tokens | Reused | Read | Prompt tok/s | First token (s) | Decode tok/s |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 10664 | 0 | 10664 | 2614.4 | 4.287 | 99.6 |
| 1 | 14116 | 10396 | 3720 | 995.4 | 3.964 | 70.1 |
| 2 | 15804 | 10396 | 5408 | 1610.1 | 3.603 | 83.2 |
| 3 | 19120 | 10396 | 8724 | 2299.2 | 4.025 | 84.6 |
| 4 | 21185 | 10396 | 10789 | 2874.1 | 3.949 | 83.3 |
| 5 | 23947 | 10396 | 13551 | 3530.5 | 4.08 | 107.3 |

Per-request data: `results.json`. Engine log lines from the start: `engine-log-excerpt.txt` (when this run started the server).

## Correctness and limitations

Not measured: this is a speed suite. The conversation uses the model's own replies, so token counts differ a little between runs. Machine details come from the server, `nvidia-smi`/`rocm-smi` and the OS; background load is not recorded. Total time of the suite: 146 s.
