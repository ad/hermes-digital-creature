# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

This repo is a Hermes skill tap. The single installable artifact lives at `skills/hermes-digital-creature/`:

- `SKILL.md` — skill manifest (frontmatter + behavioral contract that Hermes loads).
- `references/` — long-form docs Hermes is instructed to read on demand (`state-model.md`, `interaction-protocols.md`, `autonomy-and-scheduling.md`).
- `scripts/creature_state.py` — the scheduling/settings runtime. Single-file Python 3.10+, standard library + SQLite only. No network, no third-party deps.
- `scripts/test_creature_state.py` — `unittest` regression suite.

There is no package, no build step, no `pyproject.toml`.

**Core design (v0.4, native-first).** There is one Hermes and one memory. Memory and character live in
**Hermes native memory** (`MEMORY.md`/`USER.md`, injected each session; `session_search`; optional
external provider like Mem0/Honcho). The skill does NOT keep a parallel memory store — that earlier
design produced "two disconnected identities." The skill is now a thin layer: a character/persona
contract, memory-curation discipline (the model writes durable facts via the Hermes memory tool), and a
proactive cadence. `creature_state.py` owns only the deterministic state Hermes does not track for this
skill: autonomy/quiet-hours/time settings, the proactive task plan, an audit of those, and a one-time
`migrate` helper.

## Common Commands

Run tests (the only check the project has):

```bash
python3 -m unittest skills/hermes-digital-creature/scripts/test_creature_state.py -v
```

Run a single test:

```bash
python3 -m unittest skills.hermes-digital-creature.scripts.test_creature_state.TestCreatureState.<method> -v
```

Exercise the runtime against a scratch data dir:

```bash
SKILL_DIR="$PWD/skills/hermes-digital-creature"
DATA_DIR="$(mktemp -d)/creature"
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" init
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" status
```

Subcommands exposed by `creature_state.py`: `init`, `status`, `daily`, `sleep`, `migrate`, `audit`, `export`, `purge`, `autonomy`, `quiet-hours`, `proactive-plan`, `proactive-diff`, `proactive-register`, `proactive-list`, `proactive-revoke`, `doctor`. (The pre-0.4 memory-engine subcommands — `remember`/`recall`/`memories`/`confirm`/`correct`/`archive`/`consolidate`/`feedback`/`trait`/`progress`/`unlock`/`activity`/`reflect` — were removed; memory is now native Hermes memory.)

## Architecture

The skill has two layers that must stay in sync:

1. **Behavioral contract** (`SKILL.md` + `references/*.md`). Loaded by Hermes as the model's instructions. Defines the conversation loop, first-contact flow, character/persona, memory-curation discipline (over native memory), autonomy modes (`off`/`gentle`/`active`), and the non-negotiable safety rules (no parallel memory store, no fabricated emotions/memories, approval gates for tool actions).
2. **Scheduling/settings runtime** (`scripts/creature_state.py`). Owns only settings + the proactive plan + audit of those. The model shells out to it and treats the emitted JSON as ground truth. **Memory is NOT here** — the model writes durable facts to native `MEMORY.md`/`USER.md` via the Hermes memory tool and recalls via injected memory / `session_search` / a configured provider.

`creature_state.py` is built around a `Store` class wrapping one SQLite DB at `<data_dir>/creature.sqlite3` (three tables: `metadata`, `proactive_tasks`, `audit`). Key invariants enforced in code, not just docs:

- Refuses to operate in a non-empty `data_dir` that lacks the ownership marker (`MARKER_FILENAME`).
- `purge` requires the literal confirmation string `DELETE-ALL-CREATURE-DATA` and the ownership marker.
- Schema version pinned in `SCHEMA_VERSION` (currently 3); `_schema()` auto-upgrades older databases (v2→v3) and writes a `schema-upgrade` audit row. It does NOT drop the legacy memory tables (`LEGACY_TABLES`) — they're left for `migrate`/`export` and reported by `doctor`. Whitelists: `AUTONOMY_LEVELS`, `WEEKDAYS`.
- Persisted settings live in the `metadata` table: `autonomy`, `quiet_hours_start`, `quiet_hours_end`, `touchpoint_time`, `sleep_time`, `progress_time`, `progress_day`. `autonomy` / `quiet-hours` subcommands read/write these and audit every change.
- Proactive scheduling: `proactive_plan_tasks()` produces the deterministic task set per autonomy level (uses stored settings unless overridden). `proactive_tasks` table is the source of truth for what Hermes cron should have registered. The autonomy setting itself counts as consent for that exact task set; anything outside still needs explicit per-action approval. Revoked rows are kept for audit (never deleted).
- `migrate` is non-destructive: it reads legacy `memories`/`traits` tables (if present) and emits a seed plan (`user_md`/`memory_md`/`persona_traits`) for the model to write into native memory; low-importance episodics are intentionally skipped.
- `doctor` checks: ownership marker, schema version, valid autonomy/time settings, DB writability, drift between the stored autonomy plan and `proactive_tasks`, and presence of leftover legacy tables.
- `daily` and `sleep` emit a `suppression` block computed from `quiet_hours` + `autonomy` plus guidance; the actual recall/review runs over native memory. Respect suppression before delivering proactive messages.

When changing the runtime, keep the CLI surface (subcommand names, flags, JSON output shape) in sync with `SKILL.md` and the references — Hermes invokes those calls as written. If you add a constraint to the script, mirror it in the relevant reference doc; if you add a behavior to a reference doc, make sure the script actually enforces it. Memory-curation rules (e.g. "don't store secrets") are now model-enforced via the contract, not the script.

## Conventions

- Standard library only. Adding a dependency breaks the local-first / no-install guarantee.
- Tests live next to the script and exercise the CLI through `main()` with a temp `--data-dir`. Add new tests there in the same style.
- README examples are user-facing documentation; if you rename a flag or subcommand, update README.md, SKILL.md, and the references in the same change.
