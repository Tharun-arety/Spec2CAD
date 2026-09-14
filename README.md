# Spec2CAD — a multimodal design-intent compiler

**Live demo: https://spec2cad.vercel.app** — a recorded replay of a real run, and
labelled as such. Vercel cannot host the pipeline itself (the CadQuery bundle
measures 1165 MB against a 500 MB function limit), so the deployment replays
genuine frozen output rather than simulating it. Uploading documents and
applying an unrecorded resolution both refuse, with the reason. For live
generation run it locally or as a container — see `DEPLOYMENT.md`.

Takes any available combination of a hand sketch, component datasheet and
written requirement, and produces the traceable evidence and design intent that
the supplied sources support. Complete inputs continue through a parametric
feature plan, generated STEP model and validation report — and when the sources
are jointly impossible, the system says so instead of quietly building something.

The thesis is not "an LLM can write CadQuery." It is the separation that makes
generated geometry accountable:

```
evidence  ≠  design intent  ≠  CAD program  ≠  measured B-Rep  ≠  release authorisation
```

---

## The demonstration

One part: a NEMA-17 stepper **motor adapter plate**, with a contradiction that
is real rather than staged.

| Source | States | |
|---|---|---|
| Sketch | plate is 40 × 50 mm | read correctly |
| Datasheet (p.3) | 31 × 31 mm hole pattern, 4 × M3, ⌀22 boss | read correctly |
| Requirement | 5 mm aluminium, normal-clearance M3, **≥4 mm edge clearance**, 1 mm chamfers | read correctly |
| ISO 273 | M3 medium clearance → ⌀3.4 mm | cited, not guessed |

Every value is right. Together they are impossible:

```
edge clearance = (40 − 31)/2 − 3.4/2 = 2.8 mm      required: 4 mm
```

The system builds the candidate anyway — **so the violation can be measured on
real geometry rather than only predicted** — measures 2.8000 mm on the solid,
blocks the release, and explains itself:

> Release BLOCKED for DesignIntent v1. STEP export is withheld.
> measured only 2.8 mm between the nearest mounting-hole edge and the plate
> boundary, against a required 4 mm. The minimum feasible plate width is 42.4 mm.
>
> Responsible parameters: `plate_width`, `hole_spacing_x`, `mounting_hole_diameter`
> — every one read correctly. They are simply not jointly satisfiable, so this is
> a **constraint conflict**, not a misreading.

A human approves widening to 45 mm. That derives **DesignIntent v2** (v1 stays
intact and retrievable), regenerates, measures **5.3000 mm**, and authorises the
STEP — which is then re-imported and re-validated, so the *artifact* is proven,
not just the in-memory result.

---

## Quickstart

Everything below runs on `C:\Users\tharu\miniforge3\python.exe`, which already
has CadQuery. Elsewhere: `pip install -r requirements.txt`.

```bash
python examples/motor_adapter/generate_inputs.py     # seeded, byte-identical
python -m spec2cad.cli examples/motor_adapter        # v1: blocked, exit 1
python -m spec2cad.cli examples/motor_adapter --approve widen_to_recommended
python -m pytest                                     # 50 tests
python -m eval.run_eval                              # 32 deterministic checks
```

Web UI (two terminals):

```bash
uvicorn api.main:app --port 8000
```

```bash
cd web && npm install && npm run dev        # http://localhost:5173
```

---

## Interface

An application shell, not a page. The frame never scrolls: a command bar, a
stage rail, a permanent 3D viewport, a feature timeline along the bottom, and a
contextual inspector on the right. Panels scroll independently.

The shape is taken from parametric CAD tools, and it maps onto data the pipeline
already produces rather than being imposed on it:

| Shell element | What it actually shows |
|---|---|
| Command bar | part, material, process, the current revision, a link to this repo, and the history toggle |
| Stage rail | Sources → Evidence → Intent → Inspect → Release, badged with live failure and proposal counts. Sources is an AI-style composer that accepts any one, two, or all three inputs. Rail and inspector sit together on the **left**, the way an activity bar and its sidebar do, so choosing a stage and reading it are one glance; the active tab takes the panel's surface so the two read as one object. Clicking the active stage collapses the panel and gives the viewport the full width. |
| Editor / viewport | Evidence opens source documents in VS Code-style tabs and replaces the CAD view; selecting a value shows its highlighted extraction region. Intent, CAD and Validate retain the built-solid viewport. |
| Timeline | the real feature history — `base_plate → shaft_opening → mounting_holes → external_chamfers`. Selecting one opens what that operation actually is: its resolved values and the parameter each came from. |
| Inspector | the panel for the selected stage; a blocked run opens on Release, a released one on Inspect. Parameters are editable — changing one derives the next revision through the same `derive()` path an accepted proposal uses. |
| Status bar | the gate decision plus the governing measurement, tinted by outcome |
| Revision graph | history as a commit log, newest first. DesignIntent revisions are already an immutable attributed chain — parent, proposal, change, approver — so they are drawn as one. A filled node was released, a hollow one refused; selecting a node opens that revision. |

**Proportion is golden-ratio, not eyeballed.** Every fixed dimension is a
Fibonacci number, so the ratios between them are φ exactly rather than an
approximation of it:

```
command bar  55 : status bar 34  =  1.6176      φ = 1.6180
inspector   377 : 233            =  φ           377 = F(14)
rail 55 · timeline 55 · radii 5/8/13 · spacing 3/5/8/13/21/34
```

The type scale steps by **√φ = 1.272** from a 14px base — 11 / 14 / 17.8 / 22.6 /
28.8. A full 1.618 jump between adjacent sizes is far too coarse for dense UI
text, so φ is applied across two steps instead of one.

**Colour is OKLCH and reserved for meaning.** Steps are perceptually even rather
than evenly spaced in sRGB, where the same numeric gap looks larger in blues
than in yellows. A cool-cast neutral ramp carries the interface; iris marks
selection and the primary action; danger/success/warn carry outcomes. No status
is conveyed by hue alone — each also carries a glyph (`✓ ✕ ! –`) and a weight
change, so the interface still reads in greyscale or with colour-vision
deficiency.

Audited on the shipped CSS: **all 14 informational pairings clear 4.5:1**
(`c6` 4.66, accent 5.15, danger 5.16, success 5.04, warn 5.61). The one token
below that line, `c5`, is used exclusively for disabled and decorative elements,
which WCAG exempts — the two places it had been carrying information were moved
to `c6`.

Type is **Geist** and **Geist Mono**, drawn for technical interfaces. Monospace
is used only for measured numerals, with tabular figures so digits align down a
column — never for labels.

Built with Tailwind v4 (CSS-first `@theme` tokens), the shadcn pattern (owned
components, `cva` variants, `cn()` merge) and Radix for tooltip behaviour. The
three.js viewport is code-split, so the initial bundle is ~250 kB.

## Extraction: both paths are first-class

| Source | How it is read | Real without an API key? |
|---|---|---|
| **Datasheet PDF** | PyMuPDF word geometry — true page number, true bounding box | **Yes, always** |
| **Requirement text** | deterministic rule parser + ISO 273 lookup | **Yes, always** |
| **Sketch** | OpenAI or Anthropic vision when a key is set; otherwise a recorded fixture | Fixture replay |

The difference is never hidden. Every evidence row carries its
`extraction_method`, the UI shows it, and `eval/metrics.py` **raises** rather
than scoring fixture data as extraction accuracy — replaying a recording
measures the recording.

Set a key in `.env` (see `.env.example`) to extract drawings for real. An
OpenAI key is enough; Anthropic is supported too.

Because the datasheet path is genuinely parsed, clicking a value in the UI
highlights the actual rectangle it came from:

> page 3 · `Mounting hole pattern` → **31 x 31 mm** boxed in red

---

## Architecture

```
inputs ──► Evidence[] ──► DesignIntent v1 ──► PREFLIGHT ──► CADProgram ──► B-Rep
           (kind +        (immutable          (symbolic,   (typed,      (diagnostic
            target,        revision)           advisory)    no Python)   candidate —
            confidence                             │                     always built)
            + authority)                           │                          │
                                                   ▼                          ▼
                          DesignIntent v2 ◄── REPAIR ◄── RELEASE GATE ◄── MEASURED
                          (approved, with      (human      (sole export   VALIDATION
                           full provenance)     approval)   authority)
```

**Four stages, deliberately not merged:**

| Stage | Runs on | Blocks? |
|---|---|---|
| Preflight | DesignIntent, symbolically | **No** — advisory, predicts only |
| Diagnostic generation | CADProgram | **No** — always builds, so violations are measurable |
| Measured validation | the B-Rep | **No** — reports ground truth |
| Release gate | measured reports | **Yes — the only gate** |

Preflight and measurement are cross-checked against each other. A disagreement
is reported as a **pipeline defect**, not a design problem.

### Design decisions worth the words

**The LLM never emits or executes Python.** It returns schema-validated
`Evidence` only. `cad/executor.py` is the sole importer of CadQuery (enforced by
a test). The CadQuery script shown in the UI is *emitted by the compiler* for
review and is never executed.

**Authority and confidence are separate axes.** Confidence is "did I read this
correctly"; authority is "is this source entitled to define this". A blurry
datasheet scan is low-confidence but definitive; a crisp value scaled off a
sketch is high-confidence but advisory. Collapsing them loses the distinction
that makes fusion defensible.

**Authority never overrules an explicit annotation.** Two sources that each
*state* a value and disagree produce `ADJUDICATION_REQUIRED` with both values
preserved — a question for a human, not something to settle with a precedence
table. A blanket "datasheet beats sketch" rule would silently discard a number a
person deliberately wrote down, and the discarded one might be right.

**Source conflicts and constraint conflicts are different things.** The headline
case is a *constraint* conflict: nobody misread anything, so it is attributed to
parameters rather than blamed on a document.

**Repairs are immutable revisions.** `DesignIntent` is frozen; a repair calls
`derive()`, which records before/after, the proposal, and the approver. v1 never
changes. Freezing the nested models mattered — with only the outer model frozen,
`intent.parameters["plate_width"].value = 45.0` silently mutated v1.

**Typed parameter references, not stringly-typed numbers.** A CAD operation
field is `NumberLiteral | ParamRef` as a tagged union, so `45` and
`"plate_width"` are different types rather than told apart by guessing. The
payoff is visible in the generated scripts for v1 and v2: they differ *only* in
`plate_width = 40` vs `45`.

**Safe vs unsafe repairs.** Widening the plate is safe. Moving the hole pattern
is not — it builds cleanly, passes every check against the altered intent, and
does not bolt to the motor; the failure surfaces at assembly. Unsafe proposals
are shown with their consequence but refuse to auto-apply.

---

## Validation measures the solid

Nothing here echoes an input parameter, so a wrongly built feature actually
fails. Public CadQuery API only:

| What | How | Verified |
|---|---|---|
| Hole ⌀ and centres | `Edge.radius()`, `Edge.Center()` | 1.7000 @ ±15.500 → spacing 31.0 |
| Plate extents | planar `Face.normalAt()` + `Face.Center()` | 45.000000 / 5.000000 |
| Material integrity | measured vs analytic volume | delta **0.000000** mm³ |
| Through holes | matching circles on top and bottom | 5 openings |
| Edge clearance | hole edges vs measured boundary | 2.8000 → 5.3000 |

Three bans, each from something that actually went wrong, enforced by
`tests/test_no_brittle_apis.py`:

- **No private OCC accessors.** `face._geomAdaptor().Cylinder().Radius()` worked
  but the public `Edge.radius()` gives the identical value.
- **No bounding boxes for dimensions.** `BoundingBox().zlen` reported **5.007**
  for a 5.000 mm plate.
- **No exact face counts.** They break on any added fillet and prove little; the
  analytic volume comparison is tolerance-aware and catches real defects.

A fourth correction is recorded in the code: the rule "chamfer must be less than
half the plate thickness" is **false**. These chamfers run along vertical edges,
so thickness does not constrain them — a 1 mm chamfer on a 1.5 mm plate builds a
valid solid. The real limit is in-plane, and that is what preflight checks.

---

## Repository

```
spec2cad/
  schemas/      evidence · design_intent · cad_ir · report
  extractors/   datasheet (real) · text (real) · vision · fixtures · drawing
  knowledge/    ISO 273 clearance table · rounding recommendations
  fusion/       source_policy · entity_resolver · conflict_detector (preflight)
  cad/          compiler · executor (sole CadQuery importer) · selectors · script_writer
  validation/   measure · topology · dimensions · requirements · gate
  repair/       repair_planner
  pipeline.py · store.py (SQLite) · cli.py
api/main.py     FastAPI
web/            React + Vite + Tailwind v4 + three.js, five sheet zones
examples/       seeded input generator + generated inputs
eval/           metrics · run_eval → report.md
scripts/        freeze_demo.py (static replay bundle)
tests/          49 tests
```

Geometry is deliberately **not** persisted. The pipeline is deterministic, so a
stored DesignIntent plus the compiler reproduces the exact solid; storing the
B-Rep too would create a second source of truth that could drift from the intent
that supposedly produced it.

---

## Scope

**Built and working:** the motor-adapter slice end to end — genuine datasheet
extraction with real traceability, rule-cited fastener lookup, two-class conflict
detection, diagnostic generation, measured validation, the release gate,
immutable repair revisions, STEP round-trip verification, a five-panel UI, 36
tests, 32 deterministic evaluation checks, a container deployment path and a
398 KB static replay bundle.

**Deliberately deferred:** the 15-case matrix and perturbation battery (inch
inputs, relocated/removed dimensions, rotated sketches, contradictory text,
altered hole patterns), GD&T, assemblies, alternate motor frames, universal
drawing parsing. Unit normalisation and source adjudication are implemented and
unit-tested, so those are the natural next increment.

Known limitations are stated plainly in `eval/report.md` under **Failure
analysis** — including that the offline demo does not exercise drawing
understanding at all, and that preflight and measured validation share a
clearance formula, so their agreement would not catch a conceptual error in it.
