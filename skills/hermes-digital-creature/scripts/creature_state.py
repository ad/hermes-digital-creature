#!/usr/bin/env python3
"""Local state engine for the Hermes Digital Creature skill.

This process intentionally has no network behavior and uses only Python stdlib.
All persistent mutations happen inside the configured data directory.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


MEMORY_TYPES = ("episodic", "preference", "procedural", "emotional", "meta-cognitive")
TRAITS = (
    "curiosity",
    "skepticism",
    "verbosity",
    "warmth",
    "abstraction",
    "autonomy",
    "caution",
    "creativity",
)
DEFAULT_TRAITS = {
    "curiosity": 0.60,
    "skepticism": 0.55,
    "verbosity": 0.45,
    "warmth": 0.45,
    "abstraction": 0.50,
    "autonomy": 0.20,
    "caution": 0.70,
    "creativity": 0.45,
}
ACTIVITY_KINDS = (
    "memory-repair",
    "preference-ranking",
    "detective-story",
    "tool-expedition",
    "explain-better",
    "quest",
)
CAPABILITIES = {
    "memory-repair": ("unlocked", "available from first contact"),
    "preference-ranking": ("unlocked", "available from first contact"),
    "explain-better": ("unlocked", "available from first contact"),
    "reflection": ("locked", "suggest after 3 feedback traces"),
    "tool-expedition": ("locked", "suggest after 2 completed activities and 3 feedback traces"),
    "proactive-check-in": ("locked", "unlock only after explicit opt-in"),
}
SENSITIVE_PATTERN = re.compile(
    r"(password|passphrase|secret|api[_ -]?key|token|credential|private[_ -]?key|seed phrase)",
    re.IGNORECASE,
)
TOKEN_PATTERN = re.compile(r"[\w-]{2,}", re.UNICODE)
TIME_PATTERN = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
AUTONOMY_LEVELS = ("off", "gentle", "active")
SCHEMA_VERSION = 2
MARKER_FILENAME = ".hermes-digital-creature-state"
DEFAULT_TOUCHPOINT_TIME = "09:00"
DEFAULT_SLEEP_TIME = "21:00"
DEFAULT_PROGRESS_TIME = "19:00"
DEFAULT_PROGRESS_DAY = "Sun"


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clamp(value: float) -> float:
    return round(max(0.0, min(1.0, value)), 4)


def ident(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def emit(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def fail(message: str, code: int = 2) -> None:
    emit({"ok": False, "error": message})
    raise SystemExit(code)


def data_dir_from_arg(value: str | None) -> Path:
    raw = value or os.environ.get("HERMES_CREATURE_HOME") or "~/.hermes/data/hermes-digital-creature"
    return Path(raw).expanduser().resolve()


def ensure_safe_content(content: str) -> str:
    text = " ".join(content.split()).strip()
    if not text:
        fail("content cannot be empty")
    if SENSITIVE_PATTERN.search(text):
        fail("refusing to store content that appears to contain credentials or secrets")
    if len(text) > 1000:
        fail("memory content must be concise (maximum 1000 characters)")
    return text


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

    def _schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                confidence REAL NOT NULL CHECK(confidence BETWEEN 0 AND 1),
                importance REAL NOT NULL CHECK(importance BETWEEN 0 AND 1),
                emotional_weight REAL NOT NULL CHECK(emotional_weight BETWEEN 0 AND 1),
                decay_rate REAL NOT NULL CHECK(decay_rate BETWEEN 0 AND 1),
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_recalled_at TEXT,
                recall_count INTEGER NOT NULL DEFAULT 0,
                source TEXT,
                consent INTEGER NOT NULL DEFAULT 0,
                supersedes_id TEXT REFERENCES memories(id),
                conflict_group TEXT
            );
            CREATE TABLE IF NOT EXISTS memory_links (
                from_id TEXT NOT NULL REFERENCES memories(id),
                to_id TEXT NOT NULL REFERENCES memories(id),
                relation TEXT NOT NULL,
                PRIMARY KEY(from_id, to_id, relation)
            );
            CREATE TABLE IF NOT EXISTS traits (
                name TEXT PRIMARY KEY,
                value REAL NOT NULL CHECK(value BETWEEN 0 AND 1),
                updated_at TEXT NOT NULL,
                reason TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS capabilities (
                name TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                reason TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                context TEXT NOT NULL,
                choice TEXT,
                signal TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS activities (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                result TEXT,
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            CREATE TABLE IF NOT EXISTS reflections (
                id TEXT PRIMARY KEY,
                content TEXT NOT NULL,
                evidence TEXT NOT NULL,
                uncertainty REAL NOT NULL CHECK(uncertainty BETWEEN 0 AND 1),
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                action TEXT NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id TEXT,
                detail TEXT NOT NULL
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
            """
        )
        timestamp = now_iso()
        current_version = self.conn.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if current_version and int(current_version["value"]) < SCHEMA_VERSION:
            self.conn.execute(
                "UPDATE metadata SET value = ? WHERE key = 'schema_version'",
                (str(SCHEMA_VERSION),),
            )
        self.conn.execute(
            "INSERT OR IGNORE INTO metadata(key, value) VALUES ('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        self.conn.execute(
            "INSERT OR IGNORE INTO metadata(key, value) VALUES ('created_at', ?)",
            (timestamp,),
        )
        for name, value in DEFAULT_TRAITS.items():
            self.conn.execute(
                "INSERT OR IGNORE INTO traits(name, value, updated_at, reason) VALUES (?, ?, ?, ?)",
                (name, value, timestamp, "initial baseline"),
            )
        for name, (status, reason) in CAPABILITIES.items():
            self.conn.execute(
                "INSERT OR IGNORE INTO capabilities(name, status, reason, updated_at) VALUES (?, ?, ?, ?)",
                (name, status, reason, timestamp),
            )
        self.conn.commit()

    def audit(self, action: str, entity_type: str, entity_id: str | None, detail: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO audit(created_at, action, entity_type, entity_id, detail) VALUES (?, ?, ?, ?, ?)",
            (now_iso(), action, entity_type, entity_id, json.dumps(detail, ensure_ascii=False, sort_keys=True)),
        )

    def memory(self, memory_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()
        if not row:
            fail(f"memory not found: {memory_id}")
        return row


def serialize(row: sqlite3.Row) -> dict[str, Any]:
    return dict(row)


def cmd_init(store: Store, _: argparse.Namespace) -> None:
    emit({"ok": True, "database": str(store.db_path), "schema_version": SCHEMA_VERSION, "local_only": True})


def cmd_status(store: Store, _: argparse.Namespace) -> None:
    counts = {
        row["status"]: row["count"]
        for row in store.conn.execute("SELECT status, COUNT(*) AS count FROM memories GROUP BY status")
    }
    traits = {row["name"]: row["value"] for row in store.conn.execute("SELECT name, value FROM traits ORDER BY name")}
    capabilities = {
        row["name"]: row["status"] for row in store.conn.execute("SELECT name, status FROM capabilities ORDER BY name")
    }
    feedback_count = store.conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
    activities = {
        row["status"]: row["count"]
        for row in store.conn.execute("SELECT status, COUNT(*) AS count FROM activities GROUP BY status")
    }
    last_event = store.conn.execute("SELECT created_at, action FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    proactive_rows = store.conn.execute(
        "SELECT task_id, schedule, autonomy, status FROM proactive_tasks WHERE status = 'registered' ORDER BY task_id"
    ).fetchall()
    emit(
        {
            "ok": True,
            "database": str(store.db_path),
            "memories": {"active": counts.get("active", 0), "archived": counts.get("archived", 0), "superseded": counts.get("superseded", 0)},
            "traits": traits,
            "capabilities": capabilities,
            "feedback_count": feedback_count,
            "activities": activities,
            "proactive_tasks": [serialize(row) for row in proactive_rows],
            "last_event": serialize(last_event) if last_event else None,
        }
    )


def cmd_remember(store: Store, args: argparse.Namespace) -> None:
    content = ensure_safe_content(args.content)
    if args.type == "emotional" and not args.consent:
        fail("emotional memory requires explicit user consent (--consent)")
    if not args.consent and args.confidence > 0.65:
        fail("unconfirmed memory confidence cannot exceed 0.65; pass --consent for confirmed user input")
    duplicate = store.conn.execute(
        "SELECT id, content FROM memories WHERE status = 'active' AND lower(content) = lower(?)",
        (content,),
    ).fetchone()
    if duplicate:
        emit({"ok": True, "duplicate": True, "memory": serialize(duplicate)})
        return
    memory_id = ident("mem")
    timestamp = now_iso()
    store.conn.execute(
        """
        INSERT INTO memories(
            id, type, content, confidence, importance, emotional_weight, decay_rate,
            status, created_at, updated_at, source, consent, conflict_group
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)
        """,
        (
            memory_id,
            args.type,
            content,
            clamp(args.confidence),
            clamp(args.importance),
            clamp(args.emotional_weight),
            clamp(args.decay_rate),
            timestamp,
            timestamp,
            args.source,
            int(args.consent),
            args.conflict_group,
        ),
    )
    if args.conflicts_with:
        store.memory(args.conflicts_with)
        group = args.conflict_group or ident("conflict")
        store.conn.execute("UPDATE memories SET conflict_group = ? WHERE id IN (?, ?)", (group, memory_id, args.conflicts_with))
        store.conn.execute(
            "INSERT OR IGNORE INTO memory_links(from_id, to_id, relation) VALUES (?, ?, 'conflicts-with')",
            (memory_id, args.conflicts_with),
        )
    store.audit("remember", "memory", memory_id, {"type": args.type, "consent": args.consent, "source": args.source})
    store.conn.commit()
    emit({"ok": True, "memory": serialize(store.memory(memory_id))})


def age_days(timestamp: str | None) -> float:
    if not timestamp:
        return 365.0
    parsed = datetime.fromisoformat(timestamp)
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds() / 86400)


def query_tokens(text: str) -> set[str]:
    return {token.casefold() for token in TOKEN_PATTERN.findall(text)}


def cmd_recall(store: Store, args: argparse.Namespace) -> None:
    tokens = query_tokens(args.query)
    candidates = store.conn.execute("SELECT * FROM memories WHERE status = 'active'").fetchall()
    ranked: list[tuple[float, sqlite3.Row, dict[str, float]]] = []
    for row in candidates:
        content_tokens = query_tokens(row["content"])
        overlap = len(tokens & content_tokens) / max(1, len(tokens))
        stale_days = age_days(row["last_recalled_at"] or row["updated_at"])
        decay = math.exp(-row["decay_rate"] * stale_days / 30.0)
        score = (
            0.42 * overlap
            + 0.23 * row["importance"]
            + 0.20 * row["confidence"]
            + 0.05 * row["emotional_weight"]
            + 0.10 * decay
        )
        if overlap > 0 or args.include_weak:
            ranked.append((score, row, {"semantic_overlap": round(overlap, 4), "freshness": round(decay, 4)}))
    ranked.sort(key=lambda item: item[0], reverse=True)
    selected = ranked[: args.limit]
    timestamp = now_iso()
    for _, row, _ in selected:
        store.conn.execute(
            "UPDATE memories SET last_recalled_at = ?, recall_count = recall_count + 1 WHERE id = ?",
            (timestamp, row["id"]),
        )
    if selected:
        store.audit("recall", "memory", None, {"query": args.query[:120], "ids": [row["id"] for _, row, _ in selected]})
        store.conn.commit()
    result = []
    for score, row, factors in selected:
        item = serialize(row)
        item["score"] = round(score, 4)
        item["factors"] = factors
        result.append(item)
    emit({"ok": True, "query": args.query, "memories": result})


def cmd_memories(store: Store, args: argparse.Namespace) -> None:
    rows = store.conn.execute(
        "SELECT * FROM memories WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
        (args.status, args.limit),
    ).fetchall()
    emit({"ok": True, "status": args.status, "memories": [serialize(row) for row in rows]})


def cmd_confirm(store: Store, args: argparse.Namespace) -> None:
    row = store.memory(args.id)
    if row["status"] != "active":
        fail("only active memories can be confirmed")
    confidence = clamp(args.confidence)
    store.conn.execute(
        "UPDATE memories SET confidence = ?, consent = 1, updated_at = ? WHERE id = ?",
        (confidence, now_iso(), args.id),
    )
    store.audit("confirm", "memory", args.id, {"confidence": confidence})
    store.conn.commit()
    emit({"ok": True, "memory": serialize(store.memory(args.id))})


def cmd_correct(store: Store, args: argparse.Namespace) -> None:
    previous = store.memory(args.id)
    if previous["status"] != "active":
        fail("only active memories can be corrected")
    content = ensure_safe_content(args.content)
    if previous["type"] == "emotional" and not args.consent:
        fail("emotional memory correction requires explicit consent (--consent)")
    new_id = ident("mem")
    timestamp = now_iso()
    store.conn.execute("UPDATE memories SET status = 'superseded', updated_at = ? WHERE id = ?", (timestamp, args.id))
    store.conn.execute(
        """
        INSERT INTO memories(
            id, type, content, confidence, importance, emotional_weight, decay_rate,
            status, created_at, updated_at, source, consent, supersedes_id, conflict_group
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, 'correction', ?, ?, ?)
        """,
        (
            new_id,
            previous["type"],
            content,
            clamp(args.confidence),
            previous["importance"],
            previous["emotional_weight"],
            previous["decay_rate"],
            timestamp,
            timestamp,
            int(args.consent),
            args.id,
            previous["conflict_group"],
        ),
    )
    feedback_id = ident("fb")
    store.conn.execute(
        "INSERT INTO feedback(id, kind, context, choice, signal, created_at) VALUES (?, 'correction', ?, ?, ?, ?)",
        (feedback_id, f"corrected {args.id}", new_id, content, timestamp),
    )
    store.audit("correct", "memory", new_id, {"supersedes": args.id, "feedback_id": feedback_id})
    store.conn.commit()
    emit({"ok": True, "memory": serialize(store.memory(new_id)), "superseded_id": args.id, "feedback_id": feedback_id})


def cmd_archive(store: Store, args: argparse.Namespace) -> None:
    row = store.memory(args.id)
    if row["status"] == "archived":
        emit({"ok": True, "already_archived": True, "id": args.id})
        return
    store.conn.execute("UPDATE memories SET status = 'archived', updated_at = ? WHERE id = ?", (now_iso(), args.id))
    store.audit("archive", "memory", args.id, {"reason": args.reason})
    store.conn.commit()
    emit({"ok": True, "archived_id": args.id, "reason": args.reason})


def cmd_consolidate(store: Store, args: argparse.Namespace) -> None:
    source_ids = list(dict.fromkeys(args.ids))
    if len(source_ids) < 2:
        fail("consolidation requires at least two source memory ids")
    sources = [store.memory(item) for item in source_ids]
    if any(row["status"] != "active" for row in sources):
        fail("consolidation sources must be active")
    content = ensure_safe_content(args.content)
    new_id = ident("mem")
    timestamp = now_iso()
    memory_type = args.type or sources[0]["type"]
    confidence = clamp(min(row["confidence"] for row in sources))
    importance = clamp(max(row["importance"] for row in sources))
    emotional_weight = clamp(max(row["emotional_weight"] for row in sources))
    decay_rate = clamp(min(row["decay_rate"] for row in sources))
    store.conn.execute(
        """
        INSERT INTO memories(id, type, content, confidence, importance, emotional_weight, decay_rate,
                             status, created_at, updated_at, source, consent)
        VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, 'consolidation', ?)
        """,
        (new_id, memory_type, content, confidence, importance, emotional_weight, decay_rate, timestamp, timestamp, int(args.consent)),
    )
    for source in sources:
        store.conn.execute("UPDATE memories SET status = 'superseded', updated_at = ? WHERE id = ?", (timestamp, source["id"]))
        store.conn.execute(
            "INSERT INTO memory_links(from_id, to_id, relation) VALUES (?, ?, 'consolidates')",
            (new_id, source["id"]),
        )
    store.audit("consolidate", "memory", new_id, {"source_ids": source_ids})
    store.conn.commit()
    emit({"ok": True, "memory": serialize(store.memory(new_id)), "source_ids": source_ids})


def cmd_feedback(store: Store, args: argparse.Namespace) -> None:
    feedback_id = ident("fb")
    context = ensure_safe_content(args.context)
    signal = ensure_safe_content(args.signal) if args.signal else None
    store.conn.execute(
        "INSERT INTO feedback(id, kind, context, choice, signal, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (feedback_id, args.kind, context, args.choice, signal, now_iso()),
    )
    store.audit("feedback", "feedback", feedback_id, {"kind": args.kind, "choice": args.choice})
    store.conn.commit()
    emit({"ok": True, "feedback_id": feedback_id})


def cmd_trait(store: Store, args: argparse.Namespace) -> None:
    if abs(args.delta) > 0.05:
        fail("one trait adjustment must be between -0.05 and 0.05")
    reason = ensure_safe_content(args.reason)
    row = store.conn.execute("SELECT value FROM traits WHERE name = ?", (args.name,)).fetchone()
    old_value = row["value"]
    new_value = clamp(old_value + args.delta)
    store.conn.execute(
        "UPDATE traits SET value = ?, updated_at = ?, reason = ? WHERE name = ?",
        (new_value, now_iso(), reason, args.name),
    )
    store.audit("trait-adjust", "trait", args.name, {"from": old_value, "to": new_value, "reason": reason})
    store.conn.commit()
    emit({"ok": True, "trait": args.name, "from": old_value, "to": new_value})


def progression_metrics(store: Store) -> dict[str, int]:
    return {
        "active_memories": store.conn.execute("SELECT COUNT(*) FROM memories WHERE status = 'active'").fetchone()[0],
        "confirmed_memories": store.conn.execute("SELECT COUNT(*) FROM memories WHERE status = 'active' AND consent = 1").fetchone()[0],
        "feedback_traces": store.conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0],
        "completed_activities": store.conn.execute("SELECT COUNT(*) FROM activities WHERE status = 'completed'").fetchone()[0],
        "reflections": store.conn.execute("SELECT COUNT(*) FROM reflections").fetchone()[0],
    }


def cmd_progress(store: Store, _: argparse.Namespace) -> None:
    metrics = progression_metrics(store)
    statuses = {
        row["name"]: row["status"] for row in store.conn.execute("SELECT name, status FROM capabilities")
    }
    suggestions: list[dict[str, str]] = []
    if statuses["reflection"] == "locked" and metrics["feedback_traces"] >= 3:
        suggestions.append({"capability": "reflection", "reason": "enough feedback exists for a grounded review"})
    if (
        statuses["tool-expedition"] == "locked"
        and metrics["feedback_traces"] >= 3
        and metrics["completed_activities"] >= 2
    ):
        suggestions.append({"capability": "tool-expedition", "reason": "training history exists; every real expedition still needs approval"})
    if statuses["proactive-check-in"] == "locked":
        suggestions.append({"capability": "proactive-check-in", "reason": "available only if the user opts in to proactive contact"})
    emit({"ok": True, "metrics": metrics, "capabilities": statuses, "unlock_suggestions": suggestions})


def cmd_unlock(store: Store, args: argparse.Namespace) -> None:
    if not args.consent:
        fail("capability unlock requires explicit user consent (--consent)")
    reason = ensure_safe_content(args.reason)
    store.conn.execute(
        "UPDATE capabilities SET status = 'unlocked', reason = ?, updated_at = ? WHERE name = ?",
        (reason, now_iso(), args.name),
    )
    store.audit("unlock", "capability", args.name, {"reason": reason, "approval_required_actions_unchanged": True})
    store.conn.commit()
    emit({"ok": True, "capability": args.name, "status": "unlocked", "approval_required_actions_unchanged": True})


def cmd_activity(store: Store, args: argparse.Namespace) -> None:
    if args.action == "start":
        activity_id = ident("act")
        title = ensure_safe_content(args.title)
        store.conn.execute(
            "INSERT INTO activities(id, kind, title, status, created_at) VALUES (?, ?, ?, 'active', ?)",
            (activity_id, args.kind, title, now_iso()),
        )
        store.audit("activity-start", "activity", activity_id, {"kind": args.kind, "title": title})
        store.conn.commit()
        emit({"ok": True, "activity_id": activity_id, "status": "active"})
        return
    row = store.conn.execute("SELECT * FROM activities WHERE id = ?", (args.id,)).fetchone()
    if not row:
        fail(f"activity not found: {args.id}")
    result = ensure_safe_content(args.result)
    store.conn.execute(
        "UPDATE activities SET status = 'completed', result = ?, completed_at = ? WHERE id = ?",
        (result, now_iso(), args.id),
    )
    store.audit("activity-complete", "activity", args.id, {"result": result})
    store.conn.commit()
    emit({"ok": True, "activity_id": args.id, "status": "completed"})


def stale_rows(store: Store) -> list[dict[str, Any]]:
    rows = store.conn.execute("SELECT * FROM memories WHERE status = 'active'").fetchall()
    result = []
    for row in rows:
        days = age_days(row["last_recalled_at"] or row["updated_at"])
        retained = row["confidence"] * math.exp(-row["decay_rate"] * days / 30.0)
        if days >= 14 and retained < 0.58:
            result.append({"id": row["id"], "content": row["content"], "age_days": round(days, 1), "retained_confidence": round(retained, 4)})
    return result


def cmd_daily(store: Store, _: argparse.Namespace) -> None:
    candidate = store.conn.execute(
        """
        SELECT * FROM memories WHERE status = 'active'
        ORDER BY (importance * confidence) DESC, COALESCE(last_recalled_at, created_at) ASC LIMIT 1
        """
    ).fetchone()
    unresolved = store.conn.execute(
        "SELECT COUNT(*) FROM memories WHERE status = 'active' AND confidence < 0.6"
    ).fetchone()[0]
    active_activity = store.conn.execute("SELECT id, kind, title FROM activities WHERE status = 'active' ORDER BY created_at LIMIT 1").fetchone()
    emit(
        {
            "ok": True,
            "recall_candidate": serialize(candidate) if candidate else None,
            "tentative_memory_count": unresolved,
            "active_activity": serialize(active_activity) if active_activity else None,
            "guidance": "Offer one recall/clarification/activity only when appropriate; do not force a check-in.",
        }
    )


def cmd_sleep(store: Store, _: argparse.Namespace) -> None:
    conflicts = [
        {"conflict_group": row["conflict_group"], "count": row["count"]}
        for row in store.conn.execute(
            "SELECT conflict_group, COUNT(*) AS count FROM memories WHERE status = 'active' AND conflict_group IS NOT NULL GROUP BY conflict_group HAVING COUNT(*) > 1"
        )
    ]
    recent_feedback = [
        serialize(row)
        for row in store.conn.execute("SELECT * FROM feedback ORDER BY created_at DESC LIMIT 5").fetchall()
    ]
    activities = {
        row["kind"]: row["count"]
        for row in store.conn.execute("SELECT kind, COUNT(*) AS count FROM activities WHERE status = 'completed' GROUP BY kind")
    }
    store.audit("sleep-analysis", "reflection", None, {"stale_count": len(stale_rows(store)), "conflict_count": len(conflicts)})
    store.conn.commit()
    emit({"ok": True, "stale_memories": stale_rows(store), "conflicts": conflicts, "recent_feedback": recent_feedback, "completed_activities": activities})


def cmd_reflect(store: Store, args: argparse.Namespace) -> None:
    content = ensure_safe_content(args.content)
    evidence = ensure_safe_content(args.evidence)
    reflection_id = ident("ref")
    store.conn.execute(
        "INSERT INTO reflections(id, content, evidence, uncertainty, created_at) VALUES (?, ?, ?, ?, ?)",
        (reflection_id, content, evidence, clamp(args.uncertainty), now_iso()),
    )
    store.audit("reflect", "reflection", reflection_id, {"uncertainty": clamp(args.uncertainty)})
    store.conn.commit()
    emit({"ok": True, "reflection_id": reflection_id})


def cmd_audit(store: Store, args: argparse.Namespace) -> None:
    rows = store.conn.execute("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (args.limit,)).fetchall()
    result = []
    for row in rows:
        item = serialize(row)
        item["detail"] = json.loads(item["detail"])
        result.append(item)
    emit({"ok": True, "audit": result})


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
    tables = ("metadata", "memories", "memory_links", "traits", "capabilities", "feedback", "activities", "reflections", "audit", "proactive_tasks")
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


def validate_time(value: str, label: str) -> str:
    if not TIME_PATTERN.match(value):
        fail(f"invalid {label} (expected HH:MM): {value}")
    return value


def proactive_plan_tasks(
    autonomy: str,
    touchpoint_time: str,
    sleep_time: str,
    progress_time: str,
    progress_day: str,
) -> list[dict[str, str]]:
    if autonomy not in AUTONOMY_LEVELS:
        fail(f"invalid autonomy: {autonomy}")
    if progress_day not in WEEKDAYS:
        fail(f"invalid progress day (Mon..Sun): {progress_day}")
    validate_time(touchpoint_time, "touchpoint-time")
    validate_time(sleep_time, "sleep-time")
    validate_time(progress_time, "progress-time")
    if autonomy == "off":
        return []
    daily = {
        "task_id": "digital-creature-daily-touchpoint",
        "schedule": f"every 1d at {touchpoint_time}",
        "skill": "hermes-digital-creature",
        "prompt": (
            "Run the daily touchpoint protocol. Respect quiet hours and autonomy. "
            "If there is no useful low-friction question or grounded observation, do not create artificial engagement."
        ),
        "deliver": "origin",
        "description": "Daily check-in: surface one recall candidate or clarification.",
    }
    if autonomy == "gentle":
        return [daily]
    sleep_task = {
        "task_id": "digital-creature-sleep-review",
        "schedule": f"every 1d at {sleep_time}",
        "skill": "hermes-digital-creature",
        "prompt": (
            "Run the sleep protocol locally. Surface at most one grounded insight or memory "
            "clarification at the next appropriate contact. Do not perform network or external file actions."
        ),
        "deliver": "local",
        "description": "Nightly sleep analysis: stale memories, conflicts, recent feedback.",
    }
    weekly = {
        "task_id": "digital-creature-weekly-progress",
        "schedule": f"every 1 week on {progress_day} at {progress_time}",
        "skill": "hermes-digital-creature",
        "prompt": (
            "Summarize progress: confirmed memories, feedback coverage, completed activities, "
            "calibrated traits. Offer at most one eligible capability suggestion. Do not unlock without consent."
        ),
        "deliver": "origin",
        "description": "Weekly progress summary and eligible capability suggestions.",
    }
    return [daily, sleep_task, weekly]


def cmd_proactive_plan(store: Store, args: argparse.Namespace) -> None:
    tasks = proactive_plan_tasks(
        args.autonomy, args.touchpoint_time, args.sleep_time, args.progress_time, args.progress_day
    )
    emit({"ok": True, "autonomy": args.autonomy, "tasks": tasks})


def cmd_proactive_register(store: Store, args: argparse.Namespace) -> None:
    if args.autonomy not in AUTONOMY_LEVELS:
        fail(f"invalid autonomy: {args.autonomy}")
    timestamp = now_iso()
    existing = store.conn.execute(
        "SELECT * FROM proactive_tasks WHERE task_id = ?", (args.task_id,)
    ).fetchone()
    description = args.description or ""
    prompt = args.prompt or ""
    deliver = args.deliver or "origin"
    if (
        existing
        and existing["status"] == "registered"
        and existing["schedule"] == args.schedule
        and existing["autonomy"] == args.autonomy
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
            args.consent_source or f"autonomy:{args.autonomy}",
        ),
    )
    store.audit(
        "proactive-register",
        "proactive_task",
        args.task_id,
        {"schedule": args.schedule, "autonomy": args.autonomy},
    )
    store.conn.commit()
    emit({"ok": True, "task_id": args.task_id, "status": "registered"})


def cmd_proactive_list(store: Store, args: argparse.Namespace) -> None:
    rows = store.conn.execute(
        "SELECT * FROM proactive_tasks ORDER BY registered_at DESC"
    ).fetchall()
    if args.status:
        rows = [row for row in rows if row["status"] == args.status]
    emit({"ok": True, "tasks": [serialize(row) for row in rows]})


def cmd_proactive_revoke(store: Store, args: argparse.Namespace) -> None:
    row = store.conn.execute(
        "SELECT * FROM proactive_tasks WHERE task_id = ?", (args.task_id,)
    ).fetchone()
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
    reason = args.reason or ""
    store.audit("proactive-revoke", "proactive_task", args.task_id, {"reason": reason})
    store.conn.commit()
    emit({"ok": True, "task_id": args.task_id, "status": "revoked"})


def cmd_proactive_diff(store: Store, args: argparse.Namespace) -> None:
    desired = proactive_plan_tasks(
        args.autonomy, args.touchpoint_time, args.sleep_time, args.progress_time, args.progress_day
    )
    desired_by_id = {task["task_id"]: task for task in desired}
    current = {
        row["task_id"]: dict(row)
        for row in store.conn.execute(
            "SELECT * FROM proactive_tasks WHERE status = 'registered'"
        ).fetchall()
    }
    to_register: list[dict[str, str]] = []
    to_update: list[dict[str, str]] = []
    for task_id, task in desired_by_id.items():
        existing = current.get(task_id)
        if not existing:
            to_register.append(task)
        elif existing["schedule"] != task["schedule"] or existing["autonomy"] != args.autonomy:
            to_update.append(task)
    to_revoke = [task_id for task_id in current if task_id not in desired_by_id]
    emit(
        {
            "ok": True,
            "autonomy": args.autonomy,
            "to_register": to_register,
            "to_update": to_update,
            "to_revoke": to_revoke,
        }
    )


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description="Local state runtime for Hermes Digital Creature")
    root.add_argument("--data-dir", help="State directory; defaults to ~/.hermes/data/hermes-digital-creature")
    commands = root.add_subparsers(dest="command", required=True)
    commands.add_parser("init").set_defaults(func=cmd_init)
    commands.add_parser("status").set_defaults(func=cmd_status)

    remember = commands.add_parser("remember")
    remember.add_argument("--type", choices=MEMORY_TYPES, required=True)
    remember.add_argument("--content", required=True)
    remember.add_argument("--confidence", type=float, default=0.6)
    remember.add_argument("--importance", type=float, default=0.5)
    remember.add_argument("--emotional-weight", type=float, default=0.0)
    remember.add_argument("--decay-rate", type=float, default=0.04)
    remember.add_argument("--source", default="conversation")
    remember.add_argument("--consent", action="store_true")
    remember.add_argument("--conflicts-with")
    remember.add_argument("--conflict-group")
    remember.set_defaults(func=cmd_remember)

    recall = commands.add_parser("recall")
    recall.add_argument("--query", required=True)
    recall.add_argument("--limit", type=int, default=5)
    recall.add_argument("--include-weak", action="store_true")
    recall.set_defaults(func=cmd_recall)

    memories = commands.add_parser("memories")
    memories.add_argument("--status", choices=("active", "archived", "superseded"), default="active")
    memories.add_argument("--limit", type=int, default=100)
    memories.set_defaults(func=cmd_memories)

    confirm = commands.add_parser("confirm")
    confirm.add_argument("--id", required=True)
    confirm.add_argument("--confidence", type=float, default=0.95)
    confirm.set_defaults(func=cmd_confirm)

    correct = commands.add_parser("correct")
    correct.add_argument("--id", required=True)
    correct.add_argument("--content", required=True)
    correct.add_argument("--confidence", type=float, default=0.95)
    correct.add_argument("--consent", action="store_true")
    correct.set_defaults(func=cmd_correct)

    archive = commands.add_parser("archive")
    archive.add_argument("--id", required=True)
    archive.add_argument("--reason", required=True)
    archive.set_defaults(func=cmd_archive)

    consolidate = commands.add_parser("consolidate")
    consolidate.add_argument("--ids", nargs="+", required=True)
    consolidate.add_argument("--content", required=True)
    consolidate.add_argument("--type", choices=MEMORY_TYPES)
    consolidate.add_argument("--consent", action="store_true")
    consolidate.set_defaults(func=cmd_consolidate)

    feedback = commands.add_parser("feedback")
    feedback.add_argument("--kind", choices=("correction", "preference-ranking", "explanation-rating", "tool-evaluation", "quest-outcome"), required=True)
    feedback.add_argument("--context", required=True)
    feedback.add_argument("--choice")
    feedback.add_argument("--signal")
    feedback.set_defaults(func=cmd_feedback)

    trait = commands.add_parser("trait")
    trait.add_argument("--name", choices=TRAITS, required=True)
    trait.add_argument("--delta", type=float, required=True)
    trait.add_argument("--reason", required=True)
    trait.set_defaults(func=cmd_trait)

    commands.add_parser("progress").set_defaults(func=cmd_progress)

    unlock = commands.add_parser("unlock")
    unlock.add_argument("--name", choices=tuple(CAPABILITIES), required=True)
    unlock.add_argument("--reason", required=True)
    unlock.add_argument("--consent", action="store_true")
    unlock.set_defaults(func=cmd_unlock)

    activity = commands.add_parser("activity")
    activity.add_argument("action", choices=("start", "complete"))
    activity.add_argument("--kind", choices=ACTIVITY_KINDS)
    activity.add_argument("--title")
    activity.add_argument("--id")
    activity.add_argument("--result")
    activity.set_defaults(func=cmd_activity)

    commands.add_parser("daily").set_defaults(func=cmd_daily)
    commands.add_parser("sleep").set_defaults(func=cmd_sleep)

    reflect = commands.add_parser("reflect")
    reflect.add_argument("--content", required=True)
    reflect.add_argument("--evidence", required=True)
    reflect.add_argument("--uncertainty", type=float, default=0.4)
    reflect.set_defaults(func=cmd_reflect)

    audit = commands.add_parser("audit")
    audit.add_argument("--limit", type=int, default=20)
    audit.set_defaults(func=cmd_audit)

    export = commands.add_parser("export")
    export.add_argument("--output", required=True)
    export.add_argument("--allow-external-path", action="store_true")
    export.set_defaults(func=cmd_export)

    purge = commands.add_parser("purge")
    purge.add_argument("--confirm", required=True)
    purge.set_defaults(func=cmd_purge)

    def add_time_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--touchpoint-time", default=DEFAULT_TOUCHPOINT_TIME)
        p.add_argument("--sleep-time", default=DEFAULT_SLEEP_TIME)
        p.add_argument("--progress-time", default=DEFAULT_PROGRESS_TIME)
        p.add_argument("--progress-day", default=DEFAULT_PROGRESS_DAY, choices=WEEKDAYS)

    proactive_plan_p = commands.add_parser("proactive-plan")
    proactive_plan_p.add_argument("--autonomy", choices=AUTONOMY_LEVELS, required=True)
    add_time_args(proactive_plan_p)
    proactive_plan_p.set_defaults(func=cmd_proactive_plan)

    proactive_register_p = commands.add_parser("proactive-register")
    proactive_register_p.add_argument("--task-id", required=True)
    proactive_register_p.add_argument("--schedule", required=True)
    proactive_register_p.add_argument("--autonomy", choices=AUTONOMY_LEVELS, required=True)
    proactive_register_p.add_argument("--description", default="")
    proactive_register_p.add_argument("--prompt", default="")
    proactive_register_p.add_argument("--deliver", default="origin")
    proactive_register_p.add_argument("--consent-source", default="")
    proactive_register_p.set_defaults(func=cmd_proactive_register)

    proactive_list_p = commands.add_parser("proactive-list")
    proactive_list_p.add_argument("--status", choices=("registered", "revoked"))
    proactive_list_p.set_defaults(func=cmd_proactive_list)

    proactive_revoke_p = commands.add_parser("proactive-revoke")
    proactive_revoke_p.add_argument("--task-id", required=True)
    proactive_revoke_p.add_argument("--reason", default="")
    proactive_revoke_p.set_defaults(func=cmd_proactive_revoke)

    proactive_diff_p = commands.add_parser("proactive-diff")
    proactive_diff_p.add_argument("--autonomy", choices=AUTONOMY_LEVELS, required=True)
    add_time_args(proactive_diff_p)
    proactive_diff_p.set_defaults(func=cmd_proactive_diff)

    return root


def validate_activity_args(args: argparse.Namespace) -> None:
    if args.command != "activity":
        return
    if args.action == "start" and (not args.kind or not args.title):
        fail("activity start requires --kind and --title")
    if args.action == "complete" and (not args.id or not args.result):
        fail("activity complete requires --id and --result")


def main() -> None:
    args = parser().parse_args()
    validate_activity_args(args)
    store = Store(data_dir_from_arg(args.data_dir))
    try:
        args.func(store, args)
    finally:
        if args.command != "purge":
            store.close()


if __name__ == "__main__":
    main()
