# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Layout

This repo is a Hermes skill tap. The single installable artifact lives at `skills/hermes-digital-creature/`:

- `SKILL.md` — skill manifest (frontmatter + behavioral contract that Hermes loads).
- `references/` — long-form docs Hermes is instructed to read on demand (`state-model.md`, `interaction-protocols.md`, `autonomy-and-scheduling.md`).
- `scripts/creature_state.py` — the entire runtime. Single-file Python 3.10+, standard library + SQLite only. No network, no third-party deps.
- `scripts/test_creature_state.py` — `unittest` regression suite.

There is no package, no build step, no `pyproject.toml`. The script is the product.

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

Subcommands exposed by `creature_state.py`: `init`, `status`, `remember`, `recall`, `memories`, `confirm`, `correct`, `archive`, `consolidate`, `feedback`, `trait`, `progress`, `unlock`, `activity`, `daily`, `sleep`, `reflect`, `audit`, `export`, `purge`, `autonomy`, `quiet-hours`, `proactive-plan`, `proactive-diff`, `proactive-register`, `proactive-list`, `proactive-revoke`, `doctor`.

## Architecture

The skill has two layers that must stay in sync:

1. **Behavioral contract** (`SKILL.md` + `references/*.md`). Loaded by Hermes as the model's instructions. Defines the conversation loop, first-contact flow, activity catalog, memory discipline, autonomy modes (`off`/`gentle`/`active`), and the non-negotiable safety rules (local-only state, no fabricated emotions/memories, approval gates for tool actions).
2. **Deterministic runtime** (`scripts/creature_state.py`). Every state-changing operation goes through this single script. The model is expected to shell out to it and treat the emitted JSON as ground truth. All mutations emit an audit event.

`creature_state.py` is built around a `Store` class wrapping one SQLite DB at `<data_dir>/creature.sqlite3`. Key invariants enforced in code, not just docs:

- Refuses to operate in a non-empty `data_dir` that lacks the ownership marker (`MARKER_FILENAME`).
- Rejects memory content matching `SENSITIVE_PATTERN` (secret/credential-like strings) and caps length.
- `emotional` memories require `--consent`; high-confidence stores require explicit confirmation.
- `correct` writes a new memory linked to the original via correction lineage; never silently overwrites.
- `purge` requires the literal confirmation string `DELETE-ALL-CREATURE-DATA`.
- Schema version pinned in `SCHEMA_VERSION` (currently 2); `_schema()` autoupgrades older databases and writes a `schema-upgrade` audit row. Whitelists for `MEMORY_TYPES`, `TRAITS`, `ACTIVITY_KINDS`, `CAPABILITIES`, `AUTONOMY_LEVELS`, `WEEKDAYS`, `RETIRED_CAPABILITIES`.
- Persisted settings live in the `metadata` table: `autonomy`, `quiet_hours_start`, `quiet_hours_end`, `touchpoint_time`, `sleep_time`, `progress_time`, `progress_day`. `autonomy` / `quiet-hours` subcommands read/write these and audit every change.
- Proactive scheduling: `proactive_plan_tasks()` produces the deterministic task set per autonomy level (uses stored settings unless overridden). `proactive_tasks` table is the source of truth for what Hermes cron should have registered. The autonomy setting itself counts as consent for that exact task set; anything outside still needs explicit per-action approval. Revoked rows are kept for audit (never deleted).
- `doctor` checks: ownership marker, schema version, valid autonomy/time settings, DB writability, and drift between the stored autonomy plan and what's recorded in `proactive_tasks`.
- Recall tokenization (`stem_token` + `query_tokens`) strips diacritics and trims common Russian/English suffixes so different word endings of the same root match.
- `daily` and `sleep` emit a `suppression` block computed from `quiet_hours` + `autonomy`; respect it before delivering proactive messages.

When changing the runtime, keep the CLI surface (subcommand names, flags, JSON output shape) backward-compatible — `SKILL.md` and the references document those calls verbatim and Hermes invokes them as written. If you add a constraint to the script, mirror it in the relevant reference doc; if you add a behavior to a reference doc, make sure the script actually enforces it.

## Conventions

- Standard library only. Adding a dependency breaks the local-first / no-install guarantee.
- Tests live next to the script and exercise the CLI through `main()` with a temp `--data-dir`. Add new tests there in the same style.
- README examples are user-facing documentation; if you rename a flag or subcommand, update README.md, SKILL.md, and the references in the same change.
