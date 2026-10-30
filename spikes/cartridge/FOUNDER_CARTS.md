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
amortised and a graft under a second to stage. Every file below is in
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
