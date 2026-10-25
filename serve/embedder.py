"""CPU-only semantic embedder for the memory store (PHASE 4).

The store's lexical recall (FTS5) stays the candidate generator; cosine similarity over
these vectors RERANKS the candidates - the semantic layer that answers "what did the user
decide about the cascade" when the stored note says "batched the date-filter parameter into
Ladder A". The temporal diagnostic (spikes/lme/TEMPORAL_DIAG.md) is the failure study this
exists to fix: multi-evidence questions rank only the lexically-closest event's row on top.

Two models, one duck-type (2026-10-24): Embedder is BAAI/bge-small-en-v1.5 (MIT, 33M, 384
dims, 512-token cap) through ONNX Runtime, CPUExecutionProvider only - this never touches
the GPU, which is the engine's. EmbeddingGemma2 is google/embeddinggemma-2 (Apache-2.0 +
the Gemma prohibited-use rider, 270M in text-only mode, 768-d native, 8,192-token context),
the same ONNX Runtime CPU recipe against the community q8 export. create() picks by name;
no name means the directory's own name decides. Opt-in by construction: with no "embedder"
object in the config's memory block this module is never imported and the store behaves
byte-identically to before.

The files are pinned by SHA-256 (SHA256SUMS beside them, written at download 2026-10-14;
the embeddinggemma-2 pin file was written at download 2026-10-24 against the repo's own
LFS oids): bge model.onnx 828e1496..., tokenizer.json d241a60d...; eg2
onnx/model_quantized.onnx_data 278a7ff1..., tokenizer.json 4d777ef5.... A mismatch raises,
it does not warn - a silently swapped embedder silently changes every ranking in the store.

bge retrieval recipe (from the model card, verified against its config): queries carry the
prefix "Represent this sentence for searching relevant passages: ", documents are embedded
unprefixed, mean pooling over last_hidden_state masked by attention_mask, L2 normalize, dot
product = cosine. The EmbeddingGemma-2 recipe (its card, verified against the shipped graph
2026-10-24): queries "task: search result | query: ...", documents "title: none | text:
..." (our rows carry no titles), the graph's own sentence_embedding output IS the masked
mean (verified: cosine 1.0 against a numpy recompute), so only L2 normalize rides here.
The export demands image/video/audio feature inputs even for pure text - empty tensors
answer it, which is the "selectively loadable encoders" fact seen from this side of the
graph. Output selection is a CLASS LAW (OUT), never a graph sniff: auto-selecting would
have silently moved bge onto a different pooling path, and silently different vectors are
exactly what the pin file exists to make loud.
"""
from __future__ import annotations

import hashlib
import numpy as np
from pathlib import Path

QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
DIMS = 384


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_pinned(model_dir: Path) -> None:
    sums = model_dir / "SHA256SUMS"
    if not sums.exists():
        return                                   # no pin file: nothing to verify against
    for line in sums.read_text(encoding="utf-8").splitlines():
        want, _, name = line.partition("  ")
        f = model_dir / name.strip()
        if not want or not f.exists():
            continue
        got = _sha256(f)
        if got != want.strip():
            raise ValueError(
                f"embedder pin mismatch for {name}: {got[:12]}... != {want.strip()[:12]}... - "
                "a swapped model silently changes every ranking in the store")


class Embedder:
    """Load bge-small ONNX from model_dir and embed text on CPU. threads caps the ORT
    intra-op parallelism so curation backfills never starve the engine's host work.

    Every model-specific choice is a class attribute (the subclass below overrides them all
    in one place): which graph file, which output tensor, which recipe prefixes, which pad
    token, which sequence cap. An instance carries .dims and .model_name so the STORE can
    filter vectors by the model that made them (serve/memory.py, the 2026-10-24 swap law)."""

    DIMS = 384
    FILE = "model.onnx"
    MAX_SEQ = 512
    OUT = "last_hidden_state"          # pooled in numpy here: bge's verified recipe
    QUERY_PREFIX = QUERY_PREFIX
    DOC_PREFIX = ""                    # bge documents embed unprefixed
    PAD_TOKEN, PAD_ID = "[PAD]", 0

    def __init__(self, model_dir: str | Path, threads: int = 4, max_seq: int | None = None,
                 file: str | None = None):
        import onnxruntime as ort                  # lazy: opt-in feature, not a base import
        from tokenizers import Tokenizer           # ditto
        d = Path(model_dir)
        fname = file or self.FILE
        if not d.is_absolute() and not (d / fname).exists():
            # repo-root relative, the same convention memory.dir follows - a config written with a
            # relative path then works whatever the server's cwd happens to be.
            d = Path(__file__).resolve().parent.parent / d
        _verify_pinned(d)
        so = ort.SessionOptions()
        so.intra_op_num_threads = max(1, int(threads))
        so.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(str(d / fname), so,
                                         providers=["CPUExecutionProvider"])
        self.tok = Tokenizer.from_file(str(d / "tokenizer.json"))
        self.tok.enable_truncation(max_length=max_seq or self.MAX_SEQ)
        self.tok.enable_padding(pad_id=self.PAD_ID, pad_token=self.PAD_TOKEN)
        self.input_names = {i.name for i in self.sess.get_inputs()}
        out_names = {o.name for o in self.sess.get_outputs()}
        if self.OUT not in out_names:
            raise ValueError(f"embedder graph has no output {self.OUT!r} "
                             f"(has: {sorted(out_names)}) - refusing to guess a pooling path")
        self.max_seq = int(max_seq or self.MAX_SEQ)
        self.dims = self.DIMS                      # the store's matrix filter reads this
        self.model_name = d.name                   # stats() names what is actually loaded

    def _encode(self, texts: list[str]) -> np.ndarray:
        enc = self.tok.encode_batch(texts)
        ids = np.fromiter((t for e in enc for t in e.ids), np.int64,
                          count=sum(len(e.ids) for e in enc)).reshape(len(enc), -1)
        mask = np.fromiter((t for e in enc for t in e.attention_mask), np.int64,
                           count=ids.size).reshape(ids.shape)
        feed = {"input_ids": ids, "attention_mask": mask}
        if "token_type_ids" in self.input_names:
            feed["token_type_ids"] = np.zeros_like(ids)
        for feat in ("image_features", "video_features", "audio_features"):
            # the multimodal export DEMANDS these inputs even for pure text: an empty tensor
            # is the honest "no media here", not a fake frame - the encoders live OUTSIDE
            # this graph, so text-only mode loads exactly what it uses.
            if feat in self.input_names:
                feed[feat] = np.zeros((0, 512), np.float32)
        out = self.sess.run([self.OUT], feed)[0]
        if self.OUT == "last_hidden_state":        # (n, seq, dims) -> masked mean
            m = mask[..., None].astype(np.float32)
            out = (out * m).sum(1) / np.clip(m.sum(1), 1e-9, None)
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return (out / np.clip(norms, 1e-9, None)).astype(np.float32)   # L2: dot = cosine

    def embed_query(self, query: str) -> np.ndarray:
        return self._encode([self.QUERY_PREFIX + (query or "")])[0]

    def embed_docs(self, texts: list[str]) -> np.ndarray:
        """Documents embed under the model's document recipe (bge: unprefixed). Chunked to
        bound peak memory on backfills; order is preserved."""
        if not texts:
            return np.zeros((0, self.DIMS), np.float32)
        return np.vstack([self._encode([self.DOC_PREFIX + t for t in chunk])
                          for chunk in _chunks(texts, 64)])


class EmbeddingGemma2(Embedder):
    """google/embeddinggemma-2, text-only mode, community q8 ONNX (worst-case cosine to
    fp32 0.9997 per the repo's own precision table). 768-d native - and stored at FULL
    dimension on purpose (owner's call, 2026-10-24): an MRL vector stored at 768 can be
    sliced to 512/256/128 later with an L2 re-normalize and no re-embed, while a store
    written at 256 can never grow back. The multimodal encoders stay out of this process
    until media rows exist; the shared 768-d space guarantees today's text vectors stay
    comparable with the image embeds of whatever day the encoder is switched on."""

    DIMS = 768
    FILE = "onnx/model_quantized.onnx"
    MAX_SEQ = 8192
    OUT = "sentence_embedding"
    QUERY_PREFIX = "task: search result | query: "
    DOC_PREFIX = "title: none | text: "
    PAD_TOKEN, PAD_ID = "<pad>", 0

    def __init__(self, model_dir: str | Path, threads: int = 4, max_seq: int | None = None,
                 file: str | None = None):
        super().__init__(model_dir, threads=threads, max_seq=max_seq, file=file)
        pid = self.tok.token_to_id(self.PAD_TOKEN)
        if pid is not None:
            self.tok.enable_padding(pad_id=pid, pad_token=self.PAD_TOKEN)
        self.model_name = "embeddinggemma-2"       # dir names vary; the stamp must not


def resolve_class(name: str) -> type:
    """Name -> class, as a pure function (loadable without any files on disk). An unknown
    name RAISES - the anti-vacuity law: an address that names no model must not quietly
    widen to whichever embedder happens to be installed."""
    n = (name or "").strip().lower()
    if "embeddinggemma" in n:
        return EmbeddingGemma2
    if "bge" in n:
        return Embedder
    raise ValueError(f"unknown embedder name {name!r}: known names contain 'bge' or "
                     f"'embeddinggemma'")


def create(model_dir: str | Path, threads: int = 4, name: str | None = None,
           max_seq: int | None = None, file: str | None = None) -> Embedder:
    """Build the embedder a config names; no name means the directory's own name decides
    (the bge default discovery in server.py writes dirs named after their model)."""
    cls = resolve_class(name or Path(model_dir).name)
    return cls(model_dir, threads=threads, max_seq=max_seq, file=file)


def _chunks(xs, n):
    for i in range(0, len(xs), n):
        yield xs[i:i + n]
