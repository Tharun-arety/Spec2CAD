"""Traceable analytic engineering calculations over measured B-Rep properties."""

from __future__ import annotations

from dataclasses import dataclass

from spec2cad.schemas.analysis_ir import (
    AnalysisProgram,
    AxialStressRequest,
    BendingStressRequest,
    FitRequest,
    MassPropertiesRequest,
    ThermalExpansionRequest,
)


@dataclass(frozen=True)
class AnalysisResult:
    id: str
    analysis_type: str
    passed: bool | None
    values: dict[str, float | str]
    assumptions: list[str]
    message: str


def run_analyses(shape, program: AnalysisProgram) -> list[AnalysisResult]:
    material = program.material
    volume_mm3 = float(shape.Volume())
    density_kg_mm3 = material.density_kg_m3 / 1e9
    results: list[AnalysisResult] = []

    for request in program.requests:
        if isinstance(request, MassPropertiesRequest):
            center = shape.Center()
            inertia_volume = type(shape).matrixOfInertia(shape)
            inertia = [
                [value * density_kg_mm3 for value in row]
                for row in inertia_volume
            ]
            results.append(AnalysisResult(
                request.id, request.type, None,
                {
                    "volume_mm3": volume_mm3,
                    "mass_kg": volume_mm3 * density_kg_mm3,
                    "center_x_mm": center.x,
                    "center_y_mm": center.y,
                    "center_z_mm": center.z,
                    "inertia_xx_kg_mm2": inertia[0][0],
                    "inertia_yy_kg_mm2": inertia[1][1],
                    "inertia_zz_kg_mm2": inertia[2][2],
                },
                [f"homogeneous isotropic {material.name}", "nominal CAD geometry"],
                "mass properties calculated from the finished B-Rep",
            ))
        elif isinstance(request, AxialStressRequest):
            if material.yield_strength_mpa is None:
                raise ValueError("axial stress safety factor requires material yield strength")
            area = volume_mm3 / request.load_path_length_mm
            stress = abs(request.force_n) / area
            safety = material.yield_strength_mpa / stress if stress > 0 else float("inf")
            safety_value: float | str = safety if stress > 0 else "infinite"
            results.append(AnalysisResult(
                request.id, request.type, safety >= request.required_safety_factor,
                {
                    "average_area_mm2": area, "stress_mpa": stress,
                    "yield_safety_factor": safety_value,
                    "required_safety_factor": request.required_safety_factor,
                },
                ["uniform axial stress", "average section area = volume/load-path length"],
                f"axial yield safety factor is {safety:.4g}",
            ))
        elif isinstance(request, BendingStressRequest):
            if material.yield_strength_mpa is None:
                raise ValueError("bending stress safety factor requires material yield strength")
            stress = abs(request.moment_n_mm) / request.section_modulus_mm3
            safety = material.yield_strength_mpa / stress if stress > 0 else float("inf")
            safety_value = safety if stress > 0 else "infinite"
            results.append(AnalysisResult(
                request.id, request.type, safety >= request.required_safety_factor,
                {
                    "stress_mpa": stress, "yield_safety_factor": safety_value,
                    "required_safety_factor": request.required_safety_factor,
                },
                ["linear elastic beam theory", "user-supplied section modulus"],
                f"bending yield safety factor is {safety:.4g}",
            ))
        elif isinstance(request, ThermalExpansionRequest):
            if material.thermal_expansion_per_c is None:
                raise ValueError("thermal expansion requires a material expansion coefficient")
            delta = (
                material.thermal_expansion_per_c
                * request.original_length_mm
                * request.temperature_change_c
            )
            results.append(AnalysisResult(
                request.id, request.type, None,
                {"length_change_mm": delta, "final_length_mm": request.original_length_mm + delta},
                ["uniform temperature", "unconstrained isotropic expansion"],
                f"predicted free length change is {delta:.6g} mm",
            ))
        elif isinstance(request, FitRequest):
            minimum_clearance = (
                request.hole_nominal_mm - request.hole_tolerance_mm
                - request.shaft_nominal_mm - request.shaft_tolerance_mm
            )
            maximum_clearance = (
                request.hole_nominal_mm + request.hole_tolerance_mm
                - request.shaft_nominal_mm + request.shaft_tolerance_mm
            )
            passed = minimum_clearance >= 0 if request.require_clearance else maximum_clearance <= 0
            results.append(AnalysisResult(
                request.id, request.type, passed,
                {
                    "minimum_clearance_mm": minimum_clearance,
                    "maximum_clearance_mm": maximum_clearance,
                },
                ["worst-case limit stack", "bilateral tolerances"],
                f"worst-case clearance range is {minimum_clearance:.6g} to {maximum_clearance:.6g} mm",
            ))
    return results
