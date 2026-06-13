# Hermes Digital Creature

`hermes-digital-creature` is a skill for [Hermes Agent](https://github.com/NousResearch/hermes-agent)
that makes Hermes feel like one continuous, growing companion in Telegram or chat — remembered
preferences, a recognizable character, learning from feedback, and optional proactive check-ins.

It is **not** a separate creature with its own brain. There is one Hermes and one memory: Hermes
native memory (`MEMORY.md` / `USER.md`, `session_search`, and any configured external memory
provider). This skill is a thin layer that gives that single Hermes a character, a disciplined way to
curate its own memory, and a proactive cadence.

> **Why 0.4 changed.** Earlier versions kept a separate SQLite "creature memory" isolated from Hermes
> native memory. In practice that created two disconnected identities — the creature only "existed"
> while the skill was loaded, and it could not see what Hermes learned elsewhere. 0.4 removes the
> parallel store: continuity and character now live in native memory, present in every session.

## What This Repository Contains

```text
skills/hermes-digital-creature/
├── SKILL.md
├── references/
│   ├── autonomy-and-scheduling.md
│   ├── interaction-protocols.md
│   └── state-model.md
└── scripts/
    ├── creature_state.py
    └── test_creature_state.py
```

The repository is a Hermes skill tap layout: the installable artifact is under
`skills/hermes-digital-creature/`.

## How Memory Works

| Content | Lives in | Accessed via |
| --- | --- | --- |
| Durable user facts / preferences | `USER.md` | Hermes memory tool (injected each session) |
| Agent's learned procedures, lessons, persona block | `MEMORY.md` | Hermes memory tool (injected each session) |
| Episodic detail of past conversations | conversation history | `session_search` (FTS over `~/.hermes/state.db`) |
| Semantic / fuzzy recall, fact extraction | external provider | provider query (Mem0/Honcho/etc.), when configured |
| Autonomy, quiet hours, proactive task plan, audit | this skill's data dir | `creature_state.py` |

The skill's local data directory holds **only** scheduling/settings state and an audit of those
changes — never user memories.

## Capabilities

- Chat-first Telegram interaction without deep button trees.
- First-contact onboarding with transparent privacy and autonomy controls.
- Continuity across every session, because memory lives in native `MEMORY.md`/`USER.md`.
- A recognizable character via a short persona block in `MEMORY.md` (name, voice, functional trait
  leanings) — guidance for tone, not emotion claims.
- Memory-curation discipline: write sparingly and atomically, correct by replacing, review stale
  entries during `sleep`.
- Optional proactive cadence: daily touchpoint, nightly sleep review, weekly progress, gated by an
  autonomy level and quiet hours.
- One-time migration that seeds native memory from a legacy creature database.

## Principles Implemented

- **One Hermes, one memory:** no parallel memory silo; the skill curates native memory.
- **Inspectable & deletable:** users inspect and edit memory through Hermes; skill scheduling state can
  be exported and purged.
- **Honest attachment:** Hermes develops continuity and recognizable preferences but never claims
  feelings or manipulates retention.
- **Controlled autonomy:** proactive interactions and tool expeditions are opt-in; critical actions
  retain approval gates.
- **Grounded growth:** progress is better-curated memory and confirmed preferences, not arbitrary XP.

## Requirements

- Hermes Agent with skills enabled.
- The Hermes **memory** feature (`MEMORY.md`/`USER.md` + memory tool). Continuity depends on it; when
  unavailable the skill degrades to an ordinary assistant for the session.
- Python 3.10 or newer for the bundled scheduling/settings runtime.
- A configured Hermes messaging gateway when using Telegram.
- Hermes **cron** support. **Required** when `digital_creature.autonomy` is `gentle` or `active` — the
  skill auto-registers proactive tasks at first contact. If cron is unavailable, the skill degrades to
  `off` and tells the user.
- Optional: an external memory provider (Mem0, Honcho, etc.) for semantic recall and fact extraction.

## Installation

### Install From A GitHub Tap

```bash
hermes skills install ad/hermes-digital-creature/skills/hermes-digital-creature
```

Alternatively add the repository as a tap and then install the skill:

```bash
hermes skills tap add ad/hermes-digital-creature
hermes skills install ad/hermes-digital-creature/hermes-digital-creature
```

### Use A Local Checkout

During development, configure Hermes to scan this checkout as an external skill directory:

```yaml
skills:
  external_dirs:
    - /absolute/path/to/hermes-digital-creature/skills
```

Hermes discovers the skill as `/hermes-digital-creature` in CLI and configured messaging surfaces.

### Configure Settings

| Setting | Default | Purpose |
| --- | --- | --- |
| `digital_creature.data_dir` | `~/.hermes/data/hermes-digital-creature` | Scheduling/settings state, audit, ownership marker (no user memories) |
| `digital_creature.quiet_hours` | `23:00-08:00` | Suppress proactive delivery in local time |
| `digital_creature.autonomy` | `gentle` | `off`, `gentle`, or `active` behavior profile |
| `digital_creature.touchpoint_time` | `09:00` | Daily touchpoint time (HH:MM, local) for `gentle`/`active` |
| `digital_creature.sleep_time` | `21:00` | Nightly sleep review time for `active` |
| `digital_creature.progress_time` | `19:00` | Weekly progress summary time for `active` |
| `digital_creature.progress_day` | `Sun` | Weekly progress summary weekday for `active` |

```bash
hermes config migrate
hermes config set skills.config.digital_creature.autonomy gentle
hermes config set skills.config.digital_creature.quiet_hours 23:00-08:00
```

## Starting The Creature

```text
/hermes-digital-creature start
```

On first contact, Hermes should:

1. Verify cron and the memory tool are available.
2. Initialize local scheduling/settings state.
3. Briefly explain that memory lives in Hermes' own `MEMORY.md`/`USER.md` (inspectable/editable),
   autonomy is configurable, and critical actions need approval.
4. Register the proactive tasks implied by the autonomy level.
5. If a legacy creature database exists, run `migrate` once and seed native memory.
6. Ask one optional setup question (name / preferred tone).

## Scheduling & Settings Runtime

Hermes invokes the script while the skill is active. It can also be inspected manually. The runtime
manages settings and the proactive plan — **memory is handled by the Hermes memory tool, not here.**

```bash
SKILL_DIR="$PWD/skills/hermes-digital-creature"
DATA_DIR="$HOME/.hermes/data/hermes-digital-creature"

python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" init
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" status
```

### Autonomy, Proactive Tasks, And Doctor

```bash
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" autonomy get
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" autonomy set --value gentle
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" quiet-hours set --start 23:00 --end 08:00

python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" proactive-plan --autonomy active
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" proactive-diff --autonomy active
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" proactive-register \
  --task-id digital-creature-daily-touchpoint \
  --schedule "every 1d at 09:00" --autonomy gentle \
  --prompt "Run the daily touchpoint protocol..." --deliver origin
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" proactive-list --status registered
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" proactive-revoke \
  --task-id digital-creature-daily-touchpoint --reason user-disable

python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" doctor
```

`proactive-plan` and `proactive-diff` fall back to stored autonomy/time settings when called without
flags. `doctor` exits non-zero on any structural error (missing marker, schema mismatch, invalid stored
times, unwritable database) and warns about plan drift and any leftover legacy memory tables.

### Daily Loop, Migration, Export, Deletion

```bash
# Suppression decision + guidance for proactive runs (operate on native memory)
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" daily
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" sleep
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" audit --limit 20

# One-time: turn a legacy creature DB into a seed plan for native memory (non-destructive)
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" migrate

# Export the skill's scheduling/settings state (and any residual legacy tables) inside the data dir
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" export --output "$DATA_DIR/export.json"

# Permanently delete the skill's data directory after an explicit user request
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" purge --confirm DELETE-ALL-CREATURE-DATA
```

`daily`/`sleep` return a suppression decision plus guidance; the actual recall/review is performed by
Hermes over native memory. Deleting user *memories* is done through the Hermes memory tool, since they
live in native storage. The runtime creates an ownership marker and refuses to purge an unowned
non-empty directory.

## Telegram And Autonomy

Proactive behavior is driven by `digital_creature.autonomy`. At first contact the skill auto-registers
the matching cron tasks; the autonomy setting itself counts as consent for that task set.

| Mode | Registered automatically | Other proactive behavior |
| --- | --- | --- |
| `off` | nothing | none — only responds when invoked |
| `gentle` | daily touchpoint (`touchpoint_time`, default `09:00`) | none beyond that single task |
| `active` | daily touchpoint + nightly sleep review (`sleep_time`, default `21:00`) + weekly progress (`progress_day` `progress_time`, default Sun `19:00`) | may propose scoped expeditions during a touchpoint (each still needs per-action approval) |

External network actions, credential usage, writes outside the data dir, destructive operations, and
**non-default** scheduled jobs still require explicit per-action approval regardless of autonomy. The
user can disable proactive contact anytime ("отключи проактивность", "stop proactive") — the skill
revokes every registered task and switches to `off`. See
[autonomy-and-scheduling.md](skills/hermes-digital-creature/references/autonomy-and-scheduling.md).

## Privacy And Security

- `creature_state.py` uses Python standard library and SQLite only; no model calls, no network.
- It refuses to initialize into a non-empty directory without its ownership marker.
- It stores no user memories — those live in Hermes native memory, governed by Hermes' own controls.
- It audits scheduling/settings mutations; full data purge requires a deliberate confirmation string.
- Sensitive content is not written to memory without user permission (a memory-curation rule the model
  follows; see [state-model.md](skills/hermes-digital-creature/references/state-model.md)).

## Current Boundaries

Implemented:

- a character/persona layer plus memory-curation discipline over Hermes native memory;
- a one-time migration from the legacy creature database;
- Telegram-oriented interaction policy;
- safe scheduling and expedition protocols for Hermes to follow.

Not implemented by this skill alone:

- Telegram gateway provisioning or authentication;
- a memory store of its own, vector embeddings, or an external vector database (it uses whatever Hermes
  memory/provider is configured);
- model training or fine-tuning;
- encrypted storage;
- Hermes core modification or automatic dependency installation.

## Development And Validation

```bash
python3 -m unittest skills/hermes-digital-creature/scripts/test_creature_state.py -v
```

The suite validates:

- `init`/`status` reporting the native memory backend;
- `autonomy` and `quiet-hours` get/set with HH:MM validation and audit;
- `daily`/`sleep` suppression reporting during quiet hours;
- `audit --entity-id` filtering;
- `proactive-plan` / `proactive-diff` / `proactive-register` / `proactive-revoke` lifecycle and idempotency;
- `doctor` drift detection and legacy-table reporting;
- `migrate` bucketing of legacy memories into a native-memory seed plan;
- schema auto-upgrade from a legacy (v2) database;
- export contents and refusal to overwrite the state database;
- refusal to operate in a non-owned non-empty state directory;
- purge confirmation handling.

The skill follows the current Hermes `SKILL.md` structure documented in:

- [Hermes Skills System](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/skills.md)
- [Creating Skills](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/creating-skills.md)
