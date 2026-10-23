import json
import os
import tempfile
import time
import unittest
from unittest import mock

from mousework import sync


class SyncingTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = os.path.join(tmp.name, "syncing.json")
        for patcher in (mock.patch.object(sync, "PATH", self.path), mock.patch("mousework.changes.emit")):
            self.emit = patcher.start()
            self.addCleanup(patcher.stop)

    def write_marker(self, **mark):
        with open(self.path, "w") as f:
            json.dump({"pid": os.getpid(), "profile": "Night", "since": time.time(), **mark}, f)

    def test_marked_while_writing_and_cleared_after(self):
        self.assertIsNone(sync.current())
        with sync.syncing("Gaming"):
            self.assertEqual(sync.current(), {"profile": "Gaming"})
        self.assertIsNone(sync.current())
        self.assertFalse(os.path.exists(self.path))

    def test_cleared_when_the_write_fails(self):
        with self.assertRaises(RuntimeError), sync.syncing("Gaming"):
            raise RuntimeError("mouse unreachable")
        self.assertIsNone(sync.current())

    def test_start_and_end_are_announced(self):
        with sync.syncing():
            pass
        self.assertEqual([c.args for c in self.emit.call_args_list], [("syncing",), ("syncing",)])

    def test_marker_of_a_dead_process_is_ignored(self):
        self.write_marker(pid=2 ** 22 + 1)  # above pid_max's default, never alive
        self.assertIsNone(sync.current())

    def test_old_marker_is_ignored(self):
        self.write_marker(since=time.time() - sync.MAX_AGE_S - 1)
        self.assertIsNone(sync.current())

    def test_damaged_marker_is_ignored(self):
        with open(self.path, "w") as f:
            f.write("{")
        self.assertIsNone(sync.current())

    def test_another_writers_marker_is_left_alone(self):
        with sync.syncing("Gaming"):
            self.write_marker(pid=1, profile="Office")  # another process took over
        self.assertEqual(sync.current(), {"profile": "Office"})


if __name__ == "__main__":
    unittest.main()
