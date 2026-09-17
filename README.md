# Spec2CAD

**Multimodal engineering intent → validated parametric CAD**

Give it a requirement, an engineering sketch, a technical document — or a combination of them.

Spec2CAD extracts traceable engineering evidence, builds an **Engineering Intent Graph**, compiles that intent into typed CAD operations, generates parametric geometry, and validates the resulting B-Rep against the requirements that produced it.

[**Live demo →**](https://spec2cad.vercel.app) · [Architecture](#architecture) · [Examples](#five-evidence-conditions) · [Quickstart](#quickstart)

```text
Text / Sketch / Technical Document
              ↓
       Evidence extraction
              ↓
    Engineering Intent Graph
              ↓
   Requirement Predicate IR
              ↓
        Feature planning
              ↓
       Parametric CAD
              ↓
   B-Rep / STEP validation
              ↓
     Repair / release gate
```

The point is not that an LLM can write CadQuery. The point is the separation between what the sources say, what the system believes the design intent is, what geometry gets built, and what the final solid actually measures.

```text
evidence ≠ design intent ≠ CAD program ≠ measured B-Rep ≠ release authorisation
```

> **Demo note** — the public Vercel deployment replays five genuine frozen pipeline runs. It does not pretend to run CadQuery inside Vercel; the full pipeline runs locally or in the container deployment described in [`DEPLOYMENT.md`](DEPLOYMENT.md).

---

## Why this exists

Real engineering intent rarely arrives as one clean prompt.

A dimension may be written on a sketch. A hole pattern may come from a supplier datasheet. A clearance requirement may be stated in text. A standard may define the actual fastener diameter. Two sources may disagree — or every source may be individually correct while the combined design is geometrically impossible.

Sending all of that directly to a code-generating model collapses evidence, interpretation, execution, and verification into one opaque step.

Spec2CAD keeps them separate so the system can answer questions such as:

- Where did this dimension come from?
- Was it explicitly stated or inferred?
- Which source is authoritative?
- Which requirement does this feature satisfy?
- Did the generated B-Rep actually meet it?
- If not, which parameters caused the failure?
- Can a repair be proposed without silently rewriting the original intent?

---

## Five evidence conditions

The public showcase is organized by **how engineering evidence arrives**, not by CAD operation.

| # | Evidence | Part | What the case demonstrates | CAD operations |
|---|---|---|---|---|
| 01 | **Text only** | Flanged shaft coupling | Generate from natural language while keeping an underspecified M5 tapping depth explicit | revolved interface · keyway · circular hole pattern |
| 02 | **Sketch only** | Sheet-metal enclosure | Reconstruct geometry from drawing marks while refusing to invent missing material/tolerance information | thin-wall body · formed walls · panel openings |
| 03 | **Text + sketch** | Motor-mount bracket | Detect a text-vs-sketch / clearance conflict, measure it on geometry, and apply an approved repair | pads · face holes · slots · gussets |
| 04 | **Sketch + technical document** | Hydraulic manifold | Resolve sketch port labels against controlled interface data before validating hidden passages | multi-face drilling · modeled threads · passage booleans |
| 05 | **Text + sketch + technical document** | Blower transition duct | Fuse all evidence, detect geometric infeasibility, block release, and lengthen the design after approval | rectangle-to-circle loft · shell · end flanges |

Open the [live demo](https://spec2cad.vercel.app) to inspect each recorded run through **Sources → Evidence → Intent → Inspect → Release**.

### Run locally

```bash
python examples/motor_adapter/generate_inputs.py     # seeded, byte-identical
python -m spec2cad.cli examples/motor_adapter        # v1: blocked, exit 1
python -m spec2cad.cli examples/motor_adapter --approve widen_to_recommended
python -m spec2cad.cli examples/mounting_bracket     # second feature distribution
python -m pytest                                     # public and pipeline tests
python -m eval.run_public_guardrails                 # abuse/cost/resource eval
python -m eval.run_eval                              # 39 deterministic checks
python -m eval.r1_native_foundation                  # B.R1: two real backends + native edit
python -m eval.r1h_native_hardening                  # B.R1H: four families + topology edit
python -m eval.run_adversarial_generalization       # adversarial stage metrics
```

Web UI (two terminals):

```bash
SPEC2CAD_DUAL_BACKEND=1 uvicorn api.main:app --port 8000
```

```bash
cd web && npm install && npm run dev        # http://localhost:5173
```
### What a run is supposed to expose

```text
Input
  ↓
Extracted evidence + provenance
  ↓
Engineering Intent Graph
  ↓
Resolved parameters + requirement predicates
  ↓
Typed feature plan
  ↓
Generated CAD
  ↓
Measured validation
  ↓
Released / blocked / repaired
```

The repository also contains a separate text-only **slotted mounting bracket** generalisation case: 80 × 50 × 4 mm, four mounting holes, two 8 × 20 mm slots, and 3 mm corner fillets. It passes through the same graph → planner → typed CAD IR → measured validation path; the planner selects from graph features rather than part-name switches.

---

## A concrete failure case

The motor-adapter path demonstrates why measurement matters.

| Source | States |
|---|---|
| Sketch | plate width = **40 mm** |
| Datasheet | **31 × 31 mm** motor-hole pattern, 4 × M3, ⌀22 boss |
| Requirement | **≥4 mm edge clearance**, 5 mm aluminium, normal-clearance M3 |
| ISO 273 lookup | M3 medium clearance → **⌀3.4 mm** |

Every value is read correctly. Together they are impossible:

```text
edge clearance = (40 − 31)/2 − 3.4/2 = 2.8 mm
required       = 4.0 mm
```

Spec2CAD still builds the diagnostic candidate so the failure can be measured on the **real solid**, not only predicted symbolically.

```text
measured edge clearance: 2.8000 mm
release: BLOCKED
```

The system attributes the failure to the responsible parameters rather than blaming a source that was read correctly. An approved repair widens the plate to 45 mm, derives a new immutable intent revision, regenerates the CAD, measures **5.3000 mm**, and then STEP-exports, re-imports, and validates the artifact again.

Audited on the shipped CSS: **all 14 informational pairings clear 4.5:1**
(`c6` 4.66, accent 5.15, danger 5.16, success 5.04, warn 5.61). The one token
below that line, `c5`, is used exclusively for disabled and decorative elements,
which WCAG exempts — the two places it had been carrying information were moved
to `c6`.

Type is **IBM Plex Sans** and **IBM Plex Mono**, drawn for technical interfaces.
The public access hero reserves **IBM Plex Serif italic** for its rotating input
modality; product UI and body copy remain Sans. Monospace is used only for measured
numerals, with tabular figures so digits align down a column — never for labels.

Built with Tailwind v4 (CSS-first `@theme` tokens), the shadcn pattern (owned
components, `cva` variants, `cn()` merge) and Radix for tooltip behaviour. The
three.js viewport is code-split, so the initial bundle is ~250 kB.

## Extraction: both paths are first-class

| Source | How it is read | Real without an API key? |
|---|---|---|
| **Datasheet PDF** | exact known rows via PyMuPDF; bounded PDF text also joins semantic planning when a compatible model is configured | **Known rows only** |
| **Requirement text** | deterministic plate parser + ISO 273 lookup; a schema-capable model maps broader language to the typed feature vocabulary | **Plate fallback only** |
| **Sketch** | joins the same schema-constrained semantic pass as text and PDF; Anthropic remains available for the legacy plate reader | **No for arbitrary uploads** |

The difference is never hidden. Every evidence row carries its
`extraction_method`, the UI shows it, and `eval/metrics.py` **raises** rather
than scoring fixture data as extraction accuracy — replaying a recording
measures the recording.

Set `OPENAI_API_KEY` in the root `.env.local` (see `.env.example`). The same
server-side key enables both structured requirement reasoning and sketch
vision; it is never sent to the browser. `.env.local` edits are picked up on
the next request. `SPEC2CAD_REASONING_MODEL` and `SPEC2CAD_OPENAI_MODEL` may
override the text and vision models independently. Anthropic remains supported
for sketch vision only.

Live users may instead open **Model → Bring my own API key** in the agent panel.
The key, model and provider selection stay in that browser tab's memory and are
sent only with generation requests; they are not written to run state, browser
storage, evidence, logs or artifacts. OpenAI works directly. Other providers
must expose OpenAI-compatible chat completions with strict JSON-schema output
and, for sketches, compatible image input. Custom HTTPS hosts are restricted to
the deployment's approved host list (`SPEC2CAD_ALLOWED_MODEL_HOSTS`, plus the
built-in common-provider list) so the public API cannot become an arbitrary
network proxy. A native provider with a different wire protocol still requires
an explicit adapter.

Because the datasheet path is genuinely parsed, clicking a value in the UI
highlights the actual rectangle it came from:

> page 3 · `Mounting hole pattern` → **31 x 31 mm** boxed in red

---

## Architecture

```text
inputs
  │
  ▼
Agent interpretation
(plan / bounded question / explanation)
  │
  ▼
Evidence[]
(kind · value · source · confidence · authority · region)
  │
  ▼
Engineering Intent Graph
(entities · relations · provenance · constraints)
  │
  ├──────────────► DesignIntent compatibility projection
  │
  └──────────────► Requirement Predicate IR
                         │
                         ▼
                     Feature IR
                         │
                   ┌─────┴─────┐
                   ▼           ▼
              CadQuery      FreeCAD
              adapter       worker
                   └─────┬─────┘
                         │
                         ▼
                 CSG + measured B-Rep
                         │
                         ▼
          classified reconciliation + release gate
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
           release              repair proposal
                                      │
                                      ▼
                              DesignIntent vN+1
```

### The important boundaries

**Evidence is not intent.** Every extracted fact keeps provenance, extraction method, confidence, and authority instead of being flattened into a prompt.

**Intent is not CAD code.** Dimensions, features, interfaces, requirements, source evidence, and reference geometry live as typed graph nodes and relations such as `defines`, `supported_by`, `constrains`, and `located_relative_to`.

**The LLM does not execute Python.** Model output is schema-constrained and limited to a closed typed operation vocabulary. `cad/executor.py` is the sole CadQuery importer.

**The LLM never emits or executes Python.** It returns schema-validated
`Evidence` only. The kernel facade is the sole product importer of CadQuery
(enforced by a test). The CadQuery script shown in the UI is *emitted by the
compiler* for review and is never executed.

**R1H proves two genuinely different backends across a bounded CAD vocabulary.**
The same backend-neutral Feature IR drives CadQuery and an isolated FreeCAD 1.1
worker for rectangular, cylindrical and tubular bases, circular openings,
rectangular hole patterns, linear slots, chamfers and fillets. Backend code does
not recognize demo part or parameter names: native aliases are opaque and edits
resolve stable Feature IR IDs. B.R1H builds four unrelated compositions twice,
records latency/failures, changes slot topology, and proves typed refusals. This
is deliberately not a claim of arbitrary profiles, surfacing or universal CAD.
Release-governing reconciliation remains the measured motor-interface slice;
broader family comparisons are advisory.

**Requirements compile to predicates.** A statement such as “minimum 4 mm edge clearance” becomes a typed geometric predicate such as a `MinimumDistance(...)`, which is later evaluated against the generated B-Rep.

**Confidence and authority are different.** A blurry datasheet can be low-confidence but authoritative; a crisp scaled sketch value can be high-confidence but advisory.

**Repairs create revisions.** A repair derives a new frozen intent revision with before/after values, proposal, and approver. The original revision remains intact.

---

## Validation measures the solid

Validation does not simply compare requested values with the parameters fed into the CAD program. It interrogates the generated topology.

| What | Measurement approach | Example verified result |
|---|---|---|
| Hole diameter / centres | public `Edge.radius()` / `Edge.Center()` | radius 1.7000 at ±15.500 → 31 mm spacing |
| Plate extents | planar face normals + centres | 45.000000 / 5.000000 |
| Material integrity | measured vs analytic volume | delta **0.000000 mm³** |
| Through-holes | matching circular openings on top and bottom | 5 openings |
| Edge clearance | measured hole edges vs part boundary | **2.8000 → 5.3000 mm** after repair |
| Slots | paired semicircular B-Rep arcs | **2 × 8 × 20 mm** |
| Corner fillets | external quarter-circle arcs | **4 × R3 mm** |

The project deliberately avoids brittle validation shortcuts such as private OCC accessors, bounding-box dimensions for precision measurements, and exact face-count assertions.

The release process has four separate stages:

| Stage | Operates on | Blocks release? |
|---|---|---|
| Preflight | intent, symbolically | No — advisory |
| Diagnostic generation | typed CAD program | No — build the candidate |
| Measured validation | generated B-Rep | No — report ground truth |
| Release gate | measured reports | **Yes — the only gate** |

A disagreement between symbolic preflight and measured validation is treated as a **pipeline defect**, not a design failure.

---

## Extraction and multimodal reasoning

| Source | Current path | Without an API key |
|---|---|---|
| Technical PDF | PyMuPDF for known rows; bounded PDF text can join semantic planning | known rows only |
| Requirement text | deterministic plate parser + ISO 273 lookup; broader language maps to the typed feature vocabulary through OpenAI | narrow plate fallback |
| Engineering sketch | OpenAI multimodal semantic pass; Anthropic remains supported by the legacy sketch reader | arbitrary uploads unavailable |

Every evidence row records its `extraction_method`. Recorded fixture data is explicitly excluded from extraction-accuracy claims; replaying a frozen run is not presented as measuring a vision model.

When available, source regions are retained so the UI can trace a resolved value back to the exact location it came from — for example a datasheet row containing the 31 × 31 mm mounting pattern.

---

## Interface

The UI is structured like an engineering application rather than a chat page.

- **Sources** — text, sketch, technical-document inputs
- **Evidence** — extracted values with provenance and source-region inspection
- **Intent** — resolved parameters, graph-backed design intent, requirements
- **CAD / Inspect** — generated solid and real feature history
- **Release** — measured checks, conflicts, repairs, and gate decision
- **Revision history** — immutable intent revisions and approvals

Selecting an evidence value can open the source region that produced it; selecting a CAD feature exposes the resolved parameters behind that operation.

---

## Quickstart

### Requirements

- Python with CadQuery support
- Node.js for the web client
- optional `OPENAI_API_KEY` for broader semantic text/PDF reasoning and sketch vision

```bash
pip install -r requirements.txt
```

Run the deterministic examples:

```bash
python examples/motor_adapter/generate_inputs.py
python -m spec2cad.cli examples/motor_adapter
python -m spec2cad.cli examples/motor_adapter --approve widen_to_recommended
python -m spec2cad.cli examples/mounting_bracket
```

Run validation/evaluation:

```bash
python -m pytest
python -m eval.run_public_guardrails
python -m eval.run_eval
python -m eval.run_adversarial_generalization
```

Run the application locally:

```bash
uvicorn api.main:app --port 8000
```

In a second terminal:

```bash
cd web
npm install
npm run dev
```

Then open `http://localhost:5173`.

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for the container/deployment path.

---

## Repository map

```text
spec2cad/
  schemas/      evidence · intent graph · CAD/profile · assembly · GD&T · analysis IR
  extractors/   datasheet · text · vision · drawing · recorded fixtures
  knowledge/    engineering lookup data such as ISO 273
  fusion/       source policy · entity resolution · graph construction · conflicts
  cad/          compiler · graph-driven planner · executor · selectors · assembly API
  validation/   predicates · geometry measurement · topology · requirements · release gate
  repair/       repair planning
  pipeline.py   end-to-end orchestration
  store.py      revision / graph persistence

api/            FastAPI application
web/            React + Vite + Tailwind + three.js interface
examples/       motor adapter · mounting bracket · benchmark/showcase inputs
eval/           deterministic + adversarial evaluation
scripts/        showcase / replay generation
tests/          pipeline, CAD, validation and regression tests
```

Geometry itself is not persisted as the source of truth. The intent graph plus deterministic compiler reproduces the solid; persisting a second authoritative geometry representation would create another object that can drift from the intent that supposedly generated it.

---

## Current scope

### Capability truth contract

`spec2cad/capabilities.py` is the machine-readable source for capability claims.
Each record classifies implementation maturity, integration level, release role,
supported backends, benchmark evidence, limitations and its own version as
independent fields. In particular, a bounded standalone API is not described as
production-integrated or release-governing merely because its tests pass.

`GET /health` retains the compact `capabilities` ID list for compatibility and
also returns the versioned `capability_registry` document. The generated
evaluation report renders its capability table from the same registry.

The governed production geometry slice remains the motor/plate path and its
slotted-bracket generalization. Advanced profile/sweep/loft/thread/sheet-bend
features traverse an optional model-to-EIG path but currently govern only
topology and operation material change. Assembly, GD&T and analytic calculations
are standalone results, not inputs to the production release gate. The five
specialized public-showcase solids are real CadQuery builds, but their frozen
replay builder hand-constructs the intermediate records and does not prove the
production EIG compiler path.

**Built and working:** the motor-adapter slice end to end — genuine datasheet
extraction with real traceability, rule-cited fastener lookup, two-class conflict
detection, diagnostic generation, measured validation, the release gate,
immutable repair revisions, STEP round-trip verification, a five-panel UI,
39 deterministic evaluation checks, a container deployment path and a
5.0 MB static showcase bundle.

### Working today

- multimodal evidence model with provenance, confidence, authority, and source regions
- Engineering Intent Graph as the pipeline source
- typed requirement-predicate IR
- graph-driven CAD feature planning
- schema-constrained semantic interpretation
- typed CAD program rather than arbitrary generated Python
- CadQuery execution behind a single executor boundary
- measured B-Rep validation
- release gating
- immutable repair revisions
- STEP export → re-import → re-validation
- five recorded evidence-condition showcases
- second feature-distribution / mounting-bracket generalisation case
- closed line/arc profiles, extrusion, pocketing, revolution
- modeled external helical fastener threads
- straight–arc–straight sweeps
- bounded 90° sheet-metal bends
- assemblies with component transforms and selected mate validation
- selected GD&T inspection and explicit-input engineering calculations

### Deliberately not claimed

Spec2CAD is **not** a universal CAD agent or production-ready mechanical design system.

When a server credential or request-scoped compatible credential is supplied,
the public run path feeds the
written requirement, an attached engineering sketch, and bounded text extracted
from an attached technical PDF into one schema-constrained semantic pass. The
model may select only the typed operations above; it cannot emit or execute
arbitrary CAD code. Written image dimensions are accepted as evidence, while
pixel scaling and invented dimensions are explicitly prohibited. The narrow
deterministic plate parser remains the no-model fallback.

Current limitations include:

- arbitrary engineering drawing understanding is not solved
- drawing-layout perturbations such as rotated sketches and relocated annotations are deferred
- semantic extraction quality depends on the configured multimodal model
- the typed CAD vocabulary is intentionally bounded
- general automatic mate solving is not implemented
- non-90° sheet-metal bends are outside the current supported path
- FEA is not part of the CAD validation loop
- the public Vercel demo is recorded replay, not live CadQuery execution
- the deterministic offline fixture cannot honestly measure vision generalisation
- symbolic preflight and measured clearance validation currently share some domain formulas, so agreement between them cannot detect every conceptual mistake

The adversarial suite reports graph construction, planning, execution, geometry, requirements, refusal correctness, and STEP round-trip separately rather than collapsing everything into one success number.

---

## The design principle

The long-term problem is not simply generating geometry from language.

It is preserving **engineering intent** when that intent is fragmented across different sources, converting it into operations a CAD system can execute, and then proving that the resulting artifact still satisfies the evidence and constraints that justified it.

That is the part Spec2CAD is built to explore.
