# skills

The working kit for an agent that runs the store. Each folder is one skill: a `SKILL.md`
with a front-matter `name` and `description`, a procedure, and the pitfalls measured the
expensive way.

| skill | what it is for |
|---|---|
| [shelf-ops](shelf-ops/SKILL.md) | the store's verbs - browse with words, read the map of shelves, walk one shelf, write, re-shelve, embed. Use it before shelf work: most shelf failures are on the seams between the HTTP API, the `memory_search` tool and the harvest. |
| [bench-panel](bench-panel/SKILL.md) | proving a change helped. Freeze the rubric, name the one variable, run at least three repeats, score binding and content apart, write the record where it survives. |

## Install

OpenCode reads skills from `~/.config/opencode/skills/` (and `~/.agents/skills/`):

```sh
ln -s ~/Projects/Strata-Mnemosyne/skills/shelf-ops   ~/.config/opencode/skills/shelf-ops
ln -s ~/Projects/Strata-Mnemosyne/skills/bench-panel ~/.config/opencode/skills/bench-panel
```

They load hot - no restart. Keep the set stable across a working day: a description rides
every request, so a change to the set re-forks every parked conversation's prefix once.

Add a skill when the same lesson has been learned twice. Write it as a procedure, not a
diary: a pitfall is a rule plus one clause of why, and a corrected skill is corrected in
place.
