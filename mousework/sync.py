"""Marks that Mousework is writing settings to the mouse (`syncing` in docs/json.md).

A write that changes the power settings makes the mouse drop its link for a
few seconds. While a write is under way, the writing process keeps a marker
file, so `mousework status --json` can tell widgets the mouse is syncing
rather than asleep.
"""

import json
import os
import time
from contextlib import contextmanager

from . import changes

PATH = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or "/tmp", "mousework-syncing.json")
MAX_AGE_S = 120  # no write takes this long; an older marker is a leftover


@contextmanager
def syncing(profile=None):
    """Mark the block as a write to the mouse, for the profile named (or None)."""
    tmp = f"{PATH}.{os.getpid()}"
    with open(tmp, "w") as f:
        json.dump({"pid": os.getpid(), "profile": profile, "since": time.time()}, f)
    os.replace(tmp, PATH)
    _announce()
    try:
        yield
    finally:
        try:
            if _read().get("pid") == os.getpid():  # another writer may have taken over
                os.remove(PATH)
        except (OSError, ValueError):
            pass
        _announce()


def current():
    """{"profile": name or None} while some process syncs, otherwise None."""
    try:
        mark = _read()
    except (OSError, ValueError):
        return None
    if time.time() - mark.get("since", 0) > MAX_AGE_S or not _alive(mark.get("pid")):
        return None
    return {"profile": mark.get("profile")}


def _read():
    with open(PATH) as f:
        return json.load(f)


def _alive(pid):
    if not isinstance(pid, int):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        pass
    return True


def _announce():
    try:
        changes.emit("syncing")
    except Exception:  # no session bus; widgets fall back to polling
        pass
