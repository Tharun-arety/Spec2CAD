"""Cross-representation and cross-backend reconciliation contracts."""

from .tolerances import (
    R1_TOLERANCE_POLICY,
    QuantityKind,
    ReconciliationComparison,
    ReconciliationTolerancePolicy,
    ToleranceRule,
)

__all__ = [
    "R1_TOLERANCE_POLICY",
    "QuantityKind",
    "ReconciliationComparison",
    "ReconciliationTolerancePolicy",
    "ToleranceRule",
]
from .observations import (
    Applicability,
    GovernedQuantity,
    InterfaceGeometryObservation,
    NumericObservation,
    ObservationLayer,
    ObservationSet,
    ObservationSource,
    ObservationUnit,
    Point2D,
    PointSetObservation,
    PredicateObservation,
    PredicateOutcome,
)
from .geometry import (
    GeometryReconciliationCheck,
    GeometryReconciliationError,
    GeometryReconciliationReport,
    extract_motor_observations,
    reconcile_motor_geometry,
)
from .predicates import (
    PredicateParityCheck,
    PredicateReconciliationReport,
    observe_requirement_predicates,
    reconcile_predicates,
)
from .classification import (
    ClassifiedReconciliation,
    ReconciliationClassification,
    classify_reconciliation,
)
from .sensors import (
    SENSOR_EVIDENCE_SCHEMA_VERSION,
    SensorDiagnostic,
    SensorDiagnosticSeverity,
    SensorEvidence,
    SensorLayer,
    SensorMethod,
    SensorReference,
    SensorReleaseRole,
    SensorTolerance,
)
from .sensor_extraction import (
    csg_health_sensor_evidence,
    sensor_evidence_from_observation,
    sensor_evidence_from_observation_set,
    visual_diagnostic_evidence,
)
from .consistency import (
    CONSISTENCY_MATRIX_SCHEMA_VERSION,
    ComparisonKind,
    ConsistencyCell,
    ConsistencyStatus,
    QuantityConsistencyMatrix,
    build_consistency_matrices,
)
from .native_inspection import (
    NATIVE_INSPECTION_SCHEMA_VERSION,
    NativeInspectionFinding,
    NativeInspectionKind,
    NativeInspectionReport,
    NativeInspectionStatus,
    inspect_native_health,
)
from .topology_fingerprints import (
    TOPOLOGY_FINGERPRINT_POLICY_VERSION,
    TOPOLOGY_FINGERPRINT_SCHEMA_VERSION,
    FingerprintMeasurement,
    TopologyFingerprint,
    topology_fingerprints,
)
from .localization import (
    DEFECT_DIAGNOSIS_SCHEMA_VERSION,
    DefectDiagnosis,
    DefectOrigin,
    diagnose_inconsistencies,
)
from .traceability import (
    RESPONSIBILITY_TRACE_SCHEMA_VERSION,
    DefectResponsibilityTrace,
    ResponsibilityBasis,
    ResponsibilityLink,
    ResponsibilityNamespace,
    UnresolvedResponsibilityReference,
    trace_defect_responsibility,
)
from .governing_consistency import (
    GOVERNING_CONSISTENCY_SCHEMA_VERSION,
    GoverningConsistencyAssessment,
    GoverningConsistencyStatus,
    assess_governing_consistency,
)

__all__ = [
    "Applicability", "GovernedQuantity", "InterfaceGeometryObservation",
    "NumericObservation", "ObservationLayer", "ObservationSet",
    "ObservationSource", "ObservationUnit", "Point2D",
    "PointSetObservation", "PredicateObservation", "PredicateOutcome",
    "GeometryReconciliationCheck", "GeometryReconciliationError",
    "GeometryReconciliationReport", "extract_motor_observations",
    "reconcile_motor_geometry",
    "PredicateParityCheck", "PredicateReconciliationReport",
    "observe_requirement_predicates", "reconcile_predicates",
    "ClassifiedReconciliation", "ReconciliationClassification",
    "classify_reconciliation",
    "SENSOR_EVIDENCE_SCHEMA_VERSION", "SensorDiagnostic",
    "SensorDiagnosticSeverity", "SensorEvidence", "SensorLayer",
    "SensorMethod", "SensorReference", "SensorReleaseRole",
    "SensorTolerance",
    "csg_health_sensor_evidence", "sensor_evidence_from_observation",
    "sensor_evidence_from_observation_set", "visual_diagnostic_evidence",
    "CONSISTENCY_MATRIX_SCHEMA_VERSION", "ComparisonKind",
    "ConsistencyCell", "ConsistencyStatus", "QuantityConsistencyMatrix",
    "build_consistency_matrices",
    "NATIVE_INSPECTION_SCHEMA_VERSION", "NativeInspectionFinding",
    "NativeInspectionKind", "NativeInspectionReport", "NativeInspectionStatus",
    "inspect_native_health",
    "TOPOLOGY_FINGERPRINT_POLICY_VERSION",
    "TOPOLOGY_FINGERPRINT_SCHEMA_VERSION", "FingerprintMeasurement",
    "TopologyFingerprint", "topology_fingerprints",
    "DEFECT_DIAGNOSIS_SCHEMA_VERSION", "DefectDiagnosis", "DefectOrigin",
    "diagnose_inconsistencies",
    "RESPONSIBILITY_TRACE_SCHEMA_VERSION", "DefectResponsibilityTrace",
    "ResponsibilityBasis", "ResponsibilityLink", "ResponsibilityNamespace",
    "UnresolvedResponsibilityReference", "trace_defect_responsibility",
    "GOVERNING_CONSISTENCY_SCHEMA_VERSION", "GoverningConsistencyAssessment",
    "GoverningConsistencyStatus", "assess_governing_consistency",
]
