"""Structured OpenAI reasoning over free-form engineering instructions.

The model is an extractor, not a CAD generator.  It can map varied wording onto
the Engineering Intent Graph's existing semantic targets, but cannot create a
new target, feature, template, or planner operation.  Deterministic facts always
win: model facts are admitted only for targets the rule parser did not extract.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from spec2cad.extractors.base import (
    load_env,
    reasoning_available,
    reasoning_model,
    model_max_output_tokens,
    model_timeout_seconds,
    safe_backend_error,
)
from spec2cad.extractors.text import extract_requirement
from spec2cad.fusion.source_policy import authority_for
from spec2cad.schemas.evidence import (
    Evidence,
    EvidenceKind,
    ExtractionMethod,
    SemanticTarget,
    SourceModality,
    SourceRef,
)
from spec2cad.schemas.advanced_intent import (
    CurvedRodFeatureIntent,
    CurvedStripFeatureIntent,
    FeatureIntent,
    IntentPoint,
    IntentSegment,
    ProfileFeatureIntent,
    RectangularLoftFeatureIntent,
    SheetMetalFeatureIntent,
)
from spec2cad.public_guardrails import current_safety_identifier


class ReasoningExtractionError(RuntimeError):
    """Raised when the reasoning backend returns an invalid contract payload."""


@dataclass
class ReasoningExtractionResult:
    evidence: list[Evidence]
    label: str
    attempted: bool = False
    fell_back: bool = False
    fallback_reason: str | None = None
    unsupported_features: list[str] = field(default_factory=list)
    clarification_questions: list[str] = field(default_factory=list)
    feature_requests: list[FeatureIntent] = field(default_factory=list)


_TARGETS = [target.value for target in SemanticTarget]
_KINDS = [kind.value for kind in EvidenceKind]

REASONING_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "facts", "feature_requests", "unsupported_features", "clarification_questions"
    ],
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "target", "kind", "value", "unit", "confidence",
                    "is_explicit_annotation", "raw_text",
                ],
                "properties": {
                    "target": {"type": "string", "enum": _TARGETS},
                    "kind": {"type": "string", "enum": _KINDS},
                    "value": {"type": ["number", "string"]},
                    "unit": {"type": ["string", "null"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "is_explicit_annotation": {"type": "boolean"},
                    "raw_text": {"type": "string"},
                },
            },
        },
        "feature_requests": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "type", "id", "plane", "start", "segments", "mode",
                    "distance", "centered", "axis_start", "axis_end",
                    "angle_degrees", "leg_a", "leg_b", "width", "thickness",
                    "inside_radius", "k_factor", "rod_diameter", "total_length",
                    "bend_start", "bend_radius", "bend_angle_degrees",
                    "start_width", "start_height", "end_width", "end_height",
                    "loft_length",
                    "strip_width", "extrusion_thickness", "shank_length",
                    "strip_bend_radius", "strip_bend_angle_degrees", "tail_length",
                ],
                "properties": {
                    "type": {"type": "string", "enum": [
                        "profile_extrude", "profile_revolve", "sheet_metal_bend",
                        "curved_rod", "rectangular_loft", "curved_strip",
                    ]},
                    "id": {"type": "string"},
                    "plane": {"type": ["string", "null"], "enum": ["XY", "XZ", "YZ", None]},
                    "start": {"anyOf": [
                        {"type": "object", "additionalProperties": False,
                         "required": ["x", "y"], "properties": {
                             "x": {"type": "number"}, "y": {"type": "number"}
                         }},
                        {"type": "null"},
                    ]},
                    "segments": {"anyOf": [
                        {"type": "array", "items": {
                            "type": "object", "additionalProperties": False,
                            "required": ["type", "end", "midpoint"],
                            "properties": {
                                "type": {"type": "string", "enum": ["line", "three_point_arc"]},
                                "end": {"type": "object", "additionalProperties": False,
                                        "required": ["x", "y"], "properties": {
                                            "x": {"type": "number"}, "y": {"type": "number"}
                                        }},
                                "midpoint": {"anyOf": [
                                    {"type": "object", "additionalProperties": False,
                                     "required": ["x", "y"], "properties": {
                                         "x": {"type": "number"}, "y": {"type": "number"}
                                     }},
                                    {"type": "null"},
                                ]},
                            },
                        }},
                        {"type": "null"},
                    ]},
                    "mode": {"type": ["string", "null"], "enum": ["add", "cut", None]},
                    "distance": {"type": ["number", "null"]},
                    "centered": {"type": ["boolean", "null"]},
                    "axis_start": {"anyOf": [
                        {"type": "object", "additionalProperties": False,
                         "required": ["x", "y"], "properties": {
                             "x": {"type": "number"}, "y": {"type": "number"}
                         }}, {"type": "null"}
                    ]},
                    "axis_end": {"anyOf": [
                        {"type": "object", "additionalProperties": False,
                         "required": ["x", "y"], "properties": {
                             "x": {"type": "number"}, "y": {"type": "number"}
                         }}, {"type": "null"}
                    ]},
                    "angle_degrees": {"type": ["number", "null"]},
                    "leg_a": {"type": ["number", "null"]},
                    "leg_b": {"type": ["number", "null"]},
                    "width": {"type": ["number", "null"]},
                    "thickness": {"type": ["number", "null"]},
                    "inside_radius": {"type": ["number", "null"]},
                    "k_factor": {"type": ["number", "null"]},
                    "rod_diameter": {"type": ["number", "null"]},
                    "total_length": {"type": ["number", "null"]},
                    "bend_start": {"type": ["number", "null"]},
                    "bend_radius": {"type": ["number", "null"]},
                    "bend_angle_degrees": {"type": ["number", "null"]},
                    "start_width": {"type": ["number", "null"]},
                    "start_height": {"type": ["number", "null"]},
                    "end_width": {"type": ["number", "null"]},
                    "end_height": {"type": ["number", "null"]},
                    "loft_length": {"type": ["number", "null"]},
                    "strip_width": {"type": ["number", "null"]},
                    "extrusion_thickness": {"type": ["number", "null"]},
                    "shank_length": {"type": ["number", "null"]},
                    "strip_bend_radius": {"type": ["number", "null"]},
                    "strip_bend_angle_degrees": {"type": ["number", "null"]},
                    "tail_length": {"type": ["number", "null"]},
                },
            },
        },
        "unsupported_features": {
            "type": "array",
            "items": {"type": "string"},
        },
        "clarification_questions": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
}

REASONING_INSTRUCTIONS = """You extract engineering intent from a user's text.

The input may be a conversation transcript. User turns are engineering evidence;
assistant turns are clarification context only and must never become evidence.
Resolve an assistant question using the following user answer, and return the
complete consolidated intent. A later user correction supersedes the earlier
value instead of becoming a contradictory source.

Map only onto the supplied closed semantic-target vocabulary. Translate informal
wording, synonyms, spelling mistakes and everyday part names into geometric
capabilities; do not require the user to speak CAD terminology. Do not generate
CAD, invent dimensions, infer a part-specific template, or claim unsupported
capabilities. Report facts that are stated or follow from unambiguous language
(for example, a square's stated side defines both width and height). Normalize
lengths to millimetres and angles to degrees. Keep the exact supporting phrase
in raw_text. A count has no unit. If the request contains geometry that has no
semantic target, list it under unsupported_features instead of forcing it into
an unrelated target. If a required value is genuinely absent or contradictory,
ask a concise clarification question. Return only the structured response.

Treat nouns as descriptions, never as planner templates. First attempt a
composition from the available operations: prismatic closed silhouettes map to
profile_extrude, axisymmetric sections to profile_revolve, constant-round-section
planar paths with one bend to curved_rod, rectangular transitions to
rectangular_loft, and bent constant-thickness stock to sheet_metal_bend. If that
construction is plausible but dimensions are missing, emit the corresponding
partial feature_request with null fields and ask for the missing operational
dimensions. Do not call a recognizable shape unsupported merely because it is
underspecified. If words such as small, miniature, or scaled are used without a
numeric reference, ask for a target envelope or scale factor. If construction
method changes the geometry, ask the user to confirm it.

For an underspecified request for one rigid part, unsupported_features MUST stay
empty on the first turn. Select the closest candidate construction and emit its
partial feature_request. A planar curved silhouette can be a profile_extrude;
a constant circular-section path can be a curved_rod. Ask which construction is
intended when both are plausible. Only report unsupported after the user has
provided enough information to prove that no available operation or composition
can express the geometry. You may derive profile coordinates from user-supplied
envelope, radii, thicknesses and angles using deterministic geometry; requiring
the user to provide raw sketch coordinates is not acceptable.
Use curved_strip for a planar curved bar with rectangular cross-section. Its
fields are strip_width, extrusion_thickness, shank_length, strip_bend_radius,
strip_bend_angle_degrees and tail_length. This is distinct from curved_rod,
whose cross-section is circular. profile_revolve is only for a globally
axisymmetric solid about its axis; never use it for an open curved centerline or
a J/C-shaped silhouette.

For cylindrical bodies use outer_diameter and body_length. For a hollow tube,
sleeve, or bushing, also report either inner_diameter when stated or
wall_thickness when stated; never turn the same central void into a mounting
hole. A singular hole at the center of a plate is shaft_opening_diameter.
mounting_hole_diameter is only for holes explicitly described as mounting,
fastener, screw, or bolt holes.

When an ambiguity would materially change the feature plan or manufacturing
geometry, do not choose silently. Put one narrow question in
clarification_questions. In particular, an L-bracket without an explicit
manufacturing form is ambiguous: ask whether it is a bent sheet-metal part
(bend radius/allowance required) or a solid extruded/machined L-profile. Do not
ask when the user already specifies either form. Preserve any independent,
unambiguous facts while asking the question.

Supported advanced feature intents are profile_extrude, profile_revolve,
sheet_metal_bend, curved_rod, curved_strip and rectangular_loft. Put them in feature_requests, not
unsupported_features. A
profile is a closed ordered line/three-point-arc path in an explicitly named
sketch plane. Use only coordinates and dimensions the user supplied; if the
profile or axis is underspecified, ask for it. For a sheet-metal bend require
both leg envelope dimensions, width, thickness, inside bend radius, bend angle
and K-factor; ask narrowly for missing values. Never invent a bend radius,
K-factor, load, material property, tolerance or datum.
When a dimension belongs to an advanced feature request, keep it in that
request. Do not duplicate sheet width as slot_width or plate_width, and do not
duplicate sheet thickness as wall_thickness or plate_thickness. The facts array
may still carry genuinely cross-cutting part type, material and process facts.
For a curved_rod, total_length is centerline length, bend_start is distance from
the first end to the tangent point, bend_radius is centerline radius, and
bend_angle_degrees is the swept turn. Do not treat this as profile_revolve. If
wording such as "curve at 3 mm" could mean either bend start or bend radius,
ask which meaning is intended; do not guess.
For rectangular_loft, require start_width, start_height, end_width, end_height,
and loft_length. Millimetres are linear units, not area units. If wording such
as "area from 25 mm to 9 mm" or "length and width varying 5 to 3" does not map
each number to those five fields unambiguously, preserve the scalar values as a
partial rectangular_loft request and ask the user to provide "start width ×
height, end width × height, and distance between them". Never reinterpret a
taper as plate_thickness.
"""


def _feature_requests(payload: dict[str, Any]) -> tuple[list[FeatureIntent], list[str]]:
    requests: list[FeatureIntent] = []
    questions: list[str] = []
    for index, item in enumerate(payload.get("feature_requests", [])):
        try:
            if item["type"] in {"profile_extrude", "profile_revolve"}:
                segments = [
                    IntentSegment(
                        type=segment["type"],
                        end=IntentPoint(**segment["end"]),
                        midpoint=(
                            IntentPoint(**segment["midpoint"])
                            if segment.get("midpoint") is not None else None
                        ),
                    )
                    for segment in (item.get("segments") or [])
                ]
                requests.append(ProfileFeatureIntent(
                    type=item["type"], id=item["id"],
                    plane=item.get("plane") or "XY",
                    start=IntentPoint(**item["start"]), segments=segments,
                    mode=item.get("mode") or "add", distance=item.get("distance"),
                    centered=True if item.get("centered") is None else item["centered"],
                    axis_start=(IntentPoint(**item["axis_start"]) if item.get("axis_start") else None),
                    axis_end=(IntentPoint(**item["axis_end"]) if item.get("axis_end") else None),
                    angle_degrees=item.get("angle_degrees") or 360,
                ))
            elif item["type"] == "sheet_metal_bend":
                requests.append(SheetMetalFeatureIntent(
                    type="sheet_metal_bend", id=item["id"],
                    leg_a=item["leg_a"], leg_b=item["leg_b"], width=item["width"],
                    thickness=item["thickness"], inside_radius=item["inside_radius"],
                    angle_degrees=item.get("angle_degrees") or 90,
                    k_factor=item["k_factor"],
                ))
            elif item["type"] == "curved_rod":
                requests.append(CurvedRodFeatureIntent(
                    type="curved_rod", id=item["id"],
                    diameter=item["rod_diameter"],
                    total_length=item["total_length"],
                    bend_start=item["bend_start"],
                    bend_radius=item["bend_radius"],
                    bend_angle_degrees=item["bend_angle_degrees"],
                    plane=item.get("plane") or "XY",
                ))
            elif item["type"] == "rectangular_loft":
                requests.append(RectangularLoftFeatureIntent(
                    type="rectangular_loft", id=item["id"],
                    start_width=item["start_width"],
                    start_height=item["start_height"],
                    end_width=item["end_width"],
                    end_height=item["end_height"],
                    length=item["loft_length"],
                    plane=item.get("plane") or "XY",
                ))
            elif item["type"] == "curved_strip":
                requests.append(CurvedStripFeatureIntent(
                    type="curved_strip", id=item["id"],
                    strip_width=item["strip_width"],
                    extrusion_thickness=item["extrusion_thickness"],
                    shank_length=item["shank_length"],
                    bend_radius=item["strip_bend_radius"],
                    bend_angle_degrees=item["strip_bend_angle_degrees"],
                    tail_length=item["tail_length"], plane="XY",
                ))
        except (KeyError, TypeError, ValueError) as exc:
            feature_type = item.get("type", f"feature {index}")
            if feature_type == "curved_rod":
                fields = (
                    ("rod_diameter", "round-section diameter"),
                    ("total_length", "total centerline length"),
                    ("bend_start", "straight length before the bend"),
                    ("bend_radius", "centerline bend radius"),
                    ("bend_angle_degrees", "bend sweep angle"),
                )
                missing = [label for name, label in fields if item.get(name) is None]
                if missing:
                    questions.append(
                        "To build this as a constant-round-section planar sweep, "
                        f"please provide {', '.join(missing)}."
                    )
            elif feature_type in {"profile_extrude", "profile_revolve"}:
                if feature_type == "profile_extrude":
                    questions.append(
                        "For the proposed extruded silhouette, please provide its "
                        "overall height and width, section width or inner/outer radii, "
                        "opening size, and extrusion thickness."
                    )
                else:
                    questions.append(
                        "Which construction should I use: an axisymmetric revolved "
                        "profile, an extruded 2D silhouette, a constant-round-section "
                        "curved sweep, or a rectangular-section curved sweep?"
                    )
            elif feature_type == "sheet_metal_bend":
                fields = (
                    ("leg_a", "first leg length"), ("leg_b", "second leg length"),
                    ("width", "sheet width"), ("thickness", "sheet thickness"),
                    ("inside_radius", "inside bend radius"),
                    ("angle_degrees", "bend angle"), ("k_factor", "K-factor"),
                )
                missing = [label for name, label in fields if item.get(name) is None]
                questions.append(
                    "For the sheet-metal bend, please provide " + ", ".join(missing) + "."
                )
            elif feature_type == "rectangular_loft":
                fields = (
                    ("start_width", "start width"), ("start_height", "start height"),
                    ("end_width", "end width"), ("end_height", "end height"),
                    ("loft_length", "distance between sections"),
                )
                missing = [label for name, label in fields if item.get(name) is None]
                questions.append(
                    "For the rectangular transition, please provide "
                    + ", ".join(missing) + "."
                )
            elif feature_type == "curved_strip":
                fields = (
                    ("strip_width", "in-plane section width"),
                    ("extrusion_thickness", "out-of-plane thickness"),
                    ("shank_length", "straight shank length"),
                    ("strip_bend_radius", "centerline bend radius"),
                    ("strip_bend_angle_degrees", "bend sweep angle"),
                    ("tail_length", "straight tail length after the bend"),
                )
                missing = [label for name, label in fields if item.get(name) is None]
                questions.append(
                    "To build this as a rectangular-section curved sweep, please provide "
                    + ", ".join(missing) + "."
                )
            else:
                questions.append(f"Please clarify the incomplete {feature_type} definition.")
    return requests, questions


def _feature_evidence(
    requests: list[FeatureIntent], text: str, source_name: str, model: str
) -> list[Evidence]:
    """Promote structured feature fields to ordinary attributed evidence."""
    specs: list[tuple[str, SemanticTarget, EvidenceKind, float | str, str | None]] = []
    for request in requests:
        if isinstance(request, SheetMetalFeatureIntent):
            specs.extend([
                (f"{request.id}_leg_a", SemanticTarget.SHEET_LEG_A, EvidenceKind.LINEAR_DIMENSION, request.leg_a, "mm"),
                (f"{request.id}_leg_b", SemanticTarget.SHEET_LEG_B, EvidenceKind.LINEAR_DIMENSION, request.leg_b, "mm"),
                (f"{request.id}_width", SemanticTarget.SHEET_WIDTH, EvidenceKind.LINEAR_DIMENSION, request.width, "mm"),
                (f"{request.id}_thickness", SemanticTarget.SHEET_THICKNESS, EvidenceKind.LINEAR_DIMENSION, request.thickness, "mm"),
                (f"{request.id}_radius", SemanticTarget.INSIDE_BEND_RADIUS, EvidenceKind.LINEAR_DIMENSION, request.inside_radius, "mm"),
                (f"{request.id}_angle", SemanticTarget.BEND_ANGLE, EvidenceKind.FEATURE_CALLOUT, request.angle_degrees, "deg"),
                (f"{request.id}_k_factor", SemanticTarget.K_FACTOR, EvidenceKind.NOTE, request.k_factor, None),
            ])
        elif isinstance(request, CurvedRodFeatureIntent):
            specs.extend([
                (f"{request.id}_diameter", SemanticTarget.ROD_DIAMETER, EvidenceKind.DIAMETER, request.diameter, "mm"),
                (f"{request.id}_length", SemanticTarget.ROD_TOTAL_LENGTH, EvidenceKind.LINEAR_DIMENSION, request.total_length, "mm"),
                (f"{request.id}_bend_start", SemanticTarget.ROD_BEND_START, EvidenceKind.LINEAR_DIMENSION, request.bend_start, "mm"),
                (f"{request.id}_bend_radius", SemanticTarget.ROD_BEND_RADIUS, EvidenceKind.LINEAR_DIMENSION, request.bend_radius, "mm"),
                (f"{request.id}_bend_angle", SemanticTarget.ROD_BEND_ANGLE, EvidenceKind.FEATURE_CALLOUT, request.bend_angle_degrees, "deg"),
            ])
        elif isinstance(request, ProfileFeatureIntent):
            specs.append((
                f"{request.id}_profile", SemanticTarget.PROFILE_DEFINITION,
                EvidenceKind.FEATURE_CALLOUT, request.model_dump_json(), None,
            ))
        elif isinstance(request, RectangularLoftFeatureIntent):
            specs.extend([
                (f"{request.id}_start_width", SemanticTarget.LOFT_START_WIDTH, EvidenceKind.LINEAR_DIMENSION, request.start_width, "mm"),
                (f"{request.id}_start_height", SemanticTarget.LOFT_START_HEIGHT, EvidenceKind.LINEAR_DIMENSION, request.start_height, "mm"),
                (f"{request.id}_end_width", SemanticTarget.LOFT_END_WIDTH, EvidenceKind.LINEAR_DIMENSION, request.end_width, "mm"),
                (f"{request.id}_end_height", SemanticTarget.LOFT_END_HEIGHT, EvidenceKind.LINEAR_DIMENSION, request.end_height, "mm"),
                (f"{request.id}_length", SemanticTarget.LOFT_LENGTH, EvidenceKind.LINEAR_DIMENSION, request.length, "mm"),
            ])
        elif isinstance(request, CurvedStripFeatureIntent):
            specs.extend([
                (f"{request.id}_width", SemanticTarget.STRIP_WIDTH, EvidenceKind.LINEAR_DIMENSION, request.strip_width, "mm"),
                (f"{request.id}_thickness", SemanticTarget.STRIP_THICKNESS, EvidenceKind.LINEAR_DIMENSION, request.extrusion_thickness, "mm"),
                (f"{request.id}_shank", SemanticTarget.STRIP_SHANK_LENGTH, EvidenceKind.LINEAR_DIMENSION, request.shank_length, "mm"),
                (f"{request.id}_radius", SemanticTarget.STRIP_BEND_RADIUS, EvidenceKind.LINEAR_DIMENSION, request.bend_radius, "mm"),
                (f"{request.id}_angle", SemanticTarget.STRIP_BEND_ANGLE, EvidenceKind.FEATURE_CALLOUT, request.bend_angle_degrees, "deg"),
                (f"{request.id}_tail", SemanticTarget.STRIP_TAIL_LENGTH, EvidenceKind.LINEAR_DIMENSION, request.tail_length, "mm"),
            ])

    return [Evidence(
        id=f"ev_feature_{suffix}", entity="generated_part", kind=kind,
        target=target, value=value, unit=unit,
        source=SourceRef(
            file=source_name, modality=SourceModality.REQUIREMENT_TEXT,
            detail=f"structured feature extraction by {model}",
        ),
        extraction_method=ExtractionMethod.REASONING_MODEL,
        confidence=0.98, authority=authority_for(
            SourceModality.REQUIREMENT_TEXT, target, True
        ),
        is_explicit_annotation=True, raw_text=text,
    ) for suffix, target, kind, value, unit in specs]


def _partial_feature_evidence(
    payload: dict[str, Any], text: str, source_name: str, model: str
) -> list[Evidence]:
    """Keep valid scalar facts even when the complete feature needs clarification."""
    mapping = {
        "sheet_metal_bend": {
            "leg_a": (SemanticTarget.SHEET_LEG_A, EvidenceKind.LINEAR_DIMENSION, "mm"),
            "leg_b": (SemanticTarget.SHEET_LEG_B, EvidenceKind.LINEAR_DIMENSION, "mm"),
            "width": (SemanticTarget.SHEET_WIDTH, EvidenceKind.LINEAR_DIMENSION, "mm"),
            "thickness": (SemanticTarget.SHEET_THICKNESS, EvidenceKind.LINEAR_DIMENSION, "mm"),
            "inside_radius": (SemanticTarget.INSIDE_BEND_RADIUS, EvidenceKind.LINEAR_DIMENSION, "mm"),
            "angle_degrees": (SemanticTarget.BEND_ANGLE, EvidenceKind.FEATURE_CALLOUT, "deg"),
            "k_factor": (SemanticTarget.K_FACTOR, EvidenceKind.NOTE, None),
        },
        "curved_rod": {
            "rod_diameter": (SemanticTarget.ROD_DIAMETER, EvidenceKind.DIAMETER, "mm"),
            "total_length": (SemanticTarget.ROD_TOTAL_LENGTH, EvidenceKind.LINEAR_DIMENSION, "mm"),
            "bend_start": (SemanticTarget.ROD_BEND_START, EvidenceKind.LINEAR_DIMENSION, "mm"),
            "bend_radius": (SemanticTarget.ROD_BEND_RADIUS, EvidenceKind.LINEAR_DIMENSION, "mm"),
            "bend_angle_degrees": (SemanticTarget.ROD_BEND_ANGLE, EvidenceKind.FEATURE_CALLOUT, "deg"),
        },
        "rectangular_loft": {
            "start_width": (SemanticTarget.LOFT_START_WIDTH, EvidenceKind.LINEAR_DIMENSION, "mm"),
            "start_height": (SemanticTarget.LOFT_START_HEIGHT, EvidenceKind.LINEAR_DIMENSION, "mm"),
            "end_width": (SemanticTarget.LOFT_END_WIDTH, EvidenceKind.LINEAR_DIMENSION, "mm"),
            "end_height": (SemanticTarget.LOFT_END_HEIGHT, EvidenceKind.LINEAR_DIMENSION, "mm"),
            "loft_length": (SemanticTarget.LOFT_LENGTH, EvidenceKind.LINEAR_DIMENSION, "mm"),
        },
        "curved_strip": {
            "strip_width": (SemanticTarget.STRIP_WIDTH, EvidenceKind.LINEAR_DIMENSION, "mm"),
            "extrusion_thickness": (SemanticTarget.STRIP_THICKNESS, EvidenceKind.LINEAR_DIMENSION, "mm"),
            "shank_length": (SemanticTarget.STRIP_SHANK_LENGTH, EvidenceKind.LINEAR_DIMENSION, "mm"),
            "strip_bend_radius": (SemanticTarget.STRIP_BEND_RADIUS, EvidenceKind.LINEAR_DIMENSION, "mm"),
            "strip_bend_angle_degrees": (SemanticTarget.STRIP_BEND_ANGLE, EvidenceKind.FEATURE_CALLOUT, "deg"),
            "tail_length": (SemanticTarget.STRIP_TAIL_LENGTH, EvidenceKind.LINEAR_DIMENSION, "mm"),
        },
    }
    out: list[Evidence] = []
    for index, item in enumerate(payload.get("feature_requests", [])):
        for field_name, (target, kind, unit) in mapping.get(item.get("type"), {}).items():
            value = item.get(field_name)
            if value is None:
                continue
            out.append(Evidence(
                id=f"ev_feature_partial_{index}_{field_name}", entity="generated_part",
                kind=kind, target=target, value=value, unit=unit,
                source=SourceRef(
                    file=source_name, modality=SourceModality.REQUIREMENT_TEXT,
                    detail=f"partial structured feature extraction by {model}",
                ),
                extraction_method=ExtractionMethod.REASONING_MODEL,
                confidence=0.98,
                authority=authority_for(SourceModality.REQUIREMENT_TEXT, target, True),
                is_explicit_annotation=True, raw_text=text,
            ))
    return out


def _read_text(text_or_path: str | Path, source_name: str) -> tuple[str, str]:
    if isinstance(text_or_path, Path):
        if text_or_path.exists():
            return text_or_path.read_text(encoding="utf-8"), text_or_path.name
        return str(text_or_path), source_name
    candidate = Path(text_or_path)
    if candidate.suffix == ".txt" and candidate.exists():
        return candidate.read_text(encoding="utf-8"), candidate.name
    return str(text_or_path), source_name


def _parse_response(raw: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReasoningExtractionError(
            f"reasoning backend did not return valid JSON: {exc}"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("facts"), list):
        raise ReasoningExtractionError("reasoning response is missing a facts array")
    return payload


def _model_facts(text: str, source_name: str) -> tuple[list[Evidence], dict[str, Any]]:
    from openai import OpenAI

    load_env()
    model = reasoning_model()
    client = OpenAI(
        api_key=os.environ["OPENAI_API_KEY"],
        timeout=model_timeout_seconds(), max_retries=1,
    )
    response = client.responses.create(
        model=model,
        instructions=REASONING_INSTRUCTIONS,
        input=text,
        text={
            "format": {
                "type": "json_schema",
                "name": "engineering_intent_facts",
                "strict": True,
                "schema": REASONING_JSON_SCHEMA,
            }
        },
        store=False,
        max_output_tokens=model_max_output_tokens(),
        safety_identifier=current_safety_identifier(),
        extra_headers={"X-Client-Request-Id": str(uuid.uuid4())},
    )
    payload = _parse_response(response.output_text or "")

    out: list[Evidence] = []
    target_counts: dict[SemanticTarget, int] = {}
    for index, fact in enumerate(payload["facts"]):
        try:
            target = SemanticTarget(fact["target"])
            kind = EvidenceKind(fact["kind"])
            explicit = bool(fact["is_explicit_annotation"])
            confidence = float(fact["confidence"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ReasoningExtractionError(
                f"fact {index} is outside the evidence contract: {fact!r}"
            ) from exc
        target_counts[target] = target_counts.get(target, 0) + 1
        suffix = "" if target_counts[target] == 1 else f"_{target_counts[target]}"
        out.append(Evidence(
            id=f"ev_reasoning_{target.value}{suffix}",
            entity="generated_part",
            kind=kind,
            target=target,
            value=fact["value"],
            unit=fact.get("unit"),
            source=SourceRef(
                file=source_name,
                modality=SourceModality.REQUIREMENT_TEXT,
                detail=f"semantic extraction by {model}",
            ),
            extraction_method=ExtractionMethod.REASONING_MODEL,
            confidence=confidence,
            authority=authority_for(SourceModality.REQUIREMENT_TEXT, target, explicit),
            is_explicit_annotation=explicit,
            raw_text=fact.get("raw_text"),
        ))
    return out, payload


def extract_requirement_with_reasoning(
    text_or_path: str | Path,
    source_name: str = "requirement.txt",
    *,
    enabled: bool = True,
    reasoning_context: str | None = None,
) -> ReasoningExtractionResult:
    """Combine deterministic extraction with model-based semantic extraction.

    Model evidence only fills previously absent targets, so an LLM disagreement
    cannot silently replace a value parsed directly from the user's text.
    """
    deterministic = extract_requirement(text_or_path, source_name)
    text, resolved_name = _read_text(text_or_path, source_name)
    if not enabled or not reasoning_available():
        reason = None if enabled else "reasoning disabled for this caller"
        return ReasoningExtractionResult(
            evidence=deterministic,
            label="rule parser" if not reasoning_available() else "rule parser (reasoning disabled)",
            fallback_reason=reason,
        )

    model = reasoning_model()
    try:
        inferred, payload = _model_facts(reasoning_context or text, resolved_name)
    except Exception as exc:
        return ReasoningExtractionResult(
            evidence=deterministic,
            label=f"rule parser (OpenAI {model} unavailable)",
            attempted=True,
            fell_back=True,
            fallback_reason=safe_backend_error(exc),
        )

    feature_requests, contract_questions = _feature_requests(payload)
    requested_types = {
        item.get("type") for item in payload.get("feature_requests", [])
        if isinstance(item, dict)
    }
    drop_targets: set[SemanticTarget] = set()
    if "sheet_metal_bend" in requested_types:
        drop_targets.update({
            SemanticTarget.PLATE_WIDTH, SemanticTarget.PLATE_HEIGHT,
            SemanticTarget.PLATE_THICKNESS, SemanticTarget.SLOT_WIDTH,
            SemanticTarget.SLOT_LENGTH, SemanticTarget.WALL_THICKNESS,
        })
    if "curved_rod" in requested_types:
        drop_targets.update({
            SemanticTarget.OUTER_DIAMETER, SemanticTarget.INNER_DIAMETER,
            SemanticTarget.BODY_LENGTH, SemanticTarget.WALL_THICKNESS,
        })
    if "rectangular_loft" in requested_types:
        drop_targets.update({
            SemanticTarget.PLATE_WIDTH, SemanticTarget.PLATE_HEIGHT,
            SemanticTarget.PLATE_THICKNESS,
        })
    if "curved_strip" in requested_types:
        drop_targets.update({
            SemanticTarget.PLATE_WIDTH, SemanticTarget.PLATE_HEIGHT,
            SemanticTarget.PLATE_THICKNESS, SemanticTarget.SLOT_WIDTH,
            SemanticTarget.SLOT_LENGTH,
        })
    complete_feature_evidence = _feature_evidence(
        feature_requests, text, resolved_name, model
    )
    complete_targets = {item.target for item in complete_feature_evidence}
    partial_feature_evidence = [
        item for item in _partial_feature_evidence(
            payload, text, resolved_name, model
        ) if item.target not in complete_targets
    ]
    feature_evidence = complete_feature_evidence + partial_feature_evidence
    feature_targets = {item.target for item in feature_evidence}
    suppressed = drop_targets | feature_targets
    deterministic = [item for item in deterministic if item.target not in suppressed]
    inferred = [item for item in inferred if item.target not in suppressed]
    existing = {item.target for item in deterministic}
    merged = deterministic + [item for item in inferred if item.target not in existing]
    merged.extend(feature_evidence)
    model_questions = list(payload.get("clarification_questions", []))
    return ReasoningExtractionResult(
        evidence=merged,
        label=f"rule parser + OpenAI reasoning ({model})",
        attempted=True,
        unsupported_features=list(payload.get("unsupported_features", [])),
        clarification_questions=list(dict.fromkeys(
            contract_questions + model_questions
        )),
        feature_requests=feature_requests,
    )
