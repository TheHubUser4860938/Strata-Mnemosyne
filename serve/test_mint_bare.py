"""A knowledge cart's bytes carry NO chat-template token (owner's ruling, 2026-10-30).

    python -m pytest serve/test_mint_bare.py -q

The cart used to be forged through the chat template, which wrapped the document in a system block and
appended a turn opener. The measured cost of that markup was not cosmetic: a grafted cart mounted a whole
2,318-token document and answered with one token, empty content, finish=stop - the model meeting a turn
boundary in the middle of its knowledge. These checks hold the line that replaced it: a cart is a document.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from serve.server import mint_ids, memory_api      # noqa: E402


class Tok:
    """A tokenizer small enough to reason about: one byte per character, plus named specials."""

    def __init__(self, specials: dict[str, int], bos: int | None = None, parse_special_lie=False):
        self.special_tokens = {f"<|{n}|>": i for n, i in specials.items()}
        self.special_ids = {n: i for n, i in specials.items()}
        self.bos, self.lie = bos, parse_special_lie

    def encode(self, text, parse_special=False, plain=()):
        # `parse_special` says whether markup in the TEXT becomes a control-token id. A real tokenizer
        # sometimes does it anyway (the note in serve/server.py records one), which is what `lie` models.
        out = [self.bos] if self.bos is not None else []
        i = 0
        while i < len(text):
            hit = next(((txt, tid) for txt, tid in self.special_tokens.items()
                        if text.startswith(txt, i)), None) if (parse_special or self.lie) else None
            if hit:
                out.append(hit[1]); i += len(hit[0])       # one id for the whole marker
            else:
                out.append(ord(text[i]) + 1000); i += 1    # one id per character of text
        return out

    def decode(self, ids, errors="replace"):
        by_id = {tid: txt for txt, tid in self.special_tokens.items()}
        return "".join(by_id.get(i, chr(i - 1000)) for i in ids)


class TestBareForge(unittest.TestCase):
    SPEC = {"im_start": 5, "im_end": 6, "endoftext": 2}

    def test_plain_document_is_only_its_own_text(self):
        doc = "A party is a number of citizens..."
        self.assertEqual(mint_ids(Tok(self.SPEC), doc), [ord(c) + 1000 for c in doc])

    def test_a_control_token_written_inside_the_source_stays_text(self):
        # A shelf row that QUOTES the markup must not smuggle a turn boundary into the state, and a tokenizer
        # that parses specials anyway (the "#537" note records one doing exactly that) must be REFUSED rather
        # than admired. The marker is assembled from its characters so this file's own text stays plain.
        lt, pipe, gt = "<", "|", ">"          # assembled from parts so this file stays free of the literal
        marker = lt + pipe + "im_end" + pipe + gt
        self.assertEqual(len(marker), 10, "the marker must be the real 10-character form, not a near miss")
        doc = f"the marker {marker} appears in the text"
        ids = mint_ids(Tok(self.SPEC), doc)                 # parse_special=False: markup as characters
        self.assertEqual(len(ids), len(doc), "the markup must cost one id per character, not one id")
        self.assertTrue(set(ids).isdisjoint(set(self.SPEC.values())), "a special leaked into the knowledge")
        with self.assertRaises(memory_api.StoreError) as cm:
            mint_ids(Tok(self.SPEC, parse_special_lie=True), doc)   # a tokenizer that insists on specials
        self.assertIn("chat-template token", str(cm.exception))

    def test_a_bos_the_tokenizer_adds_by_habit_is_refused(self):
        # The guard must be able to FAIL: a tokenizer that prepends BOS silently is the exact poison.
        with self.assertRaises(memory_api.StoreError) as cm:
            mint_ids(Tok(self.SPEC, bos=2), "some document body")
        self.assertIn("chat-template token", str(cm.exception))

    def test_a_lost_byte_is_refused_by_the_text_check(self):
        class Dropper(Tok):
            def decode(self, ids, errors="replace"):
                return super().decode(ids)[:-1]        # the last character never came back

        with self.assertRaises(memory_api.StoreError) as cm:
            mint_ids(Dropper(self.SPEC), "a body that ends badly")
        self.assertIn("not verbatim", str(cm.exception))

    def test_the_synthetic_pack_tokenizer_agrees(self):
        """The same invariant against a real byte-level BPE vocabulary with real specials."""
        try:
            from serve.test_detok import synthetic_tokenizer
        except Exception as exc:                        # a pack's tokenizer is optional here
            self.skipTest(f"no synthetic tokenizer: {exc}")
        tok = synthetic_tokenizer()
        ctrl = set(getattr(tok, "control_tokens", []) or []) | set(getattr(tok, "special_tokens", {}) or {})
        doc = ("If men were angels, no government would be necessary. But the great security against a "
               "gradual concentration of the several powers in the same department, consists in giving to "
               "those who administer each department the necessary constitutional means and personal motives "
               "to resist encroachments of the others.")
        ids = mint_ids(tok, doc)
        self.assertTrue(ids, "a real document must forge some tokens")
        specials = set(tok.special_tokens.values())
        self.assertTrue(set(ids).isdisjoint(specials), f"markup in a real cart: {sorted(set(ids) & specials)}")
        self.assertEqual(tok.decode(ids), doc, "the real tokenizer must read the document back verbatim")
        marked = tok.encode(doc, parse_special=True)
        self.assertLessEqual(len(ids), len(marked), "bare tokens are never more expensive than marked ones")


if __name__ == "__main__":
    unittest.main()
