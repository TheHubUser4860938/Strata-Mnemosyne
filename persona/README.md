# persona/ — the standing texts

Clio's prompt is assembled from six static files, all of them in this
folder; `memory.soul` names `persona/soul.md` and `memory.cartridges.files` names
the other five:

| file                | role                  | git                       |
|---------------------|-----------------------|---------------------------|
| `soul.md`           | who I am              | tracked                   |
| `agent.md`          | how I work            | tracked                   |
| `skill.md`          | what I can do         | tracked                   |
| `user.md`           | who the human is      | box-local (personal data) |
| `always.md`         | the map of this box   | box-local (real paths)    |
| `owner-voice.md`    | how the owner writes  | box-local (his posts)     |

The law the split serves: **personal data never enters git** — so the tracked
files speak around names and paths, and the three that carry them are copied
from the `.example` templates (the voice file has no template: it is written on
the box, from the owner's own archive) and filled in per machine. A missing file is
announced when the cartridge builds and skipped — the cart stands without it.

All of it is static on purpose: the tier-2 cartridge names itself by a content
hash of these bytes, so it rotates only when a hand edits a file. Daily life
writes zero. If a fact changes every day, it belongs in the store, not here.
