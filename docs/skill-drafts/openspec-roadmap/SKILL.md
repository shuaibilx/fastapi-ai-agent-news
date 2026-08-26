---
name: openspec-roadmap
description: Plan or reconcile a project-level OpenSpec roadmap across multiple independently deliverable changes. Use for broad initiatives that may need phased decomposition, roadmap/status requests, or progress reconciliation after changes are archived. Do not use for a single cohesive change or detailed implementation planning.
allowed-tools: Bash(openspec:*)
license: MIT
metadata:
  author: openspec
  version: "1.0"
---

# OpenSpec Roadmap

Plan a large initiative across multiple OpenSpec changes while keeping each change independently explorable, implementable, verifiable, and archivable.

## Boundary

This skill operates above individual changes.

- It MAY inspect the codebase and OpenSpec state.
- It MAY create or update `openspec/roadmap.md` after the user confirms the proposed phase structure.
- It MUST NOT implement application code.
- It MUST NOT create proposals, designs, delta specs, task files, or multiple change scaffolds.
- It MUST NOT replace the artifacts or lifecycle of an individual OpenSpec change.

The roadmap is navigation, not a second `design.md` or `tasks.md`.

## Resolve the Current Project State

Run `openspec list --json` first and use its resolved `root.path`. When a registered store is explicitly selected, preserve the corresponding `--store` flag on supported OpenSpec commands.

Read, when present:

- `<root.path>/openspec/config.yaml` or `config.yml`;
- `<root.path>/openspec/roadmap.md`;
- relevant main specs under `openspec/specs/`;
- active change artifacts under `openspec/changes/`;
- relevant archived change artifacts under `openspec/changes/archive/`;
- the code and tests needed to understand the initiative's current architecture and constraints.

Inspect only relevant material. Do not treat an old roadmap as authoritative until it has been compared with actual active and archived changes.

## Reconcile an Existing Roadmap

Before planning new phases, compare roadmap entries with OpenSpec state.

- A phase is complete only when its matching change is archived and its archived task checklist has no incomplete tasks.
- An active change remains incomplete even if its implementation tasks appear finished.
- An archived change with incomplete tasks is a discrepancy, not a completed phase.
- A planned phase has no active or archived matching change yet.

If the roadmap and actual state disagree, report the recorded state, actual state, and proposed correction. Do not edit the roadmap until the user confirms the correction.

## Decide the Planning Scale

Classify the initiative after investigating the codebase and clarifying decisions that materially affect scope, architecture, phase boundaries, or sequencing.

### Single Change

Choose `Single Change` when the work has one cohesive business outcome, one reasonably sized design, and one independently verifiable delivery.

In this case:

- do not create a roadmap solely for this request;
- recommend one concise kebab-case change ID;
- hand off to `openspec-explore` or `openspec-propose` as appropriate;
- stop without creating the change unless the user separately requests it.

### Multi-Phase

Choose `Multi-Phase` when the initiative contains multiple business capabilities that can be delivered, verified, or prioritized independently, or when one change would become difficult to reason about or review.

Split vertically by business value:

`one phase = one independently valuable OpenSpec change`

Do not mechanically split into database, backend, and frontend phases unless a technical phase has independent delivery value. Avoid both giant changes and tiny changes that have no useful outcome on their own.

For every proposed phase, define only:

- phase name;
- action-oriented kebab-case change ID;
- one-sentence business outcome;
- main boundary;
- necessary dependencies.

Do not pre-create or pre-design later changes. Each phase starts with a fresh `openspec-explore` pass against the codebase state that exists at that time.

## Present the Recommendation

Summarize:

1. current system and relevant OpenSpec state;
2. material unresolved questions, if any;
3. recommended overall direction and important trade-offs;
4. the classification: `Single Change` or `Multi-Phase`;
5. for `Multi-Phase`, a compact phase table with Change ID, outcome, boundary, and dependencies;
6. any roadmap/OpenSpec state discrepancies.

Ask the user to confirm the proposed roadmap before writing or changing `openspec/roadmap.md`. Do not create all proposed changes during this workflow.

## Roadmap File

After confirmation, create or minimally update `<root.path>/openspec/roadmap.md` using this shape:

```markdown
# Project Roadmap

> Cross-change navigation for this OpenSpec project. Detailed requirements,
> designs, and tasks remain inside each change.

## Progress

- Current Phase: Phase 2 — Semantic Retrieval
- Next Change: `add-news-semantic-retrieval`
- Completed: 1 / 5

## Phases

### Phase 1 — AI News Summary

- [x] `add-ai-news-summary`
- **Outcome:** Users can request a cached AI summary for a news article.
- **Boundary:** Single-article summarization only; no retrieval or chat.
- **Depends on:** None.

### Phase 2 — Semantic Retrieval

- [ ] `add-news-semantic-retrieval`
- **Outcome:** Users can retrieve relevant news by semantic similarity.
- **Boundary:** Indexing and retrieval only; no answer generation.
- **Depends on:** Phase 1.
```

Keep the file short. Exclude implementation steps, API details, database fields, class/function designs, detailed acceptance criteria, and per-change task lists.

## Progress Rules

- `[ ]` means planned, active, blocked, implemented-but-not-archived, or archived with incomplete tasks.
- `[x]` means the corresponding change is archived and its archived task checklist is complete.
- `Current Phase` is the active phase when one exists; otherwise it is the first incomplete phase whose dependencies are complete.
- `Next Change` is the change ID for `Current Phase`, or `None` when all phases are complete.
- `Completed` must equal the number of `[x]` entries.
- Advance one dependency-ready phase at a time unless the user explicitly approves parallel work.

When invoked after an archive or before starting another phase, reconcile these fields against actual OpenSpec state. This skill does not run automatically after another skill finishes.

## Handoff

After creating or reconciling the roadmap:

- state the completed count, current phase, and next change ID;
- recommend a fresh `openspec-explore` invocation for the current phase;
- stop and wait for the user;
- never automatically start the next phase or create its proposal.
