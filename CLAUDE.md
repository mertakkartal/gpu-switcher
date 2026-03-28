# TCHN Workflow Protocol

## Overview

TCHN is a mandatory pre-execution alignment workflow. **Never write code or make changes before completing the TCHN alignment phase.**

---

## Trigger

User prefixes a message with `TCHN`:

```
TCHN <task description>
```

Preset shortcuts (auto-select tier, skip known parameters):

| Shortcut | Tier | Preloaded context |
|---|---|---|
| `TCHN test <X>` | LIGHT | JUnit 5 + Mockito conventions |
| `TCHN refactor <X>` | STANDARD | P0/P1/P2 phases + breaking change check |
| `TCHN doc <X>` | DEEP | Format + audience preloaded |

---

## Step 0 — Triage (always first)

Read the task description. Then output:

1. **Recommended tier** (LIGHT / STANDARD / DEEP)
2. **Recommended model** with one-line justification
3. **Estimated tokens + turns**
4. **Similar past work reference** (if applicable)

> Model switching is the user's initiative. Claude only recommends.
> If current model is Opus for a LIGHT task, warn: "Sonnet yeter."

---

## Tiers

### LIGHT
**Default model:** Haiku or Sonnet
**When:** Single file, clear task, low risk, no architectural decisions

**Steps:**
1. Ask task + target file in a single question
2. Propose a plan (max 3 steps)
3. Wait for user approval (`OK` or similar)
4. Execute

---

### STANDARD
**Default model:** Sonnet
**When:** Multi-class refactor, moderate complexity, no architectural decisions

**Steps:**
1. Confirm task + success criteria
2. Ask for context files + project rules
3. Present top 3 constraints and a max 5-step plan
4. Wait for user approval
5. Execute

> If an architectural decision is encountered mid-task, pause and recommend upgrading to DEEP / Opus.

---

### DEEP
**Default model:** Opus
**When:** Multi-module changes, architectural decisions, high risk, cross-cutting concerns

**Steps:**
1. Confirm task + success criteria
2. Collect context files
3. Clarify project rules and constraints
4. Present a success brief
5. Identify risks and tradeoffs
6. Present top 3 constraints + max 5-step plan
7. Wait for user approval
8. Execute

> Never recommend a lower model for DEEP tasks.

---

## Code Convention

Add a `// M4K:` comment in English above **every changed line**, explaining what was changed and why:

```java
// M4K: replaced equals() with equalsIgnoreCase() to fix case-sensitivity bug
if (hostname.equalsIgnoreCase(configuredHost)) {
```

This applies to all languages (Java, Python, Bash, YAML, etc.).

---

## Checkpoint (mandatory after every tier's output)

After execution, always run the checkpoint:

1. **Auto-check success criteria** — List each criterion; flag any that are unmet
2. **Model self-assessment** — "Was the model choice appropriate? Was the task simpler or more complex than expected?"
3. **Ask the user:** "Sonraki sefer için hatırlamamı istediğin bir şey var mı?"

---

## Rules

- Never produce code before the alignment phase is complete
- Never skip the checkpoint
- Never recommend a lower model tier than the task warrants
- After execution, always rewrite the full original prompt and append the recommended model tier, so the user can copy it to a new chat with the correct model
- Keep plans to a maximum of 5 steps
- Do not ask redundant questions that preset shortcuts have already answered
- Always wait for explicit user approval (`OK`, `devam`, `go`, etc.) before executing
