# Community benchmark on NVIDIA GeForce RTX 4090

Measured on 2026-10-29 with `tools/strata_bench.py` (suite 1, 3 runs per test, medians with ranges). Speeds are the engine's own timings; first-token times are measured by the client over HTTP. Speed only: no correctness check was run.

## Hardware and software

- GPU and VRAM: NVIDIA GeForce RTX 4090, 24 GiB VRAM
- CPU: AMD Ryzen 7 9800X3D 8-Core Processor (8 cores, 16 threads); installed RAM: 125.4 GiB; storage: sda     WDC WD101FZBX-00ATAA0   sata; sdb     WDC WD101FZBX-00ATAA0   sata; sdc     USB DISK 3.0            usb; sr0     USB DISK 3.0            usb; zram0; nvme1n1 Samsung SSD 990 PRO 4TB nvme; nvme0n1 WD_BLACK SN850X 1000GB  nvme
- OS: Linux 7.3.0-5-cachyos; GPU driver: 615.78.08; CUDA (driver supports up to): 13.4
- Strata: project 0.1.54, commit 1da72f3a; engine 0.1.54
- GPU detail (after the run, near idle): power_limit_w=650.00, power_draw_w=318.24, pcie=gen4 x16, pstate=P0, temp_c=39
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
| short chat | 10240 (10166-10380) | 0 | 100 (100-100) | 9 | not measured | 76.0 (71.0-88.4) | 1.01 (0.90-1.23) |
| 4K prompt, fresh | 10348 (10325-10372) | 9995 (9995-9995) | 24 cap | 3 | 401.0 (376.3-404.0) | not measured | 1.05 (1.04-1.10) |
| 16K prompt, fresh | 16205 (16150-16232) | 9995 (9995-9995) | 24 cap | 3 | 1966.4 (1956.3-1971.0) | not measured | 3.35 (3.29-3.35) |
| 32K prompt, fresh | 32065 (32017-32095) | 9995 (0-9995) | 24 cap | 3 | 4508.8 (3548.9-4602.7) | not measured | 5.05 (4.97-9.25) |
| agent session, follow-up turns | 23906 (23889-23910) at the last turn | see below | up to 64 | 3 | see below | 93.9 (66.2-113.5) | 3.52 (2.96-4.19) |

Ranges are the lowest and highest of the runs; `Runs` counts requests that returned a token.

### Agent session (conversation cache)

Cache hit over the follow-up turns: 55.1 % (55.1-55.1); earlier-turn tokens read again per session: 29194 (29164-29197) (earlier turns that the cache did not hold; the 12999 (12998-13000) new tokens of the files are read once); first turn (nothing cached) first token: 3.95 s (3.90-60.31).

| Turn (run 1) | Prompt tokens | Reused | Read | Prompt tok/s | First token (s) | Decode tok/s |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 10626 | 0 | 10626 | 1775.4 | 60.314 | 69.4 |
| 1 | 14079 | 10358 | 3721 | 1106.1 | 3.601 | 66.2 |
| 2 | 15767 | 10358 | 5409 | 1654.1 | 3.523 | 86.9 |
| 3 | 19083 | 10358 | 8725 | 2419.1 | 3.835 | 94.7 |
| 4 | 21134 | 10358 | 10776 | 2696.2 | 4.192 | 113.5 |
| 5 | 23889 | 10358 | 13531 | 3441.1 | 4.164 | 108.2 |

Per-request data: `results.json`. Engine log lines from the start: `engine-log-excerpt.txt` (when this run started the server).

## Correctness and limitations

Not measured: this is a speed suite. The conversation uses the model's own replies, so token counts differ a little between runs. Machine details come from the server, `nvidia-smi`/`rocm-smi` and the OS; background load is not recorded. Total time of the suite: 200 s.
