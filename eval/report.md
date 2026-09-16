# Spec2CAD evaluation report

Generated 2026-09-16 08:45 UTC

Two suites are reported separately and never averaged together. One measures
the pipeline; the other measures an extractor. Combining them would produce a
number that describes neither.

## 1. Deterministic pipeline suite

Fixed evidence in, no API calls, fully reproducible. This is what runs in CI.

**39/39 deterministic checks passed**

| Check | Expected | Actual | Result |
|---|---|---|---|
| edge clearance at 40 mm width | `2.8` | `2.8` | pass |
| minimum feasible width | `42.4` | `42.4` | pass |
| recommended rounded width | `45.0` | `45.0` | pass |
| edge clearance at 45 mm width | `5.3` | `5.3` | pass |
| M3 medium clearance via ISO 273 | `3.4` | `3.4` | pass |
| hole spacing read from datasheet | `31.0` | `31.0` | pass |
| datasheet page attributed | `3` | `3` | pass |
| datasheet bbox captured | `True` | `True` | pass |
| boss diameter not scraped from page-4 prose | `22.0` | `22.0` | pass |
| invalid candidate still builds | `True` | `True` | pass |
| candidate is a valid solid | `True` | `True` | pass |
| single body | `1` | `1` | pass |
| clearance MEASURED on the solid | `2.8` | `2.8` | pass |
| preflight prediction matches measurement | `True` | `True` | pass |
| failure classed as a constraint conflict | `constraint_conflict` | `constraint_conflict` | pass |
| no source conflict claimed | `pass` | `pass` | pass |
| release blocked at v1 | `False` | `False` | pass |
| mesh marked provisional | `True` | `True` | pass |
| two safe proposals offered | `2` | `2` | pass |
| unsafe options still surfaced | `2` | `2` | pass |
| every unsafe option states its consequence | `True` | `True` | pass |
| unsafe repair refused without acknowledgement | `True` | `True` | pass |
| safe repairs never touch the motor interface | `True` | `True` | pass |
| v2 derives from v1 | `1` | `1` | pass |
| v1 remains at 40 mm | `40.0` | `40.0` | pass |
| v2 is 45 mm | `45.0` | `45.0` | pass |
| change recorded with before/after | `(40.0, 45.0)` | `(40.0, 45.0)` | pass |
| approver recorded | `eval` | `eval` | pass |
| v2 clearance measured | `5.3` | `5.3` | pass |
| release authorised at v2 | `True` | `True` | pass |
| no measured failures at v2 | `0` | `0` | pass |
| re-imported STEP re-validates | `True` | `True` | pass |
| second part family identified | `mounting_bracket` | `mounting_bracket` | pass |
| second part feature plan | `['base_plate', 'mounting_holes', 'base_slots', 'external_fillets']` | `['base_plate', 'mounting_holes', 'base_slots', 'external_fillets']` | pass |
| second part released | `True` | `True` | pass |
| slot width measured on B-Rep | `8.0` | `8.0` | pass |
| slot length measured on B-Rep | `20.0` | `20.0` | pass |
| fillets measured on B-Rep | `4` | `4` | pass |
| requirement executed from predicate IR | `True` | `True` | pass |

## 2. Real extractor suite

Genuine multimodal extraction against the sketch ground truth. Non-deterministic,
so it is reported across repeats with the spread shown rather than as a single
figure. Fixture-replayed evidence is structurally barred from this suite:
`score_extraction` raises `FixtureEvidenceInMetrics` rather than scoring a
recording, because replaying a recording measures the recording.

__


## 3. Capability baseline

Registry schema `1.0.0` reports **49 available**
and **0 unavailable/planned** capabilities. Implementation maturity,
pipeline integration and release role are independent fields; a tested library utility
is not described as production or release-governing unless those fields say so.

| Capability | Maturity | Integration | Release role |
|---|---|---|---|
| Deterministic text extraction | bounded | production_pipeline | governing |
| Known-row PDF extraction | bounded | production_pipeline | governing |
| Recorded sketch fixture | fixture | production_pipeline | governing |
| OpenAI multimodal extraction | bounded | optional_pipeline | governing |
| Engineering Intent Graph | proven | production_pipeline | governing |
| Typed CADProgram execution IR | proven | production_pipeline | governing |
| CadQuery backend | proven | production_pipeline | governing |
| Measured release gate | proven | production_pipeline | governing |
| STEP round-trip verification | bounded | production_pipeline | governing |
| Immutable repair revisions | bounded | production_pipeline | governing |
| Capability registry reporting | proven | production_pipeline | diagnostic |
| Box | bounded | production_pipeline | governing |
| Cylinder | bounded | production_pipeline | governing |
| Tube | bounded | production_pipeline | governing |
| Hole | bounded | production_pipeline | governing |
| Rectangular hole pattern | bounded | production_pipeline | governing |
| Linear slot pattern | bounded | production_pipeline | governing |
| Chamfer | bounded | production_pipeline | governing |
| Fillet | bounded | production_pipeline | governing |
| Profile extrude | bounded | optional_pipeline | governing |
| Profile pocket | bounded | optional_pipeline | governing |
| Profile revolve | bounded | optional_pipeline | governing |
| Curved rod sweep | bounded | optional_pipeline | governing |
| Rectangular loft | bounded | optional_pipeline | governing |
| Curved strip sweep | bounded | optional_pipeline | governing |
| Threaded fastener | bounded | optional_pipeline | governing |
| 90-degree sheet-metal bend | bounded | optional_pipeline | governing |
| Flanged coupling specialization | bounded | showcase | standalone_result |
| Controller enclosure specialization | bounded | showcase | standalone_result |
| Motor-mount bracket specialization | bounded | showcase | standalone_result |
| Hydraulic manifold specialization | bounded | showcase | standalone_result |
| Blower transition duct specialization | bounded | showcase | standalone_result |
| Assembly transforms | bounded | standalone_api | standalone_result |
| Assembly mate validation | bounded | standalone_api | standalone_result |
| Assembly collision check | bounded | standalone_api | standalone_result |
| GD&T size | bounded | standalone_api | standalone_result |
| GD&T position | bounded | standalone_api | standalone_result |
| GD&T flatness | bounded | standalone_api | standalone_result |
| GD&T perpendicularity | bounded | standalone_api | standalone_result |
| Mass properties | bounded | standalone_api | standalone_result |
| Axial stress | bounded | standalone_api | standalone_result |
| Bending stress | bounded | standalone_api | standalone_result |
| Thermal expansion | bounded | standalone_api | standalone_result |
| Worst-case fit | bounded | standalone_api | standalone_result |
| Feature IR | bounded | production_pipeline | none |
| Typed backend protocol | bounded | production_pipeline | none |
| FreeCAD backend | bounded | optional_pipeline | diagnostic |
| CAD State Graph | bounded | optional_pipeline | diagnostic |
| Cross-backend reconciliation | bounded | optional_pipeline | governing |

## 4. Failure analysis

Stated plainly, because a prototype with hidden limitations is worse than a
smaller one with known ones.

**What is genuinely measured**

- Datasheet extraction is real on every run: PyMuPDF returns the words and their
  rectangles, so the page number and highlight box are the actual coordinates of
  the actual text. This holds with or without an API key.
- All dimensional validation is read off the B-Rep. Hole diameters and centres
  come from `Edge.radius()`/`Edge.Center()`, extents from planar face positions,
  and material integrity from measured-vs-analytic volume (agreement to 1e-9 mm3).
  None of it echoes the input parameters, so a wrongly built feature fails.

**Known limitations**

- Without a vision API key, sketch evidence is replayed from a recorded fixture.
  This is labelled on every row in the UI and excluded from extraction metrics,
  but it means the offline demo does not exercise drawing understanding at all.
- The datasheet parser is a narrow table-rule reader, not a general document
  parser. It reads the rows it knows and stays silent otherwise. An unanchored
  version of it scraped `3` out of the sentence "listed in section 3" on page 4;
  that is now fixed by anchoring labels to the row start, and regression-tested,
  but the class of error is inherent to rule-based extraction.
- The production governed dimensional slice is the motor adapter/plate family plus a
  slotted-bracket generalization. The rectangular pattern supports exactly four corner
  holes; unsupported cases raise rather than approximating.
- Advanced profile, sweep, loft, threaded-fastener and 90-degree sheet-bend operations
  can traverse the optional model-to-EIG pipeline, but their governing checks currently
  cover topology and material change rather than full dimensional/interface fidelity.
- Assembly, GD&T and analytic engineering calculations are bounded standalone APIs.
  Their results are not connected to the production release gate.
- Five additional specialized solids are real CadQuery builds used by the frozen public
  showcase, but that replay builder constructs Evidence, DesignIntent and CADProgram by
  hand; it is not evidence of production EIG compilation.
- R1 cross-backend reconciliation is release-governing only for the benchmarked
  motor-adapter revisions. Other Feature IR families and native FreeCAD edits are
  explicitly unsupported until later benchmark slices promote them.
- Preflight and measured validation are cross-checked against each other, but both
  encode the same clearance formula. A conceptual error in that formula would not
  be caught by their agreement.

**Deliberately deferred**

The deterministic adversarial suite now covers changed and missing dimensions,
inch/mm normalization, contradictory sources, feature removal/reordering, an
unsatisfiable requirement, unseen feature composition, and injected pipeline
faults. Drawing-layout perturbations such as rotated sketches and relocated
annotations remain deferred because the offline fixture cannot measure vision
generalization honestly.
