#!/usr/bin/env python3
"""Local scheduling/settings runtime for the Hermes Digital Creature skill.

Native-first design: the creature's *memory and identity* live in Hermes built-in
memory (``MEMORY.md`` / ``USER.md``), session search, and any configured external
memory provider — there is only one Hermes. This script no longer keeps a parallel
memory store. It owns only the deterministic state that Hermes does not provide for
this skill on its own:

- persisted settings (autonomy level, quiet hours, proactive times);
- the proactive task plan and a record of what Hermes cron should have registered;
- diagnostics (``doctor``) and a one-time ``migrate`` helper that turns any legacy
  creature memories into a seed plan for native memory.

This process intentionally has no network behavior and uses only Python stdlib.
All persistent mutations happen inside the configured data directory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


AUTONOMY_LEVELS = ("off", "gentle", "active")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
TIME_PATTERN = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
SCHEMA_VERSION = 3
MARKER_FILENAME = ".hermes-digital-creature-state"

# Legacy tables from schema <= 2. The runtime no longer creates or writes them,
# but `migrate` reads them (when present) to seed native memory, and `export`
# includes them if they still exist so nothing is silently hidden.
LEGACY_TABLES = (
    "memories",
    "memory_links",
    "traits",
    "capabilities",
    "feedback",
    "activities",
    "reflections",
)

DEFAULT_AUTONOMY = "off"
DEFAULT_QUIET_START = "23:00"
DEFAULT_QUIET_END = "08:00"
DEFAULT_TOUCHPOINT_TIME = "09:00"
DEFAULT_SLEEP_TIME = "21:00"
DEFAULT_PROGRESS_TIME = "19:00"
DEFAULT_PROGRESS_DAY = "Sun"

METADATA_DEFAULTS: dict[str, str] = {
    "autonomy": DEFAULT_AUTONOMY,
    "quiet_hours_start": DEFAULT_QUIET_START,
    "quiet_hours_end": DEFAULT_QUIET_END,
    "touchpoint_time": DEFAULT_TOUCHPOINT_TIME,
    "sleep_time": DEFAULT_SLEEP_TIME,
    "progress_time": DEFAULT_PROGRESS_TIME,
    "progress_day": DEFAULT_PROGRESS_DAY,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def fail(message: str, code: int = 2) -> None:
    emit({"ok": False, "error": message})
    raise SystemExit(code)


def data_dir_from_arg(value: str | None) -> Path:
    raw = value or os.environ.get("HERMES_CREATURE_HOME") or "~/.hermes/data/hermes-digital-creature"
    return Path(raw).expanduser().resolve()


def parse_hhmm(value: str) -> tuple[int, int]:
    match = TIME_PATTERN.match(value)
    if not match:
        fail(f"invalid HH:MM time: {value}")
    return int(match.group(1)), int(match.group(2))


def time_to_minutes(value: str) -> int:
    h, m = parse_hhmm(value)
    return h * 60 + m


def in_quiet_hours(now_hhmm: str, start: str, end: str) -> bool:
    if start == end:
        return False
    now = time_to_minutes(now_hhmm)
    s = time_to_minutes(start)
    e = time_to_minutes(end)
    if s < e:
        return s <= now < e
    return now >= s or now < e


def current_local_hhmm() -> str:
    return datetime.now().strftime("%H:%M")


def proactive_plan_tasks(autonomy: str, settings: dict[str, str]) -> list[dict[str, str]]:
    if autonomy not in AUTONOMY_LEVELS:
        fail(f"invalid autonomy: {autonomy}")
    if autonomy == "off":
        return []
    touchpoint_time = settings.get("touchpoint_time", DEFAULT_TOUCHPOINT_TIME)
    sleep_time = settings.get("sleep_time", DEFAULT_SLEEP_TIME)
    progress_time = settings.get("progress_time", DEFAULT_PROGRESS_TIME)
    progress_day = settings.get("progress_day", DEFAULT_PROGRESS_DAY)
    for label, value in (
        ("touchpoint-time", touchpoint_time),
        ("sleep-time", sleep_time),
        ("progress-time", progress_time),
    ):
        if not TIME_PATTERN.match(value):
            fail(f"invalid {label}: {value}")
    if progress_day not in WEEKDAYS:
        fail(f"invalid progress-day: {progress_day}")
    daily = {
        "task_id": "digital-creature-daily-touchpoint",
        "schedule": f"every 1d at {touchpoint_time}",
        "skill": "hermes-digital-creature",
        "prompt": (
            "Run the daily touchpoint protocol. Recall relevant context from native memory "
            "(injected MEMORY.md/USER.md plus session_search) before deciding whether to reach out. "
            "Respect configured quiet hours and autonomy. If there is no useful low-friction question "
            "or grounded observation, do not create artificial engagement."
        ),
        "deliver": "origin",
        "description": "Daily check-in: surface one grounded recall or clarification, or stay silent.",
    }
    if autonomy == "gentle":
        return [daily]
    sleep_task = {
        "task_id": "digital-creature-sleep-review",
        "schedule": f"every 1d at {sleep_time}",
        "skill": "hermes-digital-creature",
        "prompt": (
            "Run the sleep protocol locally: review native memory hygiene using the Hermes memory "
            "tool and session_search (stale, redundant, or conflicting durable entries). Surface at most "
            "one grounded consolidation or clarification at the next appropriate contact. Do not perform "
            "network or external file actions."
        ),
        "deliver": "local",
        "description": "Nightly sleep analysis over native memory: stale, redundant, or conflicting entries.",
    }
    weekly = {
        "task_id": "digital-creature-weekly-progress",
        "schedule": f"every 1 week on {progress_day} at {progress_time}",
        "skill": "hermes-digital-creature",
        "prompt": (
            "Summarize progress from native memory and recent sessions: what was learned about the user, "
            "which preferences are now stable, and which durable memories may need confirmation. "
            "Keep it short and grounded; do not invent growth."
        ),
        "deliver": "origin",
        "description": "Weekly progress summary grounded in native memory.",
    }
    return [daily, sleep_task, weekly]


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.db_path = data_dir / "creature.sqlite3"
        self.marker_path = data_dir / MARKER_FILENAME
        unsafe_dirs = {Path("/").resolve(), Path.home().resolve(), (Path.home() / ".hermes").resolve()}
        if data_dir in unsafe_dirs:
            fail(f"refusing unsafe data directory: {data_dir}")
        if data_dir.exists() and any(data_dir.iterdir()) and not self.marker_path.exists():
            fail("refusing non-empty data directory not owned by Hermes Digital Creature")
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.marker_path.exists():
            self.marker_path.write_text(f"schema_version={SCHEMA_VERSION}\n", encoding="utf-8")
        try:
            os.chmod(data_dir, 0o700)
            os.chmod(self.marker_path, 0o600)
        except OSError:
            pass
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._schema()
        try:
            os.chmod(self.db_path, 0o600)
        except OSError:
            pass

    def close(self) -> None:
        self.conn.close()

    def table_exists(self, name: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)
        ).fetchone()
        return row is not None

    def _schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS proactive_tasks (
                task_id TEXT PRIMARY KEY,
                schedule TEXT NOT NULL,
                autonomy TEXT NOT NULL,
                description TEXT NOT NULL,
                prompt TEXT NOT NULL,
                deliver TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'registered',
                registered_at TEXT NOT NULL,
                revoked_at TEXT,
                consent_source TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                detail TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_audit_entity_id ON audit(entity_id);
            """
        )
        timestamp = now_iso()
        self.conn.execute(
            "INSERT OR IGNORE INTO metadata(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO metadata(key, value) VALUES ('created_at', ?)",
            (timestamp,),
        )
        for key, value in METADATA_DEFAULTS.items():
            self.conn.execute(
                "INSERT OR IGNORE INTO metadata(key, value) VALUES (?, ?)",
                (key, value),
            )
        current_version_row = self.conn.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if current_version_row and int(current_version_row["value"]) < SCHEMA_VERSION:
            from_version = int(current_version_row["value"])
            self.conn.execute(
                "UPDATE metadata SET value = ? WHERE key = 'schema_version'",
                (str(SCHEMA_VERSION),),
            )
            self.conn.execute(
                "INSERT INTO audit(created_at, action, entity_type, entity_id, detail) VALUES (?, ?, ?, ?, ?)",
                (
                    timestamp,
                    "schema-upgrade",
                    "metadata",
                    "schema_version",
                    json.dumps({"from": from_version, "to": SCHEMA_VERSION}, sort_keys=True),
                ),
            )
        self.conn.commit()

    def get_meta(self, key: str, default: str | None = None) -> str | None:
        row = self.conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        if row is None:
            return default
        return row["value"]

    def set_meta(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO metadata(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def settings(self) -> dict[str, str]:
        return {key: (self.get_meta(key, default) or default) for key, default in METADATA_DEFAULTS.items()}

    def audit(self, action: str, entity_type: str, entity_id: str | None, detail: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO audit(created_at, action, entity_type, entity_id, detail) VALUES (?, ?, ?, ?, ?)",
            (now_iso(), action, entity_type, entity_id, json.dumps(detail, ensure_ascii=False, sort_keys=True)),
        )


def serialize(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def cmd_init(store: Store, _: argparse.Namespace) -> None:
    emit(
        {
            "ok": True,
            "database": str(store.db_path),
            "schema_version": SCHEMA_VERSION,
            "local_only": True,
            "memory_backend": "hermes-native",
            "settings": store.settings(),
        }
    )


def cmd_status(store: Store, _: argparse.Namespace) -> None:
    last_event = store.conn.execute("SELECT created_at, action FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    proactive = [
        serialize(row)
        for row in store.conn.execute(
            "SELECT task_id, schedule, autonomy, status FROM proactive_tasks "
            "WHERE status = 'registered' ORDER BY task_id"
        )
    ]
    settings = store.settings()
    emit(
        {
            "ok": True,
            "database": str(store.db_path),
            "memory_backend": "hermes-native",
            "autonomy": settings["autonomy"],
            "quiet_hours": {"start": settings["quiet_hours_start"], "end": settings["quiet_hours_end"]},
            "times": {
                "touchpoint": settings["touchpoint_time"],
                "sleep": settings["sleep_time"],
                "progress": settings["progress_time"],
                "progress_day": settings["progress_day"],
            },
            "proactive_tasks": proactive,
            "last_event": serialize(last_event) if last_event else None,
        }
    )


def suppression_state(store: Store, now: str | None) -> dict[str, Any]:
    settings = store.settings()
    when = now or current_local_hhmm()
    parse_hhmm(when)
    quiet = in_quiet_hours(when, settings["quiet_hours_start"], settings["quiet_hours_end"])
    autonomy = settings["autonomy"]
    reasons = []
    if quiet:
        reasons.append("quiet_hours")
    if autonomy == "off":
        reasons.append("autonomy_off")
    return {
        "now": when,
        "quiet_hours": {"start": settings["quiet_hours_start"], "end": settings["quiet_hours_end"]},
        "in_quiet_hours": quiet,
        "autonomy": autonomy,
        "suppressed": bool(reasons),
        "suppression_reasons": reasons,
    }


def cmd_daily(store: Store, args: argparse.Namespace) -> None:
    suppression = suppression_state(store, getattr(args, "now", None))
    emit(
        {
            "ok": True,
            "suppression": suppression,
            "guidance": (
                "If suppression.suppressed is true, do not deliver a proactive message. "
                "Otherwise run the touchpoint using native memory: recall relevant context via the Hermes "
                "memory tool and session_search, then offer at most one grounded recall, clarification, or "
                "observation. Staying silent is a valid outcome; never force a check-in."
            ),
        }
    )


def cmd_sleep(store: Store, args: argparse.Namespace) -> None:
    suppression = suppression_state(store, getattr(args, "now", None))
    store.audit("sleep", "maintenance", None, {"suppressed": suppression["suppressed"]})
    store.conn.commit()
    emit(
        {
            "ok": True,
            "suppression": suppression,
            "guidance": (
                "Maintenance review of native memory only. Use the Hermes memory tool and session_search to "
                "find stale, redundant, or conflicting durable entries in MEMORY.md/USER.md. Propose at most "
                "one consolidation or one confirmation question at the next appropriate contact. Do not perform "
                "network or external file actions, and do not present this as consciousness or autonomous learning."
            ),
        }
    )


def cmd_audit(store: Store, args: argparse.Namespace) -> None:
    if args.entity_id:
        rows = store.conn.execute(
            "SELECT * FROM audit WHERE entity_id = ? ORDER BY id DESC LIMIT ?",
            (args.entity_id, args.limit),
        ).fetchall()
    else:
        rows = store.conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (args.limit,)).fetchall()
    result = []
    for row in rows:
        item = serialize(row)
        item["detail"] = json.loads(item["detail"])
        result.append(item)
    emit({"ok": True, "audit": result, "entity_id": args.entity_id})


def cmd_migrate(store: Store, _: argparse.Namespace) -> None:
    """Read any legacy creature memories and emit a non-destructive seed plan for native memory.

    Hermes then writes these into MEMORY.md / USER.md via its own memory tool. Nothing is
    deleted here; legacy tables remain until the user purges or manually cleans them.
    """
    user_md: list[dict[str, Any]] = []
    memory_md: list[dict[str, Any]] = []
    persona_traits: list[dict[str, Any]] = []
    source_counts: dict[str, int] = {}
    skipped_episodic = 0

    if store.table_exists("memories"):
        rows = store.conn.execute(
            "SELECT id, type, content, confidence, importance, consent FROM memories WHERE status = 'active'"
        ).fetchall()
        for row in rows:
            mem_type = row["type"]
            source_counts[mem_type] = source_counts.get(mem_type, 0) + 1
            entry = {
                "legacy_id": row["id"],
                "type": mem_type,
                "content": row["content"],
                "confidence": row["confidence"],
                "importance": row["importance"],
                "consent": bool(row["consent"]),
            }
            if mem_type in ("preference", "emotional"):
                # Facts about the user belong in USER.md.
                user_md.append(entry)
            elif mem_type in ("procedural", "meta-cognitive"):
                # Things the agent learned about how to work belong in MEMORY.md.
                memory_md.append(entry)
            else:  # episodic
                # Episodes are recoverable via session_search; only carry forward
                # high-importance, user-confirmed ones to avoid polluting native memory.
                if row["importance"] >= 0.7 and row["consent"]:
                    memory_md.append(entry)
                else:
                    skipped_episodic += 1

    if store.table_exists("traits"):
        for row in store.conn.execute("SELECT name, value FROM traits ORDER BY name").fetchall():
            persona_traits.append({"name": row["name"], "value": row["value"]})

    store.audit(
        "migrate",
        "data",
        None,
        {
            "user_md": len(user_md),
            "memory_md": len(memory_md),
            "persona_traits": len(persona_traits),
            "skipped_episodic": skipped_episodic,
        },
    )
    store.conn.commit()
    emit(
        {
            "ok": True,
            "note": (
                "Non-destructive seed plan. Write user_md entries into USER.md and memory_md entries plus a "
                "persona/traits block into MEMORY.md via the Hermes memory tool. Episodic memories below the "
                "carry-forward threshold are intentionally skipped; they remain reachable through session_search."
            ),
            "source_counts": source_counts,
            "skipped_episodic": skipped_episodic,
            "user_md": user_md,
            "memory_md": memory_md,
            "persona_traits": persona_traits,
        }
    )


def cmd_export(store: Store, args: argparse.Namespace) -> None:
    output = Path(args.output).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if store.data_dir not in output.parents and not args.allow_external_path:
        fail("export output must be inside data directory unless --allow-external-path is explicitly approved")
    if output in {store.db_path, store.marker_path} or output.name in {
        f"{store.db_path.name}-shm",
        f"{store.db_path.name}-wal",
    }:
        fail("export output cannot overwrite creature state database or ownership marker")
    tables = ["metadata", "proactive_tasks", "audit"]
    # Include legacy tables when they still exist so an export never hides residual data.
    tables.extend(name for name in LEGACY_TABLES if store.table_exists(name))
    payload: dict[str, Any] = {"exported_at": now_iso(), "schema_version": SCHEMA_VERSION}
    for table in tables:
        rows = store.conn.execute(f"SELECT * FROM {table}").fetchall()
        payload[table] = [serialize(row) for row in rows]
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    try:
        os.chmod(output, 0o600)
    except OSError:
        pass
    store.audit("export", "data", None, {"output": str(output)})
    store.conn.commit()
    emit({"ok": True, "output": str(output)})


def cmd_purge(store: Store, args: argparse.Namespace) -> None:
    if args.confirm != "DELETE-ALL-CREATURE-DATA":
        fail("purge requires --confirm DELETE-ALL-CREATURE-DATA")
    if not store.marker_path.exists():
        fail("refusing purge: data directory ownership marker is missing")
    data_dir = store.data_dir
    store.close()
    shutil.rmtree(data_dir)
    emit({"ok": True, "purged": str(data_dir)})


def cmd_autonomy(store: Store, args: argparse.Namespace) -> None:
    if args.action == "get":
        emit({"ok": True, "autonomy": store.get_meta("autonomy", DEFAULT_AUTONOMY)})
        return
    if args.value not in AUTONOMY_LEVELS:
        fail(f"invalid autonomy: {args.value}")
    previous = store.get_meta("autonomy", DEFAULT_AUTONOMY)
    store.set_meta("autonomy", args.value)
    store.audit("autonomy-set", "metadata", "autonomy", {"from": previous, "to": args.value})
    store.conn.commit()
    emit({"ok": True, "autonomy": args.value, "previous": previous})


def cmd_quiet_hours(store: Store, args: argparse.Namespace) -> None:
    if args.action == "get":
        emit(
            {
                "ok": True,
                "start": store.get_meta("quiet_hours_start", DEFAULT_QUIET_START),
                "end": store.get_meta("quiet_hours_end", DEFAULT_QUIET_END),
            }
        )
        return
    parse_hhmm(args.start)
    parse_hhmm(args.end)
    previous = {
        "start": store.get_meta("quiet_hours_start", DEFAULT_QUIET_START),
        "end": store.get_meta("quiet_hours_end", DEFAULT_QUIET_END),
    }
    store.set_meta("quiet_hours_start", args.start)
    store.set_meta("quiet_hours_end", args.end)
    store.audit(
        "quiet-hours-set",
        "metadata",
        "quiet_hours",
        {"from": previous, "to": {"start": args.start, "end": args.end}},
    )
    store.conn.commit()
    emit({"ok": True, "start": args.start, "end": args.end, "previous": previous})


def resolved_plan_settings(store: Store, args: argparse.Namespace) -> tuple[str, dict[str, str]]:
    settings = store.settings()
    autonomy = args.autonomy or settings["autonomy"]
    overrides = {
        "touchpoint_time": args.touchpoint_time or settings["touchpoint_time"],
        "sleep_time": args.sleep_time or settings["sleep_time"],
        "progress_time": args.progress_time or settings["progress_time"],
        "progress_day": args.progress_day or settings["progress_day"],
    }
    return autonomy, overrides


def cmd_proactive_plan(store: Store, args: argparse.Namespace) -> None:
    autonomy, settings = resolved_plan_settings(store, args)
    plan = proactive_plan_tasks(autonomy, settings)
    emit({"ok": True, "autonomy": autonomy, "settings": settings, "tasks": plan})


def cmd_proactive_diff(store: Store, args: argparse.Namespace) -> None:
    autonomy, settings = resolved_plan_settings(store, args)
    desired = proactive_plan_tasks(autonomy, settings)
    desired_by_id = {task["task_id"]: task for task in desired}
    current = {
        row["task_id"]: dict(row)
        for row in store.conn.execute("SELECT * FROM proactive_tasks WHERE status = 'registered'")
    }
    to_register: list[dict[str, str]] = []
    to_update: list[dict[str, str]] = []
    for task_id, task in desired_by_id.items():
        if task_id not in current:
            to_register.append(task)
            continue
        if current[task_id]["schedule"] != task["schedule"] or current[task_id]["autonomy"] != autonomy:
            to_update.append(task)
    to_revoke = [task_id for task_id in current if task_id not in desired_by_id]
    emit(
        {
            "ok": True,
            "autonomy": autonomy,
            "to_register": to_register,
            "to_update": to_update,
            "to_revoke": to_revoke,
        }
    )


def cmd_proactive_register(store: Store, args: argparse.Namespace) -> None:
    if args.autonomy not in AUTONOMY_LEVELS:
        fail(f"invalid autonomy: {args.autonomy}")
    description = args.description or ""
    prompt = args.prompt or ""
    deliver = args.deliver or "origin"
    timestamp = now_iso()
    existing = store.conn.execute(
        "SELECT * FROM proactive_tasks WHERE task_id = ?",
        (args.task_id,),
    ).fetchone()
    if (
        existing
        and existing["status"] == "registered"
        and existing["schedule"] == args.schedule
        and existing["autonomy"] == args.autonomy
        and existing["prompt"] == prompt
        and existing["deliver"] == deliver
    ):
        emit({"ok": True, "already_registered": True, "task_id": args.task_id})
        return
    store.conn.execute(
        """
        INSERT INTO proactive_tasks(task_id, schedule, autonomy, description, prompt, deliver,
                                    status, registered_at, revoked_at, consent_source)
        VALUES (?, ?, ?, ?, ?, ?, 'registered', ?, NULL, ?)
        ON CONFLICT(task_id) DO UPDATE SET
            schedule = excluded.schedule,
            autonomy = excluded.autonomy,
            description = excluded.description,
            prompt = excluded.prompt,
            deliver = excluded.deliver,
            status = 'registered',
            registered_at = excluded.registered_at,
            revoked_at = NULL,
            consent_source = excluded.consent_source
        """,
        (
            args.task_id,
            args.schedule,
            args.autonomy,
            description,
            prompt,
            deliver,
            timestamp,
            f"autonomy:{args.autonomy}",
        ),
    )
    store.audit(
        "proactive-register",
        "proactive_task",
        args.task_id,
        {"schedule": args.schedule, "autonomy": args.autonomy, "deliver": deliver},
    )
    store.conn.commit()
    emit({"ok": True, "task_id": args.task_id, "status": "registered"})


def cmd_proactive_list(store: Store, args: argparse.Namespace) -> None:
    if args.status:
        rows = store.conn.execute(
            "SELECT * FROM proactive_tasks WHERE status = ? ORDER BY task_id",
            (args.status,),
        ).fetchall()
    else:
        rows = store.conn.execute("SELECT * FROM proactive_tasks ORDER BY task_id").fetchall()
    emit({"ok": True, "tasks": [serialize(row) for row in rows]})


def cmd_proactive_revoke(store: Store, args: argparse.Namespace) -> None:
    row = store.conn.execute("SELECT * FROM proactive_tasks WHERE task_id = ?", (args.task_id,)).fetchone()
    if not row:
        fail(f"proactive task not found: {args.task_id}")
    if row["status"] == "revoked":
        emit({"ok": True, "already_revoked": True, "task_id": args.task_id})
        return
    timestamp = now_iso()
    store.conn.execute(
        "UPDATE proactive_tasks SET status = 'revoked', revoked_at = ? WHERE task_id = ?",
        (timestamp, args.task_id),
    )
    store.audit(
        "proactive-revoke",
        "proactive_task",
        args.task_id,
        {"reason": args.reason or "", "previous_schedule": row["schedule"]},
    )
    store.conn.commit()
    emit({"ok": True, "task_id": args.task_id, "status": "revoked"})


def cmd_doctor(store: Store, args: argparse.Namespace) -> None:
    checks: dict[str, Any] = {}
    warnings: list[str] = []
    errors: list[str] = []

    checks["marker_present"] = store.marker_path.exists()
    if not checks["marker_present"]:
        errors.append("ownership marker missing")

    version_row = store.conn.execute("SELECT value FROM metadata WHERE key = 'schema_version'").fetchone()
    actual_version = int(version_row["value"]) if version_row else None
    checks["schema_version"] = {
        "current": actual_version,
        "expected": SCHEMA_VERSION,
        "ok": actual_version == SCHEMA_VERSION,
    }
    if actual_version != SCHEMA_VERSION:
        errors.append(f"schema version mismatch: {actual_version} != {SCHEMA_VERSION}")

    settings = store.settings()
    autonomy_ok = settings["autonomy"] in AUTONOMY_LEVELS
    checks["autonomy"] = {"value": settings["autonomy"], "ok": autonomy_ok}
    if not autonomy_ok:
        errors.append(f"invalid stored autonomy: {settings['autonomy']}")

    times_ok = True
    for key in ("quiet_hours_start", "quiet_hours_end", "touchpoint_time", "sleep_time", "progress_time"):
        if not TIME_PATTERN.match(settings[key]):
            times_ok = False
            errors.append(f"invalid HH:MM in metadata.{key}: {settings[key]}")
    if settings["progress_day"] not in WEEKDAYS:
        times_ok = False
        errors.append(f"invalid progress_day: {settings['progress_day']}")
    checks["time_settings"] = {
        "ok": times_ok,
        "quiet_hours": {"start": settings["quiet_hours_start"], "end": settings["quiet_hours_end"]},
        "touchpoint_time": settings["touchpoint_time"],
        "sleep_time": settings["sleep_time"],
        "progress_time": settings["progress_time"],
        "progress_day": settings["progress_day"],
    }

    if autonomy_ok and times_ok:
        desired = proactive_plan_tasks(settings["autonomy"], settings)
    else:
        desired = []
    desired_by_id = {task["task_id"]: task for task in desired}
    registered_rows = store.conn.execute(
        "SELECT * FROM proactive_tasks WHERE status = 'registered'"
    ).fetchall()
    registered_ids = {row["task_id"] for row in registered_rows}
    desired_ids = set(desired_by_id)
    drift_missing = sorted(desired_ids - registered_ids)
    drift_extra = sorted(registered_ids - desired_ids)
    drift_mismatch = []
    for row in registered_rows:
        target = desired_by_id.get(row["task_id"])
        if target and (target["schedule"] != row["schedule"] or row["autonomy"] != settings["autonomy"]):
            drift_mismatch.append(row["task_id"])
    checks["proactive_tasks"] = {
        "registered_count": len(registered_ids),
        "expected_count": len(desired_ids),
        "drift_missing": drift_missing,
        "drift_extra": drift_extra,
        "drift_mismatch": drift_mismatch,
        "ok": not (drift_missing or drift_extra or drift_mismatch),
    }
    if not checks["proactive_tasks"]["ok"]:
        warnings.append("registered proactive tasks do not match autonomy plan")

    legacy_present = sorted(name for name in LEGACY_TABLES if store.table_exists(name))
    checks["legacy_tables"] = {"present": legacy_present, "ok": True}
    if legacy_present:
        warnings.append(
            "legacy memory tables are still present; run `migrate` to seed native memory, then `purge` "
            "or remove them once seeded"
        )

    last_audit = store.conn.execute("SELECT created_at FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    checks["last_audit_at"] = last_audit["created_at"] if last_audit else None

    checks["db_writable"] = os.access(store.db_path, os.W_OK)
    if not checks["db_writable"]:
        errors.append("creature.sqlite3 is not writable")

    if times_ok:
        now = args.now or current_local_hhmm()
        checks["quiet_now"] = {
            "now": now,
            "in_quiet_hours": in_quiet_hours(now, settings["quiet_hours_start"], settings["quiet_hours_end"]),
        }
    else:
        warnings.append("skipping quiet-hours evaluation due to invalid time settings")

    emit({"ok": not errors, "checks": checks, "warnings": warnings, "errors": errors})


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Local scheduling/settings runtime for Hermes Digital Creature")
    root.add_argument("--data-dir", help="State directory; defaults to ~/.hermes/data/hermes-digital-creature")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init").set_defaults(func=cmd_init)
    commands.add_parser("status").set_defaults(func=cmd_status)

    daily = commands.add_parser("daily")
    daily.add_argument("--now", help="HH:MM local time override for suppression evaluation")
    daily.set_defaults(func=cmd_daily)

    sleep_cmd = commands.add_parser("sleep")
    sleep_cmd.add_argument("--now", help="HH:MM local time override for suppression evaluation")
    sleep_cmd.set_defaults(func=cmd_sleep)

    migrate = commands.add_parser("migrate")
    migrate.set_defaults(func=cmd_migrate)

    audit = commands.add_parser("audit")
    audit.add_argument("--limit", type=int, default=20)
    audit.add_argument("--entity-id", default=None)
    audit.set_defaults(func=cmd_audit)

    export = commands.add_parser("export")
    export.add_argument("--output", required=True)
    export.add_argument("--allow-external-path", action="store_true")
    export.set_defaults(func=cmd_export)

    purge = commands.add_parser("purge")
    purge.add_argument("--confirm", required=True)
    purge.set_defaults(func=cmd_purge)

    autonomy = commands.add_parser("autonomy")
    autonomy.add_argument("action", choices=("get", "set"))
    autonomy.add_argument("--value")
    autonomy.set_defaults(func=cmd_autonomy)

    quiet = commands.add_parser("quiet-hours")
    quiet.add_argument("action", choices=("get", "set"))
    quiet.add_argument("--start")
    quiet.add_argument("--end")
    quiet.set_defaults(func=cmd_quiet_hours)

    def add_plan_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--autonomy", choices=AUTONOMY_LEVELS, default=None)
        p.add_argument("--touchpoint-time", default=None)
        p.add_argument("--sleep-time", default=None)
        p.add_argument("--progress-time", default=None)
        p.add_argument("--progress-day", choices=WEEKDAYS, default=None)

    plan = commands.add_parser("proactive-plan")
    add_plan_args(plan)
    plan.set_defaults(func=cmd_proactive_plan)

    diff = commands.add_parser("proactive-diff")
    add_plan_args(diff)
    diff.set_defaults(func=cmd_proactive_diff)

    register = commands.add_parser("proactive-register")
    register.add_argument("--task-id", required=True)
    register.add_argument("--schedule", required=True)
    register.add_argument("--autonomy", choices=AUTONOMY_LEVELS, required=True)
    register.add_argument("--description", default="")
    register.add_argument("--prompt", default="")
    register.add_argument("--deliver", default="origin")
    register.set_defaults(func=cmd_proactive_register)

    plist = commands.add_parser("proactive-list")
    plist.add_argument("--status", choices=("registered", "revoked"), default=None)
    plist.set_defaults(func=cmd_proactive_list)

    revoke = commands.add_parser("proactive-revoke")
    revoke.add_argument("--task-id", required=True)
    revoke.add_argument("--reason", default="")
    revoke.set_defaults(func=cmd_proactive_revoke)

    doctor = commands.add_parser("doctor")
    doctor.add_argument("--now", help="HH:MM local time override for quiet-hours evaluation")
    doctor.set_defaults(func=cmd_doctor)
    return root


def validate_args(args: argparse.Namespace) -> None:
    if args.command == "autonomy" and args.action == "set" and not args.value:
        fail("autonomy set requires --value")
    if args.command == "quiet-hours" and args.action == "set" and (not args.start or not args.end):
        fail("quiet-hours set requires --start and --end")


def main() -> None:
    args = parser().parse_args()
    validate_args(args)
    store = Store(data_dir_from_arg(args.data_dir))
    try:
        args.func(store, args)
    finally:
        if args.command != "purge":
            store.close()


if __name__ == "__main__":
    main()
