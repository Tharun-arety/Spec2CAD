"""Resolve defect evidence into bounded EIG, Feature IR and CSG trace links."""

from __future__ import annotations

from collections import defaultdict
from enum import Enum
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from spec2cad.cad_state_serialization import csg_content_hash
from spec2cad.feature_serialization import feature_ir_manifest
from spec2cad.schemas.cad_state_graph import (
    CADStateGraph,
    ReferenceNamespace,
    validate_csg_provenance,
)
from spec2cad.schemas.feature_ir import FeatureIR, StableId
from spec2cad.schemas.intent_graph import EngineeringIntentGraph

from .localization import DefectDiagnosis
from .sensors import SensorEvidence, SensorLayer


RESPONSIBILITY_TRACE_SCHEMA_VERSION = "1.0.0"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ResponsibilityNamespace(str, Enum):
    ENGINEERING_INTENT_GRAPH = "engineering_intent_graph"
    FEATURE_IR = "feature_ir"
    CAD_STATE_GRAPH = "cad_state_graph"


class ResponsibilityBasis(str, Enum):
    DIRECT_SENSOR = "direct_sensor"
    FEATURE_INTENT = "feature_intent"
    CSG_PROVENANCE = "csg_provenance"
    CSG_DEPENDENCY = "csg_dependency"


class ResponsibilityLink(_FrozenModel):
    namespace: ResponsibilityNamespace
    document_id: StableId
    record_id: StableId
    bases: tuple[ResponsibilityBasis, ...] = Field(min_length=1)
    sensor_ids: tuple[StableId, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_sets(self) -> "ResponsibilityLink":
        if tuple(sorted(set(self.bases), key=lambda item: item.value)) != self.bases:
            raise ValueError("responsibility bases must be sorted and unique")
        if tuple(sorted(set(self.sensor_ids))) != self.sensor_ids:
            raise ValueError("responsibility sensor ids must be sorted and unique")
        return self


class UnresolvedResponsibilityReference(_FrozenModel):
    sensor_id: StableId
    source_layer: SensorLayer
    document_id: StableId
    record_id: StableId
    reason: str = Field(min_length=1)


class DefectResponsibilityTrace(_FrozenModel):
    schema_version: Literal["1.0.0"] = RESPONSIBILITY_TRACE_SCHEMA_VERSION
    id: StableId
    diagnosis_id: StableId
    design_revision: int = Field(ge=1)
    sensor_ids: tuple[StableId, StableId]
    links: tuple[ResponsibilityLink, ...]
    unresolved_references: tuple[UnresolvedResponsibilityReference, ...] = ()
    missing_namespaces: tuple[ResponsibilityNamespace, ...] = ()
    complete: bool
    advisory: bool

    @model_validator(mode="after")
    def validate_completeness(self) -> "DefectResponsibilityTrace":
        namespaces = {item.namespace for item in self.links}
        expected = set(ResponsibilityNamespace)
        missing = tuple(sorted(expected - namespaces, key=lambda item: item.value))
        if self.missing_namespaces != missing:
            raise ValueError("missing namespaces must reflect responsibility links")
        derived_complete = not missing and not self.unresolved_references
        if self.complete != derived_complete:
            raise ValueError("trace completeness must reflect links and unresolved records")
        if tuple(sorted(self.sensor_ids)) != self.sensor_ids:
            raise ValueError("trace sensor ids must be sorted")
        return self

    def record_ids(self, namespace: ResponsibilityNamespace) -> tuple[StableId, ...]:
        return tuple(sorted({
            item.record_id for item in self.links if item.namespace is namespace
        }))


def _model_hash(value: BaseModel) -> str:
    payload = json.dumps(
        value.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _all_feature_ir_records(feature_ir: FeatureIR) -> dict[str, object]:
    records: dict[str, object] = {}

    def visit(value: object) -> None:
        if isinstance(value, BaseModel):
            record_id = getattr(value, "id", None)
            if isinstance(record_id, str):
                records[record_id] = value
            for field_name in value.__class__.model_fields:
                visit(getattr(value, field_name))
        elif isinstance(value, (tuple, list)):
            for item in value:
                visit(item)

    visit(feature_ir)
    return records


def _trace_id(
    diagnosis_id: str,
    links: tuple[ResponsibilityLink, ...],
    unresolved: tuple[UnresolvedResponsibilityReference, ...],
) -> str:
    identity = [diagnosis_id]
    identity.extend(
        f"{item.namespace.value}:{item.document_id}:{item.record_id}"
        for item in links
    )
    identity.extend(
        f"unresolved:{item.sensor_id}:{item.document_id}:{item.record_id}"
        for item in unresolved
    )
    digest = hashlib.sha256("\n".join(identity).encode("utf-8")).hexdigest()
    return f"trace.{digest[:32]}"


def trace_defect_responsibility(
    diagnoses: tuple[DefectDiagnosis, ...],
    evidence: tuple[SensorEvidence, ...],
    *,
    intent_graph: EngineeringIntentGraph,
    feature_ir: FeatureIR,
    cad_state_graphs: tuple[CADStateGraph, ...],
) -> tuple[DefectResponsibilityTrace, ...]:
    """Resolve exact sensor records and declared provenance without guessing."""
    if intent_graph.revision != feature_ir.design_revision:
        raise ValueError("EIG and Feature IR design revisions differ")
    evidence_by_id = {item.id: item for item in evidence}
    if len(evidence_by_id) != len(evidence):
        raise ValueError("SensorEvidence ids must be unique")
    eig_records = {item.id: item for item in intent_graph.nodes}
    feature_records = _all_feature_ir_records(feature_ir)
    feature_hash = feature_ir_manifest(feature_ir).content_sha256
    eig_hash = _model_hash(intent_graph)
    csg_records = {
        graph.id: {item.id: item for item in graph.nodes}
        for graph in cad_state_graphs
    }
    if len(csg_records) != len(cad_state_graphs):
        raise ValueError("CAD State Graph ids must be unique")
    for graph in cad_state_graphs:
        if graph.source_feature_ir_sha256 != feature_hash:
            raise ValueError("CAD State Graph and Feature IR identities differ")
        validate_csg_provenance(
            graph, intent_graph=intent_graph, feature_ir=feature_ir
        )

    traces: list[DefectResponsibilityTrace] = []
    for diagnosis in sorted(diagnoses, key=lambda item: item.id):
        sensors = []
        for sensor_id in diagnosis.sensor_ids:
            sensor = evidence_by_id.get(sensor_id)
            if sensor is None:
                raise ValueError(f"diagnosis references missing SensorEvidence {sensor_id}")
            if sensor.design_revision != diagnosis.design_revision:
                raise ValueError("diagnosis and SensorEvidence revisions differ")
            sensors.append(sensor)

        link_state: dict[
            tuple[ResponsibilityNamespace, str, str],
            tuple[set[ResponsibilityBasis], set[str]],
        ] = defaultdict(lambda: (set(), set()))
        unresolved: list[UnresolvedResponsibilityReference] = []
        direct_csg: set[tuple[str, str]] = set()

        def add_link(namespace, document_id, record_id, basis, sensor_ids):
            bases, contributors = link_state[(namespace, document_id, record_id)]
            before = (len(bases), len(contributors))
            bases.add(basis)
            contributors.update(sensor_ids)
            return before != (len(bases), len(contributors))

        for sensor in sensors:
            layer = sensor.source.layer
            if layer is SensorLayer.ENGINEERING_INTENT_EXPECTATION:
                if sensor.source.document_sha256 != eig_hash:
                    raise ValueError("SensorEvidence references a different EIG revision")
                for record_id in sensor.source.record_ids:
                    if record_id not in eig_records:
                        raise ValueError(f"missing EIG record {record_id}")
                    add_link(
                        ResponsibilityNamespace.ENGINEERING_INTENT_GRAPH,
                        sensor.source.document_id, record_id,
                        ResponsibilityBasis.DIRECT_SENSOR, (sensor.id,),
                    )
            elif layer is SensorLayer.FEATURE_IR_VALUE:
                if sensor.source.document_sha256 != feature_hash:
                    raise ValueError("SensorEvidence references a different Feature IR")
                for record_id in sensor.source.record_ids:
                    if record_id not in feature_records:
                        raise ValueError(f"missing Feature IR record {record_id}")
                    add_link(
                        ResponsibilityNamespace.FEATURE_IR,
                        feature_ir.id, record_id,
                        ResponsibilityBasis.DIRECT_SENSOR, (sensor.id,),
                    )
            elif layer is SensorLayer.VISUAL_DIAGNOSTIC:
                for record_id in sensor.source.record_ids:
                    unresolved.append(UnresolvedResponsibilityReference(
                        sensor_id=sensor.id,
                        source_layer=layer,
                        document_id=sensor.source.document_id,
                        record_id=record_id,
                        reason=(
                            "advisory visual record is outside the authoritative "
                            "EIG, Feature IR and CAD State Graphs"
                        ),
                    ))
            else:
                candidates = [
                    graph for graph in cad_state_graphs
                    if graph.backend_id == sensor.source.backend_id
                    and (
                        graph.id == sensor.source.document_id
                        or csg_content_hash(graph) == sensor.source.document_sha256
                    )
                ]
                if len(candidates) != 1:
                    raise ValueError(
                        f"SensorEvidence {sensor.id} does not identify one CAD State Graph"
                    )
                graph = candidates[0]
                if csg_content_hash(graph) != sensor.source.document_sha256:
                    raise ValueError("SensorEvidence references a different CAD State Graph")
                for record_id in sensor.source.record_ids:
                    if record_id not in csg_records[graph.id]:
                        raise ValueError(f"missing CSG record {record_id}")
                    direct_csg.add((graph.id, record_id))
                    add_link(
                        ResponsibilityNamespace.CAD_STATE_GRAPH,
                        graph.id, record_id,
                        ResponsibilityBasis.DIRECT_SENSOR, (sensor.id,),
                    )

        # One internal hop associates an exact observed constraint/topology node
        # with the declared CSG feature or sketch that owns/produces it.
        for graph in cad_state_graphs:
            for relationship in graph.relationships:
                if relationship.target.namespace is not ReferenceNamespace.CAD_STATE_GRAPH:
                    continue
                source = (graph.id, relationship.source.id)
                target = (graph.id, relationship.target.id)
                if source in direct_csg or target in direct_csg:
                    contributors = set()
                    for graph_id, record_id in (source, target):
                        state = link_state.get((
                            ResponsibilityNamespace.CAD_STATE_GRAPH,
                            graph_id, record_id,
                        ))
                        if state:
                            contributors.update(state[1])
                    for graph_id, record_id in (source, target):
                        add_link(
                            ResponsibilityNamespace.CAD_STATE_GRAPH,
                            graph_id, record_id,
                            ResponsibilityBasis.CSG_DEPENDENCY,
                            contributors or diagnosis.sensor_ids,
                        )

        # Resolve external CSG provenance in both directions. This connects a
        # direct CSG observation to its authority records and an EIG/FIR defect
        # to the exact backend records that declare realization of those IDs.
        changed = True
        while changed:
            changed = False
            for graph in cad_state_graphs:
                for relationship in graph.relationships:
                    if relationship.target.namespace is ReferenceNamespace.CAD_STATE_GRAPH:
                        continue
                    source_key = (
                        ResponsibilityNamespace.CAD_STATE_GRAPH,
                        graph.id,
                        relationship.source.id,
                    )
                    target_namespace = ResponsibilityNamespace(
                        relationship.target.namespace.value
                    )
                    target_document = (
                        feature_ir.id
                        if target_namespace is ResponsibilityNamespace.FEATURE_IR
                        else f"eig.r{intent_graph.revision}"
                    )
                    target_key = (
                        target_namespace,
                        target_document,
                        relationship.target.id,
                    )
                    source_states = [
                        state for key, state in link_state.items()
                        if key[0] is ResponsibilityNamespace.CAD_STATE_GRAPH
                        and key[1:] == source_key[1:]
                    ]
                    target_states = [
                        state for key, state in link_state.items()
                        if key[0] is target_namespace
                        and key[2] == relationship.target.id
                    ]
                    contributors = set().union(
                        *(state[1] for state in (*source_states, *target_states))
                    )
                    if source_states or target_states:
                        changed |= add_link(
                            *source_key,
                            ResponsibilityBasis.CSG_PROVENANCE,
                            contributors or diagnosis.sensor_ids,
                        )
                        changed |= add_link(
                            *target_key,
                            ResponsibilityBasis.CSG_PROVENANCE,
                            contributors or diagnosis.sensor_ids,
                        )

        # Every linked Feature IR record carries its authoritative EIG links.
        linked_feature_ids = {
            key[2] for key in link_state
            if key[0] is ResponsibilityNamespace.FEATURE_IR
        }
        eig_document_id = next(
            (
                sensor.source.document_id for sensor in sensors
                if sensor.source.layer is SensorLayer.ENGINEERING_INTENT_EXPECTATION
            ),
            f"eig.r{intent_graph.revision}",
        )
        for record in feature_ir.intent_linked_records():
            if record.id not in linked_feature_ids:
                continue
            feature_states = [
                state for key, state in link_state.items()
                if key[0] is ResponsibilityNamespace.FEATURE_IR and key[2] == record.id
            ]
            contributors = set().union(*(state[1] for state in feature_states))
            for intent_link in record.intent_links:
                add_link(
                    ResponsibilityNamespace.ENGINEERING_INTENT_GRAPH,
                    eig_document_id,
                    intent_link.eig_node_id,
                    ResponsibilityBasis.FEATURE_INTENT,
                    contributors or diagnosis.sensor_ids,
                )

        links = tuple(sorted(
            (
                ResponsibilityLink(
                    namespace=namespace,
                    document_id=document_id,
                    record_id=record_id,
                    bases=tuple(sorted(bases, key=lambda item: item.value)),
                    sensor_ids=tuple(sorted(contributors)),
                )
                for (namespace, document_id, record_id),
                (bases, contributors) in link_state.items()
            ),
            key=lambda item: (
                item.namespace.value, item.document_id, item.record_id
            ),
        ))
        unresolved_tuple = tuple(sorted(
            unresolved,
            key=lambda item: (item.sensor_id, item.document_id, item.record_id),
        ))
        complete = (
            {item.namespace for item in links} == set(ResponsibilityNamespace)
            and not unresolved_tuple
        )
        missing_namespaces = tuple(sorted(
            set(ResponsibilityNamespace) - {item.namespace for item in links},
            key=lambda item: item.value,
        ))
        traces.append(DefectResponsibilityTrace(
            id=_trace_id(diagnosis.id, links, unresolved_tuple),
            diagnosis_id=diagnosis.id,
            design_revision=diagnosis.design_revision,
            sensor_ids=diagnosis.sensor_ids,
            links=links,
            unresolved_references=unresolved_tuple,
            missing_namespaces=missing_namespaces,
            complete=complete,
            advisory=diagnosis.advisory,
        ))
    return tuple(traces)
