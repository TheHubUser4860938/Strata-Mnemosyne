# Founder cartridges: named so an ask finds the right cart

Written 2026-10-30, after the owner's ruling on grouping: *"the way you are grouping by subject/author is a
good plan, should also help with picking the correct MAM cartridges for each ask by me or you in testing -
like I ask you 'what was Washington's farewell address?'"*. So the naming is not decoration: **the cart name
is the router.** A person should be able to hear an ask and name the cart without opening anything.

## The measured numbers the design rests on

| fact | value | how it was measured |
|---|---|---|
| fixed floor per cart | **117.7 MB**, paid whether the cart holds 1 token or 100,000 | probe-nine (55 tok) = 118.9 MB; fed51 (2,275 tok) = 152.8 MB; the difference is the per-token term |
| cost per token of state | **~15.7 KB** | (152.8 − 117.7) MB ÷ 2,275 tok; predicted 153.3 MB for a new 2,269-tok cart, actual **152.8 MB** |
| a document *added* to a standing cart | **~6 MB** (a short charter, ~400 tok) | ch3 1,205 tok = 136.5 MB → ch6 2,863 tok = 161.8 MB, i.e. 25.3 MB for 5 more documents |
| a *new* cart | **136–162 MB** | the same two carts, each carrying the floor |
| state versus text | **~4,000×** | 15.7 KB/token against ~5.5 bytes/token of text |
| staging a cart for a graft | **~1.2 GB/s** | 118.9 MB in 45.3 ms, 152.8 MB in 51.7 ms (engine's own "graft staged" lines) |

Two consequences, both of which the owner has now ruled on:

1. **Documents belong together**, because the floor is shared and an added document is twenty times cheaper
   than a new cart. Hence no character cap: the cap was taxing the cheap thing (3bf7d273, then made a true
   default at the owner's second correction: *"no cap shouldn't be opt in but default"* — `None`, not a big
   number pretending).
2. **But not everything together.** At ~4,000× the text, the whole 114 MB founding corpus would be roughly
   **430 GB** of state. So a cart is what you consult constantly, and "don't cram a library into one
   cartridge" is a judgment about attention and cost, not a number in a config.

Measured on this box, within the range I could test: **document count is not what makes an answer hard to
get — the question is.** Against one six-document charter cart, three phrasings scored 2 of 6, 3 of 6, then
**4 of 6 exact** in the owner's own form ("what did so-and-so say about x"), with cartless controls at
0 of 6. Holding that phrasing fixed, a 3-document cart scored 2 of 3 and the 6-document cart 4 of 6: the same
rate, and one document did *better* in the bigger cart. Whether it breaks at 12 or 20 documents is
unmeasured — `bench/p1/dilution_test.py` is ready and needs the cap gone to mint at all.

## The carts, named to route

Sizes are targets from the table above: **5,000–25,000 tokens per cart (196–513 MB)**, which keeps the floor
amortised and a graft under a second to stage. **Superseded by measurement** — see "The measured law of what a
cart can carry" below: at 8,696 tokens only the front of the cart answers, so the working size is roughly
2,000–3,000 tokens with the most-asked material last. Every file below is in
`~/Documents/Clio's_Research/founding_corpus/`, and the `title` field of each mint is the routing sentence,
because the ledger shows that text wherever carts are listed.

### The founders

| cart | holds | the ask that routes there |
|---|---|---|
| `found-washington` | Farewell Address, 1796 (*charters/washington_farewell_1796.txt*, 6,249 w) + First Inaugural, 1789 (*founders/washington_inaugural_addresses.txt*) | "What was Washington's farewell address?" · "What did Washington warn against?" |
| `found-jefferson` | Declaration of Independence, 1776 + *Summary View of the Rights of British America*, 1774 (7,166 w) + *Notes on the State of Virginia*, 1781 | "What did Jefferson say about the king of Great Britain?" |
| `found-franklin` | *Autobiography* (34,866 w — split into two carts by part) + *Way to Wealth*, 1758 | "What did Franklin say about industry and frugality?" |
| `found-madison` | *Writings* vol. 1 (34,901 w), split by year; the Federalist papers stay in their own carts | "What did Madison say about factions?" |
| `found-hamilton` | *Works* (the clean Cornell and Google editions, 33–34k w each), split by volume | "What did Hamilton say about public credit?" |
| `found-adams` | *Works* vols. 1, 2, 4–6, 9, 10 (~240k w each) — **OCR, see the caveat** | "What did Adams say about a government of laws?" |
| `found-paine` | *Rights of Man* (34,818 w) + *The Age of Reason* (35,447 w) | "What did Paine say about hereditary succession?" |
| `found-dickinson` | *Letters from a Farmer in Pennsylvania*, 12 letters (302 KB) | "What did Dickinson say about Parliament regulating trade?" |

### The Federalist, by subject rather than by number

Eighty-five papers in one cart would be ~66,000 words ≈ 90,000 tokens ≈ 1.5 GB — legal, but it makes the cart
the whole book and defeats the routing. Grouped by subject, each cart is a thing someone asks about:

| cart | papers | the ask |
|---|---|---|
| `fed-republic` | 10, 14, 37, 39, 51, 63 | "What did Publius say about a republic curing the mischiefs of faction?" |
| `fed-separation` | 47–51 | "What did Publius say the great security against concentration consists in?" |
| `fed-executive` | 70–77 | "What did Publius say about energy in the executive?" |
| `fed-judiciary` | 78–83 | "What did Publius say the judiciary has neither of?" |
| `fed-taxation` | 30–36 | "What did Publius say about the power of taxation?" |
| `fed-union` | 1–9 | "What did Publius say about the utility of the Union?" |

### The charters, by era

| cart | holds | the ask |
|---|---|---|
| `charters-colonial` | Mayflower Compact 1620, Maryland Charter 1632, Fundamental Orders, the early charters | "What did the Mayflower Compact say the settlers were combining themselves into?" *(measured: answered from state)* |
| `charters-resistance` | Stamp Act resolves 1765, Declaratory Act 1766, Boston Non-Importation 1768, Quartering Act 1774, Circular Letter 1774 | *(this is `ch6`, already standing and already quizzed: 4 of 6 exact)* |
| `charters-founding` | Declaration 1776, Articles of Confederation 1781, Constitution 1787, Northwest Ordinance, Judiciary Act 1789 | "What did the Constitution say about the migration of such persons as shall think proper to admit?" |

### The influencers, for the asks about pedigree

`influence-montesquieu`, `influence-locke` (*Second Treatise*, *Human Understanding*), `influence-blackstone`,
`influence-cato`, `influence-bible` (King James), `influence-plutarch`, `influence-aristotle` — all clean in
the corpus. These are the carts for "who did the founders read?" and for any argument about pedigree.

## The measured law of what a cart can carry (2026-10-30, after the curve was run)

The targets above were written before the measurement. The measurement is now on record, and it
changes them. Instruments: `bench/p1/dilution_test.py`, `density_curve_test.py`,
`density_voice_test.py`, `position_test.py`, `framing_ab_test.py`, `farewell-position-2026-10-30.log`.
All on nested carts of the same twelve charters, three repeats, temperature 1.0, golds verified present
in the text and checked cartless first.

1. **A cart is read like a document, not like an index.** In the 12-document cart (8,696 tokens),
   retrieval by position in the cart: **positions 1-4 = 6/12, positions 5-8 = 0/12, positions
   9-12 = 1-3/12** (strict; the judged column is within one ask of it). Head strong, middle lost,
   tail partly recovered — a U-shape, which is the shape the "lost in the middle" literature predicts
   for a linear read. Document *count* was never the variable; it is a proxy for how much of the cart
   ends up in the middle.
2. **Titles are not an index the model can consult.** Asked about the Judiciary Act inside the
   twelve-document cart, the model answered: *"there is no document titled JUDICIARY ACT, 1789 — the
   only document provided is titled THE UNITED STATES BILL OF RIGHTS."* It denies documents that are
   in the state. Title lines in the cart text neither help nor hurt (arm C vs B: 9/36 vs 10/36).
3. **How the ask is worded matters less than where the answer sits.** Quoting the title vs naming the
   actor in prose: 7/36 vs 10/36 strict, 7/36 vs 11/36 judged — inside the noise at this n, and the
   position effect is six times bigger than the framing effect.
4. **State carries a *known text*, not a searchable transcript.** Probing one document (Washington's
   Farewell Address, 7,293 tokens, no titles) with exact completions: the tail (93% through) completed
   correctly **3/4 with the cart and 0/2 without**, while the head and middle completions landed on
   *other real sentences of the same document* ("bosom of his family") rather than the probed line. The
   cart gives the model the document as something it has read; an arbitrary probe can still land on the
   wrong page.
5. **Content asks beat exact-wording asks.** "Quote the words that follow X" scored 0/108 on a strict
   five-word quote, and the tolerant scorer still put it far below the same documents asked as content
   ("what do the subscribers say they combine themselves into?" → "a civil body politick"). Grade
   content with a cold temperature-0 judge, not only by substring: the judge and the substring matcher
   disagreed on 3 of 12 documents, always in the direction of a correct paraphrase called a miss.
6. **Temperature 1.0 is noisy for factual asks.** The same grafted ask abstained in 5 of 6 repeats and
   quoted the sentence verbatim in the sixth; at temperature 0.3 the abstention rate was the same. The
   bench rule stands at three repeats minimum, and a single answer is not a result — but note the
   variance is in the *abstention*, not in the temperature setting.
7. **Cost, measured on the same carts:** floor 117.7 MB, 15.3-15.6 KB/token up to ~10k tokens
   (dil3 2,082 tok = 149.9 MB, dil6 4,388 = 185.1, dil9 5,931 = 208.6, dil12 8,696 = 250.8 — the
   linear model predicts 150.0 / 185.7 / 209.6 / 252.5). Above ~19k tokens the per-token cost rises
   (fed6 18,971 tok = 525.9 MB is 21.5 KB/tok, fed12 37,376 = 806.9 MB is 18.4 KB/tok), so the linear
   model is good to about 10k tokens and optimistic beyond it. Staging a cart for a graft stays at
   ~50 ms for 229 MB (~4.6 GB/s), and a graft of 8,696 tokens costs about 0.9 s end to end.
8b. **THE WALL IS 2,048 CELLS, AND IT IS OURS** (measured 2026-10-30, `graft_cliff_test.py`,
 `cliff-fine-2026-10-30.log`). A 30-cell grid of planted facts, swept by **absolute depth** inside carts
 of 1,500 / 3,000 / 7,300 / 15,000 tokens, shows the cliff does not scale with cart length: depth 200
 answers **8/8 across every cart length** (including 15k), depth 4,000+ answers **0/8** at every length.
 A fine sweep in a single 2,700-token cart - short enough that length cannot be the variable - puts the
 wall exactly at: **1,900 = 2/2 PASS, 2,000 = 1/2 split, 2,048 = 0/2, 2,100 = 0/2, 2,200 = 0/2,
 2,500 = 0/2.** The constant is in the geometry: `qsa.hpp:112` sets `idx_top_k = 2048`, documented as
 *"2048 cells of selection budget"*, with `idx_block = 4` and `page_size = 4` cells. Three things make
 this a **restore defect** and not a limit of state-as-memory:
   - the bytes are present: `cfr-vexlin-2500` holds 2,580 tokens in **157.5 MB** against **157.5 MB**
     predicted by the fitted cost model - the K/V for the whole cart is stored, merely not consulted;
   - the same content at the same depth answers when it is read as text (**4/6** at ~7.3k tokens) and
     when the conversation is continued from parked state (**12/12** at positions 9-12);
   - so a live read selects the relevant cells and a **grafted read selects the first cells**. The
     selection budget is being spent on position instead of relevance after a restore.
 This was then confirmed on REAL documents, not planted facts
 (`cart_answer_probe.py`, `cart_2afc_test.py`). The TRUE/FALSE instrument died first and informatively:
 23 of 24 probes answered TRUE to the paper's own sentence AND to the same sentence with its rarest word
 reversed ("determinations" as "noitretuned") - the model agrees with anything plausible, so a forced
 yes/no cannot separate remembering from agreeing, exactly the hole the critic poked in MAM's abstention
 test. The two-alternative forced choice does separate them: the passage is shown with its rare word
 blanked and the model must pick between the word the paper really uses and a same-register word from a
 DIFFERENT paper in the same depth zone, A/B randomised, asked with the right cart mounted and with a
 wrong one (MAM's own runner-up control):

 | zone | right cart | wrong cart | the cart's contribution |
 |---|---|---|---|
 | inside the wall (<2,048 cells) | **11/12 = 92%** | 7/12 = 58% | **+33 points** |
 | beyond the wall | 7/11 = 64% | 7/11 = 64% | **+0 points** |

 So the wall costs **28 points of real knowledge** (92% against 64%), and past it the cart contributes
 nothing measurable: the right paper's cart picks its own word no better than a wrong paper's cart does.
 Both zones sit above the 50% coin-flip because an authentic 18th-century word is often the more
 plausible fit in context - which is why the wrong-cart column, not chance, is the honest baseline.

 The consequence for design is blunt and useful: **a cart is fully consultable up to ~2,000 tokens
 today**, which is a measured number rather than the guess this file opened with, and MAM never meets
 this wall because his cartridges are ~48 rows - forty times under it. The golden test for a fix is
 already written: graft a 2,700-cell cart, ask about the fact at 2,500, and go from 0/2 to 2/2.

9. **One graft per request.** `X-Strata-Carts-Graft` resolves a single cart (server.py:7952 sets one
   path), so "several small carts mounted together, each with its own head" is not available without
   engine work. Today the only lever is cart size and ordering.

**What this means for the founder family.** The 5,000-25,000 token target above is too big to be
consulted: at 8,696 tokens only the front of the cart answers. Until multi-cart grafting exists, the
rule that the measurements support is:

- **one document per cart** where the document fits in roughly 2,000-3,000 tokens, and
- **split long documents by section** (the Farewell Address at 7,293 tokens answered reliably only at
  its tail), one cart per section, named for what the section is about;
- **put the most-asked material last**, since the tail of the cart is adjacent to the ask and the
  middle is where answers get lost;
- **route by the ledger, not by the state**: the cart *name* and *title* are for choosing which cart to
  mount, and the model cannot be trusted to enumerate what is inside a mounted cart.


## Two caveats, labeled rather than buried

- **My cleanliness metric is weaker than it sounds.** I sorted files by their share of non-ASCII characters,
  which catches *glyph* damage but not *letter* damage. The Adams volumes open as "N THE CUSTODY OE TME
  BOSTON PUBLIC LIBRARY" — every one of those is ASCII, and three of the words are wrong. So `found-adams`
  and the archive.org Hamilton and Madison volumes are **OCR carts**: if one answers poorly, the text failed,
  not the cartridge, and I will say so instead of blaming the state.
- **A bare cart can only ever be grafted, never prefix-reused.** A real request begins with the chat
  template's turn opener while a bare cart begins with document text, so the byte-exact match that makes the
  standing cart fast is closed to knowledge carts by design. That is the right trade — knowledge is not a
  prefix — but it means every one of these carts depends on the graft path, which is why the verify-window
  fix of this morning (`e2b41dd1`) had to come first.

## The acceptance test, in his words

For each cart, one ask in the form he asked for, scored on the document's own words:

```
python3 bench/p1/founders_voice_test.py --cart found-washington
python3 bench/p1/founders_voice_test.py --cart charters-resistance
```

An ask that cannot name its cart is an ask that should go to the recall block or to a search, not to a
cartridge. The cart list is in the ledger (`op: "carts"`), and `always.md` carries the standing summary, so
the routing table above is checkable rather than remembered.
