# Creature State Model

Read this reference when manipulating memory, feedback, traits, reflection, exports, or deletion.

## Storage Boundary

`scripts/creature_state.py` writes only to its configured `--data-dir`, except an explicitly approved export path passed with `--allow-external-path`. Its SQLite store is distinct from Hermes built-in `MEMORY.md` and `USER.md`:

- Use creature storage for evolving, inspectable, decaying memories and training signals.
- Use Hermes built-in memory only when a fact must affect general Hermes sessions outside this skill and the user agrees.
- Never duplicate all creature memories into global Hermes memory.

The state script does not make network calls, call a model, schedule work, execute arbitrary commands, or encrypt files.
It writes an ownership marker in its data directory and refuses to initialize inside a non-empty unowned directory; `purge` requires that marker before deleting the directory.

## Entities

### Memory

| Field | Meaning |
| --- | --- |
| `type` | `episodic`, `preference`, `procedural`, `emotional`, or `meta-cognitive` |
| `content` | One concise statement, maximum 1000 characters |
| `confidence` | Confidence the statement is correct, not importance |
| `importance` | Expected future relevance |
| `emotional_weight` | User-confirmed salience, not Hermes emotion |
| `decay_rate` | Rate at which unrecalled confidence becomes suspect |
| `consent` | User confirmed storing the statement |
| `status` | `active`, `superseded`, or `archived` |
| `supersedes_id` | Correction lineage |
| `conflict_group` | Memories requiring reconciliation |

Suggested inputs:

| Situation | Confidence | Importance | Decay |
| --- | ---: | ---: | ---: |
| Explicit stable preference | 0.90 | 0.80 | 0.02 |
| Confirmed project episode | 0.85 | 0.55 | 0.06 |
| Tentative inferred preference | <= 0.60 | 0.45 | 0.10 |
| Procedural lesson from successful tool use | 0.75 | 0.75 | 0.04 |
| Meta-cognitive correction pattern | 0.70 | 0.65 | 0.04 |

Do not store secrets, authentication material, entire chat transcripts, raw logs, medical/legal/financial dossiers, third-party private information, or a user's emotional state inferred without explicit confirmation.

### Feedback

Feedback is a trace of learning input. Record it even when it does not justify a durable memory.

| Kind | Store after |
| --- | --- |
| `correction` | User replaces an inaccurate memory or answer premise |
| `preference-ranking` | User chooses between answer/plan styles |
| `explanation-rating` | User rates clarity or supplies a better explanation |
| `tool-evaluation` | User evaluates an expedition/result |
| `quest-outcome` | User completes or declines a cognitive activity |

### Traits

Traits are behavioral controls from 0 to 1. They do not represent feelings.

Only adjust a trait after evidence, with a small delta and a human-readable reason:

```bash
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" trait \
  --name verbosity --delta -0.05 --reason "User explicitly chose the concise explanation twice."
```

### Activity And Reflection

An activity has a declared cognitive purpose and completion result. A reflection stores a grounded insight plus its evidence and uncertainty. Never use a reflection alone as a user fact; convert it to a tentative memory or ask the user first.

### Progression And Capabilities

Progress is recorded through confirmed memories, feedback, completed activities, grounded reflections, and trait changes. `progress` reports those metrics and capability proposals. There is no abstract XP.

Initial interaction capabilities are `memory-repair`, `preference-ranking`, and `explain-better`. `reflection`, `tool-expedition`, and `proactive-check-in` are opt-in unlocks. `unlock --consent` stores the decision; it does not authorize any future critical action.

## Retrieval And Forgetting

`recall` uses deterministic lexical overlap plus importance, confidence, emotional salience, and freshness. This is intentionally interpretable, not semantic vector retrieval.

- Recall with the user's topic; do not use `--include-weak` during ordinary conversation.
- Treat scores as ranking only, not proof.
- Ask to repair a retrieved memory when `confidence < 0.6`, a conflict is listed, or the user contradicts it.
- Use `sleep` to find stale memories eligible for confirmation or archiving.
- Archive on user request; do not retain a hidden copy outside the database.

For a later advanced implementation, embeddings may be added locally as a separate retrieval index, while the SQLite record remains authoritative and deletable.

## Transparent Data Operations

Examples:

```bash
# Inspect active memory
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" memories --status active

# Correct without destroying history
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" correct \
  --id mem_xxx --content "User prefers self-hosted tools unless maintenance cost is excessive." \
  --confidence 0.95 --consent

# Archive a memory the user wants forgotten
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" archive \
  --id mem_xxx --reason user-deletion

# Export inside the state directory
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" export \
  --output "$DATA_DIR/export.json"
```

Full purge is destructive. Confirm the user's intent immediately before running:

```bash
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" purge \
  --confirm DELETE-ALL-CREATURE-DATA
```

## MVP Boundaries

This skill implements state, interaction protocols, feedback traces, and scheduler prompts. It does not by itself:

- provision or authenticate a Telegram gateway;
- change Hermes core memory providers;
- train or fine-tune an LLM;
- provide encrypted storage;
- turn lexical retrieval into embeddings;
- run continuously without Hermes cron/gateway being configured.

Describe these boundaries accurately when the user asks what is enabled.
