# Autonomy And Scheduling

Read this reference before initiating background work, reconciling scheduled jobs, running
sleep/reflection, or starting a tool expedition.

## Prerequisite

Hermes cron is **required** when autonomy is `gentle` or `active`. The skill verifies availability
during first contact and on every autonomy change. If `hermes cron list` fails to run, treat autonomy
as `off` for this environment, tell the user once, and do not pretend tasks were scheduled.

## Autonomy Levels And Default Schedule

| Setting | Tasks registered automatically | Other allowed proactive behavior |
| --- | --- | --- |
| `off` | none | only responds when invoked |
| `gentle` | daily touchpoint at `digital_creature.touchpoint_time` (default `09:00`) | none beyond that single task |
| `active` | daily touchpoint + nightly sleep review (default `21:00`) + weekly progress summary (default Sun `19:00`) | may propose scoped tool expeditions during a touchpoint; expedition itself still requires per-action approval |

The autonomy setting itself **is** the consent for the task set above. Time and weekday defaults can be
overridden through skill config (`touchpoint_time`, `sleep_time`, `progress_time`, `progress_day`).

`quiet_hours` suppresses delivery during the configured window. A suppressed run defers to the next
allowed contact; it does not silently perform actions. `daily` and `sleep` emit a `suppression` block —
respect it before delivering anything.

Each proactive run operates on **native memory** (injected `MEMORY.md`/`USER.md`, `session_search`, and
any configured provider). The runs do not read or write a separate creature store.

## Approval Gates (Unchanged)

Even at `active`, always obtain explicit per-action approval for:

- creating, editing, or removing **non-default** scheduled jobs (anything outside `proactive-plan`);
- network searches, API actions, messages sent externally as part of an expedition;
- filesystem writes outside `digital_creature.data_dir`;
- credentials or personal data access;
- destructive cleanup or full purge;
- persistent Hermes configuration changes beyond the proactive task set.

Reads and writes made by `creature_state.py` inside the configured data directory are the expected
operation of an enabled skill. Writing user facts into native memory follows the usual memory rules:
sensitive content still requires user permission before it is stored.

## First-Contact Registration Flow

On `/hermes-digital-creature start`:

1. `proactive-diff --autonomy <level>` — returns three lists: `to_register`, `to_update`, `to_revoke`.
2. For each `to_register` and `to_update` item: ask the Hermes cron tool to create the job using the
   provided `schedule`, `skill`, `prompt`, and `deliver` fields verbatim, then record:

   ```bash
   creature_state.py proactive-register \
     --task-id <id> --schedule <expr> --autonomy <level> \
     --prompt <prompt> --deliver <deliver> --description <desc>
   ```

3. For each `to_revoke`: remove the cron job via Hermes, then record
   `proactive-revoke --task-id <id> --reason autonomy-change`.
4. Summarize result in one line to the user.

If the cron tool call fails, **do not** call `proactive-register`. Report the gap and leave the diff
item pending.

## Autonomy Change Mid-Session

Same as first contact: rerun `proactive-diff` against the new level, apply each delta through Hermes
cron + the matching `proactive-*` record. Confirm in one line.

- `off → gentle/active`: registers missing tasks.
- `gentle ↔ active`: registers/revokes the differing tasks.
- `gentle/active → off`: revokes everything.

## Disabling Proactive From Chat

Recognize these intents and treat as `autonomy = off` for this session and persisted: "отключи
проактивность", "не пиши сам", "хватит писать", "stop proactive", "turn off check-ins". Run the
downgrade flow (revoke every registered task via cron + `proactive-revoke`), optionally note the
preference in `USER.md` via the memory tool, and confirm in one line.

## Proactive Task Schema

`proactive_tasks` is the source of truth for what Hermes cron should have scheduled on behalf of this
skill.

| Column | Meaning |
| --- | --- |
| `task_id` | stable identifier; matches the cron job name in Hermes |
| `schedule` | human cron expression as understood by the active Hermes cron tool |
| `autonomy` | the autonomy level at which the task was registered |
| `prompt` | prompt fired at tick time |
| `deliver` | delivery target (e.g. `origin`, `local`) |
| `status` | `registered` or `revoked` |
| `registered_at` / `revoked_at` | timestamps |
| `consent_source` | usually `autonomy:<level>`; user-specific additions use `user:<intent>` |

Revoked rows are kept for audit and never deleted by the runtime.

## Expedition Lifecycle

1. Define the useful task and scope.
2. State tools, destinations, persisted result, and expected uncertainty.
3. Get approval if the action crosses a gate.
4. Execute only the approved tools.
5. Report evidence, limitations, and any failure.
6. If a reusable, non-sensitive lesson came out of it, write one procedural memory to `MEMORY.md`.

No expedition may install software, modify security boundaries, write agent code, or use credentials
without explicit targeted user authorization.

## Reflection Contract

`sleep` is maintenance analysis, not consciousness. Its runtime output is the `suppression` decision
plus guidance; the actual review is performed by Hermes over **native memory**:

- stale durable entries in `MEMORY.md`/`USER.md` that may need confirmation or removal;
- redundant or conflicting durable entries to consolidate;
- recurring preferences observed across recent sessions (via `session_search`).

Reflection may propose a persona tweak or memory consolidation; it must not execute large changes or
infer emotional attachment without confirmation, and must not perform network or external file actions.

## Audit Expectations

Scheduling/settings mutations — including `proactive-register` and `proactive-revoke` — are visible
through:

```bash
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" audit --limit 20
```

Memory changes are visible through Hermes' own memory view/audit, since memory lives in native storage.
Hermes tool activity should remain visible in Hermes' own traces/logs. When explaining an autonomous
event, distinguish skill scheduling updates, native-memory edits, and actual external tool actions.
