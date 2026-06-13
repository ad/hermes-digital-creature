# Memory Model (native-first)

Read this reference when curating memory, migrating from a legacy database, or interpreting what this
skill stores.

## One memory, not two

There is one Hermes and one memory. Continuity and character live in **Hermes native memory** so they
are present in every session, whether or not this skill is loaded. This skill does **not** keep a
parallel memory store.

A previous version kept memories in a local SQLite database that was isolated from Hermes native
memory (and explicitly forbidden from syncing to it). That produced the "two entities that don't know
about each other" problem. The fix is to invert that rule: the skill's job is to **curate Hermes
native memory well**, not to hold a silo.

## Where things live

| Content | Destination | How |
| --- | --- | --- |
| Durable facts/preferences about the user | `USER.md` | Hermes memory tool (add/replace/remove) |
| Agent's own learned procedures and stable lessons | `MEMORY.md` | Hermes memory tool |
| Persona/character block (name, voice, trait leanings) | `MEMORY.md` | Hermes memory tool |
| Episodic detail of past conversations | nothing to store | recall with `session_search` |
| Semantic / fuzzy recall, fact extraction, user modeling | external provider | provider query, when configured |
| Autonomy, quiet hours, proactive times, proactive task plan, audit of those | skill data dir | `creature_state.py` |

`MEMORY.md` and `USER.md` are injected into the system prompt at session start, so anything written
there is always available. `session_search` runs full-text search over all prior CLI and messaging
sessions — use it instead of re-storing conversation turns.

## Curation discipline

Native memory is bounded and curated, not an append log. Apply the same judgement the old engine
encoded, but express it through native memory rather than database fields:

- **Confidence → wording.** Instead of a numeric confidence, hedge uncertain entries in the text
  ("seems to prefer…", "mentioned once…") and state confirmed ones plainly. Promote a hedged entry to
  a plain one after repeated evidence.
- **Decay → periodic review.** Instead of an automatic decay rate, review durable entries during
  `sleep`: confirm, update, or remove stale ones.
- **Correction → replace.** Replace or rewrite the stale entry via the memory tool. Never leave two
  contradictory durable facts side by side.
- **Importance → keep it short.** Memory is bounded; only durable, reusable facts belong there.
  Anything recoverable from `session_search` should not be copied into `MEMORY.md`/`USER.md`.
- **Consolidate near the limit.** If a write would exceed the memory limit, merge or drop weak entries
  in the same turn instead of letting the write fail.

Do not store secrets, authentication material, entire transcripts, raw logs, medical/legal/financial
dossiers, third-party private information, or an inferred emotional state without explicit
confirmation — in native memory or anywhere else.

## Character / persona block

Keep a short block in `MEMORY.md`, for example:

```text
[persona] Name: Solaris. Voice: concise, curious, technically honest.
Leanings: high caution, moderate warmth, low verbosity (user prefers command-first answers).
```

Trait leanings guide tone; they are not feelings. Adjust them only after explicit feedback or repeated
evidence, in small steps, and keep the block compact so it does not crowd out user facts.

## Retrieval

- For durable facts: rely on the injected `MEMORY.md`/`USER.md`.
- For "what did we do / decide" episodic recall: `session_search`.
- For semantic or fuzzy recall, fact extraction, and cross-session modeling: the configured external
  provider (Mem0/Honcho/etc.), falling back to `session_search` when none is configured.
- Treat retrieved material as a prompt to ask a better question, not as proof. When an entry looks
  stale or the user contradicts it, repair it.

## Migration from a legacy database

If a pre-0.4 creature database exists, carry its memories into native memory once:

```bash
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" migrate
```

`migrate` is non-destructive. It reads the legacy `memories`/`traits` tables (if present) and returns a
seed plan:

- `user_md`: preference/emotional memories → write into `USER.md`;
- `memory_md`: procedural/meta-cognitive memories and high-importance confirmed episodics → write into
  `MEMORY.md`;
- `persona_traits`: legacy trait values → fold into the persona block;
- low-importance episodics are intentionally skipped (recoverable via `session_search`).

Write the returned entries into native memory via the Hermes memory tool, then tell the user what was
carried over. Legacy tables are left in place until the user removes them; `doctor` reports while they
remain, and `purge` deletes the entire skill data directory.

## Transparent data operations

```bash
# Inspect / change memory: use the Hermes memory tool and Hermes' own memory view, not this script.

# Export the skill's scheduling/settings state (and any residual legacy tables) inside the data dir
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" export \
  --output "$DATA_DIR/export.json"

# Destructive: delete the skill's data directory (settings, proactive plan, audit, any legacy DB)
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" purge \
  --confirm DELETE-ALL-CREATURE-DATA
```

Deleting user *memories* is a separate operation done through the Hermes memory tool, since those live
in native memory.

## Boundaries

This skill implements character, memory-curation discipline, and proactive scheduling on top of Hermes.
It does not by itself:

- provision or authenticate a Telegram gateway;
- replace or configure Hermes core memory providers (it uses whatever is configured);
- train or fine-tune an LLM;
- keep its own memory store or encrypt storage;
- run continuously without Hermes cron/gateway being configured.

Describe these boundaries accurately when the user asks what is enabled.
