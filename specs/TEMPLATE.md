---
id: 0000
title: <short title>
status: draft            # draft | approved | in-progress | in-review | done | abandoned
mode: implement          # implement | inner-loop
branch: spec/0000-<slug>
created: YYYY-MM-DD
---

<!-- Spec template. Tweak it per project; dev-loop always follows the repo's copy.
     Every section is answered from a grill-me decision. Write "None" when a section
     is truly empty. Keep the whole spec short enough to approve in two minutes. -->

## Goal
<!-- 1–2 sentences: the problem and the outcome, from the user's side. -->

## Context
<!-- Pointers only: related notes/research or notes/brainstorm files, and the modules involved. -->

## Acceptance criteria
<!-- Numbered. Each one is independently checkable and says how it's verified.
     Review writes black-box tests from these, so describe behaviour at the
     interfaces, not implementation. -->
- AC1 — <behaviour> — verified by: <test at an interface | smoke command | eval command>
- AC2 — <behaviour> — verified by: <...>

## Setpoint
<!-- Required when mode is inner-loop. Delete this section for implement. -->
- Metric: <name and definition>
- Command: `<exact command that prints the metric>`
- Dev subset (the loop optimises on this): <...>
- Held-out set (reported at the end, never optimised on): <...>
- Baseline: <number and how it was measured>
- Target: <number>
- Budget: <max iterations> iterations · <max wall-clock>
- Long runs proposed to Rohit, not run in the loop: <e.g. full training>

## Interfaces
<!-- The public seams that tests target, and what must not change:
     function signatures, CLI flags, SDK API, file formats, tensor shapes. -->

## Edge cases
<!-- Inputs and situations the change must survive, e.g. empty input, corrupt
     file, no face, several faces, extreme pose, occlusion, IR/low light,
     dropped frames, NaN. -->

## Decisions
<!-- Each grill-me decision with its one-line reason. -->

## Out of scope

## Don't touch
<!-- Files, data, splits, thresholds and tests that are read-only for this work. -->

## Risks
<!-- What could go wrong, and the early warning sign. -->
