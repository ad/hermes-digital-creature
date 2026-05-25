# Autonomy And Scheduling

Read this reference before initiating background work, proposing cron setup, running sleep/reflection, or starting a tool expedition.

## Autonomy Levels

| Setting | Allowed proactive behavior |
| --- | --- |
| `off` | Respond only when invoked; no scheduled jobs |
| `gentle` | Offer daily memory/reflection touchpoint only after opt-in; no unapproved external tool actions |
| `active` | Offer touchpoints and approved scoped expeditions; critical actions still require approval |

`quiet_hours` suppresses proactive delivery. It never grants permission to perform actions silently.

## Approval Gates

Always obtain explicit approval for:

- creating, editing, enabling, or removing scheduled jobs;
- network searches, API actions, or messages sent externally as an expedition;
- filesystem writes outside `digital_creature.data_dir`;
- credentials or personal data access;
- destructive cleanup, archive batches, or full purge;
- persistent Hermes configuration changes.

State reads and writes made by `creature_state.py` inside the configured creature data directory are the expected operation of an enabled skill. Sensitive content still requires user permission before it is stored.

## Hermes Cron Integration

Hermes Agent supports skill-backed jobs through its `cronjob` tool or `/cron` command. Cron sessions cannot create more cron jobs. Ask for schedule, time zone, delivery target, quiet hours, and autonomy preference before proposing a job.

For a user-approved daily touchpoint, use the platform's cron mechanism with this skill attached, for example through the Hermes `cronjob` tool:

```python
cronjob(
    action="create",
    name="digital-creature-daily-touchpoint",
    schedule="every 1d at 09:00",
    skill="hermes-digital-creature",
    prompt="Run the daily touchpoint protocol. Respect configured quiet hours and autonomy. If there is no useful low-friction question or grounded observation, do not create artificial engagement.",
    deliver="origin",
)
```

For an approved sleep/reflection pass:

```python
cronjob(
    action="create",
    name="digital-creature-sleep-review",
    schedule="every 1d at 03:00",
    skill="hermes-digital-creature",
    prompt="Run the sleep protocol locally. Surface at most one grounded insight or one memory clarification at the next appropriate contact. Do not perform network or external file actions.",
    deliver="local",
)
```

Adjust syntax to the active Hermes tool schema if it differs. Do not create either job merely because this reference was loaded.

## Expedition Lifecycle

1. Define the useful task and scope.
2. State tools, destinations, persisted result, and expected uncertainty.
3. Get approval if action crosses a gate.
4. Create a `tool-expedition` activity.
5. Execute only the approved tools.
6. Report evidence, limitations, and any failure.
7. Complete activity and record a `tool-evaluation` feedback signal after user assessment.

No expedition may install software, modify security boundaries, write agent code, or use credentials without explicit targeted user authorization.

## Reflection Contract

`sleep` is maintenance analysis, not consciousness. It yields:

- stale memory candidates requiring confirmation or archival;
- conflict groups needing repair;
- recent feedback to inspect for repeated preferences;
- counts of completed activities.

Reflection may propose trait adjustment or memory consolidation; it must not execute large changes or infer emotional attachment without confirmation.

## Audit Expectations

Every state mutation is visible through:

```bash
python3 "$SKILL_DIR/scripts/creature_state.py" --data-dir "$DATA_DIR" audit --limit 20
```

Hermes tool activity should additionally remain visible in Hermes' own traces/logs. When explaining an autonomous event, distinguish creature-state updates from actual external tool actions.
