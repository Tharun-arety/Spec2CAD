# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

The primary users are mechanical engineers and technically capable product teams
who need to turn incomplete requirements, sketches, images, datasheets, and
written instructions into editable parametric CAD without surrendering
engineering authority to a language model.

## Product Purpose

Spec2CAD converts heterogeneous engineering evidence into explicit engineering
intent, compiles that intent into a backend-neutral parametric feature plan,
builds deterministic CAD through real kernels, and measures the result before
release. Success is not merely producing a plausible solid. Success is producing
a traceable model whose interpretation, parameters, build state, measurements,
and release decision can be inspected and corrected.

## Positioning

Spec2CAD is an evidence-based, intent-based AI plus CAD system. The model may
interpret source material and propose engineering meaning, but it does not emit
arbitrary executable CAD or become the authority for geometry. The Engineering
Intent Graph remains authoritative, Feature IR provides a closed deterministic
realization plan, CAD State Graphs record what each backend actually built, and
only measured governing evidence may authorize release.

When generated CAD is wrong, the system should expose where source evidence was
misread or intent was interpreted incorrectly. A user can correct the intent or
its parameters, rebuild deterministically, compare revisions, and retain that
correction as evidence for later model improvement.

## Operating Context

Users begin with text, sketches, images, PDFs, or recorded examples. They inspect
the extracted evidence and engineering intent, review the parametric feature
plan, observe builds from CadQuery and FreeCAD, reconcile measured geometry and
native state, resolve conflicts or missing information, and export STEP only
after the release gate is satisfied. Public users can choose a restricted hosted
demo or supply an ephemeral OpenAI or compatible API connection.

## Capabilities and Constraints

- Engineering Intent Graph owns engineering meaning and provenance.
- Feature IR is backend-neutral, declarative, typed, and non-executable.
- CAD State Graph is immutable observed backend state, never design authority.
- CadQuery and FreeCAD are the proven backend pair for the current release scope.
- Measured governing evidence, not model confidence or visual plausibility,
  determines release.
- Unsupported geometry and incomplete evidence fail as typed refusals or explicit
  clarification requests.
- Caller-owned credentials remain request-scoped and ephemeral.
- The current public service has bounded admission and must fail predictably when
  saturated.
- The product must not imply universal CAD support, autonomous engineering
  authority, or guaranteed correctness beyond its measured evidence.

## Brand Commitments

The product name is Spec2CAD. Its voice is precise, direct, and technically
honest. It should feel like a serious engineering instrument, not a conventional
CAD clone, a text-to-3D novelty, or an opaque AI assistant. Visual distinction
must come from the product's proof architecture and correction loop rather than
generic sci-fi, blueprint wallpaper, or ambient AI effects.

## Evidence on Hand

The repository contains working UI flows, recorded workflows, capability
registry data, deterministic evaluation reports, dual-backend benchmark results,
typed evidence and release states, real CAD artifacts, and tests for error,
clarification, reconciliation, revision, and release behavior. Commercial proof,
customer logos, testimonials, pricing, and adoption metrics are not present and
must not be fabricated.

## Product Principles

- Show the interpretation before asking the user to trust the geometry.
- Keep human-authored intent visibly distinct from model inference and measured fact.
- Make every error localizable to evidence, intent, compilation, build, or measurement.
- Preserve corrections as traceable revisions that can improve later interpretation.
- Earn release through measured agreement across the declared evidence boundary.

## Accessibility & Inclusion

All critical state must remain available without color, hover, animation, or a
3D-capable browser. Keyboard navigation, readable contrast, reduced motion, and
explicit text labels are required. Visual inspection remains advisory unless it
has been benchmarked and promoted to governing evidence.
