"""Generic, fixed FreeCAD worker entrypoint for bounded Feature IR 1.0.

This module intentionally avoids importing host-side packages. FreeCADCmd may
run in an isolated environment; the host validates the typed envelope again
after this process returns.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
from pathlib import Path


SCHEMA_VERSION = "1.0.0"


class UnsupportedFeature(ValueError):
    pass


def _canonical_bytes(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _hash(value):
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_hash(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _slug(value):
    result = re.sub(r"[^a-z0-9]+", "_", str(value).lower()).strip("_")
    return result or "record"


def _native_name(prefix, record_id):
    pieces = [piece for piece in _slug(record_id).split("_") if piece]
    camel = "".join(piece[:1].upper() + piece[1:] for piece in pieces)
    return (prefix + camel)[:80]


def _write(path, request_id, operation, status, diagnostics=(), **values):
    payload = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id,
        "operation": operation,
        "status": status,
        "freecad_version": values.get("freecad_version"),
        "native_build": values.get("native_build"),
        "cad_state_graph": values.get("cad_state_graph"),
        "artifacts": values.get("artifacts", []),
        "reimport_verified": values.get("reimport_verified"),
        "diagnostics": list(diagnostics),
    }
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(str(temporary), str(path))


def _validate_feature_ir(build_request):
    if build_request.get("backend_id") != "freecad":
        raise ValueError("build request must target freecad")
    feature_ir = build_request.get("feature_ir")
    manifest = build_request.get("feature_ir_manifest")
    encoded = _canonical_bytes(feature_ir)
    if not isinstance(manifest, dict):
        raise ValueError("Feature IR manifest is missing")
    if manifest.get("content_sha256") != hashlib.sha256(encoded).hexdigest():
        raise ValueError("Feature IR content hash mismatch")
    if manifest.get("byte_length") != len(encoded):
        raise ValueError("Feature IR byte length mismatch")
    if feature_ir.get("schema_version") != "1.0.0":
        raise ValueError("unsupported Feature IR schema")
    supported = {
        "sketch", "pad", "pocket", "rectangular_pattern", "linear_slot_pattern",
        "chamfer", "fillet",
    }
    unexpected = sorted({
        item.get("type") for item in feature_ir.get("features", [])
        if item.get("type") not in supported
    })
    if unexpected:
        raise UnsupportedFeature(
            "unsupported Feature IR features: " + ", ".join(unexpected)
        )
    return feature_ir


def _validate_build_payload(payload):
    operation = payload["operation"]
    expected = {
        "schema_version", "request_id", "operation", "build_request", "artifact_root",
    }
    if operation == "edit_parameter":
        expected |= {"native_document_path", "parameter_id", "parameter_value"}
    if set(payload) != expected:
        raise ValueError(f"{operation} request fields do not match protocol 1.0.0")
    build_request = payload["build_request"]
    feature_ir = _validate_feature_ir(build_request)
    artifact_root = Path(payload["artifact_root"]).resolve()
    if not artifact_root.is_dir():
        raise ValueError("artifact_root must be an existing directory")
    return build_request, feature_ir, artifact_root


def _validate_reimport_payload(payload):
    if set(payload) != {
        "schema_version", "request_id", "operation", "artifact", "artifact_path",
    }:
        raise ValueError("re-import request fields do not match protocol 1.0.0")
    artifact = payload["artifact"]
    if artifact.get("kind") != "neutral_model" or artifact.get("backend_id") != "freecad":
        raise ValueError("re-import requires a FreeCAD neutral artifact")
    path = Path(payload["artifact_path"]).resolve()
    if not path.is_file() or _file_hash(path) != artifact.get("content_sha256"):
        raise ValueError("re-import artifact bytes do not match the manifest")
    return path


def _parameter_maps(feature_ir):
    by_id = {item["id"]: item for item in feature_ir["parameters"]}
    aliases = {
        item["id"]: f"firp_{index:04d}"
        for index, item in enumerate(feature_ir["parameters"], 1)
    }
    return by_id, aliases


def _evaluate(expression, values):
    kind = expression["type"]
    if kind == "literal":
        return float(expression["value"])
    if kind == "parameter":
        return float(values[expression["parameter_id"]])
    left = _evaluate(expression["left"], values)
    right = _evaluate(expression["right"], values)
    return {
        "add": lambda: left + right,
        "subtract": lambda: left - right,
        "multiply": lambda: left * right,
        "divide": lambda: left / right,
    }[expression["operator"]]()


def _native_expression(expression, aliases, sheet_name="Parameters"):
    kind = expression["type"]
    if kind == "literal":
        return format(float(expression["value"]), ".17g")
    if kind == "parameter":
        return f"{sheet_name}.{aliases[expression['parameter_id']]}"
    if (
        expression["operator"] == "subtract"
        and expression["left"].get("type") == "literal"
        and float(expression["left"]["value"]) == 0.0
    ):
        right = expression["right"]
        if right.get("type") == "binary" and right.get("operator") == "divide":
            numerator = _native_expression(right["left"], aliases, sheet_name)
            denominator = _native_expression(right["right"], aliases, sheet_name)
            return f"({numerator} / -{denominator})"
        return f"(-1 * {_native_expression(right, aliases, sheet_name)})"
    operator = {"add": "+", "subtract": "-", "multiply": "*", "divide": "/"}[
        expression["operator"]
    ]
    left = _native_expression(expression["left"], aliases, sheet_name)
    right = _native_expression(expression["right"], aliases, sheet_name)
    return f"({left} {operator} {right})"


def _add_expression_constraint(sketch, Sketcher, constraint, expression):
    index = sketch.addConstraint(constraint)
    sketch.setExpression(f"Constraints[{index}]", expression)
    return index


def _is_rectangle(geometry):
    return len(geometry) == 4 and all(item["type"] == "line" for item in geometry)


def _add_sketch(body, feature, App, Part, Sketcher, values, aliases):
    name = _native_name("Sketch", feature["id"])
    sketch = body.newObject("Sketcher::SketchObject", name)
    sketch.Label = feature["label"]
    geometry = feature["sketch"]["geometry"]
    if _is_rectangle(geometry):
        for item in geometry:
            start = item["start"]
            end = item["end"]
            sketch.addGeometry(Part.LineSegment(
                App.Vector(_evaluate(start["x"], values), _evaluate(start["y"], values), 0),
                App.Vector(_evaluate(end["x"], values), _evaluate(end["y"], values), 0),
            ), bool(item.get("construction")))
        for index in range(4):
            sketch.addConstraint(Sketcher.Constraint(
                "Coincident", index, 2, (index + 1) % 4, 1
            ))
        for index in (0, 2):
            sketch.addConstraint(Sketcher.Constraint("Horizontal", index))
        for index in (1, 3):
            sketch.addConstraint(Sketcher.Constraint("Vertical", index))
        first, second = geometry[0], geometry[1]
        _add_expression_constraint(
            sketch, Sketcher,
            Sketcher.Constraint(
                "DistanceX", 0, 1, 0, 2,
                _evaluate(first["end"]["x"], values) - _evaluate(first["start"]["x"], values),
            ),
            f"({_native_expression(first['end']['x'], aliases)} - "
            f"{_native_expression(first['start']['x'], aliases)})",
        )
        _add_expression_constraint(
            sketch, Sketcher,
            Sketcher.Constraint(
                "DistanceY", 1, 1, 1, 2,
                _evaluate(second["end"]["y"], values) - _evaluate(second["start"]["y"], values),
            ),
            f"({_native_expression(second['end']['y'], aliases)} - "
            f"{_native_expression(second['start']['y'], aliases)})",
        )
        _add_expression_constraint(
            sketch, Sketcher,
            Sketcher.Constraint("DistanceX", 0, 1, _evaluate(first["start"]["x"], values)),
            _native_expression(first["start"]["x"], aliases),
        )
        _add_expression_constraint(
            sketch, Sketcher,
            Sketcher.Constraint("DistanceY", 0, 1, _evaluate(first["start"]["y"], values)),
            _native_expression(first["start"]["y"], aliases),
        )
        return sketch

    for item in geometry:
        kind = item["type"]
        if kind == "circle":
            x = _evaluate(item["center"]["x"], values)
            y = _evaluate(item["center"]["y"], values)
            radius = _evaluate(item["diameter"], values) / 2
            index = sketch.addGeometry(Part.Circle(
                App.Vector(x, y, 0), App.Vector(0, 0, 1), radius,
            ), bool(item.get("construction")))
            _add_expression_constraint(
                sketch, Sketcher, Sketcher.Constraint("Radius", index, radius),
                f"({_native_expression(item['diameter'], aliases)} / 2)",
            )
            if abs(x) < 1e-12 and abs(y) < 1e-12:
                sketch.addConstraint(Sketcher.Constraint("Coincident", index, 3, -1, 1))
            else:
                _add_expression_constraint(
                    sketch, Sketcher, Sketcher.Constraint("DistanceX", index, 3, x),
                    _native_expression(item["center"]["x"], aliases),
                )
                _add_expression_constraint(
                    sketch, Sketcher, Sketcher.Constraint("DistanceY", index, 3, y),
                    _native_expression(item["center"]["y"], aliases),
                )
        elif kind == "line":
            start, end = item["start"], item["end"]
            index = sketch.addGeometry(Part.LineSegment(
                App.Vector(_evaluate(start["x"], values), _evaluate(start["y"], values), 0),
                App.Vector(_evaluate(end["x"], values), _evaluate(end["y"], values), 0),
            ), bool(item.get("construction")))
            sketch.addConstraint(Sketcher.Constraint("Block", index))
        elif kind == "three_point_arc":
            points = [item[key] for key in ("start", "midpoint", "end")]
            vectors = [App.Vector(
                _evaluate(point["x"], values), _evaluate(point["y"], values), 0
            ) for point in points]
            index = sketch.addGeometry(
                Part.Arc(vectors[0], vectors[1], vectors[2]),
                bool(item.get("construction")),
            )
            sketch.addConstraint(Sketcher.Constraint("Block", index))
        else:
            raise UnsupportedFeature(f"unsupported sketch geometry {kind!r}")
    return sketch


def _add_circle(sketch, App, Part, Sketcher, x, y, radius, x_expr, y_expr, r_expr):
    index = sketch.addGeometry(
        Part.Circle(App.Vector(x, y, 0), App.Vector(0, 0, 1), radius), False
    )
    _add_expression_constraint(
        sketch, Sketcher, Sketcher.Constraint("Radius", index, radius), r_expr
    )
    if abs(x) < 1e-12 and abs(y) < 1e-12:
        sketch.addConstraint(Sketcher.Constraint("Coincident", index, 3, -1, 1))
    else:
        _add_expression_constraint(
            sketch, Sketcher, Sketcher.Constraint("DistanceX", index, 3, x), x_expr
        )
        _add_expression_constraint(
            sketch, Sketcher, Sketcher.Constraint("DistanceY", index, 3, y), y_expr
        )


def _add_pattern_sketch(
    body, pattern, source_sketch, App, Part, Sketcher, values, aliases,
):
    geometry = source_sketch["sketch"]["geometry"]
    if len(geometry) != 1 or geometry[0]["type"] != "circle":
        raise UnsupportedFeature("rectangular pattern source must be one circle")
    circle = geometry[0]
    count_x = int(round(_evaluate(pattern["count_x"], values)))
    count_y = int(round(_evaluate(pattern["count_y"], values)))
    if count_x < 1 or count_y < 1:
        raise ValueError("rectangular pattern counts must be positive")
    spacing_x = _evaluate(pattern["spacing_x"], values)
    spacing_y = _evaluate(pattern["spacing_y"], values)
    sketch = body.newObject(
        "Sketcher::SketchObject", _native_name("Sketch", pattern["id"])
    )
    sketch.Label = pattern["label"] + " profile"
    base_x = _evaluate(circle["center"]["x"], values)
    base_y = _evaluate(circle["center"]["y"], values)
    radius = _evaluate(circle["diameter"], values) / 2
    base_x_expr = _native_expression(circle["center"]["x"], aliases)
    base_y_expr = _native_expression(circle["center"]["y"], aliases)
    spacing_x_expr = _native_expression(pattern["spacing_x"], aliases)
    spacing_y_expr = _native_expression(pattern["spacing_y"], aliases)
    radius_expr = f"({_native_expression(circle['diameter'], aliases)} / 2)"
    for x_index in range(count_x):
        x_fraction = x_index / max(1, count_x - 1)
        for y_index in range(count_y):
            y_fraction = y_index / max(1, count_y - 1)
            x = base_x + x_fraction * spacing_x
            y = base_y + y_fraction * spacing_y
            _add_circle(
                sketch, App, Part, Sketcher, x, y, radius,
                f"({base_x_expr} + {x_fraction:.17g} * {spacing_x_expr})",
                f"({base_y_expr} + {y_fraction:.17g} * {spacing_y_expr})",
                radius_expr,
            )
    return sketch


def _add_slot_pattern_sketch(body, feature, App, Part, Sketcher, values):
    width = _evaluate(feature["width"], values)
    length = _evaluate(feature["length"], values)
    spacing = _evaluate(feature["spacing"], values)
    count = int(round(_evaluate(feature["count"], values)))
    angle = math.radians(_evaluate(feature["angle_degrees"], values))
    if count < 1 or width <= 0 or length <= width or spacing < 0:
        raise ValueError("linear slot pattern dimensions are invalid")
    sketch = body.newObject(
        "Sketcher::SketchObject", _native_name("Sketch", feature["id"])
    )
    sketch.Label = feature["label"] + " profile"
    radius = width / 2
    half_straight = (length - width) / 2

    def rotated(point, center_x):
        x, y = point
        return App.Vector(
            center_x + x * math.cos(angle) - y * math.sin(angle),
            x * math.sin(angle) + y * math.cos(angle),
            0,
        )

    for slot_index in range(count):
        center_x = (slot_index - (count - 1) / 2) * spacing
        left_top = rotated((-half_straight, radius), center_x)
        right_top = rotated((half_straight, radius), center_x)
        right_mid = rotated((half_straight + radius, 0), center_x)
        right_bottom = rotated((half_straight, -radius), center_x)
        left_bottom = rotated((-half_straight, -radius), center_x)
        left_mid = rotated((-half_straight - radius, 0), center_x)
        geometry = (
            Part.LineSegment(left_top, right_top),
            Part.Arc(right_top, right_mid, right_bottom),
            Part.LineSegment(right_bottom, left_bottom),
            Part.Arc(left_bottom, left_mid, left_top),
        )
        for item in geometry:
            index = sketch.addGeometry(item, False)
            sketch.addConstraint(Sketcher.Constraint("Block", index))
    return sketch


def _external_axis_edges(shape, direction):
    bounds = shape.BoundBox
    selected = []
    for index, edge in enumerate(shape.Edges, 1):
        vertices = edge.Vertexes
        if len(vertices) != 2:
            continue
        first, second = vertices[0].Point, vertices[1].Point
        delta = (second.x - first.x, second.y - first.y, second.z - first.z)
        length = math.sqrt(sum(item * item for item in delta))
        if length <= 1e-12:
            continue
        unit = tuple(item / length for item in delta)
        expected = tuple(float(direction.get(axis, 0)) for axis in ("x", "y", "z"))
        parallel = abs(abs(sum(a * b for a, b in zip(unit, expected))) - 1) < 1e-6
        edge_bounds = edge.BoundBox
        center = type("EdgeCenter", (), {
            "x": (edge_bounds.XMin + edge_bounds.XMax) / 2,
            "y": (edge_bounds.YMin + edge_bounds.YMax) / 2,
        })()
        on_external_bounds = (
            abs(abs(center.x - (bounds.XMin + bounds.XMax) / 2) - bounds.XLength / 2) < 1e-6
            and abs(abs(center.y - (bounds.YMin + bounds.YMax) / 2) - bounds.YLength / 2) < 1e-6
        )
        if parallel and on_external_bounds:
            selected.append(f"Edge{index}")
    return selected


def _native_summary(doc, body, final_feature, path, feature_ir, sketches, features):
    errors = []
    for obj in doc.Objects:
        states = [str(item) for item in getattr(obj, "State", ())]
        if any("error" in item.lower() or "invalid" in item.lower() for item in states):
            errors.append(f"{obj.Name}: {', '.join(states)}")
    sketch_summaries = []
    for sketch in sketches:
        dof = max(0, int(sketch.solve()))
        sketch_summaries.append({
            "name": sketch.Name,
            "fully_constrained": bool(getattr(sketch, "FullyConstrained", dof == 0)),
            "degrees_of_freedom": dof,
            "geometry_count": int(sketch.GeometryCount),
            "constraint_count": int(sketch.ConstraintCount),
        })
    return {
        "document_path": str(path),
        "document_name": doc.Name,
        "body_name": body.Name,
        "parameter_names": [item["name"] for item in feature_ir["parameters"]],
        "sketches": sketch_summaries,
        "features": [
            {"name": item.Name, "type_id": item.TypeId} for item in features
        ],
        "recompute_errors": errors,
        "solid_count": len(final_feature.Shape.Solids),
        "volume_mm3": float(final_feature.Shape.Volume),
    }


def _ref(namespace, record_id):
    return {"namespace": namespace, "id": record_id}


def _rel(record_id, kind, source_id, namespace, target_id):
    return {
        "id": record_id, "kind": kind,
        "source": _ref("cad_state_graph", source_id),
        "target": _ref(namespace, target_id),
    }


def _measurements(shape):
    bounds = shape.BoundBox
    return [
        {"name": "width", "value": float(bounds.XLength), "unit": "mm"},
        {"name": "height", "value": float(bounds.YLength), "unit": "mm"},
        {"name": "thickness", "value": float(bounds.ZLength), "unit": "mm"},
        {"name": "volume", "value": float(shape.Volume), "unit": "mm3"},
    ]


def _shape_center(shape):
    bounds = shape.BoundBox
    return [
        float((bounds.XMin + bounds.XMax) / 2),
        float((bounds.YMin + bounds.YMax) / 2),
        float((bounds.ZMin + bounds.ZMax) / 2),
    ]


def _extract_csg(
    build_request, feature_ir, doc, body, final_feature, sheet, aliases,
    sketch_pairs, feature_pairs, artifacts,
):
    nodes = []
    relationships = []
    document_id = "document.root"
    body_id = "body.main"
    datum_id = "datum.xy_plane"
    sketch_node_ids = {
        native.Name: f"sketch.{_slug(record['id'])}" for record, native in sketch_pairs
    }
    feature_node_ids = {
        native.Name: f"feature.{_slug(records[-1]['id'])}"
        for records, native, _ in feature_pairs
    }
    nodes.extend((
        {
            "kind": "document", "id": document_id, "label": doc.Label,
            "backend_native_id": doc.Name, "native_format": "FCStd",
            "editable": True, "recompute": "succeeded", "body_ids": [body_id],
        },
        {
            "kind": "datum_reference", "id": datum_id, "label": "XY plane",
            "backend_native_id": "XY_Plane", "datum_kind": "plane",
            "origin": [0.0, 0.0, 0.0], "direction": [0.0, 0.0, 1.0],
        },
    ))
    relationships.append(_rel(
        "rel.document.feature_ir_part", "realizes_feature_ir",
        document_id, "feature_ir", feature_ir["part"]["id"],
    ))
    for link in feature_ir["part"].get("intent_links", []):
        relationships.append(_rel(
            f"rel.document.intent.{_slug(link['eig_node_id'])}",
            "realizes_intent", document_id, "engineering_intent_graph",
            link["eig_node_id"],
        ))
    alias_to_parameter = {}
    for row, item in enumerate(feature_ir["parameters"], 1):
        node_id = f"parameter.{_slug(item['id'])}"
        alias = aliases[item["id"]]
        alias_to_parameter[alias] = node_id
        unit = "mm" if item["unit"] == "mm" else "degree" if item["unit"] == "degree" else "count" if item["kind"] == "count" else "none"
        nodes.append({
            "kind": "parameter_expression", "id": node_id, "label": item["label"],
            "backend_native_id": f"{sheet.Name}.{alias}",
            "parameter_name": item["name"], "value": item["value"], "unit": unit,
            "editable": True, "native_expression": sheet.getContents(f"A{row}"),
        })
        relationships.append(_rel(
            f"rel.{_slug(node_id)}.feature_ir", "realizes_feature_ir",
            node_id, "feature_ir", item["id"],
        ))
        for link in item.get("intent_links", []):
            relationships.append(_rel(
                f"rel.{_slug(node_id)}.intent.{_slug(link['eig_node_id'])}",
                "realizes_intent", node_id, "engineering_intent_graph",
                link["eig_node_id"],
            ))

    body_feature_ids = []
    for record, sketch in sketch_pairs:
        sketch_id = sketch_node_ids[sketch.Name]
        body_feature_ids.append(sketch_id)
        geometry_ids = []
        for index, geometry in enumerate(sketch.Geometry):
            geometry_id = f"geometry.{_slug(record['id'])}.{index}"
            geometry_ids.append(geometry_id)
            type_name = type(geometry).__name__.lower()
            if "line" in type_name:
                kind = "line"
                coordinates = [
                    float(geometry.StartPoint.x), float(geometry.StartPoint.y),
                    float(geometry.EndPoint.x), float(geometry.EndPoint.y),
                ]
                radius = None
            elif "circle" in type_name:
                kind = "circle"
                coordinates = [float(geometry.Center.x), float(geometry.Center.y)]
                radius = float(geometry.Radius)
            elif "arc" in type_name:
                kind = "arc"
                coordinates = [
                    float(geometry.StartPoint.x), float(geometry.StartPoint.y),
                    float(geometry.EndPoint.x), float(geometry.EndPoint.y),
                ]
                radius = float(geometry.Radius)
            else:
                raise ValueError(f"unsupported observed sketch geometry {type_name}")
            nodes.append({
                "kind": "sketch_geometry", "id": geometry_id,
                "label": f"{sketch.Label} geometry {index + 1}",
                "backend_native_id": f"{sketch.Name}.Geometry.{index}",
                "geometry_kind": kind, "construction": bool(sketch.getConstruction(index)),
                "coordinates": coordinates, "radius_mm": radius,
            })
        constraint_ids = []
        expression_map = {
            str(path): str(expression) for path, expression in getattr(sketch, "ExpressionEngine", ())
        }
        for index, constraint in enumerate(sketch.Constraints):
            linked = []
            for geometry_index in (
                getattr(constraint, "First", -1), getattr(constraint, "Second", -1),
                getattr(constraint, "Third", -1),
            ):
                if 0 <= geometry_index < len(geometry_ids) and geometry_ids[geometry_index] not in linked:
                    linked.append(geometry_ids[geometry_index])
            if not linked:
                continue
            constraint_id = f"constraint.{_slug(record['id'])}.{index}"
            constraint_ids.append(constraint_id)
            expression = expression_map.get(f"Constraints[{index}]")
            expression_id = next(
                (node_id for alias, node_id in alias_to_parameter.items() if expression and f".{alias}" in expression),
                None,
            )
            dimensional = str(constraint.Type) in {"Distance", "DistanceX", "DistanceY", "Radius", "Diameter"}
            nodes.append({
                "kind": "constraint", "id": constraint_id,
                "label": f"{sketch.Label} {constraint.Type} {index + 1}",
                "backend_native_id": f"{sketch.Name}.Constraint.{index}",
                "constraint_type": _slug(constraint.Type), "geometry_ids": linked,
                "state": "satisfied", "value": float(constraint.Value) if dimensional else None,
                "unit": "mm" if dimensional else None, "expression_id": expression_id,
            })
            if expression_id:
                relationships.append(_rel(
                    f"rel.{_slug(constraint_id)}.parameter", "references",
                    constraint_id, "cad_state_graph", expression_id,
                ))
        dof = max(0, int(sketch.solve()))
        nodes.append({
            "kind": "sketch", "id": sketch_id, "label": sketch.Label,
            "backend_native_id": sketch.Name, "support_reference_id": datum_id,
            "geometry_ids": geometry_ids, "constraint_ids": constraint_ids,
            "fully_constrained": bool(getattr(sketch, "FullyConstrained", dof == 0)),
            "degrees_of_freedom": dof,
        })
        for constraint_id in constraint_ids:
            relationships.append(_rel(
                f"rel.{_slug(sketch_id)}.{_slug(constraint_id)}", "constrained_by",
                sketch_id, "cad_state_graph", constraint_id,
            ))
        relationships.append(_rel(
            f"rel.{_slug(sketch_id)}.feature_ir", "realizes_feature_ir",
            sketch_id, "feature_ir", record["id"],
        ))
        for link in record.get("intent_links", []):
            relationships.append(_rel(
                f"rel.{_slug(sketch_id)}.intent.{_slug(link['eig_node_id'])}",
                "realizes_intent", sketch_id, "engineering_intent_graph",
                link["eig_node_id"],
            ))

    shape = final_feature.Shape
    bounds = shape.BoundBox
    solid_node = {
        "kind": "semantic_topology", "id": "topology.part_solid",
        "label": "Final part solid", "backend_native_id": "semantic:part_solid",
        "topology_kind": "solid", "semantic_role": "part_solid",
        "geometry_type": "brep_solid",
        "signature_sha256": _hash({
            "bounds": [bounds.XLength, bounds.YLength, bounds.ZLength],
            "volume": shape.Volume,
        }),
        "centroid_mm": _shape_center(shape),
        "direction": None, "adjacent_topology_ids": [],
        "measurements": _measurements(shape),
    }
    topology_nodes = [solid_node]
    cylinders = []
    for face in shape.Faces:
        surface = face.Surface
        if not hasattr(surface, "Radius") or not hasattr(surface, "Axis"):
            continue
        axis = surface.Axis
        if abs(abs(float(axis.z)) - 1) > 1e-6:
            continue
        center = surface.Center
        signature = {
            "radius": float(surface.Radius), "x": float(center.x),
            "y": float(center.y), "axis": [0.0, 0.0, 1.0],
        }
        cylinders.append((signature, face))
    cylinders.sort(key=lambda item: (-item[0]["radius"], item[0]["x"], item[0]["y"]))
    for signature, face in cylinders:
        token = _hash(signature)[:16]
        topology_nodes.append({
            "kind": "semantic_topology", "id": f"topology.cylinder_{token}",
            "label": "Cylindrical surface", "backend_native_id": f"semantic:cylinder:{token}",
            "topology_kind": "face", "semantic_role": f"cylindrical_surface_{token}",
            "geometry_type": "cylinder", "signature_sha256": _hash(signature),
            "centroid_mm": _shape_center(face),
            "direction": [0.0, 0.0, 1.0],
            "adjacent_topology_ids": ["topology.part_solid"],
            "measurements": [
                {"name": "diameter", "value": 2 * signature["radius"], "unit": "mm"},
                {"name": "center_x", "value": signature["x"], "unit": "mm"},
                {"name": "center_y", "value": signature["y"], "unit": "mm"},
            ],
        })
    nodes.extend(topology_nodes)

    previous_id = None
    for sequence, (records, native, profile_native) in enumerate(feature_pairs):
        feature_id = feature_node_ids[native.Name]
        body_feature_ids.append(feature_id)
        inputs = []
        if profile_native is not None:
            inputs.append(sketch_node_ids[profile_native.Name])
        if previous_id:
            inputs.append(previous_id)
        outputs = [item["id"] for item in topology_nodes] if native is final_feature else []
        nodes.append({
            "kind": "native_feature", "id": feature_id, "label": native.Label,
            "backend_native_id": native.Name, "native_feature_type": native.TypeId,
            "portable_feature_type": records[-1]["type"], "sequence_index": sequence,
            "suppressed": False, "input_ids": inputs, "output_topology_ids": outputs,
            "measurements": [{"name": "volume", "value": float(native.Shape.Volume), "unit": "mm3"}],
        })
        if profile_native is not None:
            relationships.append(_rel(
                f"rel.{_slug(feature_id)}.profile", "consumes_profile",
                feature_id, "cad_state_graph", sketch_node_ids[profile_native.Name],
            ))
        if previous_id:
            relationships.append(_rel(
                f"rel.{_slug(feature_id)}.dependency", "depends_on",
                feature_id, "cad_state_graph", previous_id,
            ))
        for topology in outputs:
            relationships.append(_rel(
                f"rel.{_slug(feature_id)}.{_slug(topology)}", "produces_topology",
                feature_id, "cad_state_graph", topology,
            ))
        for record in records:
            relationships.append(_rel(
                f"rel.{_slug(feature_id)}.feature_ir.{_slug(record['id'])}",
                "realizes_feature_ir", feature_id, "feature_ir", record["id"],
            ))
            for link in record.get("intent_links", []):
                relationships.append(_rel(
                    f"rel.{_slug(feature_id)}.{_slug(record['id'])}.intent.{_slug(link['eig_node_id'])}",
                    "realizes_intent", feature_id, "engineering_intent_graph",
                    link["eig_node_id"],
                ))
        previous_id = feature_id

    parameters_by_id = {
        item["id"]: item for item in feature_ir.get("parameters", [])
    }
    for interface in feature_ir.get("interfaces", []):
        if interface.get("correspondence_version") is None:
            continue
        eig_interface_id = next(
            item["eig_node_id"] for item in interface["intent_links"]
            if item["relation"] == "corresponds_to"
        )
        for binding in interface.get("geometry_bindings", []):
            diameters = [
                parameters_by_id[parameter_id]["value"]
                for parameter_id in binding["parameter_ids"]
                if parameter_id in parameters_by_id
                and "diameter" in parameters_by_id[parameter_id]["name"]
            ]
            for topology in topology_nodes:
                measured = {
                    item["name"]: item["value"]
                    for item in topology.get("measurements", [])
                }
                if topology.get("geometry_type") != "cylinder" or not any(
                    abs(measured.get("diameter", float("inf")) - expected) <= 1e-6
                    for expected in diameters
                ):
                    continue
                stem = (
                    f"rel.{_slug(topology['id'])}.interface.{_slug(binding['role'])}"
                )
                relationships.append({
                    **_rel(
                        f"{stem}.feature_ir", "corresponds_to_interface",
                        topology["id"], "feature_ir", interface["id"],
                    ),
                    "role": binding["role"],
                })
                relationships.append({
                    **_rel(
                        f"{stem}.engineering_intent_graph",
                        "corresponds_to_interface", topology["id"],
                        "engineering_intent_graph", eig_interface_id,
                    ),
                    "role": binding["role"],
                })
    nodes.insert(1, {
        "kind": "body", "id": body_id, "label": body.Label,
        "backend_native_id": body.Name, "feature_ids": body_feature_ids,
        "solid_count": len(shape.Solids),
        "measurements": [{"name": "volume", "value": float(shape.Volume), "unit": "mm3"}],
    })
    nodes.append({
        "kind": "diagnostic", "id": "diagnostic.recompute", "label": "Recompute status",
        "backend_native_id": None, "severity": "info", "code": "recompute_ok",
        "message": "FreeCAD document recomputed without errors",
        "related_node_ids": [document_id, body_id],
    })
    for artifact in artifacts:
        nodes.append({
            "kind": "artifact", "id": artifact["id"],
            "label": artifact["kind"].replace("_", " ").title(),
            "backend_native_id": None, "artifact_kind": artifact["kind"],
            "filename": artifact["filename"], "media_type": artifact["media_type"],
            "content_sha256": artifact["content_sha256"],
            "byte_length": artifact["byte_length"],
        })
    version = ".".join(str(item) for item in __import__("FreeCAD").Version()[:3])
    return {
        "schema_version": "1.0.0",
        "interface_correspondence_version": (
            "1.0.0" if any(
                item.get("correspondence_version") is not None
                for item in feature_ir.get("interfaces", [])
            ) else None
        ),
        "id": f"csg.freecad.{_slug(feature_ir['id'])}",
        "build_request_id": build_request["request_id"], "backend_id": "freecad",
        "backend_version": version,
        "source_feature_ir_sha256": build_request["feature_ir_manifest"]["content_sha256"],
        "root_document_id": document_id, "nodes": nodes, "relationships": relationships,
    }


def _build_native_model(build_request, feature_ir, artifact_root):
    import FreeCAD as App
    import Part
    import Sketcher

    parameters, aliases = _parameter_maps(feature_ir)
    values = {record_id: float(item["value"]) for record_id, item in parameters.items()}
    document_name = _native_name("CADAICO", feature_ir["id"])
    if App.listDocuments().get(document_name) is not None:
        App.closeDocument(document_name)
    doc = App.newDocument(document_name)
    doc.Label = feature_ir["label"]
    sheet = doc.addObject("Spreadsheet::Sheet", "Parameters")
    sheet.Label = "Feature IR Parameters"
    for row, item in enumerate(feature_ir["parameters"], 1):
        rendered = f"{item['value']} mm" if item["unit"] == "mm" else (
            f"{item['value']} deg" if item["unit"] == "degree" else str(item["value"])
        )
        sheet.set(f"A{row}", rendered)
        sheet.setAlias(f"A{row}", aliases[item["id"]])
        sheet.set(f"B{row}", "'" + item["id"])
        sheet.set(f"C{row}", "'" + item["label"])
    body = doc.addObject("PartDesign::Body", "MainBody")
    body.Label = feature_ir["bodies"][0]["label"]
    records = {item["id"]: item for item in feature_ir["features"]}
    pattern_sources = {
        item["source_feature_id"] for item in feature_ir["features"]
        if item["type"] == "rectangular_pattern"
    }
    sketch_pairs = []
    sketches = {}
    feature_pairs = []
    native_by_record = {}
    previous = None
    for record in feature_ir["features"]:
        kind = record["type"]
        if kind == "sketch":
            native = _add_sketch(body, record, App, Part, Sketcher, values, aliases)
            sketches[record["id"]] = native
            sketch_pairs.append((record, native))
            continue
        if kind == "pad":
            profile = sketches[record["sketch_id"]]
            native = body.newObject("PartDesign::Pad", _native_name("Feature", record["id"]))
            native.Label = record["label"]
            native.Profile = profile
            native.Length = _evaluate(record["length"], values)
            native.Midplane = bool(record["symmetric"])
            native.setExpression("Length", _native_expression(record["length"], aliases))
            doc.recompute()
            mapping = (record,)
        elif kind == "pocket":
            if record["id"] in pattern_sources:
                continue
            profile = sketches[record["sketch_id"]]
            native = body.newObject("PartDesign::Pocket", _native_name("Feature", record["id"]))
            native.Label = record["label"]
            native.Profile = profile
            native.Midplane = True
            if record["termination"] == "blind":
                native.Length = _evaluate(record["depth"], values)
                native.setExpression("Length", _native_expression(record["depth"], aliases))
            else:
                native.Length = max(1.0, previous.Shape.BoundBox.ZLength * 2)
            doc.recompute()
            mapping = (record,)
        elif kind == "rectangular_pattern":
            source = records[record["source_feature_id"]]
            source_sketch = records[source["sketch_id"]]
            profile = _add_pattern_sketch(
                body, record, source_sketch, App, Part, Sketcher, values, aliases
            )
            sketch_pairs.append((record, profile))
            native = body.newObject("PartDesign::Pocket", _native_name("Feature", record["id"]))
            native.Label = record["label"]
            native.Profile = profile
            native.Midplane = True
            native.Length = max(1.0, previous.Shape.BoundBox.ZLength * 2)
            doc.recompute()
            mapping = (source, record)
        elif kind == "linear_slot_pattern":
            profile = _add_slot_pattern_sketch(
                body, record, App, Part, Sketcher, values
            )
            sketch_pairs.append((record, profile))
            native = body.newObject(
                "PartDesign::Pocket", _native_name("Feature", record["id"])
            )
            native.Label = record["label"]
            native.Profile = profile
            native.Midplane = True
            native.Length = max(1.0, previous.Shape.BoundBox.ZLength * 2)
            doc.recompute()
            mapping = (record,)
        elif kind in {"chamfer", "fillet"}:
            reference = record["edges"]
            if reference["selector"] != "parallel_to_axis" or not reference.get("direction"):
                raise UnsupportedFeature(
                    f"{kind} currently requires a parallel-to-axis semantic edge set"
                )
            edge_names = _external_axis_edges(previous.Shape, reference["direction"])
            if not edge_names:
                raise ValueError(f"semantic edge selection found no external axis edges for {record['id']}")
            type_id = "PartDesign::Chamfer" if kind == "chamfer" else "PartDesign::Fillet"
            native = body.newObject(type_id, _native_name("Feature", record["id"]))
            native.Label = record["label"]
            native.Base = (previous, edge_names)
            property_name = "Size" if kind == "chamfer" else "Radius"
            expression = record["distance"] if kind == "chamfer" else record["radius"]
            setattr(native, property_name, _evaluate(expression, values))
            native.setExpression(property_name, _native_expression(expression, aliases))
            profile = None
            doc.recompute()
            mapping = (record,)
        else:
            raise UnsupportedFeature(f"unsupported Feature IR feature {kind!r}")
        if native.Shape.isNull():
            profile_detail = ""
            if profile is not None:
                profile_detail = (
                    f"; profile geometry={profile.GeometryCount} "
                    f"constraints={profile.ConstraintCount} dof={profile.solve()} "
                    f"state={[str(item) for item in profile.State]} "
                    f"expressions={list(profile.ExpressionEngine)}"
                )
            raise ValueError(
                f"native feature {record['id']} produced a null shape; "
                f"state={[str(item) for item in native.State]}{profile_detail}"
            )
        native_by_record[record["id"]] = native
        feature_pairs.append((mapping, native, profile))
        previous = native
    if previous is None:
        raise ValueError("Feature IR produced no solid feature")
    doc.recompute()
    stem = f"{_slug(feature_ir['part']['name'])}_r{feature_ir['design_revision']}"
    native_path = artifact_root / f"{stem}.FCStd"
    doc.saveAs(str(native_path))
    summary = _native_summary(
        doc, body, previous, native_path, feature_ir,
        [native for _, native in sketch_pairs],
        [native for _, native, _ in feature_pairs],
    )
    if summary["recompute_errors"]:
        raise ValueError("FreeCAD recompute errors: " + "; ".join(summary["recompute_errors"]))
    if summary["solid_count"] != 1 or not previous.Shape.isValid():
        raise ValueError("FreeCAD result is not one valid solid")
    step_path = artifact_root / f"{stem}.step"
    preview_path = artifact_root / f"{stem}.stl"
    previous.Shape.exportStep(str(step_path))
    previous.Shape.exportStl(str(preview_path))
    version = ".".join(str(item) for item in App.Version()[:3])
    source_hash = build_request["feature_ir_manifest"]["content_sha256"]
    artifacts = []
    for kind, path, media_type in (
        ("native_model", native_path, "application/vnd.freecad"),
        ("neutral_model", step_path, "model/step"),
        ("preview_model", preview_path, "model/stl"),
    ):
        artifacts.append({
            "schema_version": "1.0.0",
            "id": f"artifact.freecad.{kind}.r{feature_ir['design_revision']}",
            "kind": kind, "filename": path.name, "media_type": media_type,
            "content_sha256": _file_hash(path), "byte_length": path.stat().st_size,
            "backend_id": "freecad", "backend_version": version,
            "source_feature_ir_sha256": source_hash,
        })
    csg = _extract_csg(
        build_request, feature_ir, doc, body, previous, sheet, aliases,
        sketch_pairs, feature_pairs, artifacts,
    )
    return summary, csg, artifacts, version


def _edit_parameter(payload, build_request, feature_ir, artifact_root):
    import FreeCAD as App

    source_path = Path(payload["native_document_path"]).resolve()
    if not source_path.is_file() or source_path.suffix.lower() != ".fcstd":
        raise ValueError("native edit source must be an existing FCStd document")
    parameter_id = payload["parameter_id"]
    new_record = next(
        (item for item in feature_ir["parameters"] if item["id"] == parameter_id), None
    )
    if new_record is None or float(new_record["value"]) != float(payload["parameter_value"]):
        raise ValueError("edited value must match the updated Feature IR parameter ID")
    doc = App.openDocument(str(source_path))
    sheet = doc.getObject("Parameters")
    if sheet is None:
        raise ValueError("native document has no Feature IR parameter sheet")
    row = next(
        (
            index for index in range(1, 10000)
            if sheet.getContents(f"B{index}").lstrip("'") == parameter_id
        ),
        None,
    )
    if row is None:
        raise ValueError("native document does not contain the requested Feature IR parameter ID")
    rendered = f"{new_record['value']} mm" if new_record["unit"] == "mm" else (
        f"{new_record['value']} deg" if new_record["unit"] == "degree" else str(new_record["value"])
    )
    sheet.set(f"A{row}", rendered)
    doc.recompute()
    doc.save()
    App.closeDocument(doc.Name)
    return _build_native_model(build_request, feature_ir, artifact_root)


def _verify_step(path):
    import FreeCAD as App
    import Import

    name = "CADAICOStepVerification"
    if App.listDocuments().get(name) is not None:
        App.closeDocument(name)
    doc = App.newDocument(name)
    Import.insert(str(path), doc.Name)
    doc.recompute()
    shapes = [
        obj.Shape for obj in doc.Objects
        if hasattr(obj, "Shape") and not obj.Shape.isNull()
    ]
    return bool(shapes and sum(len(shape.Solids) for shape in shapes) == 1
                and all(shape.isValid() for shape in shapes))


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", default=os.environ.get("CADAICO_FREECAD_REQUEST"))
    parser.add_argument("--response", default=os.environ.get("CADAICO_FREECAD_RESPONSE"))
    args = parser.parse_args(argv)
    if not args.request or not args.response:
        parser.error("request and response paths are required")
    request_path, response_path = Path(args.request).resolve(), Path(args.response).resolve()
    request_id, operation = "invalid", "ping"
    allowed = {"ping", "build", "edit_parameter", "verify_reimport"}
    try:
        payload = json.loads(request_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("request must be a JSON object")
        request_id, operation = payload.get("request_id", "invalid"), payload.get("operation", "ping")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request_id must be a non-empty string")
        if payload.get("schema_version") != SCHEMA_VERSION:
            _write(response_path, request_id, operation if operation in allowed else "ping", "failed", ({
                "code": "protocol_mismatch", "message": "unsupported FreeCAD worker protocol",
            },))
            return 2
        if operation not in allowed:
            _write(response_path, request_id, "ping", "unsupported", ({
                "code": "unsupported_capability", "message": "operation is not implemented",
            },))
            return 2
        if operation == "ping":
            if set(payload) != {"schema_version", "request_id", "operation"}:
                raise ValueError("ping request fields do not match protocol 1.0.0")
            import FreeCAD as App
            version = ".".join(str(item) for item in App.Version()[:3])
            _write(response_path, request_id, operation, "succeeded", freecad_version=version)
        elif operation in {"build", "edit_parameter"}:
            build_request, feature_ir, artifact_root = _validate_build_payload(payload)
            result = (
                _build_native_model(build_request, feature_ir, artifact_root)
                if operation == "build"
                else _edit_parameter(payload, build_request, feature_ir, artifact_root)
            )
            summary, csg, artifacts, version = result
            _write(
                response_path, request_id, operation, "succeeded",
                freecad_version=version, native_build=summary,
                cad_state_graph=csg, artifacts=artifacts,
            )
        else:
            path = _validate_reimport_payload(payload)
            if not _verify_step(path):
                raise ValueError("STEP re-import did not produce one valid solid")
            import FreeCAD as App
            version = ".".join(str(item) for item in App.Version()[:3])
            _write(
                response_path, request_id, operation, "succeeded",
                freecad_version=version, reimport_verified=True,
            )
        return 0
    except Exception as exc:
        unsupported = isinstance(exc, UnsupportedFeature)
        _write(
            response_path, request_id, operation if operation in allowed else "ping",
            "unsupported" if unsupported else "failed", ({
                "code": "unsupported_capability" if unsupported else (
                    "build_failed" if operation in {"build", "edit_parameter"} else "invalid_request"
                ),
                "message": f"{type(exc).__name__}: {exc}",
            },),
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
