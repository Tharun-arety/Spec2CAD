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
]
