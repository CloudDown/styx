from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1].parent))

from styx.backend import passwords  # noqa: E402


class Passwords(unittest.TestCase):
    def test_hash_roundtrip(self):
        h = passwords.hash_password("cerberus-gate-99")
        self.assertTrue(h.startswith("scrypt$"))
        self.assertTrue(passwords.verify_password("cerberus-gate-99", h))
        self.assertFalse(passwords.verify_password("cerberus-gate-00", h))
        short = passwords.hash_password("ab")
        self.assertTrue(passwords.verify_password("ab", short))

    def test_rejects_empty(self):
        with self.assertRaises(passwords.PassphraseError):
            passwords.hash_password("")

    def test_write_mode(self):
        import tempfile

        with tempfile.TemporaryDirectory() as raw:
            dest = Path(raw) / "passwd"
            passwords.write_hash(dest, "cerberus-gate-99")
            if os.name != "nt":
                self.assertEqual(dest.stat().st_mode & 0o777, 0o600)
            stored = passwords.read_hash(dest)
            self.assertTrue(stored)
            self.assertTrue(passwords.verify_password("cerberus-gate-99", stored))


if __name__ == "__main__":
    unittest.main()
