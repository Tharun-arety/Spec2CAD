# Spec2CAD evaluation report

Generated 2026-09-15 08:09 UTC

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


## 3. Failure analysis

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
- The geometry vocabulary is six operations (box, hole, rectangular hole pattern,
  slot pattern, chamfer, and fillet); the rectangular pattern still supports exactly
  four corner holes. Anything else raises rather than approximating.
- Two feature distributions are supported: the motor adapter and a flat slotted
  bracket. This demonstrates graph/compiler reuse, not open-ended part synthesis.
  There is still no GD&T, tolerancing, assembly reasoning, or bent-sheet-metal model.
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
