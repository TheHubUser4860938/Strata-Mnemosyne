r"""pytest: setup.py's data-folder migration (#198) saves the data folder it settled on in the user's settings file
(%APPDATA%\Strata\settings.json, ~/.config/strata/settings.json) and can MOVE model files from a folder it finds there.
A test that reaches it must never touch the real file, so the whole session gets its own config home."""
import os
import shutil
import tempfile
from pathlib import Path

_home = tempfile.mkdtemp(prefix="strata-pytest-config-")
os.environ["APPDATA"] = _home
os.environ["XDG_CONFIG_HOME"] = _home
# (2026-10-24) The isolation had one blind spot: an EMPTY config home makes data_dir() fall
# back to the beside-the-install default, so every test gated on "the model is downloaded on
# this box" skipped ON THE BOX THAT HAS THE MODELS - the real-embedder smokes (bge since
# 2026-10-14, embeddinggemma-2 since 2026-10-24) never actually ran under pytest here, and a
# green suite hid it. The fix keeps the law and restores the fact: copy the real settings
# file in (reads see the box, writes still land in the session's throwaway home). A box with
# no settings file changes behavior not at all - same empty home as before.
try:
    import pwd as _pwd  # posix: the true home, under which the settings file lives
    _true_home = Path(_pwd.getpwuid(os.getuid()).pw_dir)
except (ImportError, KeyError):
    _true_home = None
# (2026-10-25, the v0.2.4.2 merge round) The copy serves the SERVE suite and only the serve suite: its
# real-embedder smokes are gated on "the model is on this box" - measured again today, not remembered:
# serve/test_embedder.py is 10 passed with the copy, 2 passed + 8 skipped without it. tests/terminal
# assumes the OPPOSITE (an empty config home), and with the box copied in, data_dir() answers this
# box's folder - 1,696 GB free and the model files already there - so four of their plan/download-size
# tests argue with the fixture instead of with the code. Measured on this box (RTX 4090, Linux, the
# live server up, the checkout's own strata-*.json present): 35 distinct failures in the ten worst
# files today, 31 with this scoping, 30 on a clean upstream v0.2.4.2 in the same conditions - the
# fork-side delta is down to one test (its model menu is longer than the fixture's screen). So: a run
# that names only tests/ gets the empty home upstream expects; any other run keeps the box.
# STRATA_PYTEST_BOX_CONFIG=0 or 1 overrules the guess (a combined `pytest` of both suites wants =1 to
# hold today's behavior, =0 to see the terminal suite as upstream's fixtures intend).
_args = [a for a in __import__("sys").argv[1:] if not a.startswith("-")]
_tests_only = bool(_args) and all(Path(a.replace("\\", "/")).parts[0] == "tests" for a in _args)
_BOX_CFG = os.environ.get("STRATA_PYTEST_BOX_CONFIG", "0" if _tests_only else "1") != "0"
if _true_home is not None and _BOX_CFG:
    _src = _true_home / ".config" / "strata" / "settings.json"
    if _src.is_file():
        (_Path := Path(_home) / "strata").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_src, _Path / "settings.json")
