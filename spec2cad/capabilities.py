"""Authoritative, machine-readable capability truth.

The axes in this module are deliberately independent.  A feature can be
implemented without being in the production pipeline, and it can be integrated
without being allowed to govern a release.  Public surfaces consume this
registry instead of inferring maturity from the existence of a class or test.
"""

from __future__ import annotations

from enum import Enum
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field, model_validator


CAPABILITY_SCHEMA_VERSION = "1.0.0"


class CapabilityCategory(str, Enum):
    EXTRACTION = "extraction"
    REPRESENTATION = "representation"
    GEOMETRY = "geometry"
    INSPECTION = "inspection"
    ENGINEERING = "engineering"
    PLATFORM = "platform"


class ImplementationMaturity(str, Enum):
    UNAVAILABLE = "unavailable"
    FIXTURE = "fixture"
    BOUNDED = "bounded"
    PROVEN = "proven"


class IntegrationLevel(str, Enum):
    ABSENT = "absent"
    LIBRARY = "library"
    SHOWCASE = "showcase"
    STANDALONE_API = "standalone_api"
    OPTIONAL_PIPELINE = "optional_pipeline"
    PRODUCTION_PIPELINE = "production_pipeline"


class ReleaseRole(str, Enum):
    NONE = "none"
    DIAGNOSTIC = "diagnostic"
    STANDALONE_RESULT = "standalone_result"
    GOVERNING = "governing"


class CapabilityRecord(BaseModel):
    """One independently classified product capability."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    label: str
    category: CapabilityCategory
    summary: str
    implementation_maturity: ImplementationMaturity
    integration: IntegrationLevel
    release_role: ReleaseRole
    supported_backends: tuple[str, ...] = ()
    benchmark_evidence: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")

    @model_validator(mode="after")
    def classification_is_coherent(self):
        unavailable = self.implementation_maturity is ImplementationMaturity.UNAVAILABLE
        if unavailable:
            if self.integration is not IntegrationLevel.ABSENT:
                raise ValueError("unavailable capability must have absent integration")
            if self.release_role is not ReleaseRole.NONE:
                raise ValueError("unavailable capability cannot have a release role")
            if self.supported_backends or self.benchmark_evidence:
                raise ValueError("unavailable capability cannot claim backend or benchmark evidence")
        elif self.integration is IntegrationLevel.ABSENT:
            raise ValueError("implemented capability cannot have absent integration")

        if self.release_role is ReleaseRole.GOVERNING:
            if self.integration not in {
                IntegrationLevel.PRODUCTION_PIPELINE,
                IntegrationLevel.OPTIONAL_PIPELINE,
            }:
                raise ValueError("governing capability must be integrated into a pipeline")
            if not self.benchmark_evidence:
                raise ValueError("governing capability must cite benchmark evidence")
        return self


def _record(
    capability_id: str,
    label: str,
    category: CapabilityCategory,
    summary: str,
    maturity: ImplementationMaturity,
    integration: IntegrationLevel,
    role: ReleaseRole,
    *,
    backends: tuple[str, ...] = (),
    evidence: tuple[str, ...] = (),
    limitations: tuple[str, ...] = (),
    version: str = "1.0.0",
) -> CapabilityRecord:
    return CapabilityRecord(
        id=capability_id,
        label=label,
        category=category,
        summary=summary,
        implementation_maturity=maturity,
        integration=integration,
        release_role=role,
        supported_backends=backends,
        benchmark_evidence=evidence,
        limitations=limitations,
        version=version,
    )


def _geometry_records(
    definitions: Iterable[tuple[str, str]],
    *,
    integration: IntegrationLevel,
    role: ReleaseRole,
    evidence: tuple[str, ...],
    limitations: tuple[str, ...],
) -> list[CapabilityRecord]:
    return [
        _record(
            capability_id,
            label,
            CapabilityCategory.GEOMETRY,
            f"Typed {label.lower()} realized by the CadQuery executor.",
            ImplementationMaturity.BOUNDED,
            integration,
            role,
            backends=("cadquery",),
            evidence=evidence,
            limitations=limitations,
        )
        for capability_id, label in definitions
    ]


_PRODUCTION_GEOMETRY = (
    ("box", "Box"),
    ("cylinder", "Cylinder"),
    ("tube", "Tube"),
    ("hole", "Hole"),
    ("rectangular_hole_pattern", "Rectangular hole pattern"),
    ("linear_slot_pattern", "Linear slot pattern"),
    ("chamfer", "Chamfer"),
    ("fillet", "Fillet"),
)

_ADVANCED_GEOMETRY = (
    ("profile_extrude", "Profile extrude"),
    ("profile_pocket", "Profile pocket"),
    ("profile_revolve", "Profile revolve"),
    ("curved_rod_sweep", "Curved rod sweep"),
    ("rectangular_loft", "Rectangular loft"),
    ("curved_strip_sweep", "Curved strip sweep"),
    ("threaded_fastener", "Threaded fastener"),
    ("sheet_metal_90_bend", "90-degree sheet-metal bend"),
)

_SHOWCASE_GEOMETRY = (
    ("flanged_coupling", "Flanged coupling specialization"),
    ("controller_enclosure", "Controller enclosure specialization"),
    ("motor_mount_bracket", "Motor-mount bracket specialization"),
    ("hydraulic_manifold", "Hydraulic manifold specialization"),
    ("blower_transition_duct", "Blower transition duct specialization"),
)


CAPABILITIES: tuple[CapabilityRecord, ...] = tuple([
    _record(
        "deterministic_text_extraction", "Deterministic text extraction",
        CapabilityCategory.EXTRACTION,
        "Parses the bounded plate and mounting vocabulary without a model.",
        ImplementationMaturity.BOUNDED, IntegrationLevel.PRODUCTION_PIPELINE,
        ReleaseRole.GOVERNING,
        evidence=("tests/test_pipeline.py", "eval/report.md#deterministic-pipeline-suite"),
        limitations=("Bounded plate vocabulary; not open-ended language understanding.",),
    ),
    _record(
        "known_row_pdf_extraction", "Known-row PDF extraction",
        CapabilityCategory.EXTRACTION,
        "Reads controlled datasheet rows and their source rectangles with PyMuPDF.",
        ImplementationMaturity.BOUNDED, IntegrationLevel.PRODUCTION_PIPELINE,
        ReleaseRole.GOVERNING,
        evidence=("tests/test_pipeline.py", "eval/report.md#deterministic-pipeline-suite"),
        limitations=("Known rows only; not a general technical-document parser.",),
    ),
    _record(
        "fixture_sketch_extraction", "Recorded sketch fixture",
        CapabilityCategory.EXTRACTION,
        "Replays labelled sketch evidence when no vision provider is configured.",
        ImplementationMaturity.FIXTURE, IntegrationLevel.PRODUCTION_PIPELINE,
        ReleaseRole.GOVERNING,
        evidence=("tests/test_pipeline.py::test_fixture_evidence_cannot_be_scored_as_extraction",),
        limitations=("A recording, excluded from extraction-accuracy metrics.",),
    ),
    _record(
        "openai_multimodal_extraction", "Schema-constrained multimodal extraction",
        CapabilityCategory.EXTRACTION,
        "Maps bounded text, image and PDF evidence through OpenAI or an approved "
        "OpenAI-compatible endpoint into schema-constrained facts and features.",
        ImplementationMaturity.BOUNDED, IntegrationLevel.OPTIONAL_PIPELINE,
        ReleaseRole.GOVERNING,
        evidence=("tests/test_openai_extraction.py",),
        limitations=(
            "Custom endpoints must implement compatible chat completions, image input "
            "when used, and strict JSON schema output; no repeated stochastic benchmark.",
        ),
        version="1.1.0",
    ),
    _record(
        "engineering_intent_graph", "Engineering Intent Graph",
        CapabilityCategory.REPRESENTATION,
        "Immutable authority graph for evidence, dimensions, features, interfaces and requirements.",
        ImplementationMaturity.PROVEN, IntegrationLevel.PRODUCTION_PIPELINE,
        ReleaseRole.GOVERNING,
        evidence=("tests/test_intent_graph.py", "eval/adversarial_generalization_report.md"),
        limitations=("Current production slice has a bounded node and relation vocabulary.",),
    ),
    _record(
        "cad_program", "Typed CADProgram execution IR",
        CapabilityCategory.REPRESENTATION,
        "Ordered typed operations with tagged numeric literals and parameter references.",
        ImplementationMaturity.PROVEN, IntegrationLevel.PRODUCTION_PIPELINE,
        ReleaseRole.GOVERNING, backends=("cadquery",),
        evidence=("tests/test_pipeline.py", "tests/test_advanced_capabilities.py"),
        limitations=("Execution IR, not the backend-neutral Feature IR required by R1; persisted root schema is version 1.0.0.",),
    ),
    _record(
        "cadquery_backend", "CadQuery backend",
        CapabilityCategory.PLATFORM,
        "Primary in-process geometry backend behind the typed backend protocol.",
        ImplementationMaturity.PROVEN, IntegrationLevel.PRODUCTION_PIPELINE,
        ReleaseRole.GOVERNING, backends=("cadquery",),
        evidence=("tests/test_pipeline.py", "eval/adversarial_generalization_report.md", "examples/motor_adapter/r1_reference.json"),
        limitations=("Native editable concepts remain explicitly unavailable in its CSG.",),
    ),
    _record(
        "measured_release_gate", "Measured release gate",
        CapabilityCategory.INSPECTION,
        "Withholds STEP when measured checks or unresolved source conflicts fail.",
        ImplementationMaturity.PROVEN, IntegrationLevel.PRODUCTION_PIPELINE,
        ReleaseRole.GOVERNING,
        evidence=("tests/test_pipeline.py::test_gate_blocks_v1_and_withholds_step", "eval/report.md", "examples/motor_adapter/r1_reference.json"),
        limitations=("Governed quantities are bounded to the currently integrated validators.",),
    ),
    _record(
        "step_round_trip", "STEP round-trip verification",
        CapabilityCategory.INSPECTION,
        "Re-imports STEP and reruns bounded topology, dimension and requirement checks.",
        ImplementationMaturity.BOUNDED, IntegrationLevel.PRODUCTION_PIPELINE,
        ReleaseRole.GOVERNING, backends=("cadquery",),
        evidence=("tests/test_pipeline.py::test_exported_step_revalidates_after_reimport", "eval/adversarial_generalization_report.md", "examples/motor_adapter/r1_reference.json"),
        limitations=("Caller invokes verification explicitly; no artifact manifest or hash yet.",),
    ),
    _record(
        "immutable_repair_revisions", "Immutable repair revisions",
        CapabilityCategory.ENGINEERING,
        "Derives attributed revisions and preserves protected motor-interface parameters.",
        ImplementationMaturity.BOUNDED, IntegrationLevel.PRODUCTION_PIPELINE,
        ReleaseRole.GOVERNING,
        evidence=("tests/test_pipeline.py::test_repair_creates_an_immutable_revision", "eval/report.md"),
        limitations=("Narrow motor/plate repair planner; not general synthesis.",),
    ),
    _record(
        "capability_registry_reporting", "Capability registry reporting",
        CapabilityCategory.PLATFORM,
        "Projects one versioned capability registry into API, UI, README and evaluation reports.",
        ImplementationMaturity.PROVEN, IntegrationLevel.PRODUCTION_PIPELINE,
        ReleaseRole.DIAGNOSTIC,
        evidence=("tests/test_capability_truth_surfaces.py", "tests/test_ui_capability_metadata.py"),
        limitations=("Capability truth is informational; it never authorizes a geometry release by itself.",),
    ),
    *_geometry_records(
        _PRODUCTION_GEOMETRY,
        integration=IntegrationLevel.PRODUCTION_PIPELINE,
        role=ReleaseRole.GOVERNING,
        evidence=("tests/test_pipeline.py", "tests/test_generalized_pipeline.py"),
        limitations=("Bounded selectors and construction cases only.",),
    ),
    *_geometry_records(
        _ADVANCED_GEOMETRY,
        integration=IntegrationLevel.OPTIONAL_PIPELINE,
        role=ReleaseRole.GOVERNING,
        evidence=("tests/test_advanced_capabilities.py", "tests/test_openai_extraction.py"),
        limitations=("Release checks cover topology and operation material change, not full dimensional/interface fidelity.",),
    ),
    *_geometry_records(
        _SHOWCASE_GEOMETRY,
        integration=IntegrationLevel.SHOWCASE,
        role=ReleaseRole.STANDALONE_RESULT,
        evidence=("tests/test_showcase.py",),
        limitations=("Frozen-showcase path constructs Evidence, DesignIntent and CADProgram by hand and bypasses EIG compilation.",),
    ),
    _record(
        "assembly_transforms", "Assembly transforms", CapabilityCategory.ENGINEERING,
        "Places typed component instances in a common coordinate system.",
        ImplementationMaturity.BOUNDED, IntegrationLevel.STANDALONE_API,
        ReleaseRole.STANDALONE_RESULT, backends=("cadquery",),
        evidence=("tests/test_advanced_capabilities.py", "tests/test_api_guardrails.py"),
        limitations=("Not connected to the production release gate.",),
    ),
    _record(
        "assembly_mates", "Assembly mate validation", CapabilityCategory.ENGINEERING,
        "Validates coincident-origin, fixed-offset and concentric-axis relations.",
        ImplementationMaturity.BOUNDED, IntegrationLevel.STANDALONE_API,
        ReleaseRole.STANDALONE_RESULT, backends=("cadquery",),
        evidence=("tests/test_advanced_capabilities.py", "tests/test_api_guardrails.py"),
        limitations=("Validation only; no general mate solver or production gate integration.",),
    ),
    _record(
        "collision_check", "Assembly collision check", CapabilityCategory.ENGINEERING,
        "Measures pairwise B-Rep intersection volume.",
        ImplementationMaturity.BOUNDED, IntegrationLevel.STANDALONE_API,
        ReleaseRole.STANDALONE_RESULT, backends=("cadquery",),
        evidence=("tests/test_advanced_capabilities.py", "tests/test_api_guardrails.py"),
        limitations=("Standalone assembly endpoint only.",),
    ),
    *[
        _record(
            capability_id, label, CapabilityCategory.INSPECTION,
            f"Measures bounded {label.lower()} controls on a CadQuery B-Rep.",
            ImplementationMaturity.BOUNDED, IntegrationLevel.STANDALONE_API,
            ReleaseRole.STANDALONE_RESULT, backends=("cadquery",),
            evidence=("tests/test_advanced_capabilities.py", "tests/test_api_guardrails.py"),
            limitations=("Standalone inspection endpoint; not connected to production release.",),
        )
        for capability_id, label in (
            ("gdt_size", "GD&T size"), ("gdt_position", "GD&T position"),
            ("gdt_flatness", "GD&T flatness"),
            ("gdt_perpendicularity", "GD&T perpendicularity"),
        )
    ],
    *[
        _record(
            capability_id, label, CapabilityCategory.ENGINEERING,
            f"Runs bounded {label.lower()} calculations from explicit inputs.",
            ImplementationMaturity.BOUNDED, IntegrationLevel.STANDALONE_API,
            ReleaseRole.STANDALONE_RESULT, backends=("cadquery",),
            evidence=("tests/test_advanced_capabilities.py", "tests/test_api_guardrails.py"),
            limitations=("Standalone analysis endpoint; not revision-bound or release-governing.",),
        )
        for capability_id, label in (
            ("mass_properties", "Mass properties"),
            ("axial_stress", "Axial stress"),
            ("bending_stress", "Bending stress"),
            ("thermal_expansion", "Thermal expansion"),
            ("worst_case_fit", "Worst-case fit"),
        )
    ],
    *[
        _record(
            capability_id, label, category, summary,
            ImplementationMaturity.UNAVAILABLE, IntegrationLevel.ABSENT,
            ReleaseRole.NONE, limitations=(limitation,), version="0.0.0",
        )
        for capability_id, label, category, summary, limitation in (
            (
                "feature_ir", "Feature IR", CapabilityCategory.REPRESENTATION,
                "Backend-neutral parametric realization plan.",
                "Schema 1.0.0, motor-adapter compiler, fail-closed validator, canonical hashing and governed CadQuery parity are implemented; production backend-protocol adoption remains R1.2 work.",
            ),
            (
                "backend_protocol", "Typed backend protocol", CapabilityCategory.PLATFORM,
                "Versioned build, inspection and export contracts.",
                "Planned for R1.2.",
            ),
            (
                "freecad_backend", "FreeCAD backend", CapabilityCategory.PLATFORM,
                "Out-of-process native editable FreeCAD realization.",
                "Planned for R1.3.",
            ),
            (
                "cad_state_graph", "CAD State Graph", CapabilityCategory.REPRESENTATION,
                "Immutable observation of backend-native build state.",
                "Planned for R1.3.",
            ),
            (
                "cross_backend_reconciliation", "Cross-backend reconciliation",
                CapabilityCategory.INSPECTION,
                "Typed comparison of governed observations from two backends.",
                "R1 tolerance policy 1.0.0 is defined; actual reconciliation remains planned for R1.4 because only CadQuery exists today.",
            ),
        )
    ],
])

# R1.1 establishes a bounded, parity-proven library contract without yet
# switching the production pipeline to the backend protocol.
_feature_ir_index = next(
    index for index, item in enumerate(CAPABILITIES) if item.id == "feature_ir"
)
_feature_ir_record = CAPABILITIES[_feature_ir_index].model_copy(update={
    "implementation_maturity": ImplementationMaturity.BOUNDED,
    "integration": IntegrationLevel.PRODUCTION_PIPELINE,
    "benchmark_evidence": (
        "tests/test_feature_ir_schema.py",
        "tests/test_feature_ir_schema.py::test_provenance_traverses_an_actual_motor_adapter_eig",
        "tests/test_feature_ir_compiler.py",
        "tests/test_feature_ir_validation.py",
        "tests/test_feature_ir_serialization.py",
        "tests/test_feature_ir_parity.py",
    ),
    "limitations": (
        "The bounded primitive/feature vocabulary is integrated; advanced geometry families retain the transitional CADProgram path.",
    ),
    "version": "1.0.0",
})
CAPABILITIES = (
    *CAPABILITIES[:_feature_ir_index],
    _feature_ir_record,
    *CAPABILITIES[_feature_ir_index + 1:],
)

# R1.2.1-R1.2.2 define serializable messages and semantic operation contracts;
# production adapters are introduced by the remaining R1.2 increments.
_backend_protocol_index = next(
    index for index, item in enumerate(CAPABILITIES) if item.id == "backend_protocol"
)
_backend_protocol_record = CAPABILITIES[_backend_protocol_index].model_copy(update={
    "implementation_maturity": ImplementationMaturity.BOUNDED,
    "integration": IntegrationLevel.PRODUCTION_PIPELINE,
    "supported_backends": ("cadquery", "freecad"),
    "benchmark_evidence": (
        "tests/test_backend_contracts.py",
        "tests/test_backend_protocol.py",
        "tests/test_cadquery_adapter.py",
        "tests/test_cadquery_import_boundary.py",
        "tests/test_freecad_adapter.py",
        "tests/test_feature_ir_parity.py",
    ),
    "limitations": (
        "CadQuery and FreeCAD implement the versioned operation boundary for the bounded primitive/feature vocabulary; advanced families remain internally adapted.",
    ),
    "version": "1.0.0",
})
CAPABILITIES = (
    *CAPABILITIES[:_backend_protocol_index],
    _backend_protocol_record,
    *CAPABILITIES[_backend_protocol_index + 1:],
)

# R1.3.1 introduces the observation schema before either backend emits it.
_csg_index = next(
    index for index, item in enumerate(CAPABILITIES) if item.id == "cad_state_graph"
)
_csg_record = CAPABILITIES[_csg_index].model_copy(update={
    "implementation_maturity": ImplementationMaturity.BOUNDED,
    "integration": IntegrationLevel.OPTIONAL_PIPELINE,
    "supported_backends": ("cadquery", "freecad"),
    "benchmark_evidence": (
        "tests/test_cad_state_graph_schema.py",
        "tests/test_cad_state_graph_schema.py::test_all_relationship_kinds_are_typed_and_provenance_resolves",
        "tests/test_freecad_worker.py::test_real_worker_builds_native_editable_motor_document",
        "tests/test_cadquery_adapter.py::test_adapter_build_and_inspect_both_motor_revisions",
        "tests/test_r1_native_foundation_benchmark.py",
        "eval/r1_native_foundation_report.json",
    ),
    "release_role": ReleaseRole.DIAGNOSTIC,
    "limitations": (
        "Both backends emit truthful immutable CSGs for four bounded compositions; the CSG remains evidence and never design authority.",
    ),
    "version": "1.0.0",
})
CAPABILITIES = (
    *CAPABILITIES[:_csg_index],
    _csg_record,
    *CAPABILITIES[_csg_index + 1:],
)

# R1.3.4-R1.3.5 prove the real isolated worker and a native editable motor model;
# CSG extraction, full artifacts and reconciliation are subsequent increments.
_freecad_index = next(
    index for index, item in enumerate(CAPABILITIES) if item.id == "freecad_backend"
)
_freecad_record = CAPABILITIES[_freecad_index].model_copy(update={
    "implementation_maturity": ImplementationMaturity.BOUNDED,
    "integration": IntegrationLevel.OPTIONAL_PIPELINE,
    "supported_backends": ("freecad",),
    "benchmark_evidence": (
        "tests/test_freecad_worker.py::test_real_freecad_worker_ping_when_runtime_is_available",
        "tests/test_freecad_worker.py::test_real_worker_builds_native_editable_motor_document",
        "tests/test_freecad_worker.py::test_real_worker_returns_typed_refusal_for_unsupported_selector",
        "tests/test_cad_state_graph_schema.py",
        "tests/test_freecad_adapter.py",
        "tests/test_r1_native_foundation_benchmark.py",
        "eval/r1_native_foundation_report.json",
    ),
    "release_role": ReleaseRole.DIAGNOSTIC,
    "limitations": (
        "FreeCAD 1.1 structurally realizes the bounded primitive/feature vocabulary with stable-ID native edits; surfacing, assemblies and arbitrary features remain unsupported.",
    ),
    "version": "1.0.0",
})
CAPABILITIES = (
    *CAPABILITIES[:_freecad_index],
    _freecad_record,
    *CAPABILITIES[_freecad_index + 1:],
)

# R1.4 defines evidence-layered, benchmarked release reconciliation for B.R1.
_reconciliation_index = next(
    index for index, item in enumerate(CAPABILITIES)
    if item.id == "cross_backend_reconciliation"
)
_reconciliation_record = CAPABILITIES[_reconciliation_index].model_copy(update={
    "implementation_maturity": ImplementationMaturity.BOUNDED,
    "integration": IntegrationLevel.OPTIONAL_PIPELINE,
    "supported_backends": ("cadquery", "freecad"),
    "benchmark_evidence": (
        "tests/test_reconciliation_tolerances.py",
        "tests/test_reconciliation_observations.py",
        "tests/test_cross_backend_geometry.py",
        "tests/test_cross_backend_predicates.py",
        "tests/test_reconciliation_release_gate.py",
        "tests/test_r1_native_foundation_benchmark.py",
        "eval/r1_native_foundation_report.json",
    ),
    "release_role": ReleaseRole.GOVERNING,
    "limitations": (
        "Release-governing comparison remains motor-adapter bounded; four broader compositions have advisory solid/cylindrical cross-backend checks.",
    ),
    "version": "1.0.0",
})
CAPABILITIES = (
    *CAPABILITIES[:_reconciliation_index],
    _reconciliation_record,
    *CAPABILITIES[_reconciliation_index + 1:],
)

# R1H broadens the shared bounded vocabulary without implying universal CAD.
_R1H_GEOMETRY_IDS = {item[0] for item in _PRODUCTION_GEOMETRY}
CAPABILITIES = tuple(
    item.model_copy(update={
        "summary": f"Typed {item.label.lower()} structurally realized through shared Feature IR.",
        "supported_backends": ("cadquery", "freecad"),
        "benchmark_evidence": tuple(dict.fromkeys((
            *item.benchmark_evidence, "tests/test_r1h_broad_cad.py",
        ))),
        "limitations": (
            "Bounded construction and semantic selectors only; not arbitrary CAD.",
        ),
    }) if item.id in _R1H_GEOMETRY_IDS else item
    for item in CAPABILITIES
)


_BY_ID = {item.id: item for item in CAPABILITIES}
if len(_BY_ID) != len(CAPABILITIES):
    raise RuntimeError("capability ids must be unique")


# Backwards-compatible selection for the original `/health.capabilities` list.
# The detailed records still come from CAPABILITIES; this tuple only defines the
# compact subset exposed by the pre-R1 API.
HEALTH_CAPABILITY_IDS: tuple[str, ...] = (
    "box", "cylinder", "tube", "hole", "rectangular_hole_pattern",
    "linear_slot_pattern", "chamfer", "fillet", "profile_extrude",
    "profile_pocket", "profile_revolve", "curved_rod_sweep",
    "rectangular_loft", "curved_strip_sweep", "threaded_fastener",
    "sheet_metal_90_bend", "assembly_transforms", "assembly_mates",
    "collision_check", "gdt_size", "gdt_position", "gdt_flatness",
    "gdt_perpendicularity", "mass_properties", "axial_stress",
    "bending_stress", "thermal_expansion", "worst_case_fit",
)
if not set(HEALTH_CAPABILITY_IDS) <= set(_BY_ID):
    raise RuntimeError("health capability selection contains an unknown id")


def capability(capability_id: str) -> CapabilityRecord:
    try:
        return _BY_ID[capability_id]
    except KeyError as exc:
        raise KeyError(f"unknown capability {capability_id!r}") from exc


def capability_payload() -> dict:
    """Return a deterministic JSON-compatible registry document."""
    return {
        "schema_version": CAPABILITY_SCHEMA_VERSION,
        "capabilities": [item.model_dump(mode="json") for item in CAPABILITIES],
    }
