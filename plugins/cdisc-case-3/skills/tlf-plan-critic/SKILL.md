---
name: tlf-plan-critic
description: "Independently audit a TLF plan (produced by the tlf-planner skill) for traceability and completeness before human review. Use this skill after tlf-planner, or whenever the user asks to 'audit/review/QC the TLF plan', 'check TLF coverage', 'verify every endpoint has a table', 'find missing or orphan TLFs', or 'run the coverage/traceability check'. It performs a two-way audit — forward (every objective and every resolved endpoint maps to at least one planned TLF) and backward (every TLF traces to an objective/endpoint or a regulatory rule) — plus conventional-completeness heuristics, then emits a coverage report with a verdict and, on gaps, a bounded re-run plan. It reads only the plan and the study model, never the planner's reasoning, so the check is genuinely independent."
---

# TLF Plan Critic

## Purpose

Adversarially verify a TLF plan **with fresh eyes**. The `tlf-planner` skill generates the plan;
this skill audits it. Keeping generation and criticism in separate skills/contexts is the point —
a critic that never saw the generation reasoning catches gaps the generator rationalized away.
This runs between `tlf-planner` and the human review gate:

```
USDM JSON ──▶ tlf-planner ──▶ [tlf-plan-critic] ──▶ HUMAN REVIEW ──▶ ARD datasets ──▶ {cards}/{cardx} TLFs
```

## When to use

- Immediately after `tlf-planner` produces `tlf-plan.json` + `tlf-index.md`.
- When the user wants to QC, review, or sanity-check a TLF inventory for coverage/completeness.
- To decide whether the plan is ready for human review or needs the planner re-run.

## Inputs

Read **only** these two files (deliberately not the planner's intermediate reasoning):

- `outputs/{study-folder}/tlf-plan/tlf-plan.json` — the final numbered candidates
- `outputs/{study-folder}/tlf-plan/study-model.json` — objectives/endpoints to audit against

## Output

Write `outputs/{study-folder}/tlf-plan/coverage-report.md` containing: a coverage matrix
(objective → endpoints → TLF ids, each marked covered / gap / clarification), an orphan list,
completeness recommendations, clarification action items, counts, a final **verdict**
(`clean` / `clean-with-caveats` / `gaps-found`), and — if gaps — a bounded re-run plan naming
what `tlf-planner` phase should re-run (max ~2 rounds).

## Workflow

Read `references/audit-checklist.md` first, then:

1. **Forward coverage** — for every objective and every `resolved:true` endpoint in
   `study-model.json`, confirm ≥1 `planned` TLF in `tlf-plan.json` traces to it. A resolved
   endpoint with no TLF is a **GAP**. An **unresolved** endpoint (`resolved:false`, e.g.
   END9/10/11) is a **clarification ACTION ITEM** — never a gap, never a silent drop.
2. **Backward orphan check** — every TLF must trace to an objective/endpoint **or** a
   `regulatory_rule`. Empty `objective_ids` is valid only when `regulatory_rule` is set (the
   scaffolding tables). A candidate with neither is an **orphan** error. Also flag dangling ids.
3. **Completeness heuristics** — apply the conventional checks in the checklist (e.g. safety
   objective present but no deaths table? primary continuous endpoint but no sensitivity/MMRM?
   multi-site but no by-site table? lab data but no Hy's-Law?). Surface as recommendations.
4. **Verdict & routing** — summarize counts, choose the verdict, and if gaps exist name the
   `tlf-planner` phase(s) to re-run using the checklist's routing table. This skill is
   **read-only**: it routes and reports, it never edits the plan.

## Expected CDISCPILOT01 result

`clean-with-caveats`: full forward coverage of END1–END8, zero orphans (the 6 scaffolding tables
are valid via `regulatory_rule`), zero gaps, and 3 open clarification items (END9/END10/END11).

## Reference files

- `references/audit-checklist.md` — the forward/backward/completeness rule lists, unresolved-vs-gap-vs-orphan handling, and the phase-routing table. References the shared schemas at `../../tlf-planner/references/`.
