"""Evidence: a single engineering fact observed from one source.

Three things that are easy to conflate are kept strictly separate:

  kind        -- what *sort* of observation this is (a linear dimension, a
                 thread callout, a material spec ...). A property of the mark
                 on the page.
  target      -- which design parameter the observation *informs*. A property
                 of the engineering meaning.
  confidence  -- how sure the extractor is that it *read the source correctly*.
  authority   -- whether this source is *entitled to define* this target.

confidence and authority are orthogonal and are never multiplied into a single
score. A blurry photo of a datasheet is low-confidence but definitive-authority;
a crisp value scaled off a sketch is high-confidence but advisory-authority.
Collapsing them loses exactly the distinction that makes fusion defensible.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from spec2cad.schemas.advanced_intent import FeatureIntent
from spec2cad.schemas.agent import AgentPlan


class EvidenceKind(str, Enum):
    """What sort of observation was made -- a property of the source mark."""

    LINEAR_DIMENSION = "linear_dimension"
    DIAMETER = "diameter"
    HOLE_PATTERN = "hole_pattern"
    THREAD_CALLOUT = "thread_callout"
    MATERIAL_SPEC = "material_spec"
    PROCESS_SPEC = "process_spec"
    COUNT = "count"
    CONSTRAINT = "constraint"
    FEATURE_CALLOUT = "feature_callout"
    NOTE = "note"


class SemanticTarget(str, Enum):
    """Which design parameter the observation informs.

    Deliberately a closed set for v1. An extractor that wants to report
    something outside this vocabulary must fail loudly rather than invent a
    parameter name that nothing downstream understands.
    """

    PLATE_WIDTH = "plate_width"
    PLATE_HEIGHT = "plate_height"
    PLATE_THICKNESS = "plate_thickness"
    HOLE_SPACING_X = "hole_spacing_x"
    HOLE_SPACING_Y = "hole_spacing_y"
    MOUNTING_HOLE_COUNT = "mounting_hole_count"
    MOUNTING_HOLE_DIAMETER = "mounting_hole_diameter"
    MOUNTING_THREAD_SPEC = "mounting_thread_spec"
    MOTOR_BOSS_DIAMETER = "motor_boss_diameter"
    SHAFT_OPENING_DIAMETER = "shaft_opening_diameter"
    MATERIAL = "material"
    MANUFACTURING_PROCESS = "manufacturing_process"
    MIN_HOLE_EDGE_CLEARANCE = "min_hole_edge_clearance"
    EXTERNAL_CHAMFER = "external_chamfer"
    EXTERNAL_FILLET = "external_fillet"
    SLOT_COUNT = "slot_count"
    SLOT_WIDTH = "slot_width"
    SLOT_LENGTH = "slot_length"
    SLOT_SPACING_X = "slot_spacing_x"
    SLOT_ANGLE = "slot_angle"
    PART_TYPE = "part_type"
    OUTER_DIAMETER = "outer_diameter"
    INNER_DIAMETER = "inner_diameter"
    BODY_LENGTH = "body_length"
    WALL_THICKNESS = "wall_thickness"
    SHEET_LEG_A = "sheet_leg_a"
    SHEET_LEG_B = "sheet_leg_b"
    SHEET_WIDTH = "sheet_width"
    SHEET_THICKNESS = "sheet_thickness"
    INSIDE_BEND_RADIUS = "inside_bend_radius"
    BEND_ANGLE = "bend_angle"
    K_FACTOR = "k_factor"
    ROD_DIAMETER = "rod_diameter"
    ROD_TOTAL_LENGTH = "rod_total_length"
    ROD_BEND_START = "rod_bend_start"
    ROD_BEND_RADIUS = "rod_bend_radius"
    ROD_BEND_ANGLE = "rod_bend_angle"
    PROFILE_DEFINITION = "profile_definition"
    LOFT_START_WIDTH = "loft_start_width"
    LOFT_START_HEIGHT = "loft_start_height"
    LOFT_END_WIDTH = "loft_end_width"
    LOFT_END_HEIGHT = "loft_end_height"
    LOFT_LENGTH = "loft_length"
    STRIP_WIDTH = "strip_width"
    STRIP_THICKNESS = "strip_thickness"
    STRIP_SHANK_LENGTH = "strip_shank_length"
    STRIP_BEND_RADIUS = "strip_bend_radius"
    STRIP_BEND_ANGLE = "strip_bend_angle"
    STRIP_TAIL_LENGTH = "strip_tail_length"
    FASTENER_MAJOR_DIAMETER = "fastener_major_diameter"
    THREAD_PITCH = "thread_pitch"
    THREADED_LENGTH = "threaded_length"
    FASTENER_SHANK_LENGTH = "fastener_shank_length"
    HEAD_ACROSS_FLATS = "head_across_flats"
    HEAD_HEIGHT = "head_height"
    FLANGE_DIAMETER = "flange_diameter"
    FLANGE_THICKNESS = "flange_thickness"
    HUB_DIAMETER = "hub_diameter"
    HUB_LENGTH = "hub_length"
    BORE_DIAMETER = "bore_diameter"
    KEYWAY_WIDTH = "keyway_width"
    BOLT_CIRCLE_DIAMETER = "bolt_circle_diameter"
    SET_SCREW_THREAD = "set_screw_thread"
    SET_SCREW_DEPTH = "set_screw_depth"
    ENCLOSURE_LENGTH = "enclosure_length"
    ENCLOSURE_WIDTH = "enclosure_width"
    ENCLOSURE_HEIGHT = "enclosure_height"
    DISPLAY_CUTOUT = "display_cutout"
    CUTOUT_POSITION = "cutout_position"
    GENERAL_TOLERANCE = "general_tolerance"
    PORT_LABEL = "port_label"
    PORT_MAJOR_DIAMETER = "port_major_diameter"
    PORT_MINOR_DIAMETER = "port_minor_diameter"
    TAPPING_DEPTH = "tapping_depth"
    SEALING_FACE_DIAMETER = "sealing_face_diameter"
    INSTALLATION_CLEARANCE = "installation_clearance"
    MAX_PRESSURE = "max_pressure"
    MIN_WALL_THICKNESS = "min_wall_thickness"
    PASSAGE_DIAMETER = "passage_diameter"
    PORT_SPACING = "port_spacing"
    DUCT_INLET_WIDTH = "duct_inlet_width"
    DUCT_INLET_HEIGHT = "duct_inlet_height"
    DUCT_OUTLET_DIAMETER = "duct_outlet_diameter"
    TRANSITION_LENGTH = "transition_length"
    FLANGE_WIDTH = "flange_width"
    SEALING_BEAD = "sealing_bead"
    MOULD_DRAFT = "mould_draft"
    MAX_TRANSITION_ANGLE = "max_transition_angle"
    MIN_INTERFACE_SEPARATION = "min_interface_separation"
    RIB_COUNT = "rib_count"
    ORIENTATION_NOTE = "orientation_note"


class SourceModality(str, Enum):
    SKETCH = "sketch"
    DATASHEET = "datasheet"
    REQUIREMENT_TEXT = "requirement_text"
    ENGINEERING_RULE = "engineering_rule"


class ExtractionMethod(str, Enum):
    """How the value was obtained. Surfaced per-row in the UI so the demo can
    never overclaim what was actually machine-read."""

    PDF_TEXT_LAYOUT = "pdf_text_layout"      # real PyMuPDF parse, real bbox
    RULE_PARSER = "rule_parser"              # deterministic regex/grammar
    REASONING_MODEL = "reasoning_model"      # structured semantic extraction
    KNOWLEDGE_TABLE = "knowledge_table"      # derived via a cited standard
    VISION_MODEL = "vision_model"            # genuine multimodal extraction
    RECORDED_FIXTURE = "recorded_fixture"    # replayed; never counts as extraction


class Authority(str, Enum):
    """Whether this source is entitled to *define* this target.

    Ordering matters for fusion, but see fusion/source_policy.py: authority
    alone never silently overrides an explicit annotation.
    """

    DEFINITIVE = "definitive"    # owns the fact (the datasheet owns the interface)
    SUPPORTING = "supporting"    # corroborates a definitive source
    ADVISORY = "advisory"        # inferred / scaled off / approximate

    @property
    def rank(self) -> int:
        return {"definitive": 3, "supporting": 2, "advisory": 1}[self.value]


class SourceRef(BaseModel):
    """Where the value physically came from, precisely enough to highlight it."""

    model_config = ConfigDict(extra="forbid")

    file: str
    modality: SourceModality
    page: Optional[int] = Field(
        default=None, description="1-based page number; None for images/text"
    )
    region: Optional[tuple[float, float, float, float]] = Field(
        default=None,
        description="(x0, y0, x1, y1) in the source's own coordinate space. "
        "For PDFs these are true PyMuPDF rect coords; for images, pixels.",
    )
    detail: Optional[str] = Field(
        default=None, description="e.g. a cited standard clause for rule-derived values"
    )


class Evidence(BaseModel):
    """One extracted engineering fact, fully attributed."""

    model_config = ConfigDict(extra="forbid")

    id: str
    entity: str = Field(description="the physical thing the fact is about")
    kind: EvidenceKind
    target: SemanticTarget

    value: float | int | str
    unit: Optional[str] = Field(
        default=None, description="normalised unit; None for non-dimensional values"
    )

    source: SourceRef
    extraction_method: ExtractionMethod

    confidence: float = Field(
        ge=0.0, le=1.0, description="certainty the source was READ correctly"
    )
    authority: Authority = Field(
        description="entitlement to DEFINE this target; orthogonal to confidence"
    )

    is_explicit_annotation: bool = Field(
        description="True when the source states this value outright (a dimension "
        "written on a drawing, a table cell in a datasheet). Such a value is EXACT "
        "evidence, not an approximation, regardless of modality. False only for "
        "values inferred or scaled off geometry."
    )

    raw_text: Optional[str] = Field(
        default=None, description="verbatim source text, pre-normalisation"
    )
    original_value: Optional[str] = Field(
        default=None, description="pre-unit-conversion literal, e.g. '1.575 in'"
    )
    extracted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def is_fixture(self) -> bool:
        """Fixture-replayed evidence. eval/metrics.py asserts these never reach
        a reported extraction-accuracy number."""
        return self.extraction_method is ExtractionMethod.RECORDED_FIXTURE

    def describe(self) -> str:
        unit = f" {self.unit}" if self.unit else ""
        loc = f" p.{self.source.page}" if self.source.page else ""
        return f"{self.target.value} = {self.value}{unit} [{self.source.modality.value}{loc}]"


class EvidenceSet(BaseModel):
    """All evidence gathered for one run, plus how it was gathered."""

    model_config = ConfigDict(extra="forbid")

    items: list[Evidence] = Field(default_factory=list)
    backend_used: str = Field(
        default="unknown",
        description="which extractor backend ran, recorded whether or not a key was present",
    )
    reasoning_backend: str = "not used (no requirement supplied)"
    reasoning_fell_back: bool = False
    reasoning_fallback_reason: Optional[str] = None
    unsupported_features: list[str] = Field(default_factory=list)
    clarification_questions: list[str] = Field(default_factory=list)
    agent_plan: Optional[AgentPlan] = None
    feature_requests: list[FeatureIntent] = Field(
        default_factory=list,
        description="schema-validated advanced feature intents carried into the EIG",
    )

    def by_target(self, target: SemanticTarget) -> list[Evidence]:
        return [e for e in self.items if e.target is target]

    def get(self, evidence_id: str) -> Optional[Evidence]:
        return next((e for e in self.items if e.id == evidence_id), None)

    @property
    def targets(self) -> set[SemanticTarget]:
        return {e.target for e in self.items}

    @property
    def contains_fixture_data(self) -> bool:
        return any(e.is_fixture for e in self.items)
