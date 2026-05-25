# Hermes Digital Creature

`hermes-digital-creature` is a local-first skill for [Hermes Agent](https://github.com/NousResearch/hermes-agent) that turns ordinary Telegram or chat interaction into a persistent digital creature experience.

It is not an RPG shell over an assistant. Its gameplay events produce inspectable cognitive state: corrected memories, preference rankings, explanation feedback, tool-evaluation traces, trait changes, reflection records, and opt-in capability growth.

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

The repository is a Hermes skill tap layout: the installable artifact is under `skills/hermes-digital-creature/`.

## Capabilities

### Creature Interaction

- Chat-first Telegram interaction without deep button trees.
- First-contact onboarding with transparent privacy and autonomy controls.
- Daily touchpoint protocol that can recall, clarify, or propose one useful activity.
- Functional personality shaping through traits such as curiosity, caution, verbosity, and autonomy.

### Meaningful Gameplay

| Activity | Cognitive output |
| --- | --- |
| Memory repair | Confirmation, correction lineage, or deletion of stale memories |
| Preference ranking | Feedback traces for response or plan style |
| Explain better | Explanation quality signals and optional trait adjustments |
| Detective story | Reasoning and uncertainty reflection without fictional user memories |
| Tool expedition | Approved agent execution with result evaluation and procedural learning |

### Persistent State

The bundled standard-library Python runtime stores:

- typed memories: `episodic`, `preference`, `procedural`, `emotional`, `meta-cognitive`;
- confidence, importance, emotional salience, decay rate, conflicts, links, and recall counts;
- user corrections and other feedback traces;
- behavioral traits and opt-in capability unlocks;
- activities, reflections, and mutation audit history.

State is stored locally in SQLite at:

```text
~/.hermes/data/hermes-digital-creature/creature.sqlite3
```

The location is configurable through the Hermes skill config setting `digital_creature.data_dir`.

## Principles Implemented

- **Local-first:** creature state is local SQLite data; the runtime has no network behavior.
- **Inspectable memory:** active memories and audit entries can be displayed and exported.
- **Deletable memory:** individual memories can be archived and all creature data can be explicitly purged.
- **Honest attachment:** Hermes may develop continuity and recognizable interaction preferences, but must not claim feelings or manipulate retention.
- **Controlled autonomy:** proactive interactions and tool expeditions are opt-in; critical actions retain approval gates.
- **Cognitive progression:** progress is represented by better-confirmed memories, collected feedback, reflections, and enabled capabilities rather than arbitrary XP.

## Requirements

- Hermes Agent with skills enabled.
- Python 3.10 or newer for the bundled state runtime.
- A configured Hermes messaging gateway when using Telegram.
- Hermes cron support only if proactive daily/sleep interactions are desired.

The skill is model-agnostic. For the intended interaction quality, use a model with structured tool calling, reliable multi-step reasoning, streaming, and a context window of at least 32k.

## Installation

### Install From A GitHub Tap

Once this repository is published, install the single skill directly:

```bash
hermes skills install ad/hermes-digital-creature/skills/hermes-digital-creature
```

Alternatively add the repository as a tap and then install the skill:

```bash
hermes skills tap add ad/hermes-digital-creature
hermes skills install ad/hermes-digital-creature/hermes-digital-creature
```

### Use A Local Checkout

During development, configure Hermes to scan this checkout as an external skill directory. Add the absolute `skills/` directory to `~/.hermes/config.yaml`:

```yaml
skills:
  external_dirs:
    - /absolute/path/to/hermes-digital-creature/skills
```

Hermes discovers the skill as `/hermes-digital-creature` in CLI and configured messaging surfaces.

### Configure Creature Settings

The skill declares these non-secret Hermes settings:

| Setting | Default | Purpose |
| --- | --- | --- |
| `digital_creature.data_dir` | `~/.hermes/data/hermes-digital-creature` | Local SQLite state, exports, and ownership marker |
| `digital_creature.quiet_hours` | `23:00-08:00` | Suppress proactive delivery in local time |
| `digital_creature.autonomy` | `gentle` | `off`, `gentle`, or `active` behavior profile |

Run the Hermes config migration after installation, or set values directly:

```bash
hermes config migrate
hermes config set skills.config.digital_creature.autonomy gentle
hermes config set skills.config.digital_creature.quiet_hours 23:00-08:00
```

## Starting The Creature

From Telegram or another Hermes conversation surface:

```text
/hermes-digital-creature start
```

On first contact, Hermes should:

1. Initialize its local creature state.
2. Explain local storage, inspection/deletion, optional proactive behavior, and approval gates briefly.
3. Ask one setup question, such as the preferred interaction style or creature name.
4. Store only confirmed information.

Example first exchange:

```text
User: /hermes-digital-creature start

Hermes: Я могу вести локальную память об этом взаимодействии: ее можно
просмотреть, исправить, экспортировать или удалить. Проактивные сообщения
включаются только с твоего согласия, а действия с инструментами требуют
подтверждения. Какой стиль тебе удобнее: короткий, исследовательский или смешанный?
```

## State Runtime

Hermes invokes the script while the skill is active. It can also be inspected manually:

```bash
SKILL_DIR="$PWD/skills/hermes-digital-creature"
DATA_DIR="$HOME/.hermes/data/hermes-digital-creature"

python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" init
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" status
```

### Memory Commands

```bash
# Save an explicitly confirmed preference
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" remember \
  --type preference \
  --content "User prefers local-first tooling." \
  --confidence 0.90 \
  --importance 0.80 \
  --consent

# Recall relevant memories
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" recall \
  --query "local tooling" --limit 5

# Correct a memory while preserving correction history
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" correct \
  --id mem_xxx \
  --content "User prefers local-first tooling unless maintenance cost is excessive." \
  --confidence 0.95 \
  --consent

# Archive one memory after a deletion request
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" archive \
  --id mem_xxx --reason user-deletion
```

Unconfirmed inferred memories cannot be stored with high confidence. Emotional memories require explicit consent. Strings that appear to contain credentials or secrets are rejected.

### Feedback, Traits, And Progress

```bash
# Save a style selection made by the user
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" feedback \
  --kind preference-ranking \
  --context "Compared compact and explanatory response formats." \
  --choice A \
  --signal "Preferred compact response for command tasks."

# Make a small evidence-backed trait update
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" trait \
  --name verbosity --delta -0.05 \
  --reason "User explicitly requested concise operational replies."

# Inspect progress and offered capabilities
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" progress

# Enable a capability only after opt-in
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" unlock \
  --name reflection \
  --reason "User enabled local reflection reviews." \
  --consent
```

An unlocked capability never removes approval requirements for tool actions or external side effects.

### Reflection And Daily Loop

```bash
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" daily
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" sleep
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" audit --limit 20
```

`daily` selects possible low-friction interaction material. `sleep` reports stale memories, conflicts, recent feedback, and completed activity counts. These operations analyze local state; they do not imply consciousness or perform external actions.

### Export And Deletion

```bash
# Export within the state directory
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" export \
  --output "$DATA_DIR/export.json"

# Permanently delete all creature data after an explicit user request
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" purge \
  --confirm DELETE-ALL-CREATURE-DATA
```

The runtime creates an ownership marker and refuses to purge an unowned non-empty directory.

## Telegram And Autonomy

The skill is designed for an existing Hermes Telegram gateway. It does not configure a bot token or provision the gateway itself.

Proactive behavior is intentionally bounded:

| Mode | Behavior |
| --- | --- |
| `off` | Only responds when invoked; no scheduled creature tasks |
| `gentle` | Can offer an approved daily memory/reflection touchpoint |
| `active` | Can offer approved expeditions in addition to touchpoints |

The user must explicitly approve scheduled jobs, external network actions, credential usage, writes outside creature state, destructive operations, and persistent configuration changes.

After opt-in, Hermes cron can attach this skill to a daily touchpoint or sleep review. Exact scheduling is managed by Hermes, as described in [autonomy-and-scheduling.md](skills/hermes-digital-creature/references/autonomy-and-scheduling.md).

## Privacy And Security

- `creature_state.py` uses Python standard library and SQLite only.
- It performs no model calls and no external network calls.
- It refuses to initialize into a non-empty directory without its ownership marker.
- It refuses secret-like memory content and limits memory entry length.
- It stores correction lineage rather than silently rewriting facts.
- It audits state mutations.
- Full data purge requires a deliberate confirmation string.

The current MVP does **not** provide encrypted storage at rest. Place the configured data directory on encrypted storage if that protection is required.

## Current MVP Boundaries

Implemented:

- local creature memory and audit store;
- transparent correction, retrieval, feedback, activity, reflection, and progression workflows;
- Telegram-oriented interaction policy;
- safe scheduling and expedition protocols for Hermes to follow.

Not implemented by this skill alone:

- Telegram gateway provisioning or authentication;
- vector embeddings or an external vector database;
- model training or fine-tuning;
- encrypted storage;
- Hermes core modification or automatic dependency installation.

## Development And Validation

Run the bundled regression tests:

```bash
python3 -m unittest skills/hermes-digital-creature/scripts/test_creature_state.py -v
```

The suite validates:

- memory creation, recall, correction lineage, and export;
- Cyrillic retrieval;
- sensitive-memory rejection and confidence limits;
- trait changes, activities, sleep analysis, audit, progression unlocks, and purge;
- refusal to operate in a non-owned non-empty state directory.

The skill follows the current Hermes `SKILL.md` structure documented in:

- [Hermes Skills System](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/skills.md)
- [Creating Skills](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/developer-guide/creating-skills.md)

