"""The Inkling-2-Mini family: exact verified sizes & SHA-256 hashes, shape engine component, defaults, and sources.

Pure data and small helpers; the hardware auto-selection and placement rules live in inkling_fit.py.
Exact byte sizes and SHA-256 digests are pinned from the verified R2 `.strata` v1.1 checkpoints (`SHA256SUMS.txt`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from strata_control import inkling_fit

FAMILY = "inkling-2-mini"
TAG = "inkling-2-mini-"               # run config file: strata-inkling-2-mini-sq-20.json
ARCH = "inkling2_loop"                # run config's "arch"; serve & Control route by it
SHAPE = "inkling2"                    # shape engine component: component:strata-inkling (strata_control/shape_engine.py)
COMPONENT = "strata-inkling"
EXE = "strata-inkling.exe" if os.name == "nt" else "strata-inkling"
TITLE = "Inkling-2-Mini"
BY = "Strata's native .strata v1.1 build of Thinking Machines' Inkling-2-Mini"
VISION_FILE = "Inkling-2-Mini-Vision.strata"
TOKENIZER_FILE = "tokenizer.json"
CHAT_TEMPLATE_FILE = "chat_template.jinja"
DEFAULT_CONTEXT = inkling_fit.DEFAULT_CONTEXT
CONTEXTS = inkling_fit.CONTEXTS
DEFAULT_DRAFTER = "dspark"
DRAFTERS = ("off", "dspark")
DEFAULT_VISION = True
DEFAULT_PARALLEL = inkling_fit.DEFAULT_PARALLEL
PARALLEL_CHOICES = inkling_fit.PARALLEL_CHOICES
MAX_PARALLEL = inkling_fit.MAX_PARALLEL
REASONING_EFFORTS = ("none",)
DEFAULT_REASONING_EFFORT = "none"
HAS_THINKING = False

#: file name -> (bytes, sha256 or None)
FILES = {
    "Inkling-2-Mini-SQ-20.strata": (19_346_685_952, "0bbfd52344f0dd4779a7807b5f73554a812f24c035e6877b63cd0d499f7e1b97"),
    "Inkling-2-Mini-SQ-15.strata": (14_348_316_672, "2ea32eed533afba257e2cbee7b073dc2c3da80fe55d1d2d794779b5498e30737"),
    "Inkling-2-Mini-SQ-10.strata": (10_471_526_400, "ac4d452ad03e4930abd9d46f9c5eec22b2f75a1da45a1e49bd24ccd58b065934"),
    VISION_FILE: (636_526_592, "6589eff47f9c20bc3a032faa3d449f10bf4f04a84cc6b2ee8a44d51d2b6fc677"),
}
#: Auxiliary tokenizer files hosted beside the `.strata` weights (Section 0 embeds chat_template + config; tokenizer.json holds the 200K o200k BPE vocab/merges).
TOKENIZER_FILES = {
    TOKENIZER_FILE: (26_178_678, None),
    CHAT_TEMPLATE_FILE: (6_868, None),
}
#: SC117's abliterated packs (HF `SC117/Inkling-2-Mini-abliterated-Strata`, read 2026-11-22): the same three SQ
#: quantizations with the thinking channel ablated (`late_24_47_orth`, k=1, layers 4..23 - his verification.json:
#: five-domain KL 0.013623, 95.63% same top-1, +0.7% perplexity, byte-exact layouts).  Byte sizes are identical to
#: the stock packs, so inkling_fit's placement numbers carry over, and the Vision shard is the same file.
ABLITERATED_REPO = "SC117/Inkling-2-Mini-abliterated-Strata"
ABLITERATED_SUFFIX = "-abliterated"
ABLITERATED_FILES = {
    "Inkling-2-Mini-SQ-20-abliterated.strata": (19_346_685_952, "4633e0420168ebf0913b6d834397c297e330885bcd45f1501462ed350c50a0a2"),
    "Inkling-2-Mini-SQ-15-abliterated.strata": (14_348_316_672, "b52a4827f9fef6a1bb2fc58bf55a2eff376646a6382447020ed54bf0d047925d"),
    "Inkling-2-Mini-SQ-10-abliterated.strata": (10_471_526_400, "876a4586eeff14a6d0bfbb567109a02abe2207c6e9659ff2592073bfe6790fac"),
}
#: The community Unsloth GGUF (HF `unsloth/Inkling-2-Mini-GGUF`, read 2026-11-22).  `strata-inkling` loads these
#: directly - `engine/src/inkling2/ink_gguf_loader.h:2` names UD-Q4_K_XL and takes Q8_0 losslessly as GGUF_RAW -
#: and the two parts a stock pack carries inside its one file are separate files here: the DSpark drafter
#: (`--dspark`, a `dflash`-architecture GGUF) and the picture reader (`--vision <mmproj>`, a Vision MLP, not the
#: `.strata` shard).  No re-quantization: the engine reads the expert bodies as they are written.
GGUF_REPO = "unsloth/Inkling-2-Mini-GGUF"
GGUF_VISION_FILE = "mmproj-BF16.gguf"
GGUF_DSPARK_FILE = "dspark-Inkling-2-Mini-Q8_0.gguf"
GGUF_BUILDS = {                      # build -> its GGUF file (sizes and SHA-256s from HF's tree API, same day)
    "UD-Q8_K_XL": "Inkling-2-Mini-UD-Q8_K_XL.gguf",
    "UD-Q4_K_XL": "Inkling-2-Mini-UD-Q4_K_XL.gguf",
    "UD-IQ4_XS": "Inkling-2-Mini-UD-IQ4_XS.gguf",
    "UD-IQ3_XXS": "Inkling-2-Mini-UD-IQ3_XXS.gguf",
}
GGUF_FILES = {
    "Inkling-2-Mini-UD-Q8_K_XL.gguf": (22_867_451_616, "dfb04bf37bee457f98800989dedf93ec442ede8636dbea9433992f1e527e9a41"),
    "Inkling-2-Mini-UD-Q4_K_XL.gguf": (17_629_759_456, "e62d463c135ffe283df8d94b279a96ca145ac128b52ce854478613045bf4de15"),
    "Inkling-2-Mini-UD-IQ4_XS.gguf": (15_733_755_232, "a861d21e7c6d7bc69d8cdcdfb9eb195fd37ef1cd2ab31499db61cd7d30d9b3a1"),
    "Inkling-2-Mini-UD-IQ3_XXS.gguf": (11_663_309_504, "bd7ef0865adf119b5183e45e741c629bafa649769b33b5ebf689bb4bcc4690d6"),
    GGUF_VISION_FILE: (641_805_760, "2c165c78790e78a3f45a2d1e9e931083e52ee69d45ff2a0dc9c281fdf1a666e7"),
    GGUF_DSPARK_FILE: (402_278_560, "2ec78510da837e8fc3be54a14757a0c5fbd2d8d9e85a0d92853fafdf674f3773"),
}
#: every model file setup can place in `inkling_folder`, by name: (bytes, sha256)
ALL_FILES = {**FILES, **ABLITERATED_FILES, **GGUF_FILES}

BUILD_ABOUT = {
    "SQ-20": "bit-exact lossless native SF4+MX8 LLM + DSpark drafter: 100% GPU on 24 GiB cards and 32+ GiB unified memory",
    "SQ-15": "flagship quality (beats UD-Q4_K_XL): 100% GPU on 16 GiB cards / 24 GiB Macs, or fast 3x loop-pinned hybrid on 12 GiB cards",
    "SQ-10": "compact high-speed build: 100% GPU on 12 GiB cards, 16 GiB Macs, 8 GiB cards, and Radeon 780M / Strix Point 890M iGPUs",
    "SQ-20-abliterated": "SQ-20 with the thinking channel ablated (KL 0.0136, +0.7% perplexity): answers direct, 100% GPU on 24 GiB cards",
    "SQ-15-abliterated": "SQ-15 ablated the same way: 100% GPU on 16 GiB cards / 24 GiB Macs, hybrid on 12 GiB cards",
    "SQ-10-abliterated": "SQ-10 ablated the same way: the fast small build, 100% GPU on 12 GiB cards and 8 GiB cards",
    "UD-Q8_K_XL": "Unsloth Dynamic GGUF, read as written (no requant) + the separate Q8_0 DSpark drafter: 100% GPU past 24 GiB",
    "UD-Q4_K_XL": "Unsloth Dynamic GGUF (NVFP4 layers 0-19, Q8_0 layers 20-23) + the separate Q8_0 DSpark drafter: 100% GPU on 24 GiB cards",
    "UD-IQ4_XS": "Unsloth Dynamic GGUF, the smaller IQ4: fits 16 GiB cards with the drafter beside it",
    "UD-IQ3_XXS": "Unsloth Dynamic GGUF, the compact IQ3: 12 GiB cards and 8 GiB cards with room for the drafter",
}


def build_parts(build: str) -> tuple[str | None, str, str, str | None]:
    """(Hugging Face repo, or None for the stock `.strata` source; model file; vision file; drafter file, or None when the
    drafter is inside the pack).  A stock pack carries its DSpark drafter and (beside it) its Vision shard inside the
    `.strata` family; an Unsloth GGUF needs both as their own files, so a build says which parts it is made of."""
    if build in GGUF_BUILDS:
        return GGUF_REPO, GGUF_BUILDS[build], GGUF_VISION_FILE, GGUF_DSPARK_FILE
    if build.endswith(ABLITERATED_SUFFIX):
        return ABLITERATED_REPO, f"{TITLE}-{build}.strata", VISION_FILE, None
    return None, inkling_fit.BUILDS[build]["file"], VISION_FILE, None


def build_file(build: str) -> str:
    return build_parts(build)[1]


def vision_file(build: str) -> str:
    return build_parts(build)[2]


def dspark_file(build: str) -> str | None:
    return build_parts(build)[3]


def files_of(build: str, vision: bool = DEFAULT_VISION) -> list[str]:
    """The files one build needs: its model file, the picture reader when images are on, and the drafter when the pack
    does not carry it inside (the GGUF builds' DSpark head is a separate file, the `.strata` packs embed theirs)."""
    _repo, model, vision_name, drafter = build_parts(build)
    out = [model]
    if vision:
        out.append(vision_name)
    if drafter:
        out.append(drafter)
    return out


def size_of(name: str) -> int | None:
    got = ALL_FILES.get(name) or TOKENIZER_FILES.get(name)
    return got[0] if got else None


def sha256_of(name: str) -> str | None:
    got = ALL_FILES.get(name) or TOKENIZER_FILES.get(name)
    return got[1] if got else None


def model_key(build: str) -> str:
    """"SQ-20" -> "inkling-2-mini-sq-20"."""
    return TAG + build.lower()


SOURCES_FILE = Path(__file__).resolve().parents[1] / "data" / "inkling-sources.json"
SOURCE_ENV = "STRATA_INKLING_SOURCE"


def sources(env: dict | None = None, cfg: dict | None = None, shipped: Path | None = None) -> list[dict]:
    """Download sources in priority order: config's `inkling_source`, env `STRATA_INKLING_SOURCE`, then shipped `inkling-sources.json`."""
    env = os.environ if env is None else env
    out: list[dict] = []
    for item in ((cfg or {}).get("inkling_source"),):
        out += _normalise(item)
    if env.get(SOURCE_ENV):
        out += _normalise(env[SOURCE_ENV])
    try:
        data = json.loads((shipped or SOURCES_FILE).read_text(encoding="utf-8"))
        out += _normalise(data.get("sources") if isinstance(data, dict) else data)
    except (OSError, ValueError):
        pass
    # The two community packs, last: their model file names are their own, and the shared files (the Vision shard,
    # tokenizer.json) come from the stock source above first, so a box that has them keeps them.
    out += [{"kind": "http", "base": f"https://huggingface.co/{repo}/resolve/main"} for repo in (ABLITERATED_REPO, GGUF_REPO)]
    return out


def _normalise(item) -> list[dict]:
    if isinstance(item, str):
        return [{"kind": "http", "base": item.rstrip("/")}] if item.startswith(("http://", "https://")) else []
    if isinstance(item, dict):
        base = str(item.get("base") or "").rstrip("/")
        kind = item.get("kind") if item.get("kind") in ("http", "http-parts") else "http"
        files = item.get("files") if isinstance(item.get("files"), dict) else {}
        if base.startswith(("http://", "https://")) or files:
            return [{"kind": kind, "base": base, "files": files}]
        return []
    if isinstance(item, list):
        return [x for sub in item for x in _normalise(sub)]
    return []


def urls_for(name: str, source: dict) -> list[str]:
    listed = (source.get("files") or {}).get(name)
    if listed:
        return [listed] if isinstance(listed, str) else list(listed)
    base = source.get("base") or ""
    if not base:
        return []
    return [f"{base}/{name}"]


def local_files(folder: str | os.PathLike, build: str | None = None) -> dict[str, Path]:
    """Inkling-2-Mini model files already present in `folder` with their exact pinned size (`.strata`, abliterated, or GGUF)."""
    found: dict[str, Path] = {}
    base = Path(folder)
    want = None if build is None else set(files_of(build, vision=True))
    for name, (size, _sha) in ALL_FILES.items():
        if want is not None and name not in want:
            continue
        p = base / name
        try:
            if p.is_file() and p.stat().st_size == size:
                found[name] = p
        except OSError:
            continue
    return found
