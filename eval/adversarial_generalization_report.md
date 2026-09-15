# Adversarial generalization evaluation

The feature planner and CAD vocabulary are treated as frozen. Cases vary
evidence or inject faults only through public seams. Expected refusal for
missing, contradictory, or geometrically impossible input counts as correct.

## Metrics by pipeline stage

| Stage | Passed | Total | Rate |
|---|---:|---:|---:|
| graph construction | 12 | 12 | 100% |
| feature planning | 9 | 9 | 100% |
| cad execution | 15 | 15 | 100% |
| geometric validation | 8 | 8 | 100% |
| requirement validation | 4 | 4 | 100% |
| conflict refusal correctness | 5 | 5 | 100% |
| step round trip | 3 | 3 | 100% |

Correct refusals: **4**

## Outcomes

| Level | Case | Stage | Assertion | Result | Refusal |
|---|---|---|---|---|---|
| regression | motor_adapter | graph_construction | graph has no dangling relationships | PASS | — |
| regression | motor_adapter | feature_planning | original feature sequence is stable | PASS | — |
| regression | motor_adapter | cad_execution | kernel produced one valid solid | PASS | — |
| regression | motor_adapter | cad_execution | every planned operation changed geometry | PASS | — |
| regression | motor_adapter | conflict_refusal_correctness | known unsatisfiable v1 is correctly refused | PASS | correct |
| regression | motor_adapter | requirement_validation | approved repair restores measured clearance | PASS | — |
| regression | motor_adapter | step_round_trip | exported STEP independently re-imports and revalidates | PASS | — |
| regression | slotted_mounting_bracket | graph_construction | graph has no dangling relationships | PASS | — |
| regression | slotted_mounting_bracket | feature_planning | bracket feature sequence is stable | PASS | — |
| regression | slotted_mounting_bracket | cad_execution | kernel produced one valid solid | PASS | — |
| regression | slotted_mounting_bracket | cad_execution | every planned operation changed geometry | PASS | — |
| regression | slotted_mounting_bracket | geometric_validation | topology and dimensional reports pass | PASS | — |
| regression | slotted_mounting_bracket | step_round_trip | exported STEP independently re-imports and revalidates | PASS | — |
| perturbation | changed_dimensions | graph_construction | graph has no dangling relationships | PASS | — |
| perturbation | changed_dimensions | feature_planning | dimension changes do not change feature composition | PASS | — |
| perturbation | changed_dimensions | cad_execution | kernel produced one valid solid | PASS | — |
| perturbation | changed_dimensions | cad_execution | every planned operation changed geometry | PASS | — |
| perturbation | changed_dimensions | geometric_validation | topology and dimensional reports pass | PASS | — |
| perturbation | changed_dimensions | geometric_validation | changed envelope is measured | PASS | — |
| perturbation | missing_dimensions | graph_construction | graph has no dangling relationships | PASS | — |
| perturbation | missing_dimensions | feature_planning | planner refuses an incomplete base solid | PASS | — |
| perturbation | missing_dimensions | conflict_refusal_correctness | missing evidence blocks release | PASS | correct |
| perturbation | contradictory_sources | graph_construction | graph has no dangling relationships | PASS | — |
| perturbation | contradictory_sources | conflict_refusal_correctness | explicit disagreement remains unresolved | PASS | — |
| perturbation | contradictory_sources | conflict_refusal_correctness | unadjudicated evidence blocks release as source conflict | PASS | correct |
| perturbation | inch_mm_normalization | graph_construction | graph has no dangling relationships | PASS | — |
| perturbation | inch_mm_normalization | graph_construction | inch evidence is normalized into millimetres | PASS | — |
| perturbation | inch_mm_normalization | cad_execution | kernel produced one valid solid | PASS | — |
| perturbation | inch_mm_normalization | cad_execution | every planned operation changed geometry | PASS | — |
| perturbation | inch_mm_normalization | geometric_validation | topology and dimensional reports pass | PASS | — |
| perturbation | removed_features | graph_construction | graph has no dangling relationships | PASS | — |
| perturbation | removed_features | feature_planning | absent optional features are not invented | PASS | — |
| perturbation | removed_features | cad_execution | kernel produced one valid solid | PASS | — |
| perturbation | removed_features | cad_execution | every planned operation changed geometry | PASS | — |
| perturbation | removed_features | geometric_validation | topology and dimensional reports pass | PASS | — |
| perturbation | reordered_features | graph_construction | graph has no dangling relationships | PASS | — |
| perturbation | reordered_features | feature_planning | source sentence order does not change CAD IR | PASS | — |
| perturbation | unsatisfiable_requirement | graph_construction | graph has no dangling relationships | PASS | — |
| perturbation | unsatisfiable_requirement | cad_execution | kernel produced one valid solid | PASS | — |
| perturbation | unsatisfiable_requirement | cad_execution | every planned operation changed geometry | PASS | — |
| perturbation | unsatisfiable_requirement | requirement_validation | unsatisfiable clearance is measured rather than guessed | PASS | — |
| perturbation | unsatisfiable_requirement | conflict_refusal_correctness | measured hard-requirement failure blocks release | PASS | correct |
| unseen_composition | unseen_rectangular_flange | graph_construction | graph has no dangling relationships | PASS | — |
| unseen_composition | unseen_rectangular_flange | feature_planning | existing features compose the unseen flange | PASS | — |
| unseen_composition | unseen_rectangular_flange | feature_planning | renaming the part leaves every operation unchanged | PASS | — |
| unseen_composition | unseen_rectangular_flange | cad_execution | kernel produced one valid solid | PASS | — |
| unseen_composition | unseen_rectangular_flange | cad_execution | every planned operation changed geometry | PASS | — |
| unseen_composition | unseen_rectangular_flange | geometric_validation | topology and dimensional reports pass | PASS | — |
| unseen_composition | unseen_rectangular_flange | geometric_validation | central and mounting openings plus R4 fillets are measured | PASS | — |
| unseen_composition | unseen_rectangular_flange | requirement_validation | graph relation compiles and measures the >=5 mm predicate | PASS | — |
| unseen_composition | unseen_rectangular_flange | step_round_trip | exported STEP independently re-imports and revalidates | PASS | — |
| fault_injection | wrong_executor_dimension | geometric_validation | B-Rep validation catches executor width corruption | PASS | — |
| fault_injection | symbolic_measurement_disagreement | requirement_validation | symbolic disagreement is a pipeline inconsistency | PASS | — |
| fault_injection | persisted_graph_replay | graph_construction | persisted Engineering Intent Graph reloads equivalently | PASS | — |
| fault_injection | persisted_graph_replay | feature_planning | reloaded graph reproduces equivalent CAD IR | PASS | — |
| fault_injection | persisted_graph_replay | cad_execution | reloaded graph reproduces equivalent measured geometry | PASS | — |

## Failure details

No failed assertions.
