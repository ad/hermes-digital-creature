#!/usr/bin/env python3
"""Regression smoke tests for creature_state.py."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("creature_state.py")


class CreatureStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.tmp.name) / "state"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def run_cmd(self, *args: str, expect: int = 0) -> dict:
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--data-dir", str(self.data_dir), *args],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, expect, completed.stdout + completed.stderr)
        return json.loads(completed.stdout)

    def test_memory_recall_correction_and_export(self) -> None:
        self.assertTrue(self.run_cmd("init")["local_only"])
        saved = self.run_cmd(
            "remember",
            "--type",
            "preference",
            "--content",
            "User prefers local first tooling",
            "--confidence",
            "0.9",
            "--importance",
            "0.8",
            "--consent",
        )["memory"]
        recalled = self.run_cmd("recall", "--query", "local tooling")["memories"]
        self.assertEqual(recalled[0]["id"], saved["id"])
        corrected = self.run_cmd(
            "correct",
            "--id",
            saved["id"],
            "--content",
            "User prefers local first tooling unless maintenance cost is excessive",
            "--consent",
        )
        self.assertEqual(corrected["superseded_id"], saved["id"])
        output = self.data_dir / "export.json"
        self.run_cmd("export", "--output", str(output))
        exported = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(len(exported["feedback"]), 1)
        self.assertEqual(len(exported["memories"]), 2)

    def test_export_refuses_state_database_as_destination(self) -> None:
        self.run_cmd("init")
        database = self.data_dir / "creature.sqlite3"
        result = self.run_cmd("export", "--output", str(database), expect=2)
        self.assertIn("cannot overwrite", result["error"])
        self.assertTrue(self.run_cmd("status")["ok"])

    def test_sensitive_content_and_unconfirmed_high_confidence_are_rejected(self) -> None:
        self.run_cmd(
            "remember",
            "--type",
            "preference",
            "--content",
            "api key is hidden",
            "--consent",
            expect=2,
        )
        self.run_cmd(
            "remember",
            "--type",
            "preference",
            "--content",
            "User might prefer short answers",
            "--confidence",
            "0.9",
            expect=2,
        )

    def test_refuses_non_owned_nonempty_data_directory(self) -> None:
        unowned = Path(self.tmp.name) / "not-creature-owned"
        unowned.mkdir()
        (unowned / "keep.txt").write_text("keep", encoding="utf-8")
        completed = subprocess.run(
            [sys.executable, str(SCRIPT), "--data-dir", str(unowned), "status"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertTrue((unowned / "keep.txt").exists())

    def test_recall_matches_cyrillic_topics(self) -> None:
        saved = self.run_cmd(
            "remember",
            "--type",
            "episodic",
            "--content",
            "Пользователь настраивал локальный сервер",
            "--confidence",
            "0.85",
            "--consent",
        )["memory"]
        recalled = self.run_cmd("recall", "--query", "локальный сервер")["memories"]
        self.assertEqual(recalled[0]["id"], saved["id"])

    def test_traits_activities_sleep_audit_and_purge(self) -> None:
        memory = self.run_cmd(
            "remember",
            "--type",
            "episodic",
            "--content",
            "User discussed a local server",
            "--confidence",
            "0.6",
        )["memory"]
        self.run_cmd("confirm", "--id", memory["id"])
        self.run_cmd("trait", "--name", "verbosity", "--delta", "-0.05", "--reason", "User asked for concise output")
        activity_id = self.run_cmd(
            "activity",
            "start",
            "--kind",
            "memory-repair",
            "--title",
            "Review server memory",
        )["activity_id"]
        self.run_cmd("activity", "complete", "--id", activity_id, "--result", "Confirmed by user")
        self.assertTrue(self.run_cmd("sleep")["ok"])
        self.run_cmd("unlock", "--name", "reflection", "--reason", "User wants local reflection reviews", "--consent")
        self.assertEqual(self.run_cmd("progress")["capabilities"]["reflection"], "unlocked")
        self.assertGreaterEqual(len(self.run_cmd("audit")["audit"]), 5)
        self.assertTrue(self.run_cmd("purge", "--confirm", "DELETE-ALL-CREATURE-DATA")["ok"])
        self.assertFalse(self.data_dir.exists())


if __name__ == "__main__":
    unittest.main()
