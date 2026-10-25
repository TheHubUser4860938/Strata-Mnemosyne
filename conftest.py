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
if _true_home is not None:
    _src = _true_home / ".config" / "strata" / "settings.json"
    if _src.is_file():
        (_Path := Path(_home) / "strata").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(_src, _Path / "settings.json")
