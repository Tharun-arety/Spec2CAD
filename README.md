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
                 graph-driven feature planner
                         │
                         ▼
                     CADProgram
                  (typed, no Python)
                         │
                         ▼
                       B-Rep
                         │
                         ▼
                measured validation
                         │
                         ▼
                    release gate
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
