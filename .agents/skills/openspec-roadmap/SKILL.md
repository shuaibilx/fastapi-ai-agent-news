---
name: openspec-roadmap
description: Plan or reconcile a project-level roadmap across multiple independently deliverable OpenSpec changes. Use before explore for broad initiatives, for roadmap/status requests, or after archives to reconcile progress. Do not use for a single cohesive change.
allowed-tools: Bash(openspec:*)
license: MIT
compatibility: Requires openspec CLI.
metadata:
  author: shuaibilx
  version: "1.0"
  generatedBy: "1.10.0"
---

Plan or reconcile a project-level roadmap across multiple OpenSpec changes.

**IMPORTANT: Roadmap mode is for portfolio-level planning, not implementation and not detailed change planning.** You may inspect the codebase and OpenSpec state. You may create or update the one roadmap file after the user confirms the proposed decomposition. You must not implement application code, scaffold all future changes, or create proposal/design/spec/tasks artifacts for an individual change.

The roadmap is navigation across changes. It is not a second `design.md` or `tasks.md`.

**Store selection:** If the user names a store (a store is a standalone OpenSpec repo registered on this machine) or the work lives in one, run `openspec store list --json` to discover registered store ids, then pass `--store <id>` on the commands that read or write specs and changes (`new change`, `status`, `instructions`, `list`, `show`, `validate`, `archive`, `doctor`, `context`, `schemas`, `view`). Once selected, treat `--store <id>` as sticky for the rest of the workflow. Every unscoped example of those commands below is shorthand: before running it, append the flag. For example, run `openspec status --change "<name>" --json --store "<id>"`, not the unscoped form shown below. Other commands do not take the flag. Hints printed by commands already carry the flag; keep it on follow-ups. Without a store, commands act on the nearest local `openspec/` root.

**Input**: The argument after `$openspec-roadmap (Codex) or /openspec-roadmap (other agents)` is the broad initiative to plan, an existing roadmap to reconcile, or a roadmap/status question. Examples:
- "Add AI capabilities to this news application"
- "Split this platform migration into safe changes"
- "Reconcile the roadmap after archiving add-search"
- Nothing, when the current conversation already identifies the initiative

A status-only request is read-only: report the evidence-backed state and discrepancies without editing files. Do not ask for write confirmation unless the user also wants the roadmap reconciled.

---

## 1. Resolve Reality First

Run:

```bash
openspec list --json
```

Use the returned `root.path` as the project root. Read only the material relevant to the initiative:

- `<root.path>/openspec/config.yaml` or `config.yml`, when present;
- `<root.path>/openspec/roadmap.md`, when present;
- relevant main specs under `<root.path>/openspec/specs/`;
- active change artifacts under `<root.path>/openspec/changes/`;
- relevant archives under `<root.path>/openspec/changes/archive/`;
- relevant application code, tests, and architecture documentation.

For every relevant active change, run `openspec status --change "<name>" --json` and read the artifact paths it returns. Do not treat filenames, an old roadmap, or remembered conversation state as authoritative when current OpenSpec state is available.

Apply project `context` as constraints. Apply an artifact rule only when writing the artifact it names; roadmap.md has no implicit artifact rule. Never copy configuration guidance verbatim into the roadmap.

---

## 2. Reconcile an Existing Roadmap

Before proposing new phases, compare every roadmap change ID with active and archived state.

Match an archive named `YYYY-MM-DD-<change-id>` to the exact `<change-id>` after removing one leading date prefix. Do not use substring matching.

Classify each phase from evidence:

- **Complete**: the matching change is archived and its archived task checklist has no unchecked tasks (or it has no task artifact).
- **Active**: a matching active change exists. It remains incomplete even when all tasks are checked, because it has not been archived.
- **Discrepant**: an archive exists but still contains unchecked tasks, duplicate active/archive matches exist, or recorded dependencies conflict with reality.
- **Planned**: no active or archived matching change exists.

If recorded and actual state differ, show the recorded state, evidence, and proposed correction. Ask before changing the roadmap. Never mark work complete from code presence or chat claims alone.

---

## 3. Choose the Right Planning Scale

First classify the request.

### Single Change

Use **Single Change** when the work has one cohesive business outcome, one reasonably bounded design, and one independently verifiable delivery.

In that case:

- do not create a roadmap only to hold one item;
- recommend one concise, action-oriented kebab-case change ID;
- hand off to `$openspec-explore (Codex) or /openspec-explore (other agents)` when material decisions remain, or `$openspec-propose (Codex) or /openspec-propose (other agents)` when the scope is already clear;
- do not create the change unless the user separately asks for that workflow.

### Multi-Phase Initiative

Use **Multi-Phase Initiative** when multiple capabilities can be delivered, verified, prioritized, or archived independently, or when one change would be too broad to review safely.

Split vertically by user or business outcome:

```text
one phase = one independently valuable OpenSpec change
```

Do not mechanically split into database, backend, and frontend phases unless a technical phase is itself independently useful. Avoid both giant changes and tiny changes that have no meaningful outcome on their own.

Order phases by real dependency. Prefer an early end-to-end slice that retires important uncertainty. Treat shared infrastructure as part of the first capability that needs it unless the infrastructure has a separately verifiable consumer and outcome.

For each phase define only:

- a stable phase name;
- a unique action-oriented kebab-case change ID;
- one-sentence outcome;
- explicit boundary, especially what is deferred;
- dependencies by change ID, using `None` when there are none;
- a short verification signal describing how completion will be recognized.

Do not estimate dates or effort unless the user asks. Do not pre-design later phases: each phase begins with a fresh `$openspec-explore (Codex) or /openspec-explore (other agents)` against the code and specs that exist then.

---

## 4. Present Before Writing

Present:

1. the initiative goal and current system/OpenSpec state;
2. material constraints, assumptions, and unresolved decisions;
3. the classification: **Single Change** or **Multi-Phase Initiative**;
4. the recommended direction and important trade-offs;
5. for a multi-phase initiative, a compact table containing change ID, outcome, boundary, dependencies, and verification signal;
6. any mismatch between an existing roadmap and actual OpenSpec state.

Ask the user to confirm the decomposition before creating or updating `openspec/roadmap.md`. Do not scaffold the listed changes during this workflow.

---

## 5. Write the Confirmed Roadmap

After confirmation, create or minimally update `<root.path>/openspec/roadmap.md`:

```markdown
# Project Roadmap

> Cross-change navigation for this OpenSpec project. Detailed requirements,
> designs, and tasks remain inside each change.

## Initiative

- **Goal:** <overall user or business outcome>
- **Success:** <observable initiative-level result>
- **Non-goals:** <important exclusions, or None>

## Progress

- **Current Phase:** Phase 1 — AI News Summary
- **Next Change:** `add-ai-news-summary`
- **Completed:** 0 / 3

## Phases

### Phase 1 — AI News Summary

- [ ] `add-ai-news-summary`
- **Outcome:** Users can request a concise AI summary for one article.
- **Boundary:** Single-article summaries only; no semantic retrieval or chat.
- **Depends on:** None.
- **Verify:** A summary request returns a validated result and handles provider failure.

### Phase 2 — Semantic News Retrieval

- [ ] `add-news-semantic-retrieval`
- **Outcome:** Users can find relevant articles by semantic similarity.
- **Boundary:** Indexing and retrieval only; no generated answers.
- **Depends on:** `add-ai-news-summary`.
- **Verify:** A natural-language query returns ranked relevant articles.

## Cross-Cutting Constraints

- <Only constraints that genuinely affect multiple phases; omit this section otherwise.>
```

Keep the roadmap concise. Exclude endpoints, database fields, class/function designs, detailed acceptance criteria, and per-change implementation checklists. Preserve user-authored notes that remain accurate. Make the smallest edit needed for reconciliation rather than rewriting the whole file.

---

## 6. Maintain Progress Correctly

- `[x]` means the exact matching change is archived and its archived task checklist is complete.
- `[ ]` means planned, active, blocked, implemented-but-not-archived, discrepant, or archived with unchecked tasks.
- `Current Phase` is an active phase when one exists; otherwise it is the first incomplete phase whose dependencies are complete.
- `Next Change` is the change ID for Current Phase, or `None` when every phase is complete.
- `Completed` must equal the number of `[x]` phase entries.
- Multiple phases may be active only when their dependencies permit it and the user explicitly chose parallel delivery.

When invoked after an archive or before starting another phase, reconcile these values from actual OpenSpec state. This skill does not run automatically when another workflow finishes.

---

## Handoff

After writing or reconciling the roadmap:

- report completed count, current phase, and next change ID;
- recommend a fresh `$openspec-explore (Codex) or /openspec-explore (other agents) <next-change-id>` for the next phase, or `$openspec-propose (Codex) or /openspec-propose (other agents) <next-change-id>` only when no material decisions remain;
- stop and wait for the user;
- never auto-start Explore, Propose, Apply, or Archive.

## Guardrails

- Do not implement application code.
- Do not create or edit proposal.md, design.md, delta specs, or tasks.md.
- Do not scaffold multiple future changes.
- Do not duplicate detailed requirements or tasks in roadmap.md.
- Do not mark a phase complete without archive and task evidence.
- Do not silently repair roadmap discrepancies; show evidence and ask first.
- Do not force a broad request into one giant change.
- Do not force a cohesive request into artificial phases.
- Do not modify existing OpenSpec workflow skills; Roadmap hands off to them.
