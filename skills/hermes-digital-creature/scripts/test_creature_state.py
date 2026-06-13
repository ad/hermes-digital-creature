#!/usr/bin/env python3
"""Regression smoke tests for creature_state.py (native-first runtime)."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("creature_state.py")
MARKER = ".hermes-digital-creature-state"


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

    def seed_legacy_db(self) -> None:
        """Create a schema<=2 database with legacy memories/traits the runtime no longer manages."""
        self.data_dir.mkdir(parents=True)
        (self.data_dir / MARKER).write_text("schema_version=2\n", encoding="utf-8")
        conn = sqlite3.connect(self.data_dir / "creature.sqlite3")
        conn.executescript(
            """
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE memories (
                id TEXT PRIMARY KEY, type TEXT, content TEXT, confidence REAL, importance REAL,
                emotional_weight REAL, decay_rate REAL, status TEXT, created_at TEXT, updated_at TEXT,
                last_recalled_at TEXT, recall_count INTEGER, source TEXT, consent INTEGER,
                supersedes_id TEXT, conflict_group TEXT
            );
            CREATE TABLE traits (name TEXT PRIMARY KEY, value REAL, updated_at TEXT, reason TEXT);
            """
        )
        conn.execute("INSERT INTO metadata VALUES ('schema_version', '2')")

        def add_mem(mem_id, mtype, content, importance, consent):
            conn.execute(
                "INSERT INTO memories(id, type, content, confidence, importance, emotional_weight, "
                "decay_rate, status, created_at, updated_at, recall_count, consent) "
                "VALUES (?, ?, ?, 0.8, ?, 0, 0.04, 'active', 't', 't', 0, ?)",
                (mem_id, mtype, content, importance, consent),
            )

        add_mem("mem_pref", "preference", "User prefers local-first tooling", 0.8, 1)
        add_mem("mem_proc", "procedural", "Rebase needs explicit branch", 0.7, 1)
        add_mem("mem_ep_keep", "episodic", "User shipped a major release", 0.9, 1)
        add_mem("mem_ep_skip", "episodic", "User mentioned the weather once", 0.3, 0)
        conn.execute("INSERT INTO traits VALUES ('curiosity', 0.6, 't', 'baseline')")
        conn.commit()
        conn.close()

    # --- core lifecycle -------------------------------------------------

    def test_init_reports_native_backend(self) -> None:
        result = self.run_cmd("init")
        self.assertTrue(result["local_only"])
        self.assertEqual(result["memory_backend"], "hermes-native")
        self.assertEqual(result["schema_version"], 3)

    def test_status_shape(self) -> None:
        self.run_cmd("init")
        status = self.run_cmd("status")
        self.assertEqual(status["memory_backend"], "hermes-native")
        self.assertEqual(status["autonomy"], "off")
        self.assertEqual(status["proactive_tasks"], [])
        self.assertIn("touchpoint", status["times"])

    def test_export_refuses_state_database_as_destination(self) -> None:
        self.run_cmd("init")
        database = self.data_dir / "creature.sqlite3"
        result = self.run_cmd("export", "--output", str(database), expect=2)
        self.assertIn("cannot overwrite", result["error"])
        self.assertTrue(self.run_cmd("status")["ok"])

    def test_export_contains_runtime_tables(self) -> None:
        self.run_cmd("init")
        output = self.data_dir / "export.json"
        self.run_cmd("export", "--output", str(output))
        exported = json.loads(output.read_text(encoding="utf-8"))
        self.assertIn("metadata", exported)
        self.assertIn("proactive_tasks", exported)
        self.assertIn("audit", exported)
        self.assertNotIn("memories", exported)

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

    # --- proactive scheduling ------------------------------------------

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
            "--task-id", first["task_id"],
            "--schedule", first["schedule"],
            "--autonomy", "gentle",
            "--prompt", first["prompt"],
            "--deliver", first["deliver"],
        )
        again = self.run_cmd(
            "proactive-register",
            "--task-id", first["task_id"],
            "--schedule", first["schedule"],
            "--autonomy", "gentle",
            "--prompt", first["prompt"],
            "--deliver", first["deliver"],
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
        self.run_cmd("proactive-revoke", "--task-id", first["task_id"], "--reason", "user-disable")
        registered = self.run_cmd("proactive-list", "--status", "registered")["tasks"]
        self.assertEqual(registered, [])
        revoked = self.run_cmd("proactive-list", "--status", "revoked")["tasks"]
        self.assertEqual(len(revoked), 1)
        self.assertEqual(self.run_cmd("status")["proactive_tasks"], [])
        audit = [entry["action"] for entry in self.run_cmd("audit")["audit"]]
        self.assertIn("proactive-register", audit)
        self.assertIn("proactive-revoke", audit)

    def test_proactive_plan_rejects_bad_time(self) -> None:
        self.run_cmd("init")
        result = self.run_cmd(
            "proactive-plan", "--autonomy", "gentle", "--touchpoint-time", "25:99", expect=2
        )
        self.assertIn("touchpoint-time", result["error"])

    # --- settings -------------------------------------------------------

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

    def test_sleep_reports_suppression_and_audits(self) -> None:
        self.run_cmd("init")
        self.run_cmd("autonomy", "set", "--value", "active")
        result = self.run_cmd("sleep", "--now", "21:30")
        self.assertTrue(result["ok"])
        self.assertIn("suppression", result)
        actions = [entry["action"] for entry in self.run_cmd("audit")["audit"]]
        self.assertIn("sleep", actions)

    def test_audit_entity_id_filter(self) -> None:
        self.run_cmd("init")
        self.run_cmd(
            "proactive-register",
            "--task-id", "digital-creature-daily-touchpoint",
            "--schedule", "every 1d at 09:00",
            "--autonomy", "gentle",
            "--prompt", "do the thing",
        )
        scoped = self.run_cmd("audit", "--entity-id", "digital-creature-daily-touchpoint")
        self.assertEqual(scoped["entity_id"], "digital-creature-daily-touchpoint")
        self.assertTrue(
            all(entry["entity_id"] == "digital-creature-daily-touchpoint" for entry in scoped["audit"])
        )
        self.assertGreaterEqual(len(scoped["audit"]), 1)

    def test_doctor_detects_proactive_drift(self) -> None:
        self.run_cmd("init")
        self.run_cmd("autonomy", "set", "--value", "gentle")
        bad = self.run_cmd("doctor")
        self.assertTrue(bad["ok"])  # drift is a warning, not an error
        self.assertIn("digital-creature-daily-touchpoint", bad["checks"]["proactive_tasks"]["drift_missing"])
        plan = self.run_cmd("proactive-plan")["tasks"][0]
        self.run_cmd(
            "proactive-register",
            "--task-id", plan["task_id"],
            "--schedule", plan["schedule"],
            "--autonomy", "gentle",
            "--prompt", plan["prompt"],
            "--deliver", plan["deliver"],
        )
        good = self.run_cmd("doctor")
        self.assertTrue(good["checks"]["proactive_tasks"]["ok"])
        self.assertEqual(good["checks"]["proactive_tasks"]["drift_missing"], [])

    # --- migration & legacy handling -----------------------------------

    def test_migrate_buckets_legacy_memories(self) -> None:
        self.seed_legacy_db()
        result = self.run_cmd("migrate")
        self.assertTrue(result["ok"])
        user_contents = [e["content"] for e in result["user_md"]]
        memory_contents = [e["content"] for e in result["memory_md"]]
        self.assertIn("User prefers local-first tooling", user_contents)  # preference -> USER.md
        self.assertIn("Rebase needs explicit branch", memory_contents)  # procedural -> MEMORY.md
        self.assertIn("User shipped a major release", memory_contents)  # high-importance episodic kept
        self.assertEqual(result["skipped_episodic"], 1)  # low-importance episodic skipped
        self.assertEqual([t["name"] for t in result["persona_traits"]], ["curiosity"])
        # migration is non-destructive: legacy table still present
        actions = [entry["action"] for entry in self.run_cmd("audit")["audit"]]
        self.assertIn("migrate", actions)

    def test_schema_autoupgrade_from_legacy(self) -> None:
        self.seed_legacy_db()
        self.run_cmd("init")  # opening upgrades schema 2 -> 3
        doctor = self.run_cmd("doctor")
        self.assertEqual(doctor["checks"]["schema_version"]["current"], 3)
        self.assertIn("memories", doctor["checks"]["legacy_tables"]["present"])
        actions = [entry["action"] for entry in self.run_cmd("audit")["audit"]]
        self.assertIn("schema-upgrade", actions)

    def test_export_includes_legacy_tables_when_present(self) -> None:
        self.seed_legacy_db()
        self.run_cmd("init")
        output = self.data_dir / "export.json"
        self.run_cmd("export", "--output", str(output))
        exported = json.loads(output.read_text(encoding="utf-8"))
        self.assertIn("memories", exported)
        self.assertEqual(len(exported["memories"]), 4)

    def test_purge_removes_data_dir(self) -> None:
        self.run_cmd("init")
        self.run_cmd("autonomy", "set", "--value", "gentle")
        self.assertTrue(self.run_cmd("purge", "--confirm", "DELETE-ALL-CREATURE-DATA")["ok"])
        self.assertFalse(self.data_dir.exists())

    def test_purge_requires_confirmation_string(self) -> None:
        self.run_cmd("init")
        result = self.run_cmd("purge", "--confirm", "nope", expect=2)
        self.assertIn("DELETE-ALL-CREATURE-DATA", result["error"])
        self.assertTrue(self.data_dir.exists())


if __name__ == "__main__":
    unittest.main()
