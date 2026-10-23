---
id: 0000
title: <short title>
mode: implement          # implement | inner-loop | prototype
spec: specs/0000-<slug>.md   # or "none" for a direct implement or a prototype
branch: <branch>
status: in-progress      # in-progress | in-review | done | abandoned
created: YYYY-MM-DD
---

<!-- Experiment template. Tweak it per project; dev-loop always follows the repo's copy.
     One file per work item: what was done, how it was reviewed, and what was decided. -->

## Goal
<!-- With a spec: "See spec" plus one line.
     Direct implement: the goal block Rohit approved (goal, done criteria, don't touch).
     Prototype: the question being answered. -->

## Plan
<!-- A few lines: the approach and the order of work. -->

## Log
<!-- implement: what changed (modules, not line-by-line) and the check result.
     inner-loop: one row per iteration, starting with the baseline.
     prototype: each attempt and what it showed. -->

| # | Hypothesis / attempt | Change | Result | Kept? |
|---|---|---|---|---|
| 0 | baseline | — | <metric> | — |

## Result
<!-- Final state: criteria met or not, final numbers (dev and held-out), and why it stopped. -->

## Review
<!-- Filled in by review. -->
### Check gate
### Phase 1 — black-box
### Phase 2 — code
### Verdict

## Outcome
<!-- Filled in by human-brief: the decision, the date, final numbers, and a link to the merge or PR. -->
