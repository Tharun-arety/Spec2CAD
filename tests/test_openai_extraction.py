"""OpenAI configuration and hybrid extraction tests (all API calls mocked)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import openai

from spec2cad.extractors import base
from spec2cad.extractors.reasoning import extract_requirement_with_reasoning
from spec2cad.extractors.model_provider import ModelConnection, ModelProvider
from spec2cad.schemas.evidence import ExtractionMethod, SemanticTarget, SourceModality
from spec2cad.pipeline import continue_conversation, run
from spec2cad.schemas.cad_ir import CylinderOp, TubeOp
from spec2cad.schemas.cad_ir import CurvedRodOp, RectangularLoftOp, SheetMetalBendOp
from spec2cad.schemas.cad_ir import ParamRef


def test_env_local_is_loaded_before_env_without_overriding_process_env(
    tmp_path, monkeypatch
):
    (tmp_path / ".env.local").write_text(
        "SPEC2CAD_TEST_SETTING=from-local\nSPEC2CAD_PROCESS_SETTING=from-local\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "SPEC2CAD_TEST_SETTING=from-env\nSPEC2CAD_PROCESS_SETTING=from-env\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(base, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(base, "_ENV_LOADED", False)
    monkeypatch.setattr(base, "_FILE_MANAGED_VALUES", {})
    monkeypatch.delenv("SPEC2CAD_TEST_SETTING", raising=False)
    monkeypatch.setenv("SPEC2CAD_PROCESS_SETTING", "from-process")

    base.load_env()

    assert base.os.environ["SPEC2CAD_TEST_SETTING"] == "from-local"
    assert base.os.environ["SPEC2CAD_PROCESS_SETTING"] == "from-process"
    (tmp_path / ".env.local").write_text(
        "SPEC2CAD_TEST_SETTING=updated-local\nSPEC2CAD_PROCESS_SETTING=changed-local\n",
        encoding="utf-8",
    )
    base.load_env()
    assert base.os.environ["SPEC2CAD_TEST_SETTING"] == "updated-local"
    assert base.os.environ["SPEC2CAD_PROCESS_SETTING"] == "from-process"
    monkeypatch.delenv("SPEC2CAD_TEST_SETTING", raising=False)


def test_render_secret_file_enables_openai_without_environment_key(tmp_path, monkeypatch):
    secret_file = tmp_path / "OPENAI_API_KEY"
    secret_file.write_text("secret-file-key\n", encoding="utf-8")
    monkeypatch.setattr(base, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(base, "_ENV_LOADED", False)
    monkeypatch.setattr(base, "_FILE_MANAGED_VALUES", {})
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("SPEC2CAD_OPENAI_API_KEY_FILE", str(secret_file))

    assert base.openai_api_key() == "secret-file-key"
    assert base.reasoning_available() is True
    assert base.select_backend() is base.VisionBackend.OPENAI

    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    assert base.openai_api_key() == "environment-key"


def test_public_backend_errors_do_not_echo_provider_message():
    class AuthenticationError(Exception):
        status_code = 401

    message = base.safe_backend_error(
        AuthenticationError("Incorrect API key provided: secret-fragment")
    )
    assert message == (
        "AuthenticationError: authentication failed; check the configured API key"
    )
    assert "secret-fragment" not in message


def _fake_openai(monkeypatch, payload, captured):
    class Responses:
        def create(self, **kwargs):
            captured["request"] = kwargs
            for fact in payload.get("facts", []):
                fact.setdefault("source", "requirement")
            return SimpleNamespace(output_text=json.dumps(payload))

    class Client:
        def __init__(self, api_key, **kwargs):
            captured["api_key"] = api_key
            captured["client_options"] = kwargs
            self.responses = Responses()

    monkeypatch.setattr(openai, "OpenAI", Client)


def _failing_openai(monkeypatch, error: Exception):
    class Responses:
        def create(self, **kwargs):
            raise error

    class Client:
        def __init__(self, api_key, **kwargs):
            self.responses = Responses()

    monkeypatch.setattr(openai, "OpenAI", Client)


def _fake_openai_compatible(monkeypatch, payload, captured):
    class Completions:
        def create(self, **kwargs):
            captured["request"] = kwargs
            return SimpleNamespace(choices=[SimpleNamespace(
                message=SimpleNamespace(content=json.dumps(payload)),
            )])

    class Client:
        def __init__(self, api_key, **kwargs):
            captured["api_key"] = api_key
            captured["client_options"] = kwargs
            self.chat = SimpleNamespace(completions=Completions())

    monkeypatch.setattr(openai, "OpenAI", Client)


def test_request_scoped_openai_compatible_reasoning_uses_chat_contract(monkeypatch):
    captured = {}
    _fake_openai_compatible(monkeypatch, {
        "facts": [{
            "target": "plate_thickness", "kind": "linear_dimension",
            "value": 3, "unit": "mm", "confidence": 0.98,
            "is_explicit_annotation": True, "raw_text": "3 mm thick",
            "source": "requirement",
        }],
        "feature_requests": [],
        "unsupported_features": [],
        "clarification_questions": [],
    }, captured)
    connection = ModelConnection(
        provider=ModelProvider.OPENAI_COMPATIBLE,
        api_key="caller-secret-key",
        model="openai/gpt-4o-mini",
        base_url="https://openrouter.ai/api/v1",
    )

    result = extract_requirement_with_reasoning(
        "Create a plate 3 mm thick.", model_connection=connection,
    )

    assert captured["api_key"] == "caller-secret-key"
    assert captured["client_options"]["base_url"] == "https://openrouter.ai/api/v1"
    assert captured["request"]["model"] == "openai/gpt-4o-mini"
    assert captured["request"]["response_format"]["type"] == "json_schema"
    assert captured["request"]["messages"][0]["role"] == "system"
    assert result.label == (
        "rule parser + OpenAI-compatible reasoning (openai/gpt-4o-mini)"
    )
    assert "caller-secret-key" not in repr(result)


def test_reasoning_fills_targets_missed_by_rule_parser(monkeypatch):
    captured = {}
    _fake_openai(monkeypatch, {
        "facts": [
            {
                "target": "plate_width", "kind": "linear_dimension",
                "value": 30, "unit": "mm", "confidence": 0.98,
                "is_explicit_annotation": True,
                "raw_text": "thirty millimetres on every side",
            },
            {
                "target": "plate_height", "kind": "linear_dimension",
                "value": 30, "unit": "mm", "confidence": 0.98,
                "is_explicit_annotation": True,
                "raw_text": "thirty millimetres on every side",
            },
            {
                "target": "plate_thickness", "kind": "linear_dimension",
                "value": 3, "unit": "mm", "confidence": 0.98,
                "is_explicit_annotation": True,
                "raw_text": "three millimetres thick",
            },
        ],
        "unsupported_features": [],
        "clarification_questions": [],
    }, captured)
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-key")
    monkeypatch.setenv("SPEC2CAD_REASONING_MODEL", "test-reasoning-model")

    result = extract_requirement_with_reasoning(
        "Make the mounting plate thirty millimetres on every side and three millimetres thick."
    )

    assert {item.target for item in result.evidence} == {
        SemanticTarget.PLATE_WIDTH,
        SemanticTarget.PLATE_HEIGHT,
        SemanticTarget.PLATE_THICKNESS,
    }
    assert all(
        item.extraction_method is ExtractionMethod.REASONING_MODEL
        for item in result.evidence
    )
    assert captured["api_key"] == "test-server-key"
    assert captured["request"]["model"] == "test-reasoning-model"
    assert captured["request"]["text"]["format"]["type"] == "json_schema"
    assert captured["request"]["store"] is False
    assert captured["request"]["max_output_tokens"] <= 8000
    assert captured["request"]["safety_identifier"] == "local-client"
    assert "X-Client-Request-Id" in captured["request"]["extra_headers"]
    assert captured["client_options"]["max_retries"] == 1
    assert captured["client_options"]["timeout"] <= 120


def test_model_only_fills_missing_targets_and_cannot_overwrite_exact_parse(
    monkeypatch,
):
    captured = {}
    _fake_openai(monkeypatch, {
        "facts": [
            {
                "target": "plate_width", "kind": "linear_dimension",
                "value": 99, "unit": "mm", "confidence": 0.5,
                "is_explicit_annotation": False, "raw_text": "square plate",
            },
            {
                "target": "external_fillet", "kind": "feature_callout",
                "value": 2, "unit": "mm", "confidence": 0.95,
                "is_explicit_annotation": True, "raw_text": "soften corners to R2",
            },
        ],
        "unsupported_features": [],
        "clarification_questions": [],
    }, captured)
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-key")

    result = extract_requirement_with_reasoning(
        "Create a square plate of length 30 mm and thickness 3 mm; soften corners to R2."
    )

    widths = [
        item for item in result.evidence if item.target is SemanticTarget.PLATE_WIDTH
    ]
    assert len(widths) == 1
    assert widths[0].value == 30
    assert widths[0].extraction_method is ExtractionMethod.RULE_PARSER
    assert any(
        item.target is SemanticTarget.EXTERNAL_FILLET
        and item.extraction_method is ExtractionMethod.REASONING_MODEL
        for item in result.evidence
    )


def test_cylindrical_tube_prompt_flows_from_reasoning_through_graph_and_cad(
    tmp_path, monkeypatch
):
    captured = {}
    _fake_openai(monkeypatch, {
        "facts": [
            {
                "target": "part_type", "kind": "feature_callout",
                "value": "tube", "unit": None, "confidence": 0.99,
                "is_explicit_annotation": True, "raw_text": "hollow cylinder",
            },
            {
                "target": "outer_diameter", "kind": "diameter",
                "value": 20, "unit": "mm", "confidence": 0.99,
                "is_explicit_annotation": True, "raw_text": "20 mm diameter",
            },
            {
                "target": "body_length", "kind": "linear_dimension",
                "value": 15, "unit": "mm", "confidence": 0.99,
                "is_explicit_annotation": True, "raw_text": "15 mm length",
            },
            {
                "target": "wall_thickness", "kind": "linear_dimension",
                "value": 3, "unit": "mm", "confidence": 0.99,
                "is_explicit_annotation": True, "raw_text": "thickness of 3 mm",
            },
        ],
        "unsupported_features": [],
        "clarification_questions": [],
    }, captured)
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-key")
    requirement = tmp_path / "requirement.txt"
    requirement.write_text(
        "create a cylinder with 20 mm diameter and 15 mm length with hollow "
        "inside and thickness of 3 mm",
        encoding="utf-8",
    )

    result = run(requirement=requirement, use_reasoning=True)

    assert isinstance(result.latest.program.operations[0], TubeOp)
    assert result.latest.intent.value_of("outer_diameter") == 20
    assert result.latest.intent.value_of("inner_diameter") == 14
    assert result.latest.intent.value_of("body_length") == 15
    assert result.latest.build_error is None
    assert result.latest.released is True


def test_agent_routes_complete_solid_cylinder_without_reasking_dimensions(
    tmp_path, monkeypatch
):
    captured = {}
    _fake_openai(monkeypatch, {
        "facts": [
            {
                "target": "part_type", "kind": "feature_callout",
                "value": "solid cylinder", "unit": None, "confidence": 0.99,
                "is_explicit_annotation": True, "raw_text": "create a cylinder",
            },
            {
                "target": "body_length", "kind": "linear_dimension",
                "value": 25, "unit": "mm", "confidence": 0.99,
                "is_explicit_annotation": True, "raw_text": "length 25 mm",
            },
            {
                "target": "outer_diameter", "kind": "diameter",
                "value": 15, "unit": "mm", "confidence": 0.99,
                "is_explicit_annotation": True, "raw_text": "15 mm dia",
            },
        ],
        "feature_requests": [],
        "unsupported_features": [],
        "clarification_questions": [],
        "agent": {
            "action": "execute",
            "summary": "Create a solid cylinder 25 mm long and 15 mm in diameter.",
            "steps": [
                "Create the cylindrical base solid from the supplied dimensions.",
                "Measure the result and run the release checks.",
            ],
            "tool_calls": [{
                "name": "cylinder",
                "purpose": "Create the requested solid cylinder.",
                "arguments": [
                    {"name": "length", "value": 25, "unit": "mm",
                     "source": "length 25 mm"},
                    {"name": "diameter", "value": 15, "unit": "mm",
                     "source": "15 mm dia"},
                ],
            }],
            "clarifications": [],
        },
    }, captured)
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-key")
    requirement = tmp_path / "requirement.txt"
    requirement.write_text(
        "create a cylinder of length 25 mm and 15 mm dia", encoding="utf-8"
    )

    result = run(requirement=requirement, use_reasoning=True)

    assert result.clarification_questions == []
    assert isinstance(result.latest.program.operations[0], CylinderOp)
    assert result.latest.intent.value_of("body_length") == 25
    assert result.latest.intent.value_of("outer_diameter") == 15
    assert result.agent_plan is not None
    assert result.agent_plan.action == "execute"
    assert result.agent_plan.tool_calls[0].name == "cylinder"
    assert result.latest.released is True
    assert "overall height and width" not in result.messages[-1].content


def test_sketch_only_uses_multimodal_reasoning_for_advanced_geometry(
    tmp_path, monkeypatch,
):
    captured = {}
    _fake_openai(monkeypatch, {
        "facts": [{
            "target": "part_type", "kind": "feature_callout",
            "value": "rectangular transition", "unit": None,
            "source": "sketch",
            "confidence": 0.98, "is_explicit_annotation": True,
            "raw_text": "dimensioned rectangular transition sketch",
        }],
        "feature_requests": [{
            "type": "rectangular_loft", "id": "sketched_transition", "plane": "XY",
            "start_width": 30, "start_height": 20,
            "end_width": 12, "end_height": 8, "loft_length": 40,
        }],
        "unsupported_features": [],
        "clarification_questions": [],
    }, captured)
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-key")
    sketch = tmp_path / "transition.png"
    sketch.write_bytes(b"\x89PNG\r\n\x1a\nmultimodal-test")

    result = run(sketch=sketch, use_reasoning=True)

    content = captured["request"]["input"][0]["content"]
    assert [item["type"] for item in content] == ["input_text", "input_image"]
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert isinstance(result.latest.program.operations[0], RectangularLoftOp)
    assert result.latest.execution.shape.isValid()
    assert result.latest.released is True
    assert result.sketch_backend == "openai multimodal intent (gpt-4o)"
    assert all(
        item.source.modality is SourceModality.SKETCH
        for item in result.evidence.items
    )


def test_failed_multimodal_extraction_stops_before_cad_compilation(
    tmp_path, monkeypatch,
):
    _failing_openai(monkeypatch, RuntimeError("provider returned an invalid response"))
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-key")
    sketch = tmp_path / "unscaled.png"
    sketch.write_bytes(b"\x89PNG\r\n\x1a\nmultimodal-test")
    requirement = tmp_path / "requirement.txt"
    requirement.write_text(
        "Build this and choose the dimensions for me.", encoding="utf-8",
    )

    result = run(sketch=sketch, requirement=requirement, use_reasoning=True)

    assert result.sketch_fell_back is True
    assert result.latest.program is None
    assert result.latest.execution is None
    assert result.latest.released is False
    assert result.messages[-1].kind == "clarification"
    assert "real-world reference dimension" in result.clarification_questions[0]
    assert result.latest.build_error.startswith(
        "Clarification required before CAD planning"
    )
    assert "CompilationError" not in result.latest.build_error
    assert result.latest.measured[0].checks[0].conflict_class.value == "completeness"


def test_empty_multimodal_contract_requests_scale_instead_of_compiling(
    tmp_path, monkeypatch,
):
    captured = {}
    _fake_openai(monkeypatch, {
        "facts": [], "feature_requests": [], "unsupported_features": [],
        "clarification_questions": [],
    }, captured)
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-key")
    sketch = tmp_path / "unscaled.png"
    sketch.write_bytes(b"\x89PNG\r\n\x1a\nmultimodal-test")

    result = run(sketch=sketch, use_reasoning=True)

    assert result.latest.program is None
    assert result.latest.execution is None
    assert result.latest.released is False
    assert "target overall envelope" in result.clarification_questions[0]
    assert "CompilationError" not in result.latest.build_error
    assert "If the user asks you to choose dimensions" in captured["request"]["instructions"]


def test_material_geometry_ambiguity_is_asked_before_cad_planning(
    tmp_path, monkeypatch
):
    captured = {}
    question = (
        "Should the L-bracket be a bent sheet-metal part with a bend radius "
        "and allowance, or a solid extruded/machined L-profile?"
    )
    _fake_openai(monkeypatch, {
        "facts": [],
        "feature_requests": [{
            "type": "sheet_metal_bend", "id": "main_bend",
            "leg_a": 50, "leg_b": 50, "width": 30, "thickness": 4,
            "inside_radius": None, "angle_degrees": 90, "k_factor": None,
        }],
        "unsupported_features": ["L-bracket"],
        "clarification_questions": [question],
        "agent": {
            "action": "clarify",
            "summary": "The L-bracket envelope is known, but its construction is ambiguous.",
            "steps": ["Confirm the construction method before creating geometry."],
            "tool_calls": [],
            "clarifications": [{
                "id": "bracket-construction",
                "question": question,
                "why": "Bent sheet and solid extrusion require different CAD operations.",
                "options": [
                    {"label": "Bent sheet metal", "value": "Use bent sheet metal.",
                     "description": "Model two legs with a bend radius and allowance."},
                    {"label": "Solid L-profile", "value": "Use a solid extruded L-profile.",
                     "description": "Extrude a constant L-shaped section."},
                ],
                "allow_free_text": True,
            }],
        },
    }, captured)
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-key")
    requirement = tmp_path / "requirement.txt"
    requirement.write_text("Create an L-bracket, 50 by 50 mm.", encoding="utf-8")

    result = run(requirement=requirement, use_reasoning=True)

    assert result.clarification_questions == [question]
    assert result.latest.program is None
    assert result.latest.execution is None
    assert result.latest.build_error == (
        f"Clarification required before CAD planning: {question}"
    )
    assert result.latest.released is False
    assert result.latest.measured[0].checks[0].id == "semantic_clarification_required"
    assert result.agent_plan is not None
    assert result.agent_plan.action == "clarify"
    assert [option.label for option in result.agent_plan.clarifications[0].options] == [
        "Bent sheet metal", "Solid L-profile",
    ]


def test_explicit_sheet_metal_request_flows_through_eig_planner_and_executor(
    tmp_path, monkeypatch
):
    captured = {}
    _fake_openai(monkeypatch, {
        "facts": [
            {
                "target": "part_type", "kind": "feature_callout",
                "value": "sheet metal bracket", "unit": None,
                "confidence": 0.99, "is_explicit_annotation": True,
                "raw_text": "bent sheet-metal L bracket",
            },
        ],
        "feature_requests": [{
            "type": "sheet_metal_bend", "id": "main_bend",
            "plane": None, "start": None, "segments": None, "mode": None,
            "distance": None, "centered": None,
            "axis_start": None, "axis_end": None,
            "angle_degrees": 90, "leg_a": 50, "leg_b": 40, "width": 30,
            "thickness": 2, "inside_radius": 3, "k_factor": 0.42,
        }],
        "unsupported_features": [],
        "clarification_questions": [],
    }, captured)
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-key")
    requirement = tmp_path / "requirement.txt"
    requirement.write_text(
        "Create a bent sheet-metal L bracket with 50 and 40 mm outside legs, "
        "30 mm width, 2 mm thickness, 3 mm inside bend radius, 90 degree bend "
        "and K-factor 0.42.",
        encoding="utf-8",
    )

    result = run(requirement=requirement, use_reasoning=True)

    assert isinstance(result.latest.program.operations[0], SheetMetalBendOp)
    assert result.latest.intent_graph.node("main_bend").kind.value == "advanced_feature"
    assert result.latest.execution.shape.isValid()
    assert result.latest.execution.context.derived["main_bend.flat_length"] > 0
    assert set(result.latest.intent.parameters) == {
        "sheet_leg_a", "sheet_leg_b", "sheet_width", "sheet_thickness",
        "inside_bend_radius", "bend_angle", "k_factor",
    }
    assert all(parameter.value is not None for parameter in result.latest.intent.parameters.values())
    assert {item.target.value for item in result.evidence.items} >= set(result.latest.intent.parameters)
    assert result.latest.build_error is None
    assert result.latest.released is True


def test_incomplete_model_feature_becomes_clarification_not_pipeline_error(
    tmp_path, monkeypatch
):
    captured = {}
    _fake_openai(monkeypatch, {
        "facts": [],
        "feature_requests": [{
            "type": "profile_revolve", "id": "curve_rod_revolve",
            "plane": None, "start": None, "segments": None, "mode": "add",
            "distance": None, "centered": None, "axis_start": None,
            "axis_end": None, "angle_degrees": 270,
            "leg_a": None, "leg_b": None, "width": None, "thickness": None,
            "inside_radius": None, "k_factor": None,
        }],
        "unsupported_features": [], "clarification_questions": [],
    }, captured)
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-key")
    requirement = tmp_path / "requirement.txt"
    requirement.write_text(
        "create curved rod of length 20 mm and 3 mm dia and curve at 3 mm of 270 degree",
        encoding="utf-8",
    )

    result = run(requirement=requirement, use_reasoning=True)

    assert result.latest.execution is None
    assert result.latest.build_error.startswith("Clarification required before CAD planning")
    assert "Which construction" in result.clarification_questions[0]


def test_explicit_curved_rod_flows_through_eig_planner_and_sweep(
    tmp_path, monkeypatch
):
    captured = {}
    _fake_openai(monkeypatch, {
        "facts": [{
            "target": "part_type", "kind": "feature_callout",
            "value": "curved rod", "unit": None, "confidence": 0.99,
            "is_explicit_annotation": True, "raw_text": "curved rod",
        }],
        "feature_requests": [{
            "type": "curved_rod", "id": "rod_sweep", "plane": "XY",
            "start": None, "segments": None, "mode": None, "distance": None,
            "centered": None, "axis_start": None, "axis_end": None,
            "angle_degrees": None, "leg_a": None, "leg_b": None,
            "width": None, "thickness": None, "inside_radius": None,
            "k_factor": None, "rod_diameter": 3, "total_length": 20,
            "bend_start": 3, "bend_radius": 3, "bend_angle_degrees": 270,
        }],
        "unsupported_features": [], "clarification_questions": [],
    }, captured)
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-key")
    requirement = tmp_path / "requirement.txt"
    requirement.write_text(
        "Create a 3 mm diameter curved rod with 20 mm centerline length. Start "
        "a 270 degree bend 3 mm from the first end using a 3 mm centerline radius.",
        encoding="utf-8",
    )

    result = run(requirement=requirement, use_reasoning=True)

    assert isinstance(result.latest.program.operations[0], CurvedRodOp)
    assert set(result.latest.intent.parameters) == {
        "rod_diameter", "rod_total_length", "rod_bend_start",
        "rod_bend_radius", "rod_bend_angle",
    }
    assert all(parameter.value is not None for parameter in result.latest.intent.parameters.values())
    assert {item.target.value for item in result.evidence.items} >= set(result.latest.intent.parameters)
    assert isinstance(result.latest.program.operations[0].diameter, ParamRef)
    assert result.latest.execution.shape.isValid()
    assert result.latest.released is True


def test_partial_curved_rod_evidence_remains_visible_during_clarification(
    tmp_path, monkeypatch
):
    captured = {}
    _fake_openai(monkeypatch, {
        "facts": [],
        "feature_requests": [{
            "type": "curved_rod", "id": "rod_sweep", "plane": "XY",
            "start": None, "segments": None, "mode": None, "distance": None,
            "centered": None, "axis_start": None, "axis_end": None,
            "angle_degrees": None, "leg_a": None, "leg_b": None,
            "width": None, "thickness": None, "inside_radius": None,
            "k_factor": None, "rod_diameter": 3, "total_length": 20,
            "bend_start": 3, "bend_radius": None, "bend_angle_degrees": 270,
        }],
        "unsupported_features": [],
        "clarification_questions": ["What is the centerline bend radius?"],
    }, captured)
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-key")
    requirement = tmp_path / "requirement.txt"
    requirement.write_text(
        "Create a curved rod of length 20 mm and 3 mm diameter, curve at 3 mm "
        "through 270 degrees.", encoding="utf-8",
    )

    result = run(requirement=requirement, use_reasoning=True)

    assert result.latest.execution is None
    assert set(result.latest.intent.parameters) == {
        "rod_diameter", "rod_total_length", "rod_bend_start", "rod_bend_angle",
    }
    assert all(parameter.value is not None for parameter in result.latest.intent.parameters.values())
    assert {item.target.value for item in result.evidence.items} >= set(result.latest.intent.parameters)
    assert result.clarification_questions == [
        "To build this as a constant-round-section planar sweep, please provide "
        "centerline bend radius.",
        "What is the centerline bend radius?",
    ]


def test_ambiguous_taper_clarifies_then_continues_same_conversation(
    tmp_path, monkeypatch
):
    captured = {}
    payload = {
        "facts": [],
        "feature_requests": [{
            "type": "rectangular_loft", "id": "taper", "plane": "XY",
            "start_width": 25, "start_height": 5,
            "end_width": 9, "end_height": 3, "loft_length": None,
        }],
        "unsupported_features": [],
        "clarification_questions": [
            "What is the distance between the two rectangular end sections?"
        ],
    }
    _fake_openai(monkeypatch, payload, captured)
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-key")
    requirement = tmp_path / "requirement.txt"
    original = (
        "create a tappered plate with the change of area from 25 mm to 9mm "
        "with length and width varying from 5mm to 3 mm"
    )
    requirement.write_text(original, encoding="utf-8")

    first = run(requirement=requirement, use_reasoning=True)

    assert first.latest.execution is None
    assert first.messages[0].content == original
    assert first.messages[1].kind == "clarification"
    assert {item.target.value for item in first.evidence.items} >= {
        "loft_start_width", "loft_start_height", "loft_end_width", "loft_end_height",
    }

    payload.clear()
    payload.update({
        "facts": [],
        "feature_requests": [{
            "type": "rectangular_loft", "id": "taper", "plane": "XY",
            "start_width": 25, "start_height": 5,
            "end_width": 9, "end_height": 3, "loft_length": 20,
        }],
        "unsupported_features": [], "clarification_questions": [],
    })
    second = continue_conversation(first, "The distance between them is 20 mm.")

    assert second.latest.revision == 2
    assert second.latest.intent.parent_revision == 1
    assert isinstance(second.latest.program.operations[0], RectangularLoftOp)
    assert second.latest.execution.shape.isValid()
    assert second.latest.released is True
    assert [message.role for message in second.messages] == [
        "user", "assistant", "user", "assistant",
    ]
    assert original in captured["request"]["input"]
    assert "The distance between them is 20 mm." in captured["request"]["input"]


def test_informal_part_name_maps_to_capability_and_asks_operation_fields(
    tmp_path, monkeypatch
):
    captured = {}
    _fake_openai(monkeypatch, {
        "facts": [{
            "target": "part_type", "kind": "feature_callout",
            "value": "crane hook", "unit": None, "confidence": 0.99,
            "is_explicit_annotation": True, "raw_text": "crane hook",
        }],
        "feature_requests": [{
            "type": "curved_strip", "id": "main_sweep", "plane": "XY",
            "strip_width": None, "extrusion_thickness": None,
            "shank_length": None, "strip_bend_radius": None,
            "strip_bend_angle_degrees": None, "tail_length": None,
        }],
        "unsupported_features": [],
        "clarification_questions": [
            "What target overall size or scale factor should 'smaller' mean?"
        ],
    }, captured)
    monkeypatch.setenv("OPENAI_API_KEY", "test-server-key")
    requirement = tmp_path / "requirement.txt"
    requirement.write_text("create a crane hook but a smaller scale", encoding="utf-8")

    result = run(requirement=requirement, use_reasoning=True)

    assert result.unsupported_features == []
    assert result.latest.execution is None
    assert result.messages[-1].kind == "clarification"
    assert "in-plane section width" in result.clarification_questions[0]
    assert "centerline bend radius" in result.clarification_questions[0]
    assert "scale factor" in result.clarification_questions[1]
