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

    def test_proactive_plan_per_autonomy(self) -> None:
        self.run_cmd("init")
        off = self.run_cmd("proactive-plan", "--autonomy", "off")
        self.assertEqual(off["tasks"], [])
        gentle = self.run_cmd("proactive-plan", "--autonomy", "gentle")
        self.assertEqual(len(gentle["tasks"]), 1)
        self.assertEqual(gentle["tasks"][0]["task_id"], "digital-creature-daily-touchpoint")
        self.assertIn("09:00", gentle["tasks"][0]["schedule"])
        active = self.run_cmd(
            "proactive-plan",
            "--autonomy",
            "active",
            "--touchpoint-time",
            "08:30",
            "--sleep-time",
            "22:15",
            "--progress-day",
            "Mon",
        )
        ids = [task["task_id"] for task in active["tasks"]]
        self.assertEqual(
            ids,
            [
                "digital-creature-daily-touchpoint",
                "digital-creature-sleep-review",
                "digital-creature-weekly-progress",
            ],
        )
        self.assertIn("08:30", active["tasks"][0]["schedule"])
        self.assertIn("22:15", active["tasks"][1]["schedule"])
        self.assertIn("Mon", active["tasks"][2]["schedule"])

    def test_proactive_register_revoke_and_diff(self) -> None:
        self.run_cmd("init")
        plan = self.run_cmd("proactive-plan", "--autonomy", "gentle")["tasks"]
        first = plan[0]
        self.run_cmd(
            "proactive-register",
            "--task-id",
            first["task_id"],
            "--schedule",
            first["schedule"],
            "--autonomy",
            "gentle",
            "--prompt",
            first["prompt"],
            "--deliver",
            first["deliver"],
        )
        again = self.run_cmd(
            "proactive-register",
            "--task-id",
            first["task_id"],
            "--schedule",
            first["schedule"],
            "--autonomy",
            "gentle",
            "--prompt",
            first["prompt"],
            "--deliver",
            first["deliver"],
        )
        self.assertTrue(again.get("already_registered"))
        listed = self.run_cmd("proactive-list", "--status", "registered")["tasks"]
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["task_id"], first["task_id"])
        diff_to_active = self.run_cmd("proactive-diff", "--autonomy", "active")
        diff_ids = [task["task_id"] for task in diff_to_active["to_register"]]
        self.assertIn("digital-creature-sleep-review", diff_ids)
        self.assertIn("digital-creature-weekly-progress", diff_ids)
        diff_to_off = self.run_cmd("proactive-diff", "--autonomy", "off")
        self.assertIn(first["task_id"], diff_to_off["to_revoke"])
        self.run_cmd(
            "proactive-revoke",
            "--task-id",
            first["task_id"],
            "--reason",
            "user-disable",
        )
        registered = self.run_cmd("proactive-list", "--status", "registered")["tasks"]
        self.assertEqual(registered, [])
        revoked = self.run_cmd("proactive-list", "--status", "revoked")["tasks"]
        self.assertEqual(len(revoked), 1)
        status = self.run_cmd("status")
        self.assertEqual(status["proactive_tasks"], [])
        audit = [entry["action"] for entry in self.run_cmd("audit")["audit"]]
        self.assertIn("proactive-register", audit)
        self.assertIn("proactive-revoke", audit)

    def test_proactive_plan_rejects_bad_time(self) -> None:
        self.run_cmd("init")
        result = self.run_cmd(
            "proactive-plan",
            "--autonomy",
            "gentle",
            "--touchpoint-time",
            "25:99",
            expect=2,
        )
        self.assertIn("touchpoint-time", result["error"])

    def test_autonomy_get_and_set_with_audit(self) -> None:
        self.run_cmd("init")
        initial = self.run_cmd("autonomy", "get")
        self.assertEqual(initial["autonomy"], "off")
        updated = self.run_cmd("autonomy", "set", "--value", "active")
        self.assertEqual(updated["autonomy"], "active")
        self.assertEqual(updated["previous"], "off")
        self.assertEqual(self.run_cmd("status")["autonomy"], "active")
        bad = self.run_cmd("autonomy", "set", "--value", "wild", expect=2)
        self.assertIn("invalid", bad["error"])
        actions = [entry["action"] for entry in self.run_cmd("audit")["audit"]]
        self.assertIn("autonomy-set", actions)

    def test_quiet_hours_get_and_set_validates(self) -> None:
        self.run_cmd("init")
        current = self.run_cmd("quiet-hours", "get")
        self.assertEqual(current["start"], "23:00")
        self.assertEqual(current["end"], "08:00")
        updated = self.run_cmd("quiet-hours", "set", "--start", "22:30", "--end", "07:15")
        self.assertEqual(updated["start"], "22:30")
        self.assertEqual(updated["end"], "07:15")
        bad = self.run_cmd("quiet-hours", "set", "--start", "25:00", "--end", "08:00", expect=2)
        self.assertIn("HH:MM", bad["error"])

    def test_daily_reports_quiet_hours_suppression(self) -> None:
        self.run_cmd("init")
        self.run_cmd("autonomy", "set", "--value", "gentle")
        self.run_cmd("quiet-hours", "set", "--start", "22:00", "--end", "08:00")
        quiet = self.run_cmd("daily", "--now", "23:30")
        self.assertTrue(quiet["suppression"]["suppressed"])
        self.assertIn("quiet_hours", quiet["suppression"]["suppression_reasons"])
        awake = self.run_cmd("daily", "--now", "10:00")
        self.assertFalse(awake["suppression"]["suppressed"])

    def test_audit_entity_id_filter(self) -> None:
        self.run_cmd("init")
        memory = self.run_cmd(
            "remember",
            "--type",
            "preference",
            "--content",
            "User likes audit filtering",
            "--confidence",
            "0.5",
        )["memory"]
        scoped = self.run_cmd("audit", "--entity-id", memory["id"])
        self.assertEqual(scoped["entity_id"], memory["id"])
        self.assertTrue(all(entry["entity_id"] == memory["id"] for entry in scoped["audit"]))
        self.assertGreaterEqual(len(scoped["audit"]), 1)

    def test_doctor_detects_proactive_drift(self) -> None:
        self.run_cmd("init")
        self.run_cmd("autonomy", "set", "--value", "gentle")
        bad = self.run_cmd("doctor")
        self.assertTrue(bad["ok"])
        self.assertIn("digital-creature-daily-touchpoint", bad["checks"]["proactive_tasks"]["drift_missing"])
        plan = self.run_cmd("proactive-plan")["tasks"][0]
        self.run_cmd(
            "proactive-register",
            "--task-id",
            plan["task_id"],
            "--schedule",
            plan["schedule"],
            "--autonomy",
            "gentle",
            "--prompt",
            plan["prompt"],
            "--deliver",
            plan["deliver"],
        )
        good = self.run_cmd("doctor")
        self.assertTrue(good["checks"]["proactive_tasks"]["ok"])
        self.assertEqual(good["checks"]["proactive_tasks"]["drift_missing"], [])

    def test_recall_matches_morphological_variants(self) -> None:
        saved = self.run_cmd(
            "remember",
            "--type",
            "episodic",
            "--content",
            "Пользователь настраивал локальные сервера",
            "--confidence",
            "0.85",
            "--consent",
        )["memory"]
        recalled = self.run_cmd("recall", "--query", "локальный сервер")["memories"]
        self.assertEqual(recalled[0]["id"], saved["id"])

    def test_proactive_check_in_capability_retired(self) -> None:
        self.run_cmd("init")
        caps = self.run_cmd("progress")["capabilities"]
        self.assertNotIn("proactive-check-in", caps)
        self.run_cmd(
            "unlock",
            "--name",
            "proactive-check-in",
            "--reason",
            "legacy",
            "--consent",
            expect=2,
        )

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
