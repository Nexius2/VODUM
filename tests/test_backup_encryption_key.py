from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BackupEncryptionKeyTests(unittest.TestCase):
    def test_full_backup_writers_include_encryption_key(self):
        for relative_path in (
            "app/tasks/auto_backup.py",
            "app/core/backup.py",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            self.assertIn('"vodum.encryption_key"', source)
            self.assertIn('"encryption_key": True', source)

    def test_restore_extracts_and_installs_encryption_key(self):
        source = (ROOT / "app/tasks/restore_backup.py").read_text(encoding="utf-8")

        self.assertIn('"vodum.encryption_key" in names', source)
        self.assertIn("install_encryption_key(", source)
        self.assertIn("pre_restore_key_path", source)


if __name__ == "__main__":
    unittest.main()
