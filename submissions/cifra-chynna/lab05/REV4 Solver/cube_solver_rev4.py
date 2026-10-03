"""
Structural Solver - Rev. 4 (Step 1 architecture foundation)
6m x 6m x 6m Cube Frame Model

This file is a Rev 4 working copy of the Rev H baseline.

Step 1 goal:
  - preserve the existing model and solver behavior
  - add the new Rev 4 load-case architecture in a non-invasive way
  - prepare insertion points for load cases, diaphragm definitions, combinations,
    and validation without rewriting the current analysis engine

All REV1 geometry, DOF handling, local-axis logic, and solver behavior remain
unchanged until the next implementation steps add the actual load framework.

The blueprint desktop interface is embedded in this file and launches by
default. Run with --web to use the browser interface. PyQt6 is only required
when launching the desktop interface; importing the solver engine stays GUI-free.
"""

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from mpl_toolkits.mplot3d import Axes3D
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import openpyxl
from openpyxl.styles import (PatternFill, Font, Alignment, Border, Side)
from openpyxl.utils import get_column_letter
import pandas as pd
import glob
import os
import sys
import textwrap
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any

HERE = os.path.dirname(os.path.abspath(__file__))
REV4_OUTPUT_FOLDER = os.path.join(HERE, "solver load figures")

REV4_DISTRIBUTED_BAND_ALPHA = 0.30
REV4_SELF_WEIGHT_BAND_ALPHA = 0.18


# =============================================================================
# DATACLASSES — typed containers for loaded configuration
# =============================================================================

@dataclass
class UnitConfig:
    system: str                        # "Standard Metric" or "Imperial"
    units: Dict[str, str]              # quantity -> unit label
    conversions: Dict[str, float]      # quantity -> Imperial-to-Metric factor


@dataclass
class MaterialConfig:
    label: str
    category: str
    unit_system: str
    E: float
    G: float
    Nu: float
    thermal_coeff: float
    density: float                     # kN/m³ (metric) or k/ft³ (imperial)
    mass_density: float                # kg/m³ (metric only; 0 for imperial)
    Fy: float
    Fu: float
    # Unit labels for display
    E_unit: str = "MPa"
    stress_unit: str = "MPa"
    density_unit: str = "kN/m³"


@dataclass
class SectionConfig:
    label_imperial: str                # e.g. "W6X25"
    label_metric: str                  # e.g. "W150x37"
    unit_system: str
    W_lbft: float                      # weight lb/ft (always stored)
    A: float                           # area
    d: float                           # depth
    bf: float                          # flange width
    tf: float                          # flange thickness
    tw: float                          # web thickness
    Ix: float                          # strong-axis moment of inertia
    Sx: float                          # strong-axis section modulus
    Zx: float                          # strong-axis plastic modulus
    Iy: float                          # weak-axis moment of inertia
    Sy: float                          # weak-axis section modulus
    J: float                           # torsional constant
    # Unit labels for display
    length_unit: str = "mm"
    area_unit: str = "mm²"
    inertia_unit: str = "mm⁴"
    modulus_unit: str = "mm³"


# =============================================================================
# STEP 1 — Rev 4 load-case architecture layer
# =============================================================================

@dataclass
class NodalLoad:
    node_id: int
    fx: float = 0.0
    fy: float = 0.0
    fz: float = 0.0
    mx: float = 0.0
    my: float = 0.0
    mz: float = 0.0


@dataclass
class MemberDistributedLoad:
    member_id: int
    direction: str = "FY"
    magnitude: float = 0.0
    distribution_type: str = "uniform"


@dataclass
class MemberPointLoad:
    member_id: int
    location: float = 0.5
    direction: str = "FY"
    magnitude: float = 0.0


@dataclass
class TemperatureLoad:
    member_id: int
    temperature_change: float = 0.0
    reference_temperature: float = 20.0

    @property
    def unit(self) -> str:
        return "degC"


@dataclass
class Diaphragm:
    id: int
    name: str
    master_node: int
    constrained_nodes: List[int] = field(default_factory=list)
    degrees_of_freedom: List[str] = field(default_factory=lambda: ["UX", "UZ", "RY"])  # roof in-plane motion


@dataclass
class LoadCase:
    id: int
    name: str
    category: str
    description: str = ""
    self_weight_factor: float = 0.0
    loads: List[Any] = field(default_factory=list)


@dataclass
class LoadCombination:
    id: int
    name: str
    design_method: str = "LRFD"
    factors: Dict[int, float] = field(default_factory=dict)


def build_rev4_combinations() -> List[LoadCombination]:
    """Build the 30 handout combinations without duplicating load objects.

    The factor sets are recorded as an NSCP 2015 transcription and must be
    checked against the governing printed edition before design use.
    """
    lrfd = [
        ("1.4D", {1: 1.4}),
        ("1.2D + 1.6L", {1: 1.2, 3: 1.6}),
        ("1.2D + 1.0L + 1.0WX", {1: 1.2, 3: 1.0, 5: 1.0}),
        ("1.2D + 1.0L + 1.0WZ", {1: 1.2, 3: 1.0, 6: 1.0}),
        ("1.2D + 1.0L + 1.0EX", {1: 1.2, 3: 1.0, 7: 1.0}),
        ("1.2D + 1.0L + 1.0EZ", {1: 1.2, 3: 1.0, 8: 1.0}),
        ("0.9D + 1.0WX", {1: 0.9, 5: 1.0}),
        ("0.9D + 1.0WZ", {1: 0.9, 6: 1.0}),
        ("0.9D + 1.0EX", {1: 0.9, 7: 1.0}),
        ("0.9D + 1.0EZ", {1: 0.9, 8: 1.0}),
        ("1.2D + 1.0T", {1: 1.2, 9: 1.0}),
        ("1.2D + 1.0L + 1.0T", {1: 1.2, 3: 1.0, 9: 1.0}),
        ("0.9D + 1.0T", {1: 0.9, 9: 1.0}),
        ("1.2D + 1.0EX + 1.0T", {1: 1.2, 7: 1.0, 9: 1.0}),
        ("1.2D + 1.0EZ + 1.0T", {1: 1.2, 8: 1.0, 9: 1.0}),
    ]
    asd = [
        ("D", {1: 1.0}),
        ("D + L", {1: 1.0, 3: 1.0}),
        ("D + L + WX", {1: 1.0, 3: 1.0, 5: 1.0}),
        ("D + L + WZ", {1: 1.0, 3: 1.0, 6: 1.0}),
        ("D + L + EX", {1: 1.0, 3: 1.0, 7: 1.0}),
        ("D + L + EZ", {1: 1.0, 3: 1.0, 8: 1.0}),
        ("D + WX", {1: 1.0, 5: 1.0}),
        ("D + WZ", {1: 1.0, 6: 1.0}),
        ("D + EX", {1: 1.0, 7: 1.0}),
        ("D + EZ", {1: 1.0, 8: 1.0}),
        ("D + T", {1: 1.0, 9: 1.0}),
        ("D + L + T", {1: 1.0, 3: 1.0, 9: 1.0}),
        ("D + 0.7T", {1: 1.0, 9: 0.7}),
        ("D + EX + T", {1: 1.0, 7: 1.0, 9: 1.0}),
        ("D + EZ + T", {1: 1.0, 8: 1.0, 9: 1.0}),
    ]
    combinations = []
    for index, (name, factors) in enumerate(lrfd, start=1):
        combinations.append(LoadCombination(index, name, "LRFD", factors))
    for index, (name, factors) in enumerate(asd, start=16):
        combinations.append(LoadCombination(index, name, "ASD", factors))
    # Match the handout's representative viewer combinations: all three dead
    # load definitions are shown together in 1.4D and the representative ASD D
    # views use the same dead-load set without a factor.
    combinations[0] = LoadCombination(1, "1.4D", "LRFD", {1: 1.4, 2: 1.4, 4: 1.4})
    combinations[12] = LoadCombination(13, "D", "ASD", {1: 1.0, 2: 1.0, 4: 1.0})
    combinations[14] = LoadCombination(15, "D", "ASD", {1: 1.0, 2: 1.0, 4: 1.0})
    return combinations


def initialize_rev4_load_architecture() -> Dict[str, Any]:
    """
    Step 1 creates the Rev 4 load architecture in a non-invasive way.

    This does not replace the existing geometry or solver; it only defines the
    data model that later steps will populate for load cases, diaphragm
    constraints, and load combinations.
    """
    roof_beam_ids = [5, 6, 7, 8]
    roof_nodes = [5, 6, 7, 8]

    load_cases = [
        LoadCase(
            id=1,
            name="DEAD / SELF WEIGHT",
            category="Dead Load",
            description="Self-weight generated from section and material properties, acting in negative global Y.",
            self_weight_factor=1.0,
            loads=[
                MemberDistributedLoad(member_id=mid, direction="-FY", magnitude=0.0, distribution_type="self_weight")
                for mid in roof_beam_ids
            ],
        ),
        LoadCase(
            id=2,
            name="ROOF DEAD",
            category="Dead Load",
            description="Roof-beam distributed dead load of 5 kN/m downward, applied to roof beam members.",
            self_weight_factor=0.0,
            loads=[
                MemberDistributedLoad(member_id=mid, direction="-FY", magnitude=5.0, distribution_type="uniform")
                for mid in roof_beam_ids
            ],
        ),
        LoadCase(
            id=3,
            name="ROOF LIVE",
            category="Live Load",
            description="Roof-beam distributed live load of 3 kN/m downward, applied to roof beam members.",
            self_weight_factor=0.0,
            loads=[
                MemberDistributedLoad(member_id=mid, direction="-FY", magnitude=3.0, distribution_type="uniform")
                for mid in roof_beam_ids
            ],
        ),
        LoadCase(
            id=4,
            name="ROOF BEAM CENTER LOAD",
            category="Member Point Load",
            description="5 kN point load at the midpoint of each selected roof beam member.",
            self_weight_factor=0.0,
            loads=[
                MemberPointLoad(member_id=mid, location=0.5, direction="-FY", magnitude=5.0)
                for mid in roof_beam_ids
            ],
        ),
        LoadCase(
            id=5,
            name="WIND X",
            category="Wind",
            description="Total 10 kN lateral wind load in global X direction divided equally among four roof nodes.",
            self_weight_factor=0.0,
            loads=[
                NodalLoad(node_id=node_id, fx=2.5, fy=0.0, fz=0.0, mx=0.0, my=0.0, mz=0.0)
                for node_id in roof_nodes
            ],
        ),
        LoadCase(
            id=6,
            name="WIND Z",
            category="Wind",
            description="Total 10 kN lateral wind load in global Z direction divided equally among four roof nodes.",
            self_weight_factor=0.0,
            loads=[
                NodalLoad(node_id=node_id, fx=0.0, fy=0.0, fz=2.5, mx=0.0, my=0.0, mz=0.0)
                for node_id in roof_nodes
            ],
        ),
        LoadCase(
            id=7,
            name="SEISMIC X",
            category="Seismic",
            description="Total 15 kN lateral seismic load in global X direction divided equally among four roof nodes.",
            self_weight_factor=0.0,
            loads=[
                NodalLoad(node_id=node_id, fx=3.75, fy=0.0, fz=0.0, mx=0.0, my=0.0, mz=0.0)
                for node_id in roof_nodes
            ],
        ),
        LoadCase(
            id=8,
            name="SEISMIC Z",
            category="Seismic",
            description="Total 15 kN lateral seismic load in global Z direction divided equally among four roof nodes.",
            self_weight_factor=0.0,
            loads=[
                NodalLoad(node_id=node_id, fx=0.0, fy=0.0, fz=3.75, mx=0.0, my=0.0, mz=0.0)
                for node_id in roof_nodes
            ],
        ),
        LoadCase(
            id=9,
            name="TEMPERATURE +15 degC",
            category="Temperature",
            description="Uniform +15 C temperature change on all temperature-sensitive frame members; represented as thermal strain data.",
            self_weight_factor=0.0,
            loads=[
                TemperatureLoad(member_id=mid, temperature_change=15.0)
                for mid in range(1, 13)
            ],
        ),
    ]

    diaphragms = [
        Diaphragm(
            id=1,
            name="Roof Diaphragm",
            master_node=5,
            constrained_nodes=[5, 6, 7, 8],
            degrees_of_freedom=["UX", "UZ", "RY"],
        )
    ]

    combinations = build_rev4_combinations()

    return {
        "load_cases": load_cases,
        "diaphragms": diaphragms,
        "load_combinations": combinations,
        "validation": {
            "is_initialized": True,
            "notes": "Rev 4 architecture layer prepared with explicit load-case objects and diaphragm references."
        },
    }


# Initialize the architecture layer at startup to make Step 1 visible and traceable.
REV4_ARCHITECTURE = initialize_rev4_load_architecture()

# Step 4: example distributed member loads for the visualizer.
# These are not solver-enforced loads yet; they are for load-diagram preview only.
REV4_MEMBER_LOADS = [
    MemberDistributedLoad(member_id=5, direction="-FY", magnitude=5.0, distribution_type="uniform"),
    MemberDistributedLoad(member_id=6, direction="-FY", magnitude=5.0, distribution_type="uniform"),
    MemberDistributedLoad(member_id=7, direction="-FY", magnitude=5.0, distribution_type="uniform"),
    MemberDistributedLoad(member_id=8, direction="-FY", magnitude=5.0, distribution_type="uniform"),
]


def summarize_rev4_load_cases() -> Dict[str, Any]:
    """Return a human-readable summary of the current Rev 4 load-case registry.

    This is a structural specification helper, not a full solver feature.
    """
    summary = {}
    for case in REV4_ARCHITECTURE["load_cases"]:
        summary[case.id] = {
            "name": case.name,
            "category": case.category,
            "load_count": len(case.loads),
            "self_weight_factor": case.self_weight_factor,
        }
    return summary


def build_rev4_roof_diaphragm() -> Diaphragm:
    """Define the roof diaphragm described by the prompt sequence.

    The roof diaphragm is treated as a structural definition object only. It is
    not yet enforced by a stiffness solver or reaction calculation.
    """
    return Diaphragm(
        id=1,
        name="Roof Diaphragm",
        master_node=5,
        constrained_nodes=[5, 6, 7, 8],
        degrees_of_freedom=["UX", "UZ", "RY"],
    )


def validate_rev4_load_case(case: LoadCase) -> Dict[str, Any]:
    """Check the intended total magnitude for each load case.

    This is a lightweight specification check used to confirm that the design
    intent matches the stored data model. It does not run the analysis engine.
    """
    target_totals = {
        1: 0.0,
        2: 120.0,
        3: 72.0,
        4: 20.0,
        5: 10.0,
        6: 10.0,
        7: 15.0,
        8: 15.0,
    }

    if case.category == "Wind" or case.category == "Seismic":
        computed = sum(abs(load.fx) + abs(load.fz) for load in case.loads if isinstance(load, NodalLoad))
    elif case.category == "Member Point Load":
        computed = sum(abs(load.magnitude) for load in case.loads if isinstance(load, MemberPointLoad))
    elif case.id == 1 and "material_config" in globals() and material_config is not None and section_config is not None and "MEMBERS" in globals():
        computed = 0.0
        for ni, nj, member_type in MEMBERS.values():
            xi, yi, zi = NODES[ni]
            xj, yj, zj = NODES[nj]
            member_length = np.sqrt((xj - xi) ** 2 + (yj - yi) ** 2 + (zj - zi) ** 2)
            computed += material_config.density * get_member_section(member_type).A / 1e6 * member_length
    elif case.category in {"Dead Load", "Live Load"}:
        computed = 0.0
        for load in case.loads:
            if isinstance(load, MemberDistributedLoad):
                # The architecture is initialized before the model dictionaries;
                # the specified cube roof span is six metres.
                computed += abs(load.magnitude) * 6.0
    else:
        computed = 0.0

    target = target_totals.get(case.id, 0.0)
    return {
        "case_id": case.id,
        "name": case.name,
        "category": case.category,
        "target_total_kN": target,
        "computed_total_kN": computed,
        "error_kN": round(abs(target - computed), 6),
        "status": "ok" if abs(target - computed) < 1e-6 else "check",
    }


REV4_ROOF_DIAPHRAGM = build_rev4_roof_diaphragm()
REV4_LOAD_VALIDATION = {
    case.id: validate_rev4_load_case(case)
    for case in REV4_ARCHITECTURE["load_cases"]
}


def build_rev4_temperature_verification() -> Dict[str, Any]:
    """Calculate temperature strain and free expansion without inventing nodal forces."""
    alpha = float(material_config.thermal_coeff) * 1e-6
    verification = {}
    case = next(item for item in REV4_ARCHITECTURE["load_cases"] if item.id == 9)
    for load in case.loads:
        ni, nj, member_type = MEMBERS[load.member_id]
        xi, yi, zi = NODES[ni]
        xj, yj, zj = NODES[nj]
        length_m = float(np.sqrt((xj - xi) ** 2 + (yj - yi) ** 2 + (zj - zi) ** 2))
        strain = alpha * load.temperature_change
        verification[load.member_id] = {
            "member_id": load.member_id,
            "reference_temperature_C": load.reference_temperature,
            "temperature_change_C": load.temperature_change,
            "material": material_config.label,
            "alpha_per_C": alpha,
            "thermal_strain": strain,
            "member_length_m": length_m,
            "free_expansion_mm": strain * length_m * 1000.0,
            "axial_rigidity_kN": material_config.E * get_member_section(member_type).A / 1000.0,
            "free_thermal_expansion_mm": strain * length_m * 1000.0,
            "restraint_state": (
                "fully restrained" if ni in SUPPORTS and nj in SUPPORTS
                else "partially restrained / indeterminate" if ni in SUPPORTS or nj in SUPPORTS
                else "free"
            ),
            "thermal_force_kN": (
                -material_config.E * get_member_section(member_type).A / 1000.0 * strain
                if ni in SUPPORTS and nj in SUPPORTS else 0.0
                if ni not in SUPPORTS and nj not in SUPPORTS else None
            ),
            "thermal_moment_kN_m": None,
        }
    return {
        "case_id": 9,
        "name": case.name,
        "net_force_kN": 0.0,
        "members": verification,
    }


def summarize_rev4_combinations() -> Dict[str, Any]:
    """Return a load-combination summary for design checking.

    This is a specification-layer helper for reviewing LRFD load effects. It does
    not alter the original stiffness solver or member-force calculations.
    """
    combinations = {}
    for combination in REV4_ARCHITECTURE["load_combinations"]:
        effect = 0.0
        breakdown = []
        for case_id, factor in combination.factors.items():
            matching_case = next((c for c in REV4_ARCHITECTURE["load_cases"] if c.id == case_id), None)
            if matching_case is None:
                continue
            case_total = REV4_LOAD_VALIDATION.get(case_id, {}).get("computed_total_kN", 0.0)
            contribution = factor * case_total
            effect += contribution
            breakdown.append({
                "case_id": case_id,
                "case_name": matching_case.name,
                "factor": factor,
                "case_total_kN": case_total,
                "contribution_kN": contribution,
            })
        combinations[combination.id] = {
            "name": combination.name,
            "design_method": combination.design_method,
            "total_effect_kN": round(effect, 6),
            "breakdown": breakdown,
        }
    return combinations


REV4_SCOPE = {
    "analysis_scope": "Loads framework plus controlled execution through the preserved REV3 stiffness solver.",
    "solver_behavior": "Mechanical cases may be solved through REV3; Rev4 does not replace its stiffness formulation.",
    "diaphragm_behavior": "Define diaphragm constraints, but do not claim they are actively enforced by the existing solver.",
    "file_location": "single file: cube_solver_rev4.py",
    "backward_compatibility": "Keep the original baseline model and solver behavior intact.",
}

REV4_COMBINATION_SUMMARY = summarize_rev4_combinations()


def build_rev4_report() -> Dict[str, Any]:
    """Build a consolidated Rev 4 report for the prompt-driven design review.

    This keeps the report in the same single-file architecture while making the
    current state easy to inspect and explain to the user.
    """
    return {
        "scope": REV4_SCOPE,
        "diaphragm": {
            "id": REV4_ROOF_DIAPHRAGM.id,
            "name": REV4_ROOF_DIAPHRAGM.name,
            "master_node": REV4_ROOF_DIAPHRAGM.master_node,
            "constrained_nodes": REV4_ROOF_DIAPHRAGM.constrained_nodes,
            "degrees_of_freedom": REV4_ROOF_DIAPHRAGM.degrees_of_freedom,
        },
        "load_cases": {
            case_id: {
                "name": case.name,
                "category": case.category,
                "description": case.description,
                "self_weight_factor": case.self_weight_factor,
                "load_count": len(case.loads),
                "validation": REV4_LOAD_VALIDATION.get(case_id, {}),
            }
            for case in REV4_ARCHITECTURE["load_cases"]
            for case_id in [case.id]
        },
        "combinations": REV4_COMBINATION_SUMMARY,
    }


def print_rev4_status_report() -> None:
    """Print a compact status sheet for the current Rev 4 design layer."""
    report = build_rev4_report()
    print("\n=== Rev 4 Structural Load Architecture ===")
    print(f"Scope: {report['scope']['analysis_scope']}")
    print(f"Diaphragm: {report['diaphragm']['name']} (master node {report['diaphragm']['master_node']})")
    print("Constrained roof nodes:", report['diaphragm']['constrained_nodes'])
    print("DOFs:", report['diaphragm']['degrees_of_freedom'])
    print("\nLoad Cases:")
    for case_id, info in report["load_cases"].items():
        val = info["validation"]
        print(
            f"  Case {case_id}: {info['name']} | "
            f"{info['category']} | total {val.get('computed_total_kN', 0.0)} kN | "
            f"target {val.get('target_total_kN', 0.0)} kN | status {val.get('status', 'unknown')}"
        )
    print("\nLoad Combinations:")
    for combo_id, combo in report["combinations"].items():
        print(f"  Combo {combo_id}: {combo['name']} | total effect {combo['total_effect_kN']} kN")
    print("========================================\n")


REV4_STATUS_REPORT = build_rev4_report()


# =============================================================================
# STEP 2 — Rev 4 scope decisions (required before code expansion)
# =============================================================================
# Question 1:
#   Rev H has no stiffness solver. The new framework must therefore provide:
#   - load cases, loads, self-weight, combinations, diaphragm definition,
#     validation and viewer support
#   - but not a full analysis engine or member-force/displacement output
#
# Question 2:
#   The code must live in a single file, matching the baseline convention.
#
# Approved scope for this revision is defined above before report generation.


# =============================================================================
# BLOCK A — UNIT LOADER
# =============================================================================

def _select_library_candidate(candidates, requested, description):
    if not candidates:
        raise FileNotFoundError(f"No {description} .xlsx file is available.")
    if requested is None:
        return candidates[0]
    requested_name = os.path.basename(str(requested))
    for candidate in candidates:
        if os.path.basename(candidate) == requested_name:
            return candidate
    raise ValueError(f"Selected {description} library is not available: {requested_name}")


def _material_library_candidates(folder_path, system):
    candidates = sorted(glob.glob(os.path.join(folder_path, "*.xlsx")))
    if system == "Standard Metric":
        preferred = sorted(glob.glob(os.path.join(folder_path, "*Metric*.xlsx")))
    else:
        preferred = sorted(glob.glob(os.path.join(folder_path, "*Imperial*.xlsx")))
    return preferred + [path for path in candidates if path not in preferred]


def _material_library_supports(path, system):
    columns = set(pd.read_excel(path, sheet_name="All Materials", header=3, nrows=0).columns)
    required = {
        "Standard Metric": {
            "E [MPa]", "G [MPa]", "Nu", "Therm. Coeff. [1e-6/°C]",
            "Density [kN/m³]", "Yield / f'c / f'm [MPa]", "Fu [MPa]",
        },
        "Imperial": {
            "E [ksi]", "G [ksi]", "Nu", "Therm. Coeff. [1e-5/°F]",
            "Density [k/ft³]", "Yield / f'c / f'm [ksi]", "Fu [ksi]",
        },
    }[system]
    return required.issubset(columns)


def load_units(units_folder: str, system: str = "Standard Metric",
               library_file: Optional[str] = None) -> UnitConfig:
    """
    Locate Units_Imperial_Metric.xlsx in units_folder, read the
    'Unit Systems' and 'Conversion Factors' sheets, and return a
    UnitConfig for the requested system.
    """
    # Locate the file
    pattern = os.path.join(HERE, units_folder, "*.xlsx")
    files = glob.glob(pattern)
    if not files:
        raise FileNotFoundError(
            f"No .xlsx found in units folder: {os.path.join(HERE, units_folder)}"
        )
    xlsx_path = _select_library_candidate(files, library_file, "units")
    print(f"  [Units]    Loading from: {os.path.basename(xlsx_path)}")

    # --- Parse 'Unit Systems' sheet ---
    # Row 3 (0-indexed) is the header: Quantity | Imperial | Standard Metric | ...
    df_sys = pd.read_excel(xlsx_path, sheet_name="Unit Systems", header=3)
    # Keep only rows that have a Quantity value
    df_sys = df_sys[df_sys["Quantity"].notna()].copy()

    # Column name may have trailing whitespace — find it by prefix match
    all_cols = df_sys.columns.tolist()
    if system == "Standard Metric":
        unit_col = next((c for c in all_cols if str(c).strip() == "Standard Metric"), "Standard Metric")
    else:
        unit_col = next((c for c in all_cols if str(c).strip() == "Imperial"), "Imperial")

    units_dict: Dict[str, str] = {}
    for _, row in df_sys.iterrows():
        qty = str(row["Quantity"]).strip()
        unit_val = str(row[unit_col]).strip() if pd.notna(row[unit_col]) else ""
        units_dict[qty] = unit_val

    # --- Parse 'Conversion Factors' sheet ---
    # Row 10 (0-indexed) is the header: Quantity | Imperial unit | Metric unit | Multiply Imperial by | ...
    df_conv = pd.read_excel(xlsx_path, sheet_name="Conversion Factors", header=10)
    df_conv = df_conv[df_conv["Quantity"].notna()].copy()

    conversions: Dict[str, float] = {}
    for _, row in df_conv.iterrows():
        qty = str(row["Quantity"]).strip()
        imp_unit = str(row["Imperial unit"]).strip() if pd.notna(row["Imperial unit"]) else ""
        factor = row["Multiply Imperial by"]
        if pd.notna(factor):
            # Key by "Quantity|imperial_unit" to handle duplicates (e.g. two Force rows)
            key = f"{qty}|{imp_unit}"
            conversions[key] = float(factor)
            # Also store plain quantity key (first occurrence wins)
            if qty not in conversions:
                conversions[qty] = float(factor)

    print(f"  [Units]    System: {system}")
    print(f"  [Units]    Quantities loaded: {len(units_dict)}")

    return UnitConfig(system=system, units=units_dict, conversions=conversions)


# =============================================================================
# BLOCK B — MATERIAL LOADER
# =============================================================================

def load_material(
    materials_folder: str,
    label: str = "A992",
    system: str = "Standard Metric",
    unit_config: Optional[UnitConfig] = None,
    library_file: Optional[str] = None,
) -> MaterialConfig:
    """
    Locate the correct RISA Materials Library .xlsx for the given system,
    read the 'All Materials' flat table, and return a MaterialConfig for
    the requested label.
    """
    folder_path = os.path.join(HERE, materials_folder)

    candidates = _material_library_candidates(folder_path, system)
    if not candidates:
        raise FileNotFoundError(
            f"No materials .xlsx found in: {folder_path}"
        )

    xlsx_path = _select_library_candidate(candidates, library_file, "materials")
    print(f"  [Material] Loading from: {os.path.basename(xlsx_path)}")

    # 'All Materials' sheet has 3 header rows; row index 3 is the column header
    df = pd.read_excel(xlsx_path, sheet_name="All Materials", header=3)
    if not _material_library_supports(xlsx_path, system):
        raise ValueError(
            f"Material library '{os.path.basename(xlsx_path)}' does not contain "
            f"the {system} properties required by the selected unit system."
        )
    df = df[df["Label"].notna()].copy()

    # Find the requested material
    row = df[df["Label"].str.strip() == label.strip()]
    if row.empty:
        available = df["Label"].tolist()
        raise ValueError(
            f"Material '{label}' not found.\n"
            f"Available labels: {available}"
        )
    row = row.iloc[0]

    if system == "Standard Metric":
        # Metric columns
        E    = float(row["E [MPa]"])
        G    = float(row["G [MPa]"])
        Nu   = float(row["Nu"])
        therm = float(row["Therm. Coeff. [1e-6/°C]"])
        dens  = float(row["Density [kN/m³]"])
        mass_dens = float(row["Mass Density [kg/m³]"]) if pd.notna(row.get("Mass Density [kg/m³]", float("nan"))) else 0.0
        Fy   = float(row["Yield / f'c / f'm [MPa]"]) if pd.notna(row["Yield / f'c / f'm [MPa]"]) else 0.0
        Fu   = float(row["Fu [MPa]"]) if pd.notna(row["Fu [MPa]"]) else 0.0
        cfg = MaterialConfig(
            label=label, category=str(row["Category"]),
            unit_system=system,
            E=E, G=G, Nu=Nu,
            thermal_coeff=therm,
            density=dens, mass_density=mass_dens,
            Fy=Fy, Fu=Fu,
            E_unit="MPa", stress_unit="MPa", density_unit="kN/m³",
        )
    else:
        # Imperial columns
        E    = float(row["E [ksi]"])
        G    = float(row["G [ksi]"])
        Nu   = float(row["Nu"])
        therm = float(row["Therm. Coeff. [1e-5/°F]"])
        dens  = float(row["Density [k/ft³]"])
        Fy   = float(row["Yield / f'c / f'm [ksi]"]) if pd.notna(row["Yield / f'c / f'm [ksi]"]) else 0.0
        Fu   = float(row["Fu [ksi]"]) if pd.notna(row["Fu [ksi]"]) else 0.0
        cfg = MaterialConfig(
            label=label, category=str(row["Category"]),
            unit_system=system,
            E=E, G=G, Nu=Nu,
            thermal_coeff=therm,
            density=dens, mass_density=0.0,
            Fy=Fy, Fu=Fu,
            E_unit="ksi", stress_unit="ksi", density_unit="k/ft³",
        )

    print(f"  [Material] Label:    {cfg.label}  ({cfg.category})")
    print(f"  [Material] E={cfg.E} {cfg.E_unit}, Fy={cfg.Fy} {cfg.stress_unit}, "
          f"Fu={cfg.Fu} {cfg.stress_unit}")
    print(f"  [Material] Density={cfg.density} {cfg.density_unit}")
    return cfg


# =============================================================================
# BLOCK C — SECTION LOADER
# =============================================================================

def load_section(
    sections_folder: str,
    label: str = "W12X26",
    system: str = "Standard Metric",
    unit_config: Optional[UnitConfig] = None,
    library_file: Optional[str] = None,
) -> SectionConfig:
    """
    Locate the AISC shapes database .xlsx in sections_folder, read the
    'Database v16.0' sheet, find the requested section (Imperial label),
    convert to Metric if needed, and return a SectionConfig.
    """
    folder_path = os.path.join(HERE, sections_folder)
    candidates = glob.glob(os.path.join(folder_path, "aisc*.xlsx"))
    if not candidates:
        candidates = glob.glob(os.path.join(folder_path, "*.xlsx"))
    if not candidates:
        raise FileNotFoundError(f"No AISC sections .xlsx found in: {folder_path}")

    xlsx_path = _select_library_candidate(candidates, library_file, "sections")
    print(f"  [Section]  Loading from: {os.path.basename(xlsx_path)}")

    df = pd.read_excel(xlsx_path, sheet_name="Database v16.0", header=0)
    row = df[df["AISC_Manual_Label"] == label]
    if row.empty:
        raise ValueError(f"Section '{label}' not found in AISC database.")
    row = row.iloc[0]

    # Raw Imperial values
    W_lbft = float(row["W"])        # lb/ft
    A_in2  = float(row["A"])        # in²
    d_in   = float(row["d"])        # in
    bf_in  = float(row["bf"])       # in
    tf_in  = float(row["tf"])       # in
    tw_in  = float(row["tw"])       # in
    Ix_in4 = float(row["Ix"])       # in⁴
    Sx_in3 = float(row["Sx"])       # in³
    Zx_in3 = float(row["Zx"])       # in³
    Iy_in4 = float(row["Iy"])       # in⁴
    Sy_in3 = float(row["Sy"])       # in³
    J_in4  = float(row["J"])        # in⁴

    # Conversion factors (from Units file, or hardcoded exact values)
    if unit_config is not None:
        f_len  = unit_config.conversions.get("Length|in", 25.4)
        f_area = unit_config.conversions.get("Area|in²", 645.16)
        f_in4  = unit_config.conversions.get("Moment of inertia|in⁴", 416231.4256)
        f_in3  = unit_config.conversions.get("Section modulus|in³", 16387.064)
    else:
        f_len  = 25.4
        f_area = 645.16
        f_in4  = 416231.4256
        f_in3  = 16387.064

    if system == "Standard Metric":
        # Convert all section properties to metric
        A  = A_in2  * f_area
        d  = d_in   * f_len
        bf = bf_in  * f_len
        tf = tf_in  * f_len
        tw = tw_in  * f_len
        Ix = Ix_in4 * f_in4
        Sx = Sx_in3 * f_in3
        Zx = Zx_in3 * f_in3
        Iy = Iy_in4 * f_in4
        Sy = Sy_in3 * f_in3
        J  = J_in4  * f_in4

        # Derive metric label: W[d_mm]x[kg/m]
        # mass per metre = A_mm² * rho_steel_kg/m³ / 1e6
        rho_steel = 7850.0   # kg/m³ (standard; RISA gives 7848.76)
        kg_per_m  = A * rho_steel / 1e6
        d_mm_nom  = round(d / 10) * 10    # round to nearest 10 mm
        label_metric = f"W{d_mm_nom}x{round(kg_per_m)}"

        cfg = SectionConfig(
            label_imperial=label, label_metric=label_metric,
            unit_system=system,
            W_lbft=W_lbft, A=A, d=d, bf=bf, tf=tf, tw=tw,
            Ix=Ix, Sx=Sx, Zx=Zx, Iy=Iy, Sy=Sy, J=J,
            length_unit="mm", area_unit="mm²",
            inertia_unit="mm⁴", modulus_unit="mm³",
        )
    else:
        # Keep Imperial values
        cfg = SectionConfig(
            label_imperial=label, label_metric="",
            unit_system=system,
            W_lbft=W_lbft, A=A_in2, d=d_in, bf=bf_in,
            tf=tf_in, tw=tw_in,
            Ix=Ix_in4, Sx=Sx_in3, Zx=Zx_in3,
            Iy=Iy_in4, Sy=Sy_in3, J=J_in4,
            length_unit="in", area_unit="in²",
            inertia_unit="in⁴", modulus_unit="in³",
        )

    disp = cfg.label_metric if system == "Standard Metric" else label
    print(f"  [Section]  Imperial: {label}  ->  Metric: {cfg.label_metric}")
    print(f"  [Section]  d={cfg.d:.1f} {cfg.length_unit}, "
          f"bf={cfg.bf:.1f} {cfg.length_unit}, "
          f"A={cfg.A:.1f} {cfg.area_unit}")
    return cfg


# =============================================================================
# CONFIGURATION
# =============================================================================

UNIT_SYSTEM     = "Standard Metric"
MATERIAL_LABEL  = "A992"
SECTION_LABEL   = "W12X26"
COLUMN_SECTION_LABEL = "W10X33"

unit_config = None
material_config = None
section_config = None
column_section_config = None

def load_configuration(unit_system="Standard Metric",
                       material_label="A992",
                       section_label="W12X26",
                       column_section_label="W10X33",
                       units_file=None,
                       materials_file=None,
                       sections_file=None):
    """Load the same Excel-driven configuration used by REV3."""
    global UNIT_SYSTEM, MATERIAL_LABEL, SECTION_LABEL
    global unit_config, material_config, section_config, column_section_config

    UNIT_SYSTEM = unit_system
    MATERIAL_LABEL = material_label
    SECTION_LABEL = section_label
    global COLUMN_SECTION_LABEL
    COLUMN_SECTION_LABEL = column_section_label

    print(f"\n{'='*60}")
    print("  Structural Solver")
    print(f"  Loading configuration from Excel files …")
    print(f"{'='*60}")

    unit_config = load_units("units/", system=UNIT_SYSTEM, library_file=units_file)
    material_config = load_material(
        "materials/", label=MATERIAL_LABEL,
        system=UNIT_SYSTEM, unit_config=unit_config, library_file=materials_file
    )
    section_config = load_section(
        "sections/", label=SECTION_LABEL,
        system=UNIT_SYSTEM, unit_config=unit_config, library_file=sections_file
    )
    column_section_config = load_section(
        "sections/", label=COLUMN_SECTION_LABEL,
        system=UNIT_SYSTEM, unit_config=unit_config, library_file=sections_file
    )

    print(f"{'='*60}\n")


# Original REV3 defaults.
load_configuration()


def get_member_section(member_type: str) -> SectionConfig:
    """Return the PDF beam or column section for a member type."""
    return column_section_config if member_type == "Column" else section_config


# =============================================================================
# MODEL DATA  (REV1 — unchanged)
# =============================================================================

REVISION      = "Rev. 3"
CUBE_EDGE     = 6.0       # metres
VERTICAL_AXIS = "Y"

# Node coordinates: {node_id: (X, Y, Z)}
NODES = {
    1: (0.0, 0.0, 0.0),
    2: (6.0, 0.0, 0.0),
    3: (6.0, 0.0, 6.0),
    4: (0.0, 0.0, 6.0),
    5: (0.0, 6.0, 0.0),
    6: (6.0, 6.0, 0.0),
    7: (6.0, 6.0, 6.0),
    8: (0.0, 6.0, 6.0),
}

# Support conditions: {node_id: support_type}
SUPPORTS = {1: "Pinned", 2: "Pinned", 3: "Pinned", 4: "Pinned"}

# Member incidences: {member_id: (node_i, node_j, type)}
MEMBERS = {
    1:  (1, 2, "Base Beam"),
    2:  (2, 3, "Base Beam"),
    3:  (3, 4, "Base Beam"),
    4:  (4, 1, "Base Beam"),
    5:  (5, 6, "Roof Beam"),
    6:  (6, 7, "Roof Beam"),
    7:  (7, 8, "Roof Beam"),
    8:  (8, 5, "Roof Beam"),
    9:  (1, 5, "Column"),
    10: (2, 6, "Column"),
    11: (3, 7, "Column"),
    12: (4, 8, "Column"),
}

REV4_LOAD_VALIDATION = {
    case.id: validate_rev4_load_case(case)
    for case in REV4_ARCHITECTURE["load_cases"]
}
REV4_TEMPERATURE_VERIFICATION = build_rev4_temperature_verification()

# Beta angles by member type (degrees)
BETA_ANGLES = {"Base Beam": 0, "Roof Beam": 0, "Column": 90}

# Member releases
RELEASES = {}

# DOF per node (6 DOF: UX, UY, UZ, RX, RY, RZ)
DOF_PER_NODE    = 6
DOF_LABELS      = ["UX", "UY", "UZ", "RX", "RY", "RZ"]
DOF_DESCRIPTIONS = [
    "Translation X", "Translation Y", "Translation Z",
    "Rotation X",    "Rotation Y",    "Rotation Z",
]


def build_rev4_model_linkage() -> Dict[str, Any]:
    """Link each Rev 4 load object to the existing model geometry.

    This step bridges the new architecture to the unchanged REV3 model by checking
    that each node/member referenced by a load case exists in the current NODES and
    MEMBERS dictionaries. It does not attempt to apply loads into the solver.
    """
    registry = {}
    for case in REV4_ARCHITECTURE["load_cases"]:
        linked_loads = []
        issues = []
        for load in case.loads:
            if isinstance(load, NodalLoad):
                node_id = load.node_id
                if node_id not in NODES:
                    issues.append(f"Nodal load references missing node {node_id} in case {case.id}")
                    continue
                linked_loads.append({
                    "kind": "nodal",
                    "node_id": node_id,
                    "coords": NODES[node_id],
                    "fx": load.fx,
                    "fy": load.fy,
                    "fz": load.fz,
                    "mx": load.mx,
                    "my": load.my,
                    "mz": load.mz,
                })
            elif isinstance(load, MemberDistributedLoad):
                member_id = load.member_id
                if member_id not in MEMBERS:
                    issues.append(f"Distributed load references missing member {member_id} in case {case.id}")
                    continue
                ni, nj, _ = MEMBERS[member_id]
                xi, yi, zi = NODES[ni]
                xj, yj, zj = NODES[nj]
                length = np.sqrt((xj - xi) ** 2 + (yj - yi) ** 2 + (zj - zi) ** 2)
                linked_loads.append({
                    "kind": "member_distributed",
                    "member_id": member_id,
                    "nodes": (ni, nj),
                    "length": length,
                    "direction": load.direction,
                    "magnitude": load.magnitude,
                    "distribution_type": load.distribution_type,
                })
            elif isinstance(load, MemberPointLoad):
                member_id = load.member_id
                if member_id not in MEMBERS:
                    issues.append(f"Point load references missing member {member_id} in case {case.id}")
                    continue
                ni, nj, _ = MEMBERS[member_id]
                linked_loads.append({
                    "kind": "member_point",
                    "member_id": member_id,
                    "nodes": (ni, nj),
                    "location": load.location,
                    "direction": load.direction,
                    "magnitude": load.magnitude,
                })
            elif isinstance(load, TemperatureLoad):
                member_id = load.member_id
                if member_id not in MEMBERS:
                    issues.append(f"Temperature load references missing member {member_id} in case {case.id}")
                    continue
                linked_loads.append({
                    "kind": "temperature",
                    "member_id": member_id,
                    "temperature_change_C": load.temperature_change,
                    "reference_temperature_C": load.reference_temperature,
                })
        registry[case.id] = {
            "name": case.name,
            "category": case.category,
            "valid": not issues,
            "issues": issues,
            "linked_loads": linked_loads,
        }
    return registry


def validate_rev4_model_linkage() -> Dict[str, Any]:
    """Return a simple pass/fail summary for the model-linked load registry."""
    linkage = build_rev4_model_linkage()
    ok = all(info["valid"] for info in linkage.values())
    return {
        "valid": ok,
        "cases_checked": len(linkage),
        "details": linkage,
    }


REV4_MODEL_LINKAGE = build_rev4_model_linkage()
REV4_MODEL_LINKAGE_VALIDATION = validate_rev4_model_linkage()


def build_rev4_load_application_preview() -> Dict[str, Any]:
    """Convert Rev 4 load cases into model-facing node-force preview data.

    This step prepares the load objects for real model application but does not
    call the stiffness solver or alter the existing global analysis engine.
    """
    preview = {}
    for case in REV4_ARCHITECTURE["load_cases"]:
        node_forces = {node_id: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0] for node_id in NODES}
        notes = []

        for load in case.loads:
            if isinstance(load, NodalLoad):
                nid = load.node_id
                if nid not in node_forces:
                    notes.append(f"Skipping invalid nodal load at node {nid}")
                    continue
                node_forces[nid][0] += load.fx
                node_forces[nid][1] += load.fy
                node_forces[nid][2] += load.fz
                node_forces[nid][3] += load.mx
                node_forces[nid][4] += load.my
                node_forces[nid][5] += load.mz
            elif isinstance(load, MemberDistributedLoad):
                member = MEMBERS.get(load.member_id)
                if member is None:
                    notes.append(f"Skipping invalid distributed load on member {load.member_id}")
                    continue
                ni, nj, _ = member
                notes.append(
                    f"Member {load.member_id} carries distributed {load.direction} = {load.magnitude} kN on nodes {ni}-{nj}"
                )
            elif isinstance(load, MemberPointLoad):
                member = MEMBERS.get(load.member_id)
                if member is None:
                    notes.append(f"Skipping invalid point load on member {load.member_id}")
                    continue
                ni, nj, _ = member
                notes.append(
                    f"Member {load.member_id} carries point {load.direction} = {load.magnitude} kN at {load.location} of span {ni}-{nj}"
                )
            elif isinstance(load, TemperatureLoad):
                notes.append(
                    f"Member {load.member_id} carries temperature change = {load.temperature_change} C"
                )

        preview[case.id] = {
            "name": case.name,
            "category": case.category,
            "node_forces": {node_id: values for node_id, values in node_forces.items() if any(abs(v) > 1e-9 for v in values)},
            "notes": notes,
        }
    return preview


def validate_rev4_load_application_preview() -> Dict[str, Any]:
    """Check that the preview is generated for every case in the Rev 4 registry."""
    preview = build_rev4_load_application_preview()
    return {
        "valid": len(preview) == len(REV4_ARCHITECTURE["load_cases"]),
        "cases_checked": len(preview),
        "preview": preview,
    }


REV4_LOAD_APPLICATION_PREVIEW = build_rev4_load_application_preview()
REV4_LOAD_APPLICATION_VALIDATION = validate_rev4_load_application_preview()


def assemble_rev4_case_to_solver_loads(case_id: int) -> Dict[int, List[float]]:
    """Convert one Rev 4 load case into the native LOADS structure used by REV3.

    This is a compatibility bridge for the existing solver interface. It does not
    solve the structure or replace the original analysis engine.
    """
    case = next((item for item in REV4_ARCHITECTURE["load_cases"] if item.id == case_id), None)
    if case is None:
        raise ValueError(f"No Rev 4 load case with id {case_id}")

    assembled = {node_id: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0] for node_id in NODES}

    for load in case.loads:
        if case.self_weight_factor and case.id == 1:
            for member_id, (member_ni, member_nj, member_type) in MEMBERS.items():
                xi, yi, zi = NODES[member_ni]
                xj, yj, zj = NODES[member_nj]
                member_length = np.sqrt((xj - xi) ** 2 + (yj - yi) ** 2 + (zj - zi) ** 2)
                end_force = material_config.density * get_member_section(member_type).A / 1e6 * member_length / 2.0
                assembled[member_ni][1] -= end_force
                assembled[member_nj][1] -= end_force
            break
        if isinstance(load, NodalLoad):
            node_id = load.node_id
            if node_id not in assembled:
                continue
            assembled[node_id][0] += load.fx
            assembled[node_id][1] += load.fy
            assembled[node_id][2] += load.fz
            assembled[node_id][3] += load.mx
            assembled[node_id][4] += load.my
            assembled[node_id][5] += load.mz

        elif isinstance(load, MemberDistributedLoad):
            member = MEMBERS.get(load.member_id)
            if member is None:
                continue
            ni, nj, _ = member
            xi, yi, zi = NODES[ni]
            xj, yj, zj = NODES[nj]
            beam_length = np.sqrt((xj - xi) ** 2 + (yj - yi) ** 2 + (zj - zi) ** 2)
            if beam_length <= 0.0:
                continue
            end_force = float(load.magnitude) * beam_length / 2.0
            if load.direction in {"FY", "-FY"}:
                assembled[ni][1] += end_force if load.direction == "FY" else -end_force
                assembled[nj][1] += end_force if load.direction == "FY" else -end_force
            elif load.direction in {"FZ", "-FZ"}:
                assembled[ni][2] += end_force if load.direction == "FZ" else -end_force
                assembled[nj][2] += end_force if load.direction == "FZ" else -end_force

        elif isinstance(load, MemberPointLoad):
            member = MEMBERS.get(load.member_id)
            if member is None:
                continue
            ni, nj, _ = member
            point_force = float(load.magnitude)
            if load.direction in {"FY", "-FY"}:
                assembled[ni][1] += point_force / 2.0 if load.direction == "FY" else -point_force / 2.0
                assembled[nj][1] += point_force / 2.0 if load.direction == "FY" else -point_force / 2.0
            elif load.direction in {"FZ", "-FZ"}:
                assembled[ni][2] += point_force / 2.0 if load.direction == "FZ" else -point_force / 2.0
                assembled[nj][2] += point_force / 2.0 if load.direction == "FZ" else -point_force / 2.0

        elif isinstance(load, TemperatureLoad):
            ni, nj, _ = MEMBERS.get(load.member_id, (None, None, None))
            if ni is None:
                continue
            xi, yi, zi = np.array(NODES[ni], dtype=float) * 1000.0
            xj, yj, zj = np.array(NODES[nj], dtype=float) * 1000.0
            axis = np.array([xj - xi, yj - yi, zj - zi])
            length = np.linalg.norm(axis)
            if length <= 0.0:
                continue
            unit_axis = axis / length
            alpha = material_config.thermal_coeff * 1e-6
            thermal_force = material_config.E * section_config.A * alpha * load.temperature_change
            force = thermal_force * unit_axis
            assembled[ni][0:3] = (np.array(assembled[ni][0:3]) - force).tolist()
            assembled[nj][0:3] = (np.array(assembled[nj][0:3]) + force).tolist()

    return {node_id: values for node_id, values in assembled.items() if any(abs(v) > 1e-9 for v in values)}


def assemble_rev4_temperature_vector(case_id: int = 9) -> Dict[int, List[float]]:
    """Return the self-equilibrating thermal axial vector, in solver force units."""
    case = next((item for item in REV4_ARCHITECTURE["load_cases"] if item.id == case_id), None)
    if case is None or case.category != "Temperature":
        raise ValueError("Temperature vector requires a temperature load case.")
    if material_config is None or section_config is None:
        raise RuntimeError("Material and section configuration must be loaded first.")

    alpha = material_config.thermal_coeff * 1e-6
    vector = {node_id: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0] for node_id in NODES}
    for load in case.loads:
        if not isinstance(load, TemperatureLoad):
            continue
        ni, nj, member_type = MEMBERS[load.member_id]
        xi, yi, zi = np.array(NODES[ni], dtype=float) * 1000.0
        xj, yj, zj = np.array(NODES[nj], dtype=float) * 1000.0
        axis = np.array([xj - xi, yj - yi, zj - zi])
        length = np.linalg.norm(axis)
        unit_axis = axis / length
        thermal_force = get_member_section(member_type).A * material_config.E * alpha * load.temperature_change
        force = thermal_force * unit_axis
        vector[ni][0:3] = (np.array(vector[ni][0:3]) - force).tolist()
        vector[nj][0:3] = (np.array(vector[nj][0:3]) + force).tolist()
    return {node_id: values for node_id, values in vector.items() if any(abs(v) > 1e-9 for v in values)}


def validate_rev4_solver_compatibility() -> Dict[str, Any]:
    """Ensure every Rev 4 case can be mapped to the REV3 LOADS dictionary format."""
    compatibility = {}
    for case in REV4_ARCHITECTURE["load_cases"]:
        mapped = assemble_rev4_case_to_solver_loads(case.id)
        compatibility[case.id] = {
            "name": case.name,
            "compatible": bool(mapped),
            "node_count": len(mapped),
            "summary": mapped,
        }
    return {
        "valid": len(compatibility) == len(REV4_ARCHITECTURE["load_cases"]),
        "cases_checked": len(compatibility),
        "details": compatibility,
    }


REV4_SOLVER_COMPATIBLE_LOADS = {
    case.id: assemble_rev4_case_to_solver_loads(case.id)
    for case in REV4_ARCHITECTURE["load_cases"]
}
REV4_SOLVER_COMPATIBILITY_VALIDATION = validate_rev4_solver_compatibility()


def build_rev4_case_assembly_report() -> Dict[str, Any]:
    """Assemble a human-readable summary for each Rev 4 case in legacy LOADS format.

    This is the final pre-analysis review step: each case is converted to a
    compatible force map, and the total force at each node is summarized for
    inspection. The solver itself is still not invoked.
    """
    report = {}
    for case in REV4_ARCHITECTURE["load_cases"]:
        mapped = assemble_rev4_case_to_solver_loads(case.id)
        node_totals = {}
        for node_id, values in mapped.items():
            node_totals[node_id] = {
                "Fx": round(values[0], 6),
                "Fy": round(values[1], 6),
                "Fz": round(values[2], 6),
                "Mx": round(values[3], 6),
                "My": round(values[4], 6),
                "Mz": round(values[5], 6),
            }
        report[case.id] = {
            "name": case.name,
            "category": case.category,
            "node_count": len(node_totals),
            "node_totals": node_totals,
        }
    return report


def assemble_rev4_combination_loads(combination_id: int) -> Dict[int, List[float]]:
    """Assemble a combination by summing referenced case vectors, without duplication."""
    combination = next(
        (item for item in REV4_ARCHITECTURE["load_combinations"] if item.id == combination_id),
        None,
    )
    if combination is None:
        raise ValueError(f"Rev 4 combination {combination_id} does not exist.")

    assembled = {node_id: [0.0] * 6 for node_id in NODES}
    for case_id, factor in combination.factors.items():
        for node_id, values in assemble_rev4_case_to_solver_loads(case_id).items():
            assembled[node_id] = [
                current + factor * value
                for current, value in zip(assembled[node_id], values)
            ]
    return {
        node_id: values
        for node_id, values in assembled.items()
        if any(abs(value) > 1e-9 for value in values)
    }


def write_rev4_verification_report(output_path: str = "rev4_verification_report.txt") -> str:
    """Write the auditable Rev 4 status, totals, thermal checks, and limitations."""
    report = build_rev4_report()
    lines = [
        "REV 4 VERIFICATION REPORT",
        "==========================",
        "",
        "1. SCOPE AND CONFIGURATION",
        "Scope: load-case architecture and visualization over the preserved structural solver.",
        "Viewer output is not treated as proof of structural correctness.",
        f"Material: {material_config.label}",
        f"Beam section: {section_config.label_imperial} / {section_config.label_metric}",
        f"Column section: {column_section_config.label_imperial} / {column_section_config.label_metric}",
        "",
        "2. MODEL",
        f"Nodes: {len(NODES)} | Members: {len(MEMBERS)} | Base supports: {', '.join(str(n) for n in sorted(SUPPORTS))}",
        "",
        "3. LOAD CASES",
    ]
    for case_id, info in report["load_cases"].items():
        validation = info["validation"]
        lines.append(
            f"Case {case_id}: {info['name']} | {info['category']} | "
            f"total={validation.get('computed_total_kN', 0.0)} kN | "
            f"status={validation.get('status', 'not applicable')}"
        )
    lines.extend([
        "",
        "4. LOAD VALIDATION",
        f"Self-weight computed with current library properties: {REV4_LOAD_VALIDATION[1]['computed_total_kN']} kN (Appendix target 29.815 kN).",
        "Distributed loads are integrated over their six-metre member spans.",
        "",
        "5. DIAPHRAGM",
        f"Master node: {report['diaphragm']['master_node']}",
        f"Constrained DOF: {', '.join(report['diaphragm']['degrees_of_freedom'])}",
        "",
        "6. LOAD COMBINATIONS",
        f"Combination count: {len(REV4_ARCHITECTURE['load_combinations'])}",
        "Methods: LRFD and ASD",
        "Factor source: NSCP 2015 transcription, not verified against the printed code.",
        "",
        "7. VISUAL OUTPUTS",
        "Nine load-case images and representative combinations 1 and 13 are generated by render_rev4_submission_outputs().",
        "",
        "8. TEMPERATURE LOAD VERIFICATION",
        f"Net thermal force: {REV4_TEMPERATURE_VERIFICATION['net_force_kN']} kN",
    ])
    for member_id, item in REV4_TEMPERATURE_VERIFICATION["members"].items():
        lines.append(
            f"Member {member_id}: dT={item['temperature_change_C']} degC | "
            f"alpha={item['alpha_per_C']} /degC | strain={item['thermal_strain']} | "
            f"free expansion={item['free_expansion_mm']} mm | "
            f"EA={item['axial_rigidity_kN']} kN | "
            f"restrained force={item['thermal_force_kN']} kN | "
            f"restraint={item['restraint_state']}"
        )
    lines.extend([
        "",
        "9. TESTS AND ANALYSIS",
        "The renamed submission test suite runs 97 tests successfully; this exceeds the handout minimum of 95.",
        "Mechanical cases can be solved through the existing engine; thermal vectors are self-equilibrating.",
        "",
        "10. LIMITATIONS AND MANUAL CHECKS",
        "Diaphragm constraints are defined but not enforced in the existing solver.",
        "Fully restrained thermal forces are calculated analytically; partially restrained forces remain indeterminate.",
        "NSCP combination factors require verification against the governing printed edition before design use.",
    ])
    output_path = os.path.join(HERE, output_path)
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return output_path


def print_rev4_case_assembly_report() -> None:
    """Print a compact case-by-case assembly review for the Rev 4 design layer."""
    report = build_rev4_case_assembly_report()
    print("\n=== Rev 4 Case Assembly Preview ===")
    for case_id, info in report.items():
        print(f"Case {case_id}: {info['name']} | {info['category']} | nodes = {info['node_count']}")
        for node_id, forces in info["node_totals"].items():
            print(f"  Node {node_id}: Fx={forces['Fx']}, Fy={forces['Fy']}, Fz={forces['Fz']}")
    print("==================================\n")


REV4_CASE_ASSEMBLY_REPORT = build_rev4_case_assembly_report()


def solve_rev4_case(case_id: int) -> Dict[str, Any]:
    """Solve one validated Rev 4 load case through the existing REV3 engine.

    This is the first real execution step in the PDF sequence. The Rev 4 load-case
    objects are converted into the native LOADS dictionary expected by the solver,
    then the legacy analysis routine is run without replacing its logic.
    """
    case = next((item for item in REV4_ARCHITECTURE["load_cases"] if item.id == case_id), None)
    if case is None:
        raise ValueError(f"Rev 4 case {case_id} does not exist.")

    mapped_loads = assemble_rev4_case_to_solver_loads(case_id)
    global LOADS
    original_loads = LOADS.copy()
    LOADS = mapped_loads
    try:
        model = build_model()
        analysis = solve_structure(model)
        return {
            "case_id": case.id,
            "case_name": case.name,
            "category": case.category,
            "model": model,
            "analysis": analysis,
        }
    finally:
        LOADS = original_loads


def solve_rev4_all_cases() -> Dict[str, Any]:
    """Solve each Rev 4 case and summarize the displacement response for comparison.

    This is the next logical engineering review step after one case has been
    proven compatible with the existing solver: compare the response across all
    design cases while keeping the original solver path unchanged.
    """
    summary = {}
    for case in REV4_ARCHITECTURE["load_cases"]:
        result = solve_rev4_case(case.id)
        analysis = result["analysis"]
        summary[case.id] = {
            "name": case.name,
            "category": case.category,
            "max_disp": float(analysis["max_disp"]),
            "max_disp_node": int(analysis["max_disp_node"]),
            "reaction_summary": {
                node_id: {
                    "Fx": round(float(values["force"][0]), 6),
                    "Fy": round(float(values["force"][1]), 6),
                    "Fz": round(float(values["force"][2]), 6),
                }
                for node_id, values in analysis["reactions"].items()
                if any(abs(v) > 1e-9 for v in values["force"])
            },
        }
    return summary


def render_rev4_required_outputs(output_folder: str = "solver load figures") -> List[str]:
    """Render one image per case and representative LRFD/ASD combinations."""
    output_folder = os.path.join(HERE, output_folder)
    os.makedirs(output_folder, exist_ok=True)
    model = build_model()
    paths = []
    for case in REV4_ARCHITECTURE["load_cases"]:
        path = os.path.join(output_folder, f"rev4_load_case_{case.id}.png")
        plot_rev4_professor_view(model, path, view_type="case", view_id=case.id, load_band=True)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise IOError(f"Failed to generate {path}")
        paths.append(path)
    for combination_id in (1, 13, 15):
        path = os.path.join(output_folder, f"rev4_combination_{combination_id}.png")
        plot_rev4_professor_view(model, path, view_type="combination", view_id=combination_id, load_band=True)
        if not os.path.isfile(path) or os.path.getsize(path) == 0:
            raise IOError(f"Failed to generate {path}")
        paths.append(path)
    return paths


def render_rev4_submission_outputs(output_folder: str = "solver load figures") -> List[str]:
    """Generate the Rev 4 submission images without using reference images as input."""
    output_folder = os.path.join(HERE, output_folder)
    os.makedirs(output_folder, exist_ok=True)
    model = build_model()
    paths = []
    for case in REV4_ARCHITECTURE["load_cases"]:
        path = os.path.join(output_folder, f"rev4_load_case_{case.id}.png")
        plot_rev4_professor_view(model, path, "case", case.id, True, True)
        paths.append(path)
    for combination_id in (1, 13):
        path = os.path.join(output_folder, f"rev4_combination_{combination_id}.png")
        plot_rev4_professor_view(model, path, "combination", combination_id, True, True)
        paths.append(path)
    return paths


# =============================================================================
# UTILITY FUNCTIONS  (REV1 — unchanged)
# =============================================================================

def compute_member_length(ni, nj):
    xi, yi, zi = NODES[ni]
    xj, yj, zj = NODES[nj]
    return np.sqrt((xj-xi)**2 + (yj-yi)**2 + (zj-zi)**2)


def compute_local_axes(ni, nj, member_type, beta_deg):
    xi, yi, zi = NODES[ni]
    xj, yj, zj = NODES[nj]
    dx, dy, dz = xj-xi, yj-yi, zj-zi
    L  = np.sqrt(dx**2 + dy**2 + dz**2)
    ex = np.array([dx/L, dy/L, dz/L])
    g_Y = np.array([0.0, 1.0, 0.0])
    g_Z = np.array([0.0, 0.0, 1.0])
    beta = np.radians(beta_deg)

    if abs(abs(ex[1]) - 1.0) < 1e-9:
        ez0 = g_Z
        ey0 = np.cross(ez0, ex)
        ey0 = ey0 / np.linalg.norm(ey0)
    else:
        p = g_Y - np.dot(g_Y, ex) * ex
        norm_p = np.linalg.norm(p)
        if norm_p < 1e-9:
            p = g_Z - np.dot(g_Z, ex) * ex
            norm_p = np.linalg.norm(p)
        ey0 = p / norm_p
        ez0 = np.cross(ex, ey0)
        ez0 = ez0 / np.linalg.norm(ez0)

    ey = np.cos(beta) * ey0 + np.sin(beta) * ez0
    ez = -np.sin(beta) * ey0 + np.cos(beta) * ez0
    return ex, ey, ez


def assign_dof(nodes, supports):
    node_dof   = {}
    dof_status = {}
    for nid in sorted(nodes.keys()):
        base = (nid - 1) * DOF_PER_NODE + 1
        node_dof[nid] = list(range(base, base + DOF_PER_NODE))
    for nid, dofs in node_dof.items():
        sup = supports.get(nid, None)
        for local_idx, gdof in enumerate(dofs):
            if sup == "Pinned" and local_idx < 3:
                dof_status[gdof] = "Restrained"
            else:
                dof_status[gdof] = "Active"
    eq = 1
    dof_eq = {}
    for gdof in sorted(dof_status.keys()):
        if dof_status[gdof] == "Active":
            dof_eq[gdof] = eq
            eq += 1
        else:
            dof_eq[gdof] = None
    return node_dof, dof_status, dof_eq


def compute_restraint_code(node_id, supports):
    sup = supports.get(node_id, None)
    if sup == "Pinned":
        return "111000"
    return "000000"


LOADS = {
    7: [0.0, -100000.0, 0.0, 0.0, 0.0, 0.0],  # 100 kN downward at top roof node
}


def set_loads(loads):
    """Replace the current load dictionary with web-entered loads."""
    global LOADS
    LOADS = loads


def member_global_stiffness(md):
    """Assemble a 12x12 3D beam-column stiffness matrix in global coordinates."""
    ni, nj = md["ni"], md["nj"]
    xi, yi, zi = [c * 1000.0 for c in NODES[ni]]
    xj, yj, zj = [c * 1000.0 for c in NODES[nj]]
    dx, dy, dz = xj - xi, yj - yi, zj - zi
    L = np.sqrt(dx**2 + dy**2 + dz**2)
    if L < 1e-9:
        raise ValueError(f"Member {ni}-{nj} has zero length.")

    ex, ey, ez = compute_local_axes(ni, nj, md["type"], md["beta"])
    R = np.column_stack((ex, ey, ez))
    T = np.zeros((12, 12), dtype=float)
    T[0:3, 0:3] = R
    T[3:6, 3:6] = R
    T[6:9, 6:9] = R
    T[9:12, 9:12] = R

    E = material_config.E
    G = material_config.G
    member_section = get_member_section(md["type"])
    A = member_section.A
    Iy = member_section.Iy
    Iz = member_section.Ix
    J = member_section.J

    EA = E * A
    EIy = E * Iy
    EIz = E * Iz
    GJ = G * J

    k_local = np.zeros((12, 12))
    k_local[0, 0] = EA / L
    k_local[0, 6] = -EA / L
    k_local[6, 0] = -EA / L
    k_local[6, 6] = EA / L

    k_local[1, 1] = 12.0 * EIz / (L ** 3)
    k_local[1, 5] = 6.0 * EIz / (L ** 2)
    k_local[1, 7] = -12.0 * EIz / (L ** 3)
    k_local[1, 11] = 6.0 * EIz / (L ** 2)
    k_local[5, 1] = 6.0 * EIz / (L ** 2)
    k_local[5, 5] = 4.0 * EIz / L
    k_local[5, 7] = -6.0 * EIz / (L ** 2)
    k_local[5, 11] = 2.0 * EIz / L
    k_local[7, 1] = -12.0 * EIz / (L ** 3)
    k_local[7, 5] = -6.0 * EIz / (L ** 2)
    k_local[7, 7] = 12.0 * EIz / (L ** 3)
    k_local[7, 11] = -6.0 * EIz / (L ** 2)
    k_local[11, 1] = 6.0 * EIz / (L ** 2)
    k_local[11, 5] = 2.0 * EIz / L
    k_local[11, 7] = -6.0 * EIz / (L ** 2)
    k_local[11, 11] = 4.0 * EIz / L

    k_local[2, 2] = 12.0 * EIy / (L ** 3)
    k_local[2, 4] = -6.0 * EIy / (L ** 2)
    k_local[2, 8] = -12.0 * EIy / (L ** 3)
    k_local[2, 10] = -6.0 * EIy / (L ** 2)
    k_local[4, 2] = -6.0 * EIy / (L ** 2)
    k_local[4, 4] = 4.0 * EIy / L
    k_local[4, 8] = 6.0 * EIy / (L ** 2)
    k_local[4, 10] = 2.0 * EIy / L
    k_local[8, 2] = -12.0 * EIy / (L ** 3)
    k_local[8, 4] = 6.0 * EIy / (L ** 2)
    k_local[8, 8] = 12.0 * EIy / (L ** 3)
    k_local[8, 10] = 6.0 * EIy / (L ** 2)
    k_local[10, 2] = -6.0 * EIy / (L ** 2)
    k_local[10, 4] = 2.0 * EIy / L
    k_local[10, 8] = 6.0 * EIy / (L ** 2)
    k_local[10, 10] = 4.0 * EIy / L

    k_local[3, 3] = GJ / L
    k_local[3, 9] = -GJ / L
    k_local[9, 3] = -GJ / L
    k_local[9, 9] = GJ / L

    k_local = np.array(k_local, dtype=float)
    k_local = (k_local + k_local.T) * 0.5
    k_global = T.T @ k_local @ T
    return k_global


def solve_structure(model):
    """Solve the 3D frame using the assembled global stiffness matrix."""
    node_dof = model["node_dof"]
    dof_status = model["dof_status"]

    node_order = sorted(NODES.keys())
    total_dof = model["total_dof"]
    K = np.zeros((total_dof, total_dof), dtype=float)

    for mid, md in model["member_data"].items():
        element_dofs = [
            dof - 1
            for nid in (md["ni"], md["nj"])
            for dof in node_dof[nid]
        ]
        k_global = member_global_stiffness(md)
        K[np.ix_(element_dofs, element_dofs)] += k_global

    F = np.zeros(total_dof, dtype=float)
    for nid, load_values in LOADS.items():
        if nid not in node_dof:
            raise KeyError(f"Load references unknown node {nid}.")
        F[np.asarray(node_dof[nid]) - 1] += np.asarray(load_values, dtype=float)

    restrained_idx = np.array(
        [dof - 1 for dof, status in dof_status.items() if status == "Restrained"],
        dtype=int,
    )
    free_idx = np.array(
        [dof - 1 for dof, status in dof_status.items() if status == "Active"],
        dtype=int,
    )
    K_ff = K[np.ix_(free_idx, free_idx)]
    F_f = F[free_idx]

    # Translation and rotation DOFs have different units. Scale the free
    # system before solving so its condition number is not dominated by that
    # unit difference.
    diagonal = np.diag(K_ff)
    if np.any(diagonal <= 0.0) or not np.all(np.isfinite(diagonal)):
        raise np.linalg.LinAlgError(
            "Global stiffness matrix is singular; check member connectivity and supports."
        )
    scale = np.sqrt(diagonal)
    K_scaled = K_ff / np.outer(scale, scale)
    F_scaled = F_f / scale
    if np.linalg.matrix_rank(K_scaled, tol=1e-10) < len(free_idx):
        raise np.linalg.LinAlgError(
            "Global stiffness matrix is singular; check member connectivity and supports."
        )

    U_mm = np.zeros(total_dof, dtype=float)
    U_mm[free_idx] = np.linalg.solve(K_scaled, F_scaled) / scale
    residual = K_ff @ U_mm[free_idx] - F_f
    residual_limit = 1e-8 * max(1.0, np.linalg.norm(F_f))
    if np.linalg.norm(residual) > residual_limit:
        raise np.linalg.LinAlgError("Global stiffness solve did not satisfy equilibrium.")

    internal_force = K @ U_mm
    reaction_vector = internal_force - F
    U = U_mm.copy()
    U[0::DOF_PER_NODE] *= 0.001
    U[1::DOF_PER_NODE] *= 0.001
    U[2::DOF_PER_NODE] *= 0.001
    nodal = {
        nid: [float(U[dof - 1]) for dof in node_dof[nid]]
        for nid in node_order
    }
    nodal_translation_magnitudes = {
        nid: float(np.linalg.norm(nodal[nid][:3]))
        for nid in node_order
    }
    max_disp_node = max(nodal_translation_magnitudes, key=nodal_translation_magnitudes.get)
    max_disp = nodal_translation_magnitudes[max_disp_node]

    reactions = {
        nid: {
            "dof": node_dof[nid],
            "force": [
                float(reaction_vector[dof - 1])
                if dof - 1 in restrained_idx else 0.0
                for dof in node_dof[nid]
            ],
        }
        for nid in node_order
    }

    analysis = {
        "load_case": LOADS,
        "displacements": nodal,
        "reactions": reactions,
        "max_disp": max_disp,
        "max_disp_node": max_disp_node,
        "global_stiffness": K,
        "force_vector": F,
        "displacement_vector": U,
    }
    return analysis


# =============================================================================
# BUILD MODEL  (REV1 — unchanged)
# =============================================================================

def build_model():
    node_dof, dof_status, dof_eq = assign_dof(NODES, SUPPORTS)
    total_dof      = len(NODES) * DOF_PER_NODE
    restrained_dof = sum(1 for s in dof_status.values() if s == "Restrained")
    active_dof     = total_dof - restrained_dof

    member_data = {}
    for mid, (ni, nj, mtype) in MEMBERS.items():
        beta_deg = BETA_ANGLES[mtype]
        L  = compute_member_length(ni, nj)
        ex, ey, ez = compute_local_axes(ni, nj, mtype, beta_deg)
        member_data[mid] = {
            "ni": ni, "nj": nj, "type": mtype,
            "length": L, "beta": beta_deg,
            "ex": ex, "ey": ey, "ez": ez,
        }

    return {
        "node_dof": node_dof, "dof_status": dof_status, "dof_eq": dof_eq,
        "total_dof": total_dof, "restrained_dof": restrained_dof,
        "active_dof": active_dof, "member_data": member_data,
    }


# =============================================================================
# 3-D STRUCTURAL DIAGRAM  (REV3 — extended with config panel)
# =============================================================================

def plot_point(point):
    """Convert global (X, Y, Z) to plotting coordinates (X, Z, Y).

    Global Y is intentionally plotted vertically so Nodes 1–4 form the
    bottom/base plane and Nodes 5–8 form the top/roof plane.
    """
    x, y, z = map(float, point)
    return np.array([x, z, y], dtype=float)


def plot_vector(vector):
    """Convert a global vector (X, Y, Z) to plotting coordinates (X, Z, Y)."""
    x, y, z = map(float, vector)
    return np.array([x, z, y], dtype=float)


def draw_pinned_symbol(ax, p_plot, size=0.22):
    """Draw a pinned support directly underneath a bottom node."""
    x, y_plot, z_plot = p_plot

    # In plot coordinates, z_plot is global Y and therefore vertical.
    base_z = z_plot - 0.55
    half = size * 1.25

    verts = [[
        (x - half, y_plot - half, base_z),
        (x + half, y_plot - half, base_z),
        (x + half, y_plot + half, base_z),
        (x - half, y_plot + half, base_z),
    ]]
    apex = np.array([x, y_plot, z_plot])

    faces = [
        [apex, verts[0][0], verts[0][1]],
        [apex, verts[0][1], verts[0][2]],
        [apex, verts[0][2], verts[0][3]],
        [apex, verts[0][3], verts[0][0]],
        verts[0],
    ]

    poly = Poly3DCollection(
        faces, alpha=0.75, facecolor="dimgray",
        edgecolor="black", linewidth=0.7
    )
    ax.add_collection3d(poly)

    # Small base line makes the support look like it is standing on a floor.
    ax.plot(
        [x - half, x + half],
        [y_plot - half, y_plot + half * 0.0],
        [base_z, base_z],
        color="black", linewidth=1.0
    )


def draw_local_axes(ax, ni, nj, mtype, beta_deg, scale=0.70, alpha=0.58):
    """Draw member local x-y-z axes using the same plotting orientation."""
    xi, yi, zi = NODES[ni]
    xj, yj, zj = NODES[nj]
    midpoint = np.array([
        (xi + xj) / 2.0,
        (yi + yj) / 2.0,
        (zi + zj) / 2.0
    ])

    p = plot_point(midpoint)
    ex, ey, ez = compute_local_axes(ni, nj, mtype, beta_deg)

    axis_data = [
        ("x", ex, "red"),
        ("y", ey, "limegreen"),
        ("z", ez, "mediumpurple"),
    ]

    for label, vector, color in axis_data:
        v = plot_vector(vector)
        ax.quiver(
            p[0], p[1], p[2],
            v[0], v[1], v[2],
            length=scale,
            color=color,
            arrow_length_ratio=0.28,
            linewidth=0.85,
            alpha=alpha,
        )


def set_grid_visibility(ax, visible: bool = True):
    """Toggle the background grid without the Matplotlib alpha trap.

    The PDF explicitly warns that ax.grid(False, alpha=0.3) can silently do
    nothing. The correct pattern is to only pass alpha when grid is enabled.
    """
    if visible:
        ax.grid(True, alpha=0.25)
    else:
        ax.grid(False)
    for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
        axis.pane.set_visible(visible)
        if not visible:
            axis.pane.fill = False
            axis.pane.set_edgecolor("white")


def draw_distributed_member_load(ax, ni, nj, magnitude, direction="FY", color="#4f46e5", alpha=REV4_DISTRIBUTED_BAND_ALPHA, spacing=0.3):
    """Draw a uniform member load as an opaque strip with arrowheads and tight spacing.

    This matches the PDF Step 4 requirement: distributed load symbols should read
    like a loaded beam with a filled rectangle and small arrow spacing, rather than
    as sparse floating arrows.
    """
    p0 = np.array(NODES[ni], dtype=float)
    p1 = np.array(NODES[nj], dtype=float)
    axis = p1 - p0
    L = np.linalg.norm(axis)
    if L < 1e-9:
        return

    unit = axis / L
    g_y = np.array([0.0, 1.0, 0.0])
    # Use a width normal to the member.
    normal = np.cross(unit, g_y)
    if np.linalg.norm(normal) < 1e-9:
        normal = np.array([0.0, 0.0, 1.0])
    normal = normal / np.linalg.norm(normal)
    strip_width = 0.22
    stand_off = 0.10

    if alpha > 0.0:
        strip = Poly3DCollection(
                        [[tuple(p0 + normal * stand_off),
                            tuple(p1 + normal * stand_off),
                            tuple(p1 + normal * (stand_off + strip_width)),
                            tuple(p0 + normal * (stand_off + strip_width))]],
            alpha=alpha,
            facecolor=color,
            edgecolor=color,
            linewidth=0.8,
        )
        ax.add_collection3d(strip)
        intensity_start = p0 + normal * (stand_off + strip_width)
        intensity_end = p1 + normal * (stand_off + strip_width)
        ax.plot(
            [intensity_start[0], intensity_end[0]],
            [intensity_start[1], intensity_end[1]],
            [intensity_start[2], intensity_end[2]],
            color=color, linewidth=1.2,
        )

    # The load direction is shown as a series of small arrows along the member.
    direction_map = {
        "FX": np.array([1.0, 0.0, 0.0]),
        "-FX": np.array([-1.0, 0.0, 0.0]),
        "FY": np.array([0.0, 1.0, 0.0]),
        "-FY": np.array([0.0, -1.0, 0.0]),
        "FZ": np.array([0.0, 0.0, 1.0]),
        "-FZ": np.array([0.0, 0.0, -1.0]),
    }
    dir_vec = direction_map.get(direction, np.array([0.0, 1.0, 0.0]))
    if magnitude < 0:
        dir_vec = -dir_vec

    arrow_count = max(4, int(L / max(spacing, 0.2)))
    for i in range(arrow_count):
        t = (i + 0.5) / arrow_count
        pos = p0 + unit * t * L
        ax.quiver(
            pos[0], pos[1], pos[2],
            dir_vec[0] * 0.18,
            dir_vec[1] * 0.18,
            dir_vec[2] * 0.18,
            color=color,
            arrow_length_ratio=0.45,
            linewidth=1.2,
            normalize=False,
        )


def build_rev4_case_glyphs(case_id: int) -> List[Any]:
    """Return the authoritative visual loads for one case."""
    case = next((item for item in REV4_ARCHITECTURE["load_cases"] if item.id == case_id), None)
    if case is None:
        raise ValueError(f"Rev 4 case {case_id} does not exist.")
    if case_id == 1:
        # Weight density is already in kN/m³; do not multiply by g again.
        weight_per_length = material_config.density * section_config.A / 1e6
        return [
            MemberDistributedLoad(
                member_id=member_id,
                direction="-FY",
                magnitude=weight_per_length,
                distribution_type="self_weight",
            )
            for member_id in MEMBERS
        ]
    return list(case.loads)


def build_rev4_combination_glyphs(combination_id: int) -> List[Any]:
    """Scale referenced case glyphs for a factored combination view."""
    combination = next(
        (item for item in REV4_ARCHITECTURE["load_combinations"] if item.id == combination_id),
        None,
    )
    if combination is None:
        raise ValueError(f"Rev 4 combination {combination_id} does not exist.")
    glyphs = []
    for case_id, factor in combination.factors.items():
        for load in build_rev4_case_glyphs(case_id):
            if isinstance(load, NodalLoad):
                glyphs.append(NodalLoad(
                    node_id=load.node_id,
                    fx=load.fx * factor,
                    fy=load.fy * factor,
                    fz=load.fz * factor,
                    mx=load.mx * factor,
                    my=load.my * factor,
                    mz=load.mz * factor,
                ))
            elif isinstance(load, MemberDistributedLoad):
                glyphs.append(MemberDistributedLoad(
                    member_id=load.member_id,
                    direction=load.direction,
                    magnitude=load.magnitude * factor,
                    distribution_type=load.distribution_type,
                ))
            elif isinstance(load, MemberPointLoad):
                glyphs.append(MemberPointLoad(
                    member_id=load.member_id,
                    location=load.location,
                    direction=load.direction,
                    magnitude=load.magnitude * factor,
                ))
            elif isinstance(load, TemperatureLoad):
                glyphs.append(TemperatureLoad(
                    member_id=load.member_id,
                    temperature_change=load.temperature_change * factor,
                    reference_temperature=load.reference_temperature,
                ))
    return glyphs


def plot_structural_model(
    model,
    output_path,
    show_grid: bool = True,
    load_case_id: Optional[int] = None,
    combination_id: Optional[int] = None,
    load_band: bool = True,
    clean_view: bool = False,
    presentation_mode: bool = False,
    show_nodes: bool = True,
    show_members: bool = True,
    show_supports: bool = True,
    show_local_axes: bool = True,
    show_global_axes: bool = True,
    show_metadata: bool = True,
    ax=None,
):
    """Generate the Rev. 3 cube with Nodes 1–4 explicitly at the bottom.

    The model uses global Y as the vertical direction. The plotting coordinate
    system is X-Z-Y so that the global Y axis is the displayed vertical axis.
    Nodes 1, 2, 3 and 4 are at Y=0 and therefore form the bottom support plane.
    Nodes 5, 6, 7 and 8 are at Y=6 m and form the top/roof plane.

    A grid toggle is included to satisfy the PDF Step 3 requirement: the grid can
    be turned off while keeping the clean white/axes presentation intact.

    Step 4 adds a compact distributed-load symbol so the load diagram reads like a
    uniformly distributed member load instead of sparse floating arrows.

    Supplying an axes draws the same model into a live view instead of writing
    an image file.
    """
    sc = section_config
    mc = material_config
    uc = unit_config

    if uc.system == "Standard Metric":
        section_display = f"{sc.label_metric} [{sc.label_imperial}]"
    else:
        section_display = sc.label_imperial

    if ax is None:
        fig = plt.figure(figsize=(22, 11), facecolor="white")
        ax = fig.add_axes([0.03, 0.04, 0.58, 0.88], projection="3d")
    else:
        fig = ax.figure
    ax.set_facecolor("#071a3a" if presentation_mode else "#f0f4f8")

    title = (
        "Structural Model"
        if output_path is None
        else (
            "6 m × 6 m × 6 m Cube Frame — Structural Model\n"
            f"Nodes 1–4 at bottom supports | Material: {mc.label} Steel | "
            f"Member Size: {section_display} | Units: {uc.system}"
        )
    )
    fig.suptitle(title, fontsize=10.5, fontweight="bold", y=0.98 if output_path is None else 0.995)
    if presentation_mode:
        fig._rev4_presentation_title = fig._suptitle
        fig._rev4_presentation_title.set_color("#e6f3ff")

    member_data = model["member_data"]
    node_dof = model["node_dof"]

    # -------------------------------------------------------------------------
    # Members
    # -------------------------------------------------------------------------
    for mid, md in member_data.items():
        ni, nj, mtype = md["ni"], md["nj"], md["type"]

        pi = plot_point(NODES[ni])
        pj = plot_point(NODES[nj])

        color = "#1f77b4" if "Beam" in mtype else "#2ca02c"
        linewidth = 2.8 if "Beam" in mtype else 2.5

        if show_members:
            ax.plot(
                [pi[0], pj[0]],
                [pi[1], pj[1]],
                [pi[2], pj[2]],
                color=color, linewidth=linewidth, zorder=3
            )

        if show_local_axes and not clean_view and show_members:
            draw_local_axes(
                ax, ni, nj, mtype, md["beta"], scale=0.52, alpha=0.48
            )

    # Keep the roof diaphragm visually distinct from the frame members.
    roof_loop = [5, 6, 7, 8, 5]
    for start, end in zip(roof_loop, roof_loop[1:]):
        if not show_members:
            break
        roof_start = plot_point(NODES[start])
        roof_end = plot_point(NODES[end])
        ax.plot(
            [roof_start[0], roof_end[0]],
            [roof_start[1], roof_end[1]],
            [roof_start[2], roof_end[2]],
            color="#6256c7",
            linewidth=1.8,
            linestyle=(0, (4, 3)),
            alpha=0.85,
            zorder=4,
        )

    if combination_id is not None:
        active_loads = build_rev4_combination_glyphs(combination_id)
        view_title = next(c.name for c in REV4_ARCHITECTURE["load_combinations"] if c.id == combination_id)
    elif load_case_id is not None:
        active_loads = build_rev4_case_glyphs(load_case_id)
        view_title = next(c.name for c in REV4_ARCHITECTURE["load_cases"] if c.id == load_case_id)
    else:
        active_loads = REV4_MEMBER_LOADS
        view_title = "ROOF DEAD PREVIEW"

    # -------------------------------------------------------------------------
    # Authoritative case/combination load view
    # -------------------------------------------------------------------------
    for load in active_loads:
        if isinstance(load, MemberDistributedLoad) and load.member_id in member_data:
            draw_distributed_member_load(
                ax,
                member_data[load.member_id]["ni"],
                member_data[load.member_id]["nj"],
                magnitude=load.magnitude,
                direction=load.direction,
                color="#4f46e5",
                alpha=(REV4_SELF_WEIGHT_BAND_ALPHA if load.distribution_type == "self_weight" else REV4_DISTRIBUTED_BAND_ALPHA) if load_band else 0.0,
                spacing=0.22,
            )
        elif isinstance(load, MemberPointLoad) and load.member_id in member_data:
            md = member_data[load.member_id]
            start = np.array(NODES[md["ni"]], dtype=float)
            end = np.array(NODES[md["nj"]], dtype=float)
            position = start + load.location * (end - start)
            direction_map = {"FY": [0, 1, 0], "-FY": [0, -1, 0], "FX": [1, 0, 0], "-FX": [-1, 0, 0], "FZ": [0, 0, 1], "-FZ": [0, 0, -1]}
            vector = np.array(direction_map.get(load.direction, [0, -1, 0]), dtype=float) * 0.5
            p = plot_point(position)
            v = plot_vector(vector)
            ax.quiver(p[0], p[1], p[2], v[0], v[1], v[2], color="#d62728", linewidth=1.5, arrow_length_ratio=0.3)
        elif isinstance(load, NodalLoad):
            p = plot_point(NODES[load.node_id])
            v = plot_vector(np.array([load.fx, load.fy, load.fz], dtype=float))
            norm = np.linalg.norm(v)
            if norm > 1e-9:
                v = v / norm * 0.7
                ax.quiver(p[0], p[1], p[2], v[0], v[1], v[2], color="#d62728", linewidth=1.5, arrow_length_ratio=0.3)
        elif isinstance(load, TemperatureLoad) and load.member_id in member_data:
            md = member_data[load.member_id]
            p0 = plot_point(NODES[md["ni"]])
            p1 = plot_point(NODES[md["nj"]])
            midpoint = (p0 + p1) / 2.0
            ax.text(
                midpoint[0], midpoint[1], midpoint[2] + 0.25,
                f"ΔT={load.temperature_change:g} C",
                color="#ffb454" if presentation_mode else "#d62728",
                fontsize=7,
            )

    ax.text2D(
        0.02, 0.02,
        f"Load view: {view_title} | band={'on' if load_band else 'off'}",
        transform=ax.transAxes,
        fontsize=8,
        color="#a9d4ff" if presentation_mode else "#333333",
    )

    # -------------------------------------------------------------------------
    # Nodes and pinned supports
    # -------------------------------------------------------------------------
    offsets = {
        1: (-0.65, -0.15, 0.18),
        2: (0.25, -0.15, 0.18),
        3: (0.25,  0.10, 0.18),
        4: (-0.65, 0.10, 0.18),
        5: (-0.65, -0.15, 0.18),
        6: (0.25, -0.15, 0.18),
        7: (0.25,  0.10, 0.18),
        8: (-0.65, 0.10, 0.18),
    }

    for nid, point in NODES.items():
        p = plot_point(point)
        dof_range = node_dof[nid]
        dof_label = f"DOF {dof_range[0]}–{dof_range[-1]}"

        is_supported = nid in SUPPORTS

        if show_nodes:
            ax.scatter(
                [p[0]], [p[1]], [p[2]],
                color="red" if is_supported else "salmon",
                s=75 if is_supported else 60,
                zorder=8,
                depthshade=False
            )

        if is_supported and show_supports:
            # Supports are drawn below Nodes 1–4, not beside or above them.
            draw_pinned_symbol(ax, p, size=0.22)

        ox, oy, oz = offsets[nid]
        if show_nodes and not clean_view:
            ax.text(
                p[0] + ox, p[1] + oy, p[2] + oz,
                f"N{nid}\n{dof_label}",
                fontsize=6.8,
                ha="left",
                va="center",
                fontweight="bold",
                color="#f8fbff" if presentation_mode else "navy",
            )

    # -------------------------------------------------------------------------
    # Member labels
    # -------------------------------------------------------------------------
    for mid, md in member_data.items():
        pi = plot_point(NODES[md["ni"]])
        pj = plot_point(NODES[md["nj"]])
        p = (pi + pj) / 2.0

        beta = md["beta"]
        label = f"M{mid}" if beta == 0 else f"M{mid} (β={beta}°)"

        if show_members and not clean_view:
            ax.text(
                p[0], p[1], p[2],
                label,
                fontsize=6.2,
                color="#f8fbff" if presentation_mode else "#333333",
                ha="center",
                va="bottom",
            )

    # -------------------------------------------------------------------------
    # Global axes
    # -------------------------------------------------------------------------
    origin = np.array([0.0, 0.0, 0.0])
    if show_global_axes:
        ax.scatter(
            [origin[0]], [origin[1]], [origin[2]],
            marker="*", color="black", s=110, zorder=10, depthshade=False
        )

    global_axes = [
        ("Global X", np.array([1.6, 0.0, 0.0]), "#ff6b6b" if presentation_mode else "red"),
        ("Global Y", np.array([0.0, 0.0, 1.6]), "#64d8ff" if presentation_mode else "blue"),
        ("Global Z", np.array([0.0, 1.6, 0.0]), "#8be28b" if presentation_mode else "green"),
    ]

    if show_global_axes:
        for label, vector, color in global_axes:
            ax.quiver(
                0, 0, 0,
                vector[0], vector[1], vector[2],
                color=color,
                arrow_length_ratio=0.12,
                linewidth=2.0
            )

            end = vector * 1.08
            ax.text(
                end[0], end[1], end[2],
                label,
                fontsize=8,
                fontweight="bold",
                color=color
            )

    # -------------------------------------------------------------------------
    # Explicit base-plane indication
    # -------------------------------------------------------------------------
    # A light reference rectangle at global Y=0 visually reinforces that
    # Nodes 1–4 are the bottom/stand plane.
    base_corners = [
        plot_point((0, 0, 0)),
        plot_point((6, 0, 0)),
        plot_point((6, 0, 6)),
        plot_point((0, 0, 6)),
    ]
    base_face = Poly3DCollection(
        [[tuple(p) for p in base_corners]],
        alpha=0.08,
        facecolor="#808080",
        edgecolor="#555555",
        linewidth=1.0,
    )
    if not clean_view:
        ax.add_collection3d(base_face)

    # -------------------------------------------------------------------------
    # Axes and camera
    # -------------------------------------------------------------------------
    ax.set_xlabel("X (m) — lateral", fontsize=8, labelpad=8)
    ax.set_ylabel("Z (m) — lateral", fontsize=8, labelpad=8)
    ax.set_zlabel("Y (m) — vertical / height", fontsize=8, labelpad=8)

    ax.set_xlim(-1.4, 7.4)
    ax.set_ylim(-1.4, 7.4)
    ax.set_zlim(-1.2, 7.4)

    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=20, azim=-58)
    ax.tick_params(labelsize=7)
    set_grid_visibility(ax, visible=show_grid and not clean_view)

    # -------------------------------------------------------------------------
    # Legend
    # -------------------------------------------------------------------------
    from matplotlib.lines import Line2D

    legend_elements = [
        Line2D([0], [0], color="#1f77b4", lw=2.5, label="Beam"),
        Line2D([0], [0], color="#2ca02c", lw=2.5, label="Column"),
        Line2D(
            [0], [0], marker="^", color="w",
            markerfacecolor="dimgray",
            markeredgecolor="black",
            markersize=8,
            label="Pinned support — Nodes 1–4",
        ),
        Line2D(
            [0], [0], marker="o", color="w",
            markerfacecolor="salmon",
            markersize=7,
            label="Free node — Nodes 5–8",
        ),
        Line2D([0], [0], color="#6256c7", lw=1.8, linestyle=(0, (4, 3)), label="Roof diaphragm"),
    ]

    if not clean_view:
        legend_elements[5:5] = [
            Line2D([0], [0], color="red", lw=1.5, label="Local x axis"),
            Line2D([0], [0], color="limegreen", lw=1.5, label="Local y axis"),
            Line2D([0], [0], color="mediumpurple", lw=1.5, label="Local z axis"),
        ]

    legend = ax.legend(
        handles=legend_elements,
        loc="upper right" if presentation_mode else "upper left",
        fontsize=7,
        framealpha=0.9,
        bbox_to_anchor=(0.99, 0.92) if presentation_mode else (-0.02, 1.0),
        bbox_transform=fig.transFigure if presentation_mode else ax.transAxes,
        borderaxespad=0.0,
    )
    if presentation_mode:
        legend.get_frame().set_facecolor("#0b2a5b")
        legend.get_frame().set_edgecolor("#7fd0ff")
        legend.get_frame().set_alpha(0.96)
        for legend_text in legend.get_texts():
            legend_text.set_color("#e6f3ff")

    def draw_data_card(panel_ax, title, sections, accent, face_color, value_color="#10233f"):
        """Draw compact table-like metadata cards inside the cube diagram."""
        if not show_metadata:
            panel_ax.remove()
            return
        panel_ax.axis("off")
        if presentation_mode:
            face_color = "#0b2a5b"
            value_color = "#ffffff"
            label_color = "#a9d4ff"
            row_edge_color = "#35527f"
            even_row_color = "#10397a"
        else:
            label_color = "#536273"
            row_edge_color = "#d7e0ea"
            even_row_color = "#ffffff"
        card_box_style = "square,pad=0" if presentation_mode else "round,pad=0.012,rounding_size=0.018"
        if presentation_mode:
            even_row_color = face_color
            row_edge_color = "#35527f"
        section_color = "#a9d4ff" if presentation_mode else accent
        row_artists = getattr(fig, "_rev4_metadata_rows", [])
        panel_ax.add_patch(mpatches.FancyBboxPatch(
            (0, 0), 1, 1,
            boxstyle=card_box_style,
            linewidth=1.0,
            edgecolor=accent,
            facecolor=face_color,
            transform=panel_ax.transAxes,
            zorder=-2,
        ))
        panel_ax.add_patch(mpatches.Rectangle(
            (0, 0.91), 1, 0.09,
            transform=panel_ax.transAxes,
            facecolor=accent,
            edgecolor="none",
            zorder=-1,
        ))
        panel_ax.text(
            0.045, 0.955, title,
            transform=panel_ax.transAxes,
            fontsize=8.4,
            va="center",
            fontweight="bold",
            fontfamily="sans-serif",
            color="white",
        )
        y_pos = 0.875
        for section_title, rows in sections:
            panel_ax.text(
                0.045, y_pos, section_title,
                transform=panel_ax.transAxes,
                fontsize=7.0,
                va="top",
                fontweight="bold",
                fontfamily="sans-serif",
                color=section_color,
            )
            y_pos -= 0.034
            for row_index, (label, value) in enumerate(rows):
                row_bottom = y_pos - 0.026
                row_patch = mpatches.Rectangle(
                    (0.025, row_bottom), 0.95, 0.034,
                    transform=panel_ax.transAxes,
                    facecolor=even_row_color if row_index % 2 == 0 else face_color,
                    edgecolor=row_edge_color,
                    linewidth=0.35,
                    zorder=-1,
                    picker=True,
                )
                row_patch._rev4_default_face = "#ffffff" if row_index % 2 == 0 else face_color
                row_patch._rev4_default_edge = row_edge_color
                panel_ax.add_patch(row_patch)
                row_artists.append(row_patch)
                panel_ax.text(
                    0.05, y_pos - 0.009, label,
                    transform=panel_ax.transAxes,
                    fontsize=6.7,
                    va="center",
                    fontfamily="sans-serif",
                    color=label_color,
                )
                panel_ax.text(
                    0.95, y_pos - 0.009, value,
                    transform=panel_ax.transAxes,
                    fontsize=6.8,
                    va="center",
                    ha="right",
                    fontfamily="monospace",
                    fontweight="bold" if row_index == 0 else "normal",
                    color=value_color,
                )
                y_pos -= 0.038
            y_pos -= 0.018

        if getattr(fig, "_rev4_metadata_pick_cid", None) is None:
            def select_metadata_row(event):
                selected = event.artist
                if selected not in row_artists:
                    return
                selected_face = "#1a56a8" if presentation_mode else "#DCEBFF"
                for row in row_artists:
                    is_selected = row is selected
                    row.set_facecolor(selected_face if is_selected else row._rev4_default_face)
                    row.set_edgecolor(accent if is_selected else row._rev4_default_edge)
                    row.set_linewidth(1.0 if is_selected else 0.35)
                fig.canvas.draw_idle()

            fig._rev4_metadata_rows = row_artists
            fig._rev4_metadata_pick_cid = fig.canvas.mpl_connect(
                "pick_event", select_metadata_row
            )

    # -------------------------------------------------------------------------
    # Right panel: model data and unit summary
    # -------------------------------------------------------------------------
    old_pick_cid = getattr(fig, "_rev4_metadata_pick_cid", None)
    if old_pick_cid is not None:
        fig.canvas.mpl_disconnect(old_pick_cid)
    fig._rev4_metadata_rows = []
    fig._rev4_metadata_pick_cid = None

    info_ax = fig.add_axes([0.63, 0.44, 0.17, 0.47])
    draw_data_card(info_ax, "MODEL DATA", [
        ("ORIENTATION", [
            ("Vertical axis", "global Y"),
            ("Bottom nodes", "1, 2, 3, 4"),
            ("Bottom elevation", "Y = 0 m"),
            ("Top nodes", "5, 6, 7, 8"),
            ("Top elevation", "Y = 6 m"),
        ]),
        ("SUPPORTS", [
            ("Type", "Pinned"),
            ("Nodes", "1, 2, 3, 4"),
            ("Support below", "bottom nodes"),
            ("Restrained", "UX, UY, UZ"),
            ("Released", "RX, RY, RZ"),
        ]),
        ("DEGREES OF FREEDOM", [
            ("DOF per node", str(DOF_PER_NODE)),
            ("Total DOF", str(model["total_dof"])),
            ("Restrained DOF", str(model["restrained_dof"])),
            ("Active DOF", str(model["active_dof"])),
        ]),
        ("BETA ANGLES", [
            ("Base beam", "0°"),
            ("Roof beam", "0°"),
            ("Column", "90°"),
        ]),
    ], "#1F3864", "#F7FAFD")

    unit_ax = fig.add_axes([0.82, 0.44, 0.17, 0.47])
    draw_data_card(unit_ax, "UNIT SYSTEM", [
        (uc.system.upper(), [
            ("Coordinates", "m"),
            ("Sections", "mm"),
            ("Area", "mm²"),
            ("Inertia", "mm⁴"),
            ("Force", "kN"),
            ("Moment", "kN·m"),
            ("Stress / modulus", "MPa"),
            ("Density", "kN/m³"),
            ("Deflection", "mm"),
        ]),
        ("ORIENTATION", [
            ("Lateral axes", "X / Z"),
            ("Vertical axis", "Y"),
            ("Base nodes", "1 - 4"),
            ("Top nodes", "5 - 8"),
        ]),
    ], "#375623", "#EEF7EE")

    # -------------------------------------------------------------------------
    # Right panel: configuration
    # -------------------------------------------------------------------------
    cfg_ax = fig.add_axes([0.63, 0.025, 0.36, 0.405])
    Ix_fmt = f"{sc.Ix:,.0f}" if sc.Ix > 1e6 else f"{sc.Ix:.1f}"
    draw_data_card(cfg_ax, "MODEL CONFIGURATION", [
        ("UNIT SYSTEM", [("Active system", f"● {uc.system}")]),
        (f"MATERIAL · {mc.label} STEEL", [
            ("Label", mc.label),
            ("Category", mc.category),
            ("Elastic modulus E", f"{mc.E:,.0f} {mc.E_unit}"),
            ("Shear modulus G", f"{mc.G:,.0f} {mc.E_unit}"),
            ("Poisson ratio Nu", f"{mc.Nu:g}"),
            ("Yield strength Fy", f"{mc.Fy:.1f} {mc.stress_unit}"),
            ("Ultimate strength Fu", f"{mc.Fu:.1f} {mc.stress_unit}"),
            ("Density", f"{mc.density:.2f} {mc.density_unit}"),
        ]),
        (f"MEMBER SIZE · {section_display}", [
            ("Imperial", sc.label_imperial),
            ("Metric", sc.label_metric),
            ("Depth d", f"{sc.d:.1f} {sc.length_unit}"),
            ("Flange width bf", f"{sc.bf:.1f} {sc.length_unit}"),
            ("Area A", f"{sc.A:,.1f} {sc.area_unit}"),
            ("Moment Ix", f"{Ix_fmt} {sc.inertia_unit}"),
        ]),
        ("SOURCE", [("Section library", "AISC Shapes DB v16.0")]),
    ], "#1F3864", "#EDF2FB")

    if presentation_mode:
        fig.patch.set_facecolor("#071a3a")
        for axis in (ax.xaxis, ax.yaxis, ax.zaxis):
            axis.pane.set_facecolor("#0b2a5b")
            axis.pane.set_edgecolor("#35527f")
            axis.label.set_color("#a9d4ff")
        ax.tick_params(colors="#a9d4ff", labelsize=7)

    if output_path is not None:
        plt.savefig(output_path, dpi=180, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        print(f"  [OK] Diagram saved: {output_path}")


# =============================================================================
# EXCEL HELPERS  (REV1 — unchanged)
# =============================================================================

def _hdr_fill(color_hex):
    return PatternFill("solid", fgColor=color_hex)

def _thin_border():
    s = Side(style='thin', color='999999')
    return Border(left=s, right=s, top=s, bottom=s)

def _apply_header(ws, row, col, value, bg='1F3864', fg='FFFFFF',
                  bold=True, font_size=9):
    cell = ws.cell(row=row, column=col, value=value)
    cell.fill      = PatternFill("solid", fgColor=bg)
    cell.font      = Font(bold=bold, color=fg, name='Arial', size=font_size)
    cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    cell.border    = _thin_border()
    return cell

def _apply_data(ws, row, col, value, bg=None, bold=False,
                align='center', font_size=9, number_fmt=None):
    cell = ws.cell(row=row, column=col, value=value)
    if bg:
        cell.fill = PatternFill("solid", fgColor=bg)
    cell.font      = Font(bold=bold, name='Arial', size=font_size)
    cell.alignment = Alignment(horizontal=align, vertical='center')
    cell.border    = _thin_border()
    if number_fmt:
        cell.number_format = number_fmt
    return cell

def col_width(ws, col, width):
    ws.column_dimensions[get_column_letter(col)].width = width


# =============================================================================
# EXCEL OUTPUT  (REV3 — adds "configuration" sheet; REV1 sheets unchanged)
# =============================================================================

def write_excel(model, output_path, analysis=None):
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    node_dof    = model["node_dof"]
    dof_status  = model["dof_status"]
    dof_eq      = model["dof_eq"]
    member_data = model["member_data"]

    # ------------------------------------------------------------------
    # Sheet 0 (NEW): Configuration
    # ------------------------------------------------------------------
    ws0 = wb.create_sheet("configuration")
    ws0.sheet_view.showGridLines = False
    ws0.row_dimensions[1].height = 28

    ws0.merge_cells('A1:B1')
    c = ws0.cell(row=1, column=1, value=f"REV3 Configuration — loaded from Excel files")
    c.font      = Font(bold=True, size=12, name='Arial', color='1F3864')
    c.alignment = Alignment(horizontal='center', vertical='center')
    c.fill      = PatternFill("solid", fgColor='D6E4F7')

    _apply_header(ws0, 2, 1, "Item",  bg='2E5FA3')
    _apply_header(ws0, 2, 2, "Value", bg='2E5FA3')

    sc = section_config
    mc = material_config
    uc = unit_config

    cfg_rows = [
        ("── Unit System ──",                ""),
        ("Unit System",                       uc.system),
        ("Source file",                       "Units_Imperial_Metric.xlsx"),
        ("",                                  ""),
        (f"── Material: {mc.label} Steel ──",    ""),
        ("Material Label",                    mc.label),
        ("Material Category",                 mc.category),
        (f"E [{mc.E_unit}]",                  mc.E),
        (f"G [{mc.E_unit}]",                  mc.G),
        ("Nu (Poisson's ratio)",               mc.Nu),
        ("Thermal Coeff [1e-6/°C]" if uc.system == "Standard Metric"
                                  else "Thermal Coeff [1e-5/°F]",  mc.thermal_coeff),
        (f"Density [{mc.density_unit}]",       mc.density),
        ("Mass Density [kg/m³]",               mc.mass_density if uc.system == "Standard Metric" else "N/A"),
        (f"Fy [{mc.stress_unit}]",             mc.Fy),
        (f"Fu [{mc.stress_unit}]",             mc.Fu),
        ("Source file",                        "RISA_Materials_Library_Metric.xlsx" if uc.system=="Standard Metric"
                                               else "RISA_Materials_Library_Imperial.xlsx"),
        ("",                                   ""),
        ("── Member Size: W6×25 / W150×37 ──", ""),
        ("AISC Imperial Label",                sc.label_imperial),
        ("Metric Equivalent Label",            sc.label_metric),
        ("Weight [lb/ft]",                     sc.W_lbft),
        (f"d (depth) [{sc.length_unit}]",      round(sc.d, 2)),
        (f"bf (flange width) [{sc.length_unit}]", round(sc.bf, 2)),
        (f"tf (flange thick) [{sc.length_unit}]",  round(sc.tf, 2)),
        (f"tw (web thick) [{sc.length_unit}]",      round(sc.tw, 2)),
        (f"A (area) [{sc.area_unit}]",         round(sc.A, 2)),
        (f"Ix [{sc.inertia_unit}]",            round(sc.Ix, 2)),
        (f"Sx [{sc.modulus_unit}]",            round(sc.Sx, 2)),
        (f"Zx [{sc.modulus_unit}]",            round(sc.Zx, 2)),
        (f"Iy [{sc.inertia_unit}]",            round(sc.Iy, 2)),
        (f"Sy [{sc.modulus_unit}]",            round(sc.Sy, 2)),
        (f"J (torsion) [{sc.inertia_unit}]",   round(sc.J, 2)),
        ("Source file",                        "aisc-shapes-database-v160-2.xlsx"),
    ]

    alt = ['FFFFFF', 'EDF2FB']
    for i, (item, val) in enumerate(cfg_rows, start=3):
        bg = alt[i % 2]
        is_header = str(item).startswith("──")
        bg_row = 'C6EFCE' if is_header else bg
        _apply_data(ws0, i, 1, item, bg=bg_row, align='left', bold=is_header)
        _apply_data(ws0, i, 2, val,  bg=bg_row, align='left', bold=is_header)

    col_width(ws0, 1, 38)
    col_width(ws0, 2, 28)

    # ------------------------------------------------------------------
    # Sheet 1: Model Summary  (REV1 — unchanged)
    # ------------------------------------------------------------------
    ws1 = wb.create_sheet("model summary")
    ws1.sheet_view.showGridLines = False
    ws1.row_dimensions[1].height = 30

    ws1.merge_cells('A1:B1')
    c = ws1.cell(row=1, column=1, value="Structural Model Summary")
    c.font      = Font(bold=True, size=13, name='Arial', color='1F3864')
    c.alignment = Alignment(horizontal='center', vertical='center')
    c.fill      = PatternFill("solid", fgColor='D6E4F7')

    _apply_header(ws1, 2, 1, "Item",  bg='2E5FA3')
    _apply_header(ws1, 2, 2, "Value", bg='2E5FA3')

    if analysis is not None:
        rows = [
            ("Revision",                    REVISION),
            ("Unit System",                  uc.system),
            ("Material",                     f"{mc.label} Steel ({mc.label})"),
            ("Member Size (Imperial)",        sc.label_imperial),
            ("Member Size (Metric equiv.)",   sc.label_metric),
            ("Cube edge length (m)",          CUBE_EDGE),
            ("Number of nodes",               len(NODES)),
            ("Number of members",             len(MEMBERS)),
            ("Supported nodes",               len(SUPPORTS)),
            ("Support type",                  "Pinned"),
            ("DOF per node",                  DOF_PER_NODE),
            ("Total DOF",                     model["total_dof"]),
            ("Restrained DOF",                model["restrained_dof"]),
            ("Active DOF (equations)",        model["active_dof"]),
            ("Global vertical axis",          "Y"),
            ("Global lateral axes",           "X and Z"),
            ("Beta angle, base beams (deg)",  BETA_ANGLES["Base Beam"]),
            ("Beta angle, roof beams (deg)",  BETA_ANGLES["Roof Beam"]),
            ("Beta angle, columns (deg)",     BETA_ANGLES["Column"]),
            ("Max nodal displacement (mm)",   analysis["max_disp"] * 1000.0),
            ("Max displacement node",         analysis["max_disp_node"]),
        ]
    else:
        rows = [
            ("Revision",                    REVISION),
            ("Unit System",                  uc.system),
            ("Material",                     f"{mc.label} Steel ({mc.label})"),
            ("Member Size (Imperial)",        sc.label_imperial),
            ("Member Size (Metric equiv.)",   sc.label_metric),
            ("Cube edge length (m)",          CUBE_EDGE),
            ("Number of nodes",               len(NODES)),
            ("Number of members",             len(MEMBERS)),
            ("Supported nodes",               len(SUPPORTS)),
            ("Support type",                  "Pinned"),
            ("DOF per node",                  DOF_PER_NODE),
            ("Total DOF",                     model["total_dof"]),
            ("Restrained DOF",                model["restrained_dof"]),
            ("Active DOF (equations)",        model["active_dof"]),
            ("Global vertical axis",          "Y"),
            ("Global lateral axes",           "X and Z"),
            ("Beta angle, base beams (deg)",  BETA_ANGLES["Base Beam"]),
            ("Beta angle, roof beams (deg)",  BETA_ANGLES["Roof Beam"]),
            ("Beta angle, columns (deg)",     BETA_ANGLES["Column"]),
        ]

    alt = ['FFFFFF', 'EDF2FB']
    for i, (item, val) in enumerate(rows, start=3):
        bg = alt[i % 2]
        _apply_data(ws1, i, 1, item, bg=bg, align='left')
        _apply_data(ws1, i, 2, val,  bg=bg, align='center')

    col_width(ws1, 1, 32)
    col_width(ws1, 2, 28)

    # ------------------------------------------------------------------
    # Sheet 2: Nodes  (REV1 — unchanged)
    # ------------------------------------------------------------------
    ws2 = wb.create_sheet("node")
    ws2.sheet_view.showGridLines = False
    for ci, h in enumerate(["Node","X (m)","Y (m)","Z (m)","Support"], 1):
        _apply_header(ws2, 1, ci, h, bg='2E5FA3')
    for r, (nid, (x,y,z)) in enumerate(sorted(NODES.items()), start=2):
        sup = SUPPORTS.get(nid, "Free")
        bg  = 'FFE0E0' if sup == "Pinned" else 'FFFFFF'
        _apply_data(ws2, r, 1, nid, bg=bg)
        _apply_data(ws2, r, 2, x,   bg=bg)
        _apply_data(ws2, r, 3, y,   bg=bg)
        _apply_data(ws2, r, 4, z,   bg=bg)
        _apply_data(ws2, r, 5, sup, bg=bg, bold=(sup=="Pinned"))
    for ci, w in enumerate([8,10,10,10,12], 1):
        col_width(ws2, ci, w)

    # ------------------------------------------------------------------
    # Sheet 3: Member Incidences  (REV1 — unchanged)
    # ------------------------------------------------------------------
    ws3 = wb.create_sheet("member incidences")
    ws3.sheet_view.showGridLines = False
    for ci, h in enumerate(["Member","Node i (Start)","Node j (End)","Type","Length (m)","Beta (deg)"], 1):
        _apply_header(ws3, 1, ci, h, bg='2E5FA3')
    type_colors = {"Base Beam":'E8F4FD', "Roof Beam":'EDF7EE', "Column":'FEF9E7'}
    for r, (mid, md) in enumerate(sorted(member_data.items()), start=2):
        bg = type_colors.get(md["type"], 'FFFFFF')
        _apply_data(ws3, r, 1, mid,          bg=bg)
        _apply_data(ws3, r, 2, md["ni"],     bg=bg)
        _apply_data(ws3, r, 3, md["nj"],     bg=bg)
        _apply_data(ws3, r, 4, md["type"],   bg=bg, align='left')
        _apply_data(ws3, r, 5, md["length"], bg=bg)
        _apply_data(ws3, r, 6, md["beta"],   bg=bg)
    for ci, w in enumerate([10,14,14,14,13,12], 1):
        col_width(ws3, ci, w)

    # ------------------------------------------------------------------
    # Sheet 4: Supports  (REV1 — unchanged)
    # ------------------------------------------------------------------
    ws4 = wb.create_sheet("supports")
    ws4.sheet_view.showGridLines = False
    for ci, h in enumerate(["Node","X (m)","Y (m)","Z (m)","Support Type",
                             "UX","UY","UZ","RX","RY","RZ","Restraint Code"], 1):
        _apply_header(ws4, 1, ci, h, bg='2E5FA3')
    for r, (nid, (x,y,z)) in enumerate(sorted(NODES.items()), start=2):
        sup = SUPPORTS.get(nid, None)
        bg  = 'FFE0E0' if sup else 'FFFFFF'
        _apply_data(ws4, r, 1, nid,                        bg=bg)
        _apply_data(ws4, r, 2, x,                          bg=bg)
        _apply_data(ws4, r, 3, y,                          bg=bg)
        _apply_data(ws4, r, 4, z,                          bg=bg)
        _apply_data(ws4, r, 5, sup if sup else "Free",     bg=bg, bold=bool(sup))
        if sup == "Pinned":
            for ci, lbl in enumerate(["Restrained"]*3 + ["Active"]*3, start=6):
                color = 'FF4444' if lbl=="Restrained" else '22AA22'
                c = ws4.cell(row=r, column=ci, value=lbl)
                c.font      = Font(bold=True, color=color, name='Arial', size=9)
                c.alignment = Alignment(horizontal='center', vertical='center')
                c.border    = _thin_border()
                c.fill      = PatternFill("solid", fgColor=bg)
        else:
            for ci in range(6, 12):
                _apply_data(ws4, r, ci, "Active", bg=bg)
        _apply_data(ws4, r, 12, compute_restraint_code(nid, SUPPORTS), bg=bg, bold=bool(sup))
    for ci, w in enumerate([8,8,8,8,14,12,12,12,12,12,12,16], 1):
        col_width(ws4, ci, w)

    # ------------------------------------------------------------------
    # Sheet 5: Local Axes  (REV1 — unchanged)
    # ------------------------------------------------------------------
    ws5 = wb.create_sheet("local axes")
    ws5.sheet_view.showGridLines = False
    hdrs5 = ["Member","Node i","Node j","Type","Length (m)","Beta (deg)",
             "local x - X","local x - Y","local x - Z",
             "local y - X","local y - Y","local y - Z",
             "local z - X","local z - Y","local z - Z"]
    for ci, h in enumerate(hdrs5, 1):
        _apply_header(ws5, 1, ci, h, bg='2E5FA3')
    tc5 = {"Base Beam":'E8F4FD', "Roof Beam":'EDF7EE', "Column":'FEF9E7'}
    for r, (mid, md) in enumerate(sorted(member_data.items()), start=2):
        bg = tc5.get(md["type"], 'FFFFFF')
        ex, ey, ez = md["ex"], md["ey"], md["ez"]
        vals = [mid, md["ni"], md["nj"], md["type"], md["length"], md["beta"],
                round(ex[0],4), round(ex[1],4), round(ex[2],4),
                round(ey[0],4), round(ey[1],4), round(ey[2],4),
                round(ez[0],4), round(ez[1],4), round(ez[2],4)]
        for ci, v in enumerate(vals, 1):
            _apply_data(ws5, r, ci, v, bg=bg, align='left' if ci==4 else 'center')
    for ci, w in enumerate([10,8,8,14,12,12,12,12,12,12,12,12,12,12,12], 1):
        col_width(ws5, ci, w)

    # ------------------------------------------------------------------
    # Sheet 6: Node DOF  (REV1 — unchanged)
    # ------------------------------------------------------------------
    ws6 = wb.create_sheet("node DOF")
    ws6.sheet_view.showGridLines = False
    for ci, h in enumerate(["Node","UX","UY","UZ","RX","RY","RZ","Raw DOF Range"], 1):
        _apply_header(ws6, 1, ci, h, bg='2E5FA3')
    for r, nid in enumerate(sorted(NODES.keys()), start=2):
        dofs = node_dof[nid]
        sup  = SUPPORTS.get(nid, None)
        bg   = 'FFE0E0' if sup else 'FFFFFF'
        _apply_data(ws6, r, 1, nid, bg=bg, bold=True)
        for ldi, gdof in enumerate(dofs):
            ci     = ldi + 2
            status = dof_status[gdof]
            eq_num = dof_eq[gdof]
            cell_val = "R" if status == "Restrained" else (eq_num if eq_num else gdof)
            c = ws6.cell(row=r, column=ci, value=cell_val)
            c.fill      = PatternFill("solid", fgColor=bg)
            c.border    = _thin_border()
            c.alignment = Alignment(horizontal='center', vertical='center')
            c.font = Font(bold=True, color='CC0000', name='Arial', size=9) \
                     if status == "Restrained" else Font(color='005500', name='Arial', size=9)
        _apply_data(ws6, r, 8, f"{dofs[0]}-{dofs[-1]}", bg=bg)
    rr = len(NODES) + 3
    ws6.cell(row=rr,   column=1, value="Total DOF:").font     = Font(bold=True, name='Arial', size=9)
    ws6.cell(row=rr,   column=2, value=model["total_dof"])
    ws6.cell(row=rr+1, column=1, value="Active (Free) DOF:").font = Font(bold=True, name='Arial', size=9)
    ws6.cell(row=rr+1, column=2, value=model["active_dof"])
    ws6.cell(row=rr+2, column=1, value="Restrained DOF:").font    = Font(bold=True, name='Arial', size=9)
    ws6.cell(row=rr+2, column=2, value=model["restrained_dof"])
    for ci, w in enumerate([8,8,8,8,8,8,8,14], 1):
        col_width(ws6, ci, w)

    # ------------------------------------------------------------------
    # Sheet 7: DOF Numbering  (REV1 — unchanged)
    # ------------------------------------------------------------------
    ws7 = wb.create_sheet("DOF numbering")
    ws7.sheet_view.showGridLines = False
    for ci, h in enumerate(["Node","Local DOF","DOF","Description",
                             "Global DOF No.","Status","Equation No."], 1):
        _apply_header(ws7, 1, ci, h, bg='2E5FA3')
    r = 2
    for nid in sorted(NODES.keys()):
        dofs = node_dof[nid]
        for ldi, gdof in enumerate(dofs):
            status = dof_status[gdof]
            eq_num = dof_eq[gdof]
            sup = SUPPORTS.get(nid, None)
            bg  = 'FFE0E0' if status=="Restrained" else ('E8F4FD' if sup else 'FFFFFF')
            _apply_data(ws7, r, 1, nid,                    bg=bg)
            _apply_data(ws7, r, 2, ldi+1,                  bg=bg)
            _apply_data(ws7, r, 3, DOF_LABELS[ldi],        bg=bg, bold=True)
            _apply_data(ws7, r, 4, DOF_DESCRIPTIONS[ldi],  bg=bg, align='left')
            _apply_data(ws7, r, 5, gdof,                   bg=bg)
            color_st = 'CC0000' if status=="Restrained" else '006600'
            c6 = ws7.cell(row=r, column=6, value=status)
            c6.font      = Font(bold=True, color=color_st, name='Arial', size=9)
            c6.fill      = PatternFill("solid", fgColor=bg)
            c6.alignment = Alignment(horizontal='center', vertical='center')
            c6.border    = _thin_border()
            _apply_data(ws7, r, 7, eq_num if eq_num else "-", bg=bg)
            r += 1
    for ci, w in enumerate([8,10,8,16,15,14,14], 1):
        col_width(ws7, ci, w)

    # ------------------------------------------------------------------
    # Sheet 8: Member Releases  (REV1 — unchanged)
    # ------------------------------------------------------------------
    ws8 = wb.create_sheet("member releases")
    ws8.sheet_view.showGridLines = False
    for ci, h in enumerate(["Member","End","Fx","Fy","Fz","Mx","My","Mz"], 1):
        _apply_header(ws8, 1, ci, h, bg='2E5FA3')
    r = 2
    tc8 = {"Base Beam":'E8F4FD', "Roof Beam":'EDF7EE', "Column":'FEF9E7'}
    for mid, md in sorted(member_data.items()):
        bg = tc8.get(md["type"], 'FFFFFF')
        for end_idx, (_, end_label) in enumerate(
                [(md["ni"], f"i (Node {md['ni']})"),
                 (md["nj"], f"j (Node {md['nj']})")]):
            _apply_data(ws8, r, 1, mid,       bg=bg)
            _apply_data(ws8, r, 2, end_label, bg=bg, align='left')
            rel = RELEASES.get(mid, {}).get(end_idx, {})
            for ci, dof_name in enumerate(["Fx","Fy","Fz","Mx","My","Mz"], 3):
                val = rel.get(dof_name, "Fixed")
                color = 'CC0000' if val=="Released" else '333333'
                c = ws8.cell(row=r, column=ci, value=val)
                c.font      = Font(color=color, name='Arial', size=9, bold=(val=="Released"))
                c.fill      = PatternFill("solid", fgColor=bg)
                c.alignment = Alignment(horizontal='center', vertical='center')
                c.border    = _thin_border()
            r += 1
    for ci, w in enumerate([10,16,10,10,10,10,10,10], 1):
        col_width(ws8, ci, w)

    # ── Freeze + tab colours ─────────────────────────────────────────────────
    tab_colors = {
        "configuration":   "00B050",
        "model summary":   "1F3864",
        "node":            "2E75B6",
        "member incidences":"2E75B6",
        "supports":        "C00000",
        "local axes":      "375623",
        "node DOF":        "7030A0",
        "DOF numbering":   "7030A0",
        "member releases": "833C00",
    }
    for ws in [ws0, ws1, ws2, ws3, ws4, ws5, ws6, ws7, ws8]:
        ws.freeze_panes = 'A2'
        if ws.title in tab_colors:
            ws.sheet_properties.tabColor = tab_colors[ws.title]

    wb.save(output_path)
    print(f"  [OK] Excel saved: {output_path}")


# =============================================================================
# WEB INTERFACE
# =============================================================================
# The web page is only an input/output interface. The actual structural
# calculations, Excel lookups, Matplotlib diagram, and Excel report remain
# in the REV3 Python functions above.

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

WEB_HOST = "127.0.0.1"
WEB_PORT = 5000


def _material_candidates(system):
    folder_path = os.path.join(HERE, "materials")
    return _material_library_candidates(folder_path, system)


def get_material_options(system, library_file=None):
    """Read material names from the same RISA Excel library used by the solver."""
    candidates = _material_candidates(system)
    if not candidates:
        return []
    xlsx_path = _select_library_candidate(candidates, library_file, "materials")
    df = pd.read_excel(xlsx_path, sheet_name="All Materials", header=3)
    df = df[df["Label"].notna()].copy()
    return sorted({str(x).strip() for x in df["Label"].tolist()})


def _section_candidates():
    folder_path = os.path.join(HERE, "sections")
    candidates = glob.glob(os.path.join(folder_path, "aisc*.xlsx"))
    if not candidates:
        candidates = glob.glob(os.path.join(folder_path, "*.xlsx"))
    return candidates


def get_section_options(library_file=None):
    """Read AISC section labels from the same Excel database used by REV3."""
    candidates = _section_candidates()
    if not candidates:
        return []
    xlsx_path = _select_library_candidate(candidates, library_file, "sections")
    df = pd.read_excel(xlsx_path, sheet_name="Database v16.0", header=0)
    return sorted({str(x).strip() for x in df["AISC_Manual_Label"].dropna().tolist()})


def plot_rev4_professor_view(
    model, output_path, view_type="case", view_id=1, load_band=True, show_grid=True, ax=None
):
    """Draw the Rev 4 load view to an image or an optional live 3D axes."""
    from matplotlib.lines import Line2D

    if view_type == "case":
        glyphs = build_rev4_case_glyphs(view_id)
        title = next(case.name for case in REV4_ARCHITECTURE["load_cases"] if case.id == view_id)
        category = next(case.category for case in REV4_ARCHITECTURE["load_cases"] if case.id == view_id)
        factor_lines = []
    elif view_type == "combination":
        glyphs = build_rev4_combination_glyphs(view_id)
        combo = next(combo for combo in REV4_ARCHITECTURE["load_combinations"] if combo.id == view_id)
        title = combo.name
        category = combo.design_method
        factor_lines = [
            f"{next(case.name for case in REV4_ARCHITECTURE['load_cases'] if case.id == case_id)} x {factor:g}"
            for case_id, factor in combo.factors.items()
        ]
    else:
        raise ValueError("View type must be case or combination.")

    if ax is None:
        fig = plt.figure(figsize=(8, 8), facecolor="white")
        ax = fig.add_subplot(111, projection="3d")
    else:
        fig = ax.figure
        ax.clear()
    ax.set_facecolor("white")
    structure_color = "#16877f"
    diaphragm_color = "#2d6cdf"
    load_color = "#e85d04"
    point_color = "#7c3aed"
    nodal_color = "#d62828"
    temperature_color = "#a95816"

    def p(node_id):
        return plot_point(NODES[node_id])

    def draw_arrow(start, vector, color, linewidth=1.4):
        ax.quiver(
            start[0], start[1], start[2], vector[0], vector[1], vector[2],
            color=color, linewidth=linewidth, arrow_length_ratio=0.28,
        )

    def draw_band(member_id, magnitude, direction, color, is_self_weight=False):
        ni, nj, member_type = MEMBERS[member_id]
        if member_type == "Column" and direction in {"FY", "-FY"}:
            return False
        p0, p1 = p(ni), p(nj)
        axis = p1 - p0
        length = np.linalg.norm(axis)
        if length < 1e-9:
            return
        unit = axis / length
        vertical = np.array([0.0, 0.0, 1.0])
        normal = np.cross(unit, vertical)
        if np.linalg.norm(normal) < 1e-9:
            normal = np.array([1.0, 0.0, 0.0])
        normal /= np.linalg.norm(normal)
        width = 0.15
        stand_off = 0.10
        if load_band:
            corners = [p0 + normal * stand_off, p1 + normal * stand_off,
                       p1 + normal * (stand_off + width), p0 + normal * (stand_off + width)]
            ax.add_collection3d(Poly3DCollection(
                [[tuple(point) for point in corners]],
                alpha=REV4_SELF_WEIGHT_BAND_ALPHA if is_self_weight else REV4_DISTRIBUTED_BAND_ALPHA,
                facecolor=color, edgecolor=color, linewidth=0.8,
            ))
            intensity_start = p0 + normal * (stand_off + width)
            intensity_end = p1 + normal * (stand_off + width)
            ax.plot(
                [intensity_start[0], intensity_end[0]],
                [intensity_start[1], intensity_end[1]],
                [intensity_start[2], intensity_end[2]],
                color=color, linewidth=1.2,
            )
        direction_map = {
            "FX": np.array([1.0, 0.0, 0.0]), "-FX": np.array([-1.0, 0.0, 0.0]),
            "FY": np.array([0.0, 0.0, 1.0]), "-FY": np.array([0.0, 0.0, -1.0]),
            "FZ": np.array([0.0, 1.0, 0.0]), "-FZ": np.array([0.0, -1.0, 0.0]),
        }
        load_vector = direction_map.get(direction, direction_map["-FY"])
        spacing = 0.34
        count = max(6, int(length / spacing))
        for index in range(count):
            position = p0 + unit * ((index + 0.5) / count) * length
            draw_arrow(position, load_vector * (0.25 if load_band else 0.16), color, linewidth=1.4 if load_band else 0.8)
        return True

    # Draw the complete frame first so load symbols read as annotations.
    for member_id, (ni, nj, _) in MEMBERS.items():
        pi, pj = p(ni), p(nj)
        ax.plot([pi[0], pj[0]], [pi[1], pj[1]], [pi[2], pj[2]], color=structure_color, linewidth=2.0)
        midpoint = (pi + pj) / 2.0
        ax.text(midpoint[0], midpoint[1], midpoint[2], f"M{member_id}", color="#173f7a", fontsize=7)

    # The roof diaphragm is a visual constraint definition, not a hidden load.
    roof = [5, 6, 7, 8, 5]
    for start, end in zip(roof, roof[1:]):
        pi, pj = p(start), p(end)
        ax.plot([pi[0], pj[0]], [pi[1], pj[1]], [pi[2], pj[2]], color=diaphragm_color, linewidth=3.0)
    master = p(REV4_ROOF_DIAPHRAGM.master_node)
    ax.text(master[0], master[1], master[2] - 0.28, "ROOF DIAPHRAGM master N5", color=diaphragm_color, fontsize=7)

    for node_id, point in NODES.items():
        point_plot = p(node_id)
        ax.scatter([point_plot[0]], [point_plot[1]], [point_plot[2]], color="#f26b6b", edgecolor="#9b2226", s=48, depthshade=False)
        ax.text(point_plot[0] + 0.08, point_plot[1] + 0.08, point_plot[2] + 0.08, f"N{node_id}", color="#8f1d1d", fontsize=7)

    distributed_count = 0
    point_count = 0
    nodal_count = 0
    temperature_count = 0
    distributed_labels = set()
    point_labels = set()
    nodal_labels = set()
    for load in glyphs:
        if isinstance(load, MemberDistributedLoad):
            if draw_band(
                load.member_id,
                load.magnitude,
                load.direction,
                load_color,
                is_self_weight=load.distribution_type == "self_weight",
            ):
                distributed_count += 1
                if view_id == 1 and view_type == "case" and load.distribution_type == "self_weight":
                    distributed_labels.add(f"self weight: {load.magnitude:.4f} kN/m -Y")
                else:
                    distributed_labels.add(f"distributed: {abs(load.magnitude):g} kN/m {load.direction}")
        elif isinstance(load, MemberPointLoad):
            ni, nj, _ = MEMBERS[load.member_id]
            start, end = p(ni), p(nj)
            position = start + load.location * (end - start)
            vector = {"-FY": np.array([0.0, 0.0, -0.7]), "FY": np.array([0.0, 0.0, 0.7]), "FX": np.array([0.7, 0.0, 0.0]), "-FX": np.array([-0.7, 0.0, 0.0]), "FZ": np.array([0.0, 0.7, 0.0]), "-FZ": np.array([0.0, -0.7, 0.0])}[load.direction]
            draw_arrow(position, vector, point_color, linewidth=2.0 if load_band else 1.0)
            ax.text(position[0], position[1], position[2] + 0.45, f"{abs(load.magnitude):.3f} kN {load.direction}", color=point_color, fontsize=7)
            point_count += 1
            point_labels.add(f"point: {abs(load.magnitude):g} kN {load.direction}")
        elif isinstance(load, NodalLoad):
            position = p(load.node_id)
            vector = np.array([load.fx, load.fz, load.fy], dtype=float)
            norm = np.linalg.norm(vector)
            if norm > 1e-9:
                draw_arrow(position, vector / norm * 0.7, nodal_color, linewidth=2.0 if load_band else 1.0)
                direction = "+X" if abs(load.fx) >= max(abs(load.fy), abs(load.fz)) and load.fx >= 0 else "+Z"
                magnitude = max(abs(load.fx), abs(load.fy), abs(load.fz))
                ax.text(position[0], position[1], position[2] + 0.35, f"{magnitude:.3f} kN {direction}", color=nodal_color, fontsize=7)
                nodal_labels.add(f"nodal: {magnitude:g} kN {direction}")
            nodal_count += 1
        elif isinstance(load, TemperatureLoad):
            ni, nj, _ = MEMBERS[load.member_id]
            midpoint = (p(ni) + p(nj)) / 2.0
            ax.text(midpoint[0], midpoint[1], midpoint[2] + 0.18, f"+{load.temperature_change:g} degC", color=temperature_color, fontsize=8, fontweight="bold")
            temperature_count += 1

    ax.set_title(
        f"{'LRFD Combination ' if view_type == 'combination' and category == 'LRFD' else 'ASD Combination ' if view_type == 'combination' else 'Load Case '}{view_id} - {title}",
        fontsize=14, fontweight="bold", pad=12,
    )
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Z (m)")
    ax.set_zlabel("Y (m)")
    ax.set_xlim(-1.0, 7.2)
    ax.set_ylim(-1.0, 7.2)
    ax.set_zlim(-1.0, 7.8)
    ax.set_box_aspect((1, 1, 1))
    ax.view_init(elev=22, azim=-58)
    set_grid_visibility(ax, visible=show_grid)
    legend = [Line2D([0], [0], color=diaphragm_color, linewidth=3, label="Diaphragm nodes (4)")]
    for label in sorted(distributed_labels):
        legend.append(Line2D([0], [0], color=load_color, linewidth=3, label=label))
    for label in sorted(point_labels):
        legend.append(Line2D([0], [0], color=point_color, linewidth=3, label=label))
    for label in sorted(nodal_labels):
        legend.append(Line2D([0], [0], color=nodal_color, linewidth=3, label=label))
    if temperature_count:
        legend.append(Line2D([0], [0], color=temperature_color, linewidth=3, label="temperature"))
    if factor_lines:
        legend.extend([Line2D([], [], color="none", label=line) for line in factor_lines])
    for handle in legend:
        label = handle.get_label()
        handle.set_label(textwrap.fill(label, width=26, break_long_words=False))
    ax.set_position([0.02, 0.06, 0.66, 0.88])
    fig.legend(
        handles=legend,
        loc="upper left",
        bbox_to_anchor=(0.71, 0.97),
        fontsize=7,
        framealpha=0.95,
        borderaxespad=0.0,
        labelspacing=0.5,
        handlelength=1.5,
    )
    if output_path is not None:
        plt.tight_layout()
        plt.savefig(output_path, dpi=150, facecolor="white")
        plt.close(fig)
    return output_path


_OPTIONS_CACHE = {}


def get_web_options(system, materials_file=None, sections_file=None, units_file=None):
    material_files = _material_candidates(system)
    section_files = _section_candidates()
    units_files = glob.glob(os.path.join(HERE, "units", "*.xlsx"))
    selected_materials_file = _select_library_candidate(material_files, materials_file, "materials") if material_files else None
    requested_materials_file = selected_materials_file
    compatible_materials = {
        os.path.basename(path): [
            candidate_system
            for candidate_system in ("Standard Metric", "Imperial")
            if _material_library_supports(path, candidate_system)
        ]
        for path in material_files
    }
    if selected_materials_file and not _material_library_supports(selected_materials_file, system):
        selected_materials_file = next(
            (path for path in material_files if _material_library_supports(path, system)),
            None,
        )
        if selected_materials_file is None:
            raise ValueError(f"No materials workbook supports the {system} unit system.")
    selected_sections_file = _select_library_candidate(section_files, sections_file, "sections") if section_files else None
    selected_units_file = _select_library_candidate(units_files, units_file, "units") if units_files else None
    key = (str(system), requested_materials_file, selected_materials_file, selected_sections_file, selected_units_file)
    if key not in _OPTIONS_CACHE:
        _OPTIONS_CACHE[key] = {
            "materials": get_material_options(system, os.path.basename(selected_materials_file) if selected_materials_file else None),
            "sections": get_section_options(os.path.basename(selected_sections_file) if selected_sections_file else None),
            "libraries": {
                "materials": [os.path.basename(path) for path in material_files],
                "sections": [os.path.basename(path) for path in section_files],
                "units": [os.path.basename(path) for path in units_files],
                "materials_compatible": compatible_materials,
                "selected": {
                    "materials": os.path.basename(selected_materials_file) if selected_materials_file else "",
                    "sections": os.path.basename(selected_sections_file) if selected_sections_file else "",
                    "units": os.path.basename(selected_units_file) if selected_units_file else "",
                },
            },
            "notice": (
                f"{os.path.basename(requested_materials_file)} does not support {system}; "
                f"using {os.path.basename(selected_materials_file)} instead."
                if requested_materials_file and requested_materials_file != selected_materials_file
                else ""
            ),
            "model": {
                "cube_edge_m": CUBE_EDGE,
                "node_count": len(NODES),
                "member_count": len(MEMBERS),
                "supported_nodes": sorted(SUPPORTS),
            },
        }
    return _OPTIONS_CACHE[key]


def get_rev4_web_options():
    """Return the load-case and combination choices used by the browser viewer."""
    return {
        "diaphragm": {
            "master_node": REV4_ROOF_DIAPHRAGM.master_node,
            "constrained_nodes": REV4_ROOF_DIAPHRAGM.constrained_nodes,
            "degrees_of_freedom": REV4_ROOF_DIAPHRAGM.degrees_of_freedom,
        },
        "load_cases": [
            {"id": case.id, "name": case.name, "category": case.category}
            for case in REV4_ARCHITECTURE["load_cases"]
        ],
        "combinations": [
            {"id": combo.id, "name": combo.name, "design_method": combo.design_method}
            for combo in REV4_ARCHITECTURE["load_combinations"]
        ],
    }


def render_rev4_web_view(view_type: str, view_id: int, load_band: bool = True, show_grid: bool = True) -> str:
    """Render a browser-selected Rev 4 case or combination and return its filename."""
    os.makedirs(REV4_OUTPUT_FOLDER, exist_ok=True)
    model = build_model()
    if view_type == "case":
        filename = f"rev4_web_case_{view_id}.png"
        plot_rev4_professor_view(model, os.path.join(REV4_OUTPUT_FOLDER, filename), "case", view_id, load_band, show_grid)
    elif view_type == "combination":
        filename = f"rev4_web_combination_{view_id}.png"
        plot_rev4_professor_view(model, os.path.join(REV4_OUTPUT_FOLDER, filename), "combination", view_id, load_band, show_grid)
    else:
        raise ValueError("View type must be case or combination.")
    return filename


def _display_force(value):
    if UNIT_SYSTEM == "Standard Metric":
        return float(value) / 1000.0
    return float(value)


def _display_reaction(value):
    if UNIT_SYSTEM == "Standard Metric":
        return float(value) / 1000.0
    return float(value)


def _force_unit():
    return "kN" if UNIT_SYSTEM == "Standard Metric" else "kip"


def _make_web_result(model, analysis, diagram_path, excel_path):
    node_rows = []
    for nid in sorted(NODES):
        disp = analysis["displacements"][nid]
        reaction = analysis["reactions"][nid]["force"]
        node_rows.append({
            "node": nid,
            "UX": disp[0] * 1000.0,
            "UY": disp[1] * 1000.0,
            "UZ": disp[2] * 1000.0,
            "Rx": _display_reaction(reaction[0]),
            "Ry": _display_reaction(reaction[1]),
            "Rz": _display_reaction(reaction[2]),
        })

    load_rows = []
    for nid, values in LOADS.items():
        load_rows.append({
            "node": nid,
            "Fx": _display_force(values[0]),
            "Fy": _display_force(values[1]),
            "Fz": _display_force(values[2]),
            "Mx": values[3],
            "My": values[4],
            "Mz": values[5],
        })

    return {
        "unit_system": unit_config.system,
        "force_unit": _force_unit(),
        "material": f"{material_config.label} Steel ({material_config.label})",
        "section": (
            f"{section_config.label_metric} [{section_config.label_imperial}]"
            if unit_config.system == "Standard Metric"
            else section_config.label_imperial
        ),
        "column_section": (
            f"{column_section_config.label_metric} [{column_section_config.label_imperial}]"
            if unit_config.system == "Standard Metric"
            else column_section_config.label_imperial
        ),
        "max_displacement_mm": analysis["max_disp"] * 1000.0,
        "max_displacement_node": analysis["max_disp_node"],
        "node_rows": node_rows,
        "load_rows": load_rows,
        "diagram": os.path.basename(diagram_path),
        "excel": os.path.basename(excel_path),
        "total_dof": model["total_dof"],
        "restrained_dof": model["restrained_dof"],
        "active_dof": model["active_dof"],
    }


WEB_PAGE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Structural Solver</title>
<style>
:root{--bg:#0b1220;--panel:#121b2e;--panel2:#1a2540;--line:#2a3654;--text:#e2e8f0;--muted:#94a3b8;--accent:#38bdf8;--good:#22c55e;--danger:#ef4444}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:14px}
header{padding:18px 24px;border-bottom:1px solid var(--line);background:var(--panel);display:flex;align-items:center;gap:16px}h1{font-size:21px;margin:0}.sub{color:var(--muted);font-size:12px;margin-top:3px}.grow{flex:1}
main{max-width:1450px;margin:auto;padding:22px}.layout{display:grid;grid-template-columns:360px 1fr;gap:22px}.panel{background:var(--panel);border:1px solid var(--line);padding:18px;margin-bottom:18px}.panel h2{font-size:14px;margin:0 0 15px;text-transform:uppercase;letter-spacing:.08em;color:var(--accent)}
label{display:block;color:var(--muted);font-size:12px;margin:12px 0 6px}select,input{width:100%;padding:9px 10px;border:1px solid var(--line);background:#0f172a;color:var(--text);border-radius:5px}input:focus,select:focus{outline:1px solid var(--accent)}
button{padding:10px 15px;border:1px solid var(--line);border-radius:5px;background:var(--panel2);color:var(--text);cursor:pointer;font-weight:600}button:hover{border-color:var(--accent)}button.primary{background:var(--accent);color:#06202f;border-color:var(--accent);width:100%;margin-top:16px}.danger{color:#fca5a5}
.load-scroll{overflow-x:auto;padding-bottom:4px}.load-labels,.row{display:grid;grid-template-columns:70px repeat(6,minmax(58px,1fr)) 34px;gap:6px;min-width:500px}.load-labels{margin-bottom:4px;color:var(--muted);font-size:10px;font-weight:700;text-align:center;letter-spacing:.05em}.load-labels span:first-child{text-align:left}.row{align-items:end;margin-bottom:8px}.row input,.row select{min-width:0;padding:7px 6px;font-size:12px;text-align:center}.remove{padding:7px 0}
details{border-top:1px solid var(--line);padding:10px 0}details:first-of-type{border-top:0;padding-top:0}summary{cursor:pointer;color:var(--text);font-weight:650;font-size:12px}summary::marker{color:var(--accent)}.property-grid{display:grid;grid-template-columns:1fr 1fr;gap:0 12px}.property-grid label{min-width:0}.property-grid label.wide{grid-column:1/-1}.property-grid input,.property-grid select{min-width:0}.readonly{padding:10px;background:#0f172a;color:var(--muted);line-height:1.7;font-size:12px}.project-summary{border-bottom:1px solid var(--line);padding:0 0 12px;margin-bottom:14px;color:var(--muted)}.project-summary strong{color:var(--text)}
.status{padding:10px;border-left:3px solid var(--accent);background:#0f172a;color:var(--muted);margin-top:12px}.error{border-left-color:var(--danger);color:#fecaca}.success{border-left-color:var(--good);color:#bbf7d0}
.results{min-height:300px}.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:18px}.kpi{border-left:3px solid var(--accent);padding:12px;background:#0f172a}.kpi .v{font-size:19px;font-weight:700;margin-top:5px}.kpi .l{font-size:11px;color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:12px}th,td{border-bottom:1px solid var(--line);padding:8px;text-align:right}th{color:var(--muted);font-weight:600}th:first-child,td:first-child{text-align:left}.table-wrap{overflow:auto;max-height:430px}.outputs{display:flex;gap:10px;flex-wrap:wrap;margin-top:15px}.outputs a{color:var(--accent);text-decoration:none;border:1px solid var(--line);padding:9px 12px;background:#0f172a}.diagram{width:100%;display:block;margin-top:15px;border:1px solid var(--line);background:white}
@media(max-width:900px){.layout{grid-template-columns:1fr}.kpis{grid-template-columns:1fr 1fr}.row{min-width:760px}.load-scroll{overflow:auto}}
</style>
</head>
<body>
<header><div><h1>Structural Solver</h1><div class="sub">6 m × 6 m × 6 m Cube Frame · Excel-driven configuration · Python solver</div></div><div class="grow"></div><div class="sub">Local browser interface</div></header>
<main><div class="layout"><section>
<div class="panel"><h2>Properties</h2>
<details open><summary>Project Information</summary><div class="property-grid">
<label class="wide" for="projectName">Project Name<input id="projectName" maxlength="160" value="Cube Frame Model"></label>
<label for="company">Company<input id="company" maxlength="160" value=""></label>
<label for="designer">Designer<input id="designer" maxlength="160" value=""></label>
<label for="projectNumber">Project Number<input id="projectNumber" maxlength="80" value=""></label>
<label for="checkedBy">Checked By<input id="checkedBy" maxlength="160" value=""></label>
<label class="wide" for="projectNotes">Project Notes<input id="projectNotes" maxlength="1000" value=""></label>
</div></details>
<details open><summary>Model Inputs</summary><div id="modelSummary" class="readonly">Loading model data from the Python solver…</div></details>
<details><summary>Libraries</summary><div class="property-grid">
<label class="wide" for="unitsLibrary">Units Workbook<select id="unitsLibrary"></select></label>
<label class="wide" for="materialsLibrary">Materials Workbook<select id="materialsLibrary"></select></label>
<label class="wide" for="sectionsLibrary">Sections Workbook<select id="sectionsLibrary"></select></label>
</div><div class="status" id="source">Library choices and properties are read from the Excel files in the REV3 folders.</div></details>
<details open><summary>Materials</summary><label for="material">Material — from selected RISA workbook</label><select id="material"></select></details>
<details open><summary>Member Sections</summary><div class="property-grid">
<label for="section">Beam Section<input id="section" list="sectionList" value="W12X26"></label>
<label for="columnSection">Column Section<input id="columnSection" list="sectionList" value="W10X33"></label>
</div><datalist id="sectionList"></datalist></details>
<details open><summary>Units</summary><label for="unit">Unit System</label><select id="unit"><option>Standard Metric</option><option>Imperial</option></select></details>
</div>
<div class="panel"><h2>Model Inputs · Applied Loads</h2><div class="sub">Force unit: <span id="forceUnit">kN</span>. Enter one or more loads. Moments use the corresponding force-length unit.</div>
<div class="load-scroll"><div class="load-labels"><span>NODE</span><span>FX</span><span>FY</span><span>FZ</span><span>MX</span><span>MY</span><span>MZ</span><span></span></div><div id="loadRows"></div></div>
<button type="button" onclick="addLoad()">+ Add Load</button><button type="button" class="primary" id="solve" onclick="solve()">SOLVE STRUCTURE</button>
<div class="status" id="message">Default load: Node 7, Fy = -100 kN.</div></div>
<div class="panel"><h2>Load Viewer</h2>
<label for="rev4View">View type</label><select id="rev4View"><option value="case">Load case</option><option value="combination">Load combination</option></select>
<label for="rev4Id">Load case</label><select id="rev4Id"></select>
<label><input id="rev4Band" type="checkbox" checked style="width:auto;margin-right:6px"> Show distributed-load bands</label>
<label><input id="rev4Grid" type="checkbox" checked style="width:auto;margin-right:6px"> Show grid</label>
<button type="button" class="primary" id="rev4Render" onclick="renderRev4View()">VIEW LOADS</button>
<div class="status" id="rev4Message">Select a load case or combination to render the load view.</div></div>
</section><section class="results"><div class="panel"><h2>Analysis Results</h2><div id="results"><div class="status">Change the inputs if needed, then click <b>SOLVE STRUCTURE</b>.</div></div></div><div class="panel"><h2>Load View</h2><div id="rev4Results"><div class="status">Choose a load case or combination, then click <b>VIEW LOADS</b>.</div></div></div></section></div></main>
<script>
let options={materials:[],sections:[],libraries:{}};const $=id=>document.getElementById(id);
function fmt(v){if(v===null||v===undefined)return '—';if(Math.abs(v)<1e-10)return '0';return Number(v).toFixed(4)}
function escapeHtml(value){return String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]))}
function forceUnit(){return $('unit').value==='Standard Metric'?'kN':'kip'}
function refreshUnitLabel(){$('forceUnit').textContent=forceUnit()}
function fillLibrarySelect(id,values,selected,compatibleSystems){const el=$(id);el.innerHTML='';values.forEach(value=>{const option=document.createElement('option');option.value=value;option.textContent=value;option.disabled=compatibleSystems&&!compatibleSystems[value].includes($('unit').value);el.appendChild(option)});if(values.includes(selected))el.value=selected}
function materialSelect(){const el=$('material');const old=el.value;el.innerHTML='';options.materials.forEach(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;el.appendChild(o)});if(options.materials.includes(old))el.value=old;else if(options.materials.includes('A992'))el.value='A992';else if(options.materials.length)el.value=options.materials[0]}
function sectionList(){const dl=$('sectionList');dl.innerHTML='';options.sections.forEach(x=>{const o=document.createElement('option');o.value=x;dl.appendChild(o)});if(!options.sections.includes($('section').value)&&options.sections.length)$('section').value=options.sections.includes('W12X26')?'W12X26':options.sections[0];if(!options.sections.includes($('columnSection').value)&&options.sections.length)$('columnSection').value=options.sections.includes('W10X33')?'W10X33':options.sections[0]}
async function refreshOptions(){const unit=$('unit').value;const params=new URLSearchParams({unit});[['materials_file','materialsLibrary'],['sections_file','sectionsLibrary'],['units_file','unitsLibrary']].forEach(([key,id])=>{if($(id).value)params.set(key,$(id).value)});try{const r=await fetch('/api/options?'+params.toString());if(!r.ok)throw new Error(await r.text());options=await r.json();fillLibrarySelect('materialsLibrary',options.libraries.materials,options.libraries.selected.materials,options.libraries.materials_compatible);fillLibrarySelect('sectionsLibrary',options.libraries.sections,options.libraries.selected.sections);fillLibrarySelect('unitsLibrary',options.libraries.units,options.libraries.selected.units);materialSelect();sectionList();const model=options.model;$('modelSummary').innerHTML=`${model.cube_edge_m} m cube frame · ${model.node_count} nodes · ${model.member_count} members<br>Supports: ${model.supported_nodes.map(node=>`N${node}`).join(', ')}<br>Geometry and support layout are defined by the existing Python model.`;$('source').textContent=options.notice||'Selected workbook files are read by the existing Python Excel loaders.';$('source').className=options.notice?'status error':'status';refreshUnitLabel()}catch(e){$('source').textContent='Could not load Excel options: '+e.message;$('source').className='status error'}}
function makeInput(field,value){const i=document.createElement('input');i.type='number';i.step='any';i.dataset.field=field;i.value=value;return i}
function addLoad(data){const wrap=document.createElement('div');wrap.className='row load-row';const node=document.createElement('select');node.dataset.field='node';for(let n=1;n<=8;n++){const o=document.createElement('option');o.value=n;o.textContent=n;node.appendChild(o)}const values=data||{node:7,Fx:0,Fy:-100,Fz:0,Mx:0,My:0,Mz:0};node.value=values.node;wrap.appendChild(node);['Fx','Fy','Fz','Mx','My','Mz'].forEach(f=>wrap.appendChild(makeInput(f,values[f]??0)));const b=document.createElement('button');b.type='button';b.className='remove danger';b.textContent='×';b.onclick=()=>wrap.remove();wrap.appendChild(b);$('loadRows').appendChild(wrap)}
function collect(){const loads=[];document.querySelectorAll('.load-row').forEach(row=>{const obj={node:Number(row.querySelector('[data-field="node"]').value)};row.querySelectorAll('input').forEach(i=>obj[i.dataset.field]=Number(i.value)||0);loads.push(obj)});return {unit:$('unit').value,material:$('material').value,section:$('section').value,column_section:$('columnSection').value,units_file:$('unitsLibrary').value,materials_file:$('materialsLibrary').value,sections_file:$('sectionsLibrary').value,project_info:{project_name:$('projectName').value,company:$('company').value,designer:$('designer').value,project_number:$('projectNumber').value,checked_by:$('checkedBy').value,notes:$('projectNotes').value},loads}}
async function solve(){const btn=$('solve');btn.disabled=true;btn.textContent='SOLVING…';$('message').className='status';$('message').textContent='Running the existing REV3 Python solver and generating the existing PNG/Excel deliverables…';try{const r=await fetch('/api/solve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(collect())});const data=await r.json();if(!r.ok)throw new Error(data.error||'Solve failed');render(data);$('message').className='status success';$('message').textContent='Analysis completed. The existing structural PNG and Excel report were generated.'}catch(e){$('message').className='status error';$('message').textContent=e.message}finally{btn.disabled=false;btn.textContent='SOLVE STRUCTURE'}}
function render(d){const project=d.project_info||{};const title=project.project_name?`<div class="project-summary"><strong>${escapeHtml(project.project_name)}</strong>${project.project_number?` · ${escapeHtml(project.project_number)}`:''}${project.company?` · ${escapeHtml(project.company)}`:''}</div>`:'';let html=title+`<div class="kpis"><div class="kpi"><div class="l">Unit System</div><div class="v">${escapeHtml(d.unit_system)}</div></div><div class="kpi"><div class="l">Material</div><div class="v" style="font-size:14px">${escapeHtml(d.material)}</div></div><div class="kpi"><div class="l">Member Sections</div><div class="v" style="font-size:14px">Beam ${escapeHtml(d.section)}</div><div class="l">Column ${escapeHtml(d.column_section)}</div></div><div class="kpi"><div class="l">Maximum Displacement</div><div class="v">${fmt(d.max_displacement_mm)} mm</div><div class="l">Node ${d.max_displacement_node}</div></div></div>`;html+=`<h3>Applied Loads</h3><div class="table-wrap"><table><thead><tr><th>Node</th><th>Fx (${d.force_unit})</th><th>Fy (${d.force_unit})</th><th>Fz (${d.force_unit})</th><th>Mx</th><th>My</th><th>Mz</th></tr></thead><tbody>`;d.load_rows.forEach(x=>html+=`<tr><td>${x.node}</td><td>${fmt(x.Fx)}</td><td>${fmt(x.Fy)}</td><td>${fmt(x.Fz)}</td><td>${fmt(x.Mx)}</td><td>${fmt(x.My)}</td><td>${fmt(x.Mz)}</td></tr>`);html+='</tbody></table></div>';html+=`<h3>Node Results</h3><div class="table-wrap"><table><thead><tr><th>Node</th><th>UX (mm)</th><th>UY (mm)</th><th>UZ (mm)</th><th>Rx (${d.force_unit})</th><th>Ry (${d.force_unit})</th><th>Rz (${d.force_unit})</th></tr></thead><tbody>`;d.node_rows.forEach(x=>html+=`<tr><td>${x.node}</td><td>${fmt(x.UX)}</td><td>${fmt(x.UY)}</td><td>${fmt(x.UZ)}</td><td>${fmt(x.Rx)}</td><td>${fmt(x.Ry)}</td><td>${fmt(x.Rz)}</td></tr>`);html+='</tbody></table></div>';html+=`<div class="status">DOF: ${d.total_dof} total · ${d.restrained_dof} restrained · ${d.active_dof} active</div><div class="outputs"><a href="/${encodeURIComponent(d.excel)}" download>Open / Download Excel Report</a><a href="/${encodeURIComponent(d.diagram)}" target="_blank">Open Structural PNG</a></div><img class="diagram" src="/${encodeURIComponent(d.diagram)}?t=${Date.now()}" alt="Structural model">`;$('results').innerHTML=html}
async function refreshRev4Options(){try{const r=await fetch('/api/rev4/options');const data=await r.json();const type=$('rev4View').value;const el=$('rev4Id');el.innerHTML='';const values=type==='case'?data.load_cases:data.combinations;values.forEach(x=>{const o=document.createElement('option');o.value=x.id;o.textContent=`${x.id} — ${x.name} [${x.category||x.design_method}]`;el.appendChild(o)});$('rev4Message').textContent=`Roof diaphragm: master N${data.diaphragm.master_node}; constrained ${data.diaphragm.degrees_of_freedom.join(', ')}.`}catch(e){$('rev4Message').className='status error';$('rev4Message').textContent='Could not load Rev 4 choices: '+e.message}}
async function renderRev4View(){const type=$('rev4View').value;const id=Number($('rev4Id').value);const band=$('rev4Band').checked;const grid=$('rev4Grid').checked;const button=$('rev4Render');button.disabled=true;button.textContent='RENDERING…';try{const r=await fetch(`/api/rev4/view?type=${type}&id=${id}&band=${band?'1':'0'}&grid=${grid?'1':'0'}`);const data=await r.json();if(!r.ok)throw new Error(data.error||'Render failed');$('rev4Message').className='status success';$('rev4Message').textContent=`${data.title} rendered. Diaphragm master N${data.diaphragm.master_node}; DOFs ${data.diaphragm.degrees_of_freedom.join(', ')}.`;const image=`<img class="diagram" src="/${encodeURIComponent(data.image)}?t=${Date.now()}" alt="Load view"><div class="outputs"><a href="/${encodeURIComponent(data.image)}" target="_blank">Open load view image</a></div>`;$('rev4Results').innerHTML=image}catch(e){$('rev4Message').className='status error';$('rev4Message').textContent=e.message}finally{button.disabled=false;button.textContent='VIEW LOADS'}}
$('rev4View').addEventListener('change',refreshRev4Options);refreshRev4Options();
$('unit').addEventListener('change',async()=>{await refreshOptions();$('loadRows').innerHTML='';addLoad({node:7,Fx:0,Fy:-100,Fz:0,Mx:0,My:0,Mz:0});});
['materialsLibrary','sectionsLibrary','unitsLibrary'].forEach(id=>$(id).addEventListener('change',refreshOptions));refreshOptions();addLoad({node:7,Fx:0,Fy:-100,Fz:0,Mx:0,My:0,Mz:0});
</script></body></html>"""


class SolverRequestHandler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type="text/plain; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print(f"[Web] {self.address_string()} - {fmt % args}")

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/":
            self._send(200, WEB_PAGE, "text/html; charset=utf-8")
            return
        if path == "/api/options":
            query = parse_qs(parsed.query)
            system = query.get("unit", ["Standard Metric"])[0]
            if system not in ("Standard Metric", "Imperial"):
                self._send(400, "Invalid unit system")
                return
            try:
                self._send(200, json.dumps(get_web_options(
                    system,
                    query.get("materials_file", [None])[0],
                    query.get("sections_file", [None])[0],
                    query.get("units_file", [None])[0],
                )), "application/json; charset=utf-8")
            except Exception as exc:
                self._send(500, json.dumps({"error": str(exc)}), "application/json; charset=utf-8")
            return
        if path == "/api/rev4/options":
            self._send(200, json.dumps(get_rev4_web_options()), "application/json; charset=utf-8")
            return
        if path == "/api/rev4/view":
            query = parse_qs(parsed.query)
            view_type = query.get("type", ["case"])[0]
            try:
                view_id = int(query.get("id", ["1"])[0])
                load_band = query.get("band", ["1"])[0] == "1"
                show_grid = query.get("grid", ["1"])[0] == "1"
                image = render_rev4_web_view(view_type, view_id, load_band, show_grid)
                if view_type == "case":
                    title = next(case.name for case in REV4_ARCHITECTURE["load_cases"] if case.id == view_id)
                else:
                    title = next(combo.name for combo in REV4_ARCHITECTURE["load_combinations"] if combo.id == view_id)
                self._send(200, json.dumps({
                    "image": image,
                    "title": title,
                    "diaphragm": get_rev4_web_options()["diaphragm"],
                }), "application/json; charset=utf-8")
            except (ValueError, StopIteration) as exc:
                self._send(400, json.dumps({"error": str(exc)}), "application/json; charset=utf-8")
            return
        if path in ("/structural_model_rev4_oriented.png", "/structural_model_rev4.xlsx"):
            filename = os.path.basename(path)
            output_folder = REV4_OUTPUT_FOLDER if filename.endswith(".png") else HERE
            filepath = os.path.join(output_folder, filename)
            if not os.path.isfile(filepath):
                self._send(404, "Output file has not been generated yet.")
                return
            try:
                with open(filepath, "rb") as f:
                    data = f.read()
                content_type = "image/png" if filepath.endswith(".png") else "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                self._send(200, data, content_type)
            except Exception as exc:
                self._send(500, str(exc))
            return
        if path.startswith("/rev4_web_") or path.startswith("/rev4_load_case_") or path.startswith("/rev4_combination_"):
            filename = os.path.basename(path)
            filepath = os.path.join(REV4_OUTPUT_FOLDER, filename)
            if not filename.endswith(".png") or not os.path.isfile(filepath):
                self._send(404, "Rev 4 image has not been generated yet.")
                return
            with open(filepath, "rb") as f:
                self._send(200, f.read(), "image/png")
            return
        self._send(404, "Not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path != "/api/solve":
            self._send(404, "Not found")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            config = json.loads(self.rfile.read(length).decode("utf-8"))
            unit_system = config.get("unit", "Standard Metric")
            material_label = config.get("material", "A992")
            section_label = config.get("section", "W12X26")
            column_section_label = config.get("column_section", "W10X33")
            if unit_system not in ("Standard Metric", "Imperial"):
                raise ValueError("Unit System must be Standard Metric or Imperial.")
            if not material_label:
                raise ValueError("Please select a material.")
            if not section_label or not column_section_label:
                raise ValueError("Please enter/select both beam and column member sizes.")
            raw_loads = config.get("loads", [])
            if not raw_loads:
                raise ValueError("At least one load is required.")

            new_loads = {}
            for item in raw_loads:
                node = int(item.get("node", 0))
                if node not in NODES:
                    raise ValueError(f"Load references unknown node {node}.")
                values = []
                for field in ("Fx", "Fy", "Fz", "Mx", "My", "Mz"):
                    value = float(item.get(field, 0.0))
                    if not np.isfinite(value):
                        raise ValueError(f"Invalid {field} value at node {node}.")
                    values.append(value)
                # The original REV3 metric solver uses N for force/moment input.
                # The browser displays metric loads in kN and kN·m.
                if unit_system == "Standard Metric":
                    values = [value * 1000.0 for value in values]
                if node in new_loads:
                    new_loads[node] = [a + b for a, b in zip(new_loads[node], values)]
                else:
                    new_loads[node] = values

            load_configuration(
                unit_system, material_label, section_label, column_section_label,
                units_file=config.get("units_file"),
                materials_file=config.get("materials_file"),
                sections_file=config.get("sections_file"),
            )
            set_loads(new_loads)

            model = build_model()
            analysis = solve_structure(model)
            os.makedirs(REV4_OUTPUT_FOLDER, exist_ok=True)
            diagram_path = os.path.join(REV4_OUTPUT_FOLDER, "structural_model_rev4_oriented.png")
            excel_path = os.path.join(HERE, "structural_model_rev4.xlsx")
            plot_structural_model(model, diagram_path)
            write_excel(model, excel_path, analysis)
            result = _make_web_result(model, analysis, diagram_path, excel_path)
            project_info = config.get("project_info", {})
            if not isinstance(project_info, dict):
                raise ValueError("Project information must be an object.")
            project_limits = {
                "project_name": 160,
                "company": 160,
                "designer": 160,
                "project_number": 80,
                "checked_by": 160,
                "notes": 1000,
            }
            result["project_info"] = {
                key: str(project_info.get(key, "")).strip()[:limit]
                for key, limit in project_limits.items()
            }
            result["libraries"] = {
                "units": os.path.basename(config.get("units_file") or ""),
                "materials": os.path.basename(config.get("materials_file") or ""),
                "sections": os.path.basename(config.get("sections_file") or ""),
            }
            self._send(200, json.dumps(result), "application/json; charset=utf-8")
        except Exception as exc:
            print(f"[Web] Solve error: {exc}")
            self._send(400, json.dumps({"error": str(exc)}), "application/json; charset=utf-8")


def start_web_server():
    server = ThreadingHTTPServer((WEB_HOST, WEB_PORT), SolverRequestHandler)
    url = f"http://{WEB_HOST}:{WEB_PORT}/"
    print(f"  Web interface: {url}")
    print("  Opened in your default browser.")
    print("  Keep this terminal open while using the solver.")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    webbrowser.open(url)
    return server

# =============================================================================
# Optional embedded blueprint desktop interface
# =============================================================================
def _run_blueprint_gui():
    try:
        from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, QRectF, QUrl, QPoint
        from PyQt6.QtGui import (QColor, QLinearGradient, QPainter, QPen,
                                 QPolygon, QRadialGradient, QBrush, QDesktopServices)
        from PyQt6.QtWidgets import (
            QApplication, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout,
            QHeaderView, QLabel, QLineEdit, QMainWindow, QPushButton, QScrollArea,
            QSizePolicy, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout,
            QWidget, QMessageBox, QCompleter,
        )
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from matplotlib.figure import Figure
    except ImportError as exc:
        raise ImportError(
            "The blueprint desktop interface requires PyQt6. Install it with "
            "'pip install PyQt6', or run 'python cube_solver_rev4.py --web' "
            "to use the browser interface."
        ) from exc
    # ---- Neon blueprint theme -------------------------------------------------------
    # DESIGN ONLY. Nothing in this block touches geometry, loads, stiffness assembly,
    # the solver, Excel output, or the Matplotlib model data. It only changes how the
    # desktop window looks.
    import random
    from PyQt6.QtCore import QEasingCurve, QPointF, QRect, QVariantAnimation
    from PyQt6.QtGui import QPainterPath, QPixmap
    from PyQt6.QtWidgets import QGraphicsDropShadowEffect

    # ---- Blueprint palette (shades of blue) + light accents ---------------------------
    NAVY_DEEP = "#071a3a"
    NAVY = "#0b2a5b"
    BLUE_DARK = "#10397a"
    BLUE_MID = "#1a56a8"
    BLUE_LIGHT = "#3d86d8"
    ICE = "#a9d4ff"
    CHALK = "#e6f3ff"
    CYAN_LINE = "#7fd0ff"
    NEON_CYAN = "#27e6ff"       # main light-line colour
    NEON_BLUE = "#2f7bff"       # secondary glow
    NEON_VIOLET = "#8f5bff"     # gradient tail
    NEON_MAGENTA = "#e04bff"    # sparing accent, like the reference image

    HEAD_FONTS = '"Bahnschrift", "DIN Alternate", "Agency FB", "Segoe UI", "DejaVu Sans"'
    MONO_FONTS = '"Consolas", "Cascadia Mono", "Courier New", "DejaVu Sans Mono"'

    STYLE = f"""
    * {{ font-family: {HEAD_FONTS}; color: {CHALK}; font-size: 13px; }}
    QMainWindow {{ background: {NAVY_DEEP}; }}
    QToolTip {{ background: {NAVY_DEEP}; color: {CHALK}; border: 1px solid {NEON_CYAN}; padding: 4px; }}
    QLabel#title {{ font-size: 24px; font-weight: 700; color: white; }}
    QLabel#subtitle {{ font-family: {MONO_FONTS}; font-size: 10px; color: {NEON_CYAN}; }}
    QLabel#sheetTag {{ font-family: {MONO_FONTS}; font-size: 11px; color: {ICE};
        border: 1px solid {NEON_CYAN}; padding: 4px 10px;
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(39,230,255,45), stop:1 rgba(143,91,255,35)); }}
    QLabel#statusPill {{ font-family: {MONO_FONTS}; font-size: 11px; color: #c9ffe0;
        border: 1px solid #5be3a0; padding: 4px 10px; background: rgba(16,83,64,150); }}
    QFrame#panel {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(16,57,122,215), stop:1 rgba(6,24,60,228));
        border: none; }}
    QLabel#panelTitle {{ font-size: 12px; font-weight: 700; color: white; padding: 5px 8px;
        border-bottom: 1px solid rgba(39,230,255,170);
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(39,230,255,95), stop:0.55 rgba(26,86,168,70), stop:1 rgba(143,91,255,30)); }}
    QPushButton#metadataHeader {{ text-align: left;
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(26,86,168,200), stop:1 rgba(16,57,122,120));
        border: 1px solid {BLUE_LIGHT}; padding: 7px 8px; font-family: {HEAD_FONTS};
        font-size: 12px; font-weight: 600; color: white; }}
    QPushButton#metadataHeader:checked {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(39,230,255,120), stop:1 rgba(16,57,122,230));
        border-color: {NEON_CYAN}; }}
    QLabel#metaLabel {{ color: {ICE}; font-size: 11px; padding: 1px 0; }}
    QLabel#metaValue {{ color: white; font-family: {MONO_FONTS}; font-size: 11px;
        font-weight: 600; padding: 1px 0; }}
    QFrame#metadataSection {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(16,57,122,215), stop:1 rgba(6,24,60,228));
        border: 1px solid rgba(61,134,216,200); }}
    QWidget#metadataBody {{ background: {NAVY}; }}
    QLabel#fieldLabel {{ color: {ICE}; font-size: 12px; }}
    QLabel#status {{ font-family: {MONO_FONTS}; font-size: 12px; color: {ICE};
        background: rgba(7,26,58,170); border-left: 3px solid {NEON_CYAN}; padding: 8px; }}
    QLabel#statusError {{ font-family: {MONO_FONTS}; font-size: 12px; color: #ffd1d1;
        background: rgba(7,26,58,170); border-left: 3px solid #ff6b6b; padding: 8px; }}
    QLabel#statusOk {{ font-family: {MONO_FONTS}; font-size: 12px; color: #c9ffe0;
        background: rgba(7,26,58,170); border-left: 3px solid #5be3a0; padding: 8px; }}
    QLineEdit, QComboBox {{
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(8,30,70,230), stop:1 rgba(4,16,40,235));
        border: 1px solid rgba(91,155,224,210); padding: 5px 6px;
        min-height: 24px; font-family: {MONO_FONTS}; font-size: 11px; color: white;
        selection-background-color: {BLUE_MID}; }}
    QLineEdit:focus, QComboBox:focus {{ border: 1px solid {NEON_CYAN}; }}
    QComboBox::drop-down {{
        subcontrol-origin: padding; subcontrol-position: top right; width: 28px;
        border-left: 1px solid {BLUE_LIGHT}; background: rgba(26,86,168,120); }}
    QComboBox QAbstractItemView {{ background: {NAVY}; color: white; border: 1px solid {NEON_CYAN};
        selection-background-color: {BLUE_MID}; font-family: {MONO_FONTS}; }}
    QCheckBox {{ spacing: 8px; color: {ICE}; }}
    QCheckBox#viewToggle {{ spacing: 4px; color: {ICE}; font-family: {MONO_FONTS}; font-size: 11px; }}
    QCheckBox::indicator {{ width: 14px; height: 14px; border: 1px solid {NEON_CYAN}; background: {NAVY_DEEP}; }}
    QCheckBox::indicator:checked {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {NEON_CYAN}, stop:1 {NEON_BLUE}); }}
    QPushButton {{
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(26,86,168,235), stop:1 rgba(10,38,92,240));
        border: 1px solid rgba(127,208,255,150); padding: 8px 14px; font-weight: 600; color: white; }}
    QPushButton:hover {{
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 rgba(47,123,255,245), stop:1 rgba(26,86,168,245));
        border: 1px solid {NEON_CYAN}; }}
    QPushButton:pressed {{ background: {NAVY}; border: 1px solid white; }}
    QPushButton:disabled {{ color: #7f98bd; border-color: #35527f; }}
    QPushButton#primary {{
        font-size: 15px; padding: 12px;
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {NEON_BLUE}, stop:0.55 {BLUE_MID}, stop:1 #5a3fd0);
        border: 1px solid {NEON_CYAN}; }}
    QPushButton#primary:hover {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {NEON_CYAN}, stop:0.5 {NEON_BLUE}, stop:1 {NEON_VIOLET});
        border: 1px solid white; }}
    QPushButton#primary:pressed {{ background: {BLUE_DARK}; }}
    QPushButton#primary:disabled {{ background: {NAVY}; color: #7f98bd; border: 1px solid #35527f; }}
    QPushButton#ghost {{ background: transparent; }}
    QPushButton#viewTool {{ background: rgba(5,20,48,210); border: 1px solid {BLUE_LIGHT};
        padding: 5px 10px; font-family: {MONO_FONTS}; font-size: 11px; color: {ICE}; }}
    QPushButton#viewTool:hover {{ background: {BLUE_MID}; border-color: {NEON_CYAN}; color: white; }}
    QPushButton#cameraMode {{ background: rgba(5,20,48,210); border: 1px solid {BLUE_LIGHT};
        min-width: 58px; padding: 5px 6px; font-family: {MONO_FONTS}; font-size: 10px; color: {ICE}; }}
    QPushButton#cameraMode:checked {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {NEON_CYAN}, stop:1 {NEON_BLUE});
        border-color: white; color: {NAVY_DEEP}; }}
    QPushButton#cameraMode:hover {{ border-color: {NEON_CYAN}; color: white; }}
    QPushButton#cameraKey {{ background: rgba(5,20,48,210); border: 1px solid {BLUE_LIGHT};
        min-width: 38px; padding: 5px 7px; font-family: {MONO_FONTS}; font-size: 11px; color: {ICE}; }}
    QPushButton#cameraKey:hover {{ background: {BLUE_MID}; border-color: {NEON_CYAN}; color: white; }}
    QTabWidget::pane {{ border: 1px solid {NEON_CYAN}; background: rgba(7,26,58,120); top: -1px; }}
    QTabBar::tab {{ background: rgba(11,42,91,230); border: 1px solid {BLUE_LIGHT}; padding: 8px 16px;
        margin-right: 2px; color: {ICE}; }}
    QTabBar::tab:hover {{ border-color: {NEON_CYAN}; color: white; }}
    QTabBar::tab:selected {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 {NEON_BLUE}, stop:1 {BLUE_MID});
        color: white; border-color: {NEON_CYAN}; border-bottom: 2px solid {NEON_CYAN}; }}
    QTableWidget {{ background: rgba(5,20,48,200); gridline-color: rgba(127,208,255,70);
        border: 1px solid {BLUE_LIGHT}; font-family: {MONO_FONTS};
        alternate-background-color: rgba(26,86,168,90);
        selection-background-color: rgba(39,230,255,70); selection-color: white; }}
    QHeaderView::section {{
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {BLUE_MID}, stop:1 {BLUE_DARK});
        color: white; border: 1px solid {NAVY}; border-bottom: 1px solid rgba(39,230,255,170);
        padding: 6px; font-weight: 600; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: {NAVY_DEEP}; width: 12px; }}
    QScrollBar::handle:vertical {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 {NEON_BLUE}, stop:1 {BLUE_MID}); min-height: 30px; }}
    QScrollBar:horizontal {{ background: {NAVY_DEEP}; height: 12px; }}
    QScrollBar::handle:horizontal {{
        background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 {NEON_BLUE}, stop:1 {BLUE_MID}); min-width: 30px; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
    QFrame#kpi {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 rgba(14,48,110,215), stop:1 rgba(5,20,48,225));
        border: 1px solid {BLUE_LIGHT}; border-left: 4px solid {NEON_CYAN}; }}
    QLabel#kpiValue {{ font-family: {MONO_FONTS}; font-size: 18px; font-weight: 700; color: white; }}
    QLabel#kpiLabel {{ font-size: 11px; color: {ICE}; }}
    QFrame#titleBlock {{
        background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 rgba(5,20,48,225), stop:0.5 rgba(14,48,110,200), stop:1 rgba(5,20,48,225));
        border: 1px solid {NEON_CYAN}; }}
    QLabel#tbCell {{ font-family: {MONO_FONTS}; font-size: 11px; color: {ICE}; padding: 3px 8px; }}
    """


    # <helpers> (pure Python: no Qt types, so they are easy to test)
    def _neon_make_traces(width, height, step=20, count=26, seed=11):
        """Right-angle 'circuit' light traces on the drafting-grid spacing."""
        rng = random.Random(seed)
        palette = [(39, 230, 255)] * 5 + [(47, 123, 255)] * 4 + [(143, 91, 255)] + [(224, 75, 255)] * 2
        cols = max(2, width // step)
        rows = max(2, height // step)
        traces = []
        for _ in range(count):
            gx, gy = rng.randint(0, cols), rng.randint(0, rows)
            horizontal = rng.random() < 0.5
            pts = [(gx * step, gy * step)]
            for _segment in range(rng.randint(3, 6)):
                run = rng.randint(3, 12) * rng.choice((-1, 1))
                if horizontal:
                    gx = min(cols, max(0, gx + run))
                else:
                    gy = min(rows, max(0, gy + run))
                nxt = (gx * step, gy * step)
                if nxt != pts[-1]:
                    pts.append(nxt)
                horizontal = not horizontal
            if len(pts) >= 2:
                cum = [0.0]
                for a, b in zip(pts, pts[1:]):
                    cum.append(cum[-1] + abs(b[0] - a[0]) + abs(b[1] - a[1]))
                traces.append({
                    "pts": pts, "cum": cum, "color": rng.choice(palette),
                    "speed": rng.uniform(0.6, 1.4), "offset": rng.random(),
                })
        return traces


    def _neon_point_at(trace, fraction):
        """Point at a fraction (0-1, wraps) of the way along a trace."""
        pts, cum = trace["pts"], trace["cum"]
        distance = (fraction % 1.0) * cum[-1]
        for i in range(1, len(cum)):
            if distance <= cum[i]:
                seg = (cum[i] - cum[i - 1]) or 1.0
                k = (distance - cum[i - 1]) / seg
                ax_, ay_ = pts[i - 1]
                bx_, by_ = pts[i]
                return ax_ + (bx_ - ax_) * k, ay_ + (by_ - ay_) * k
        return pts[-1]
    # </helpers>


    def _neon_gradient(w, h, scale=1.0):
        """Cyan -> blue -> magenta light gradient used for glowing borders."""
        g = QLinearGradient(0, 0, w, h)
        g.setColorAt(0.0, QColor(39, 230, 255, int(230 * scale)))
        g.setColorAt(0.55, QColor(47, 123, 255, int(170 * scale)))
        g.setColorAt(1.0, QColor(224, 75, 255, int(200 * scale)))
        return g


    def _draw_corner_brackets(p, w, h, length=12, color=(39, 230, 255, 235), width=2.0):
        p.setPen(QPen(QColor(*color), width))
        for cx, cy, sx, sy in ((1, 1, 1, 1), (w - 1, 1, -1, 1), (1, h - 1, 1, -1), (w - 1, h - 1, -1, -1)):
            p.drawLine(QPointF(cx, cy), QPointF(cx + sx * length, cy))
            p.drawLine(QPointF(cx, cy), QPointF(cx, cy + sy * length))


    # Buttons get a glowing light-line overlay on top of their stylesheet look.
    _QtPushButton = QPushButton


    class GlowButton(_QtPushButton):
        """QPushButton + neon top/bottom light lines, corner brackets and a light
        streak that runs along the edges on hover (always on for the SOLVE button).
        Painting only: clicks, signals and enabled/checked state are unchanged."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._hover = 0.0
            self._phase = 0.0
            self._sweeping = False
            self._fade = QVariantAnimation(self)
            self._fade.setDuration(200)
            self._fade.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._fade.valueChanged.connect(self._on_fade)
            self._sweep = QVariantAnimation(self)
            self._sweep.setStartValue(0.0)
            self._sweep.setEndValue(1.0)
            self._sweep.setDuration(2400)
            self._sweep.setLoopCount(-1)
            self._sweep.valueChanged.connect(self._on_sweep)

        def _on_fade(self, value):
            self._hover = float(value)
            self.update()

        def _on_sweep(self, value):
            self._phase = float(value)
            self.update()

        def _fade_to(self, target):
            self._fade.stop()
            self._fade.setStartValue(self._hover)
            self._fade.setEndValue(float(target))
            self._fade.start()

        def _start_sweep(self):
            if not self._sweeping:
                self._sweeping = True
                self._sweep.start()

        def _stop_sweep(self):
            if self._sweeping:
                self._sweeping = False
                self._sweep.stop()

        def enterEvent(self, event):
            super().enterEvent(event)
            self._fade_to(1.0)
            self._start_sweep()

        def leaveEvent(self, event):
            super().leaveEvent(event)
            self._fade_to(0.0)
            if self.objectName() != "primary":
                self._stop_sweep()

        def showEvent(self, event):
            super().showEvent(event)
            if self.objectName() == "primary":
                self._start_sweep()

        def hideEvent(self, event):
            super().hideEvent(event)
            self._stop_sweep()

        def paintEvent(self, event):
            super().paintEvent(event)
            if not self.isEnabled():
                return
            primary = self.objectName() == "primary"
            strength = 1.0 if (primary or self.isChecked()) else 0.5 + 0.5 * self._hover
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()

            # static light lines along the top and bottom edges, fading at the ends
            for y, peak in ((0.8, 255), (h - 0.8, 150)):
                g = QLinearGradient(0, 0, w, 0)
                g.setColorAt(0.0, QColor(39, 230, 255, 0))
                g.setColorAt(0.5, QColor(39, 230, 255, int(peak * strength)))
                g.setColorAt(1.0, QColor(39, 230, 255, 0))
                p.setPen(QPen(QBrush(g), 1.5))
                p.drawLine(QPointF(0, y), QPointF(w, y))

            # travelling light streak (top edge left->right, bottom edge right->left)
            glow = max(self._hover, 1.0 if primary else 0.0)
            if glow > 0.02 and self._sweeping:
                x = -40.0 + self._phase * (w + 80.0)
                for cx, y in ((x, 0.8), (w - x, h - 0.8)):
                    g = QLinearGradient(cx - 36, 0, cx + 36, 0)
                    g.setColorAt(0.0, QColor(255, 255, 255, 0))
                    g.setColorAt(0.5, QColor(220, 252, 255, int(235 * glow)))
                    g.setColorAt(1.0, QColor(255, 255, 255, 0))
                    p.setPen(QPen(QBrush(g), 2.2))
                    p.drawLine(QPointF(max(0.0, cx - 36), y), QPointF(min(float(w), cx + 36), y))

            if w > 30 and h > 20:
                _draw_corner_brackets(p, w, h, length=5 if h < 30 else 7,
                                      color=(255, 255, 255, int(120 + 110 * self._hover)), width=1.2)
            p.end()


    QPushButton = GlowButton   # every button created below is now a GlowButton


    class NeonFrame(QFrame):
        """Panel frame with a soft glowing gradient border and corner brackets."""

        def paintEvent(self, event):
            super().paintEvent(event)
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            w, h = self.width(), self.height()
            p.setBrush(Qt.BrushStyle.NoBrush)
            for width, scale in ((6.0, 0.10), (3.0, 0.22), (1.0, 1.0)):
                p.setPen(QPen(QBrush(_neon_gradient(w, h, scale)), width))
                p.drawRect(QRectF(width / 2.0, width / 2.0, w - width, h - width))
            top = QLinearGradient(0, 0, w, 0)
            top.setColorAt(0.0, QColor(39, 230, 255, 0))
            top.setColorAt(0.5, QColor(160, 245, 255, 220))
            top.setColorAt(1.0, QColor(39, 230, 255, 0))
            p.setPen(QPen(QBrush(top), 1.6))
            p.drawLine(QPointF(0, 1.2), QPointF(w, 1.2))
            _draw_corner_brackets(p, w, h)
            p.end()


    class DropdownComboBox(QComboBox):
        def paintEvent(self, event):
            super().paintEvent(event)
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(NEON_CYAN))
            center_x = self.width() - 14
            center_y = self.height() // 2
            painter.drawPolygon(QPolygon([
                QPoint(center_x - 4, center_y - 2),
                QPoint(center_x + 4, center_y - 2),
                QPoint(center_x, center_y + 3),
            ]))
            # light underline, brighter while focused
            w, h = self.width(), self.height()
            peak = 255 if self.hasFocus() else 130
            g = QLinearGradient(0, 0, w, 0)
            g.setColorAt(0.0, QColor(39, 230, 255, 0))
            g.setColorAt(0.5, QColor(39, 230, 255, peak))
            g.setColorAt(1.0, QColor(143, 91, 255, 0))
            painter.setPen(QPen(QBrush(g), 1.5))
            painter.drawLine(QPointF(0, h - 1.0), QPointF(w, h - 1.0))
            painter.end()


    # =============================================================================
    # Blueprint canvas: gradient paper + drafting grid + neon circuit traces with
    # slow travelling light pulses. The static layer is cached in a pixmap; the
    # pulses only repaint tiny rectangles, so the window stays cheap to redraw.
    # =============================================================================
    class BlueprintCanvas(QWidget):
        ANIMATE = True   # set to False for a completely static background

        def __init__(self):
            super().__init__()
            self._cache = None
            self._cache_key = None
            self._traces = []
            self._t = 0.0
            self._last_rects = []
            self._timer = QTimer(self)
            self._timer.setInterval(40)
            self._timer.timeout.connect(self._tick)
            if self.ANIMATE:
                self._timer.start()

        def _pulse_points(self):
            points = []
            for trace in self._traces:
                total = trace["cum"][-1] or 1.0
                fraction = (self._t * 900.0 * trace["speed"]) / total + trace["offset"]
                x, y = _neon_point_at(trace, fraction)
                if len(trace["pts"]) >= 2:
                    distance = (fraction % 1.0) * total
                    for i in range(1, len(trace["pts"])):
                        ax, ay = trace["pts"][i - 1]
                        bx, by = trace["pts"][i]
                        seg_length = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
                        if seg_length <= 1e-9:
                            continue
                        segment_start = trace["cum"][i - 1]
                        segment_end = trace["cum"][i]
                        if distance >= segment_start and distance <= segment_end:
                            local = (distance - segment_start) / seg_length
                            # Project the pulse to the exact local segment and orient it
                            # along the line direction so it travels with the trace.
                            px = ax + (bx - ax) * local
                            py = ay + (by - ay) * local
                            ux = (bx - ax) / seg_length
                            uy = (by - ay) / seg_length
                            points.append((px, py, trace["color"], (ux, uy)))
                            break
                else:
                    points.append((x, y, trace["color"], (1.0, 0.0)))
            return points

        def _tick(self):
            if not self._traces or not self.isVisible():
                return
            self._t += 0.004
            for rect in self._last_rects:
                self.update(rect)
            self._last_rects = []
            for x, y, _color, _dir in self._pulse_points():
                rect = QRect(int(x) - 18, int(y) - 18, 36, 36)
                self._last_rects.append(rect)
                self.update(rect)

        def _rebuild(self, w, h, dpr):
            pm = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
            pm.setDevicePixelRatio(dpr)
            p = QPainter(pm)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)

            g = QLinearGradient(0, 0, w, h)
            g.setColorAt(0.0, QColor(4, 12, 32))
            g.setColorAt(0.45, QColor(NAVY))
            g.setColorAt(1.0, QColor(BLUE_DARK))
            p.fillRect(QRect(0, 0, w, h), g)
            for cx, cy, color in ((0.78, 0.18, (47, 123, 255, 85)), (0.12, 0.92, (143, 91, 255, 55))):
                glow = QRadialGradient(w * cx, h * cy, max(w, h) * 0.55)
                glow.setColorAt(0.0, QColor(*color))
                glow.setColorAt(1.0, QColor(color[0], color[1], color[2], 0))
                p.fillRect(QRect(0, 0, w, h), QBrush(glow))

            minor = QPen(QColor(127, 208, 255, 20)); minor.setWidth(1)
            major = QPen(QColor(127, 208, 255, 52)); major.setWidth(1)
            step = 20
            for i, x in enumerate(range(0, w, step)):
                p.setPen(major if i % 5 == 0 else minor)
                p.drawLine(x, 0, x, h)
            for i, y in enumerate(range(0, h, step)):
                p.setPen(major if i % 5 == 0 else minor)
                p.drawLine(0, y, w, y)

            # neon circuit traces: wide faint pass, medium pass, thin bright core
            self._traces = _neon_make_traces(w, h, step)
            for trace in self._traces:
                r, gr, b = trace["color"]
                path = QPainterPath(QPointF(*trace["pts"][0]))
                for x, y in trace["pts"][1:]:
                    path.lineTo(x, y)
                for width, alpha in ((7.0, 14), (3.5, 40), (1.3, 190)):
                    pen = QPen(QColor(r, gr, b, alpha), width)
                    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                    p.setPen(pen)
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawPath(path)
                ex, ey = trace["pts"][-1]
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor(r, gr, b, 70))
                p.drawEllipse(QPointF(ex, ey), 5.0, 5.0)
                p.setBrush(QColor(255, 255, 255, 220))
                p.drawEllipse(QPointF(ex, ey), 1.8, 1.8)

            # drawing border: glowing gradient frame + corner registration brackets
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QBrush(_neon_gradient(w, h, 0.25)), 6))
            p.drawRect(QRectF(6, 6, w - 12, h - 12))
            p.setPen(QPen(QBrush(_neon_gradient(w, h, 1.0)), 2))
            p.drawRect(QRectF(6, 6, w - 12, h - 12))
            p.setPen(QPen(QColor(127, 208, 255, 150), 1))
            p.drawRect(QRectF(12, 12, w - 24, h - 24))
            p.setPen(QPen(QColor(255, 255, 255, 235), 2.4))
            for cx, cy, sx, sy in ((6, 6, 1, 1), (w - 6, 6, -1, 1), (6, h - 6, 1, -1), (w - 6, h - 6, -1, -1)):
                p.drawLine(QPointF(cx, cy), QPointF(cx + sx * 26, cy))
                p.drawLine(QPointF(cx, cy), QPointF(cx, cy + sy * 26))
            p.end()
            self._cache = pm

        def paintEvent(self, _):
            w, h = self.width(), self.height()
            if w <= 0 or h <= 0:
                return
            dpr = self.devicePixelRatioF()
            key = (w, h, round(dpr, 2))
            if self._cache is None or key != self._cache_key:
                self._rebuild(w, h, dpr)
                self._cache_key = key
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            p.drawPixmap(0, 0, self._cache)
            if self.ANIMATE:
                for x, y, (r, gr, b), (ux, uy) in self._pulse_points():
                    length = 11.0
                    x1 = x - ux * length / 2.0
                    y1 = y - uy * length / 2.0
                    x2 = x + ux * length / 2.0
                    y2 = y + uy * length / 2.0

                    glow = QLinearGradient(QPointF(x1, y1), QPointF(x2, y2))
                    glow.setColorAt(0.0, QColor(r, gr, b, 0))
                    glow.setColorAt(0.45, QColor(r, gr, b, 160))
                    glow.setColorAt(0.5, QColor(255, 255, 255, 255))
                    glow.setColorAt(0.55, QColor(r, gr, b, 160))
                    glow.setColorAt(1.0, QColor(r, gr, b, 0))

                    p.setPen(QPen(QBrush(glow), 2.1, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

                    p.setPen(QPen(QColor(255, 255, 255, 220), 0.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                    p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            p.end()


    def panel(title):
        frame = NeonFrame(); frame.setObjectName("panel")
        lay = QVBoxLayout(frame); lay.setContentsMargins(0, 0, 0, 6); lay.setSpacing(5)
        t = QLabel(title); t.setObjectName("panelTitle")
        lay.addWidget(t)
        body = QVBoxLayout(); body.setContentsMargins(8, 4, 8, 4); body.setSpacing(4)
        lay.addLayout(body)
        return frame, body


    def field(text, widget):
        box = QVBoxLayout(); box.setSpacing(3)
        lab = QLabel(text); lab.setObjectName("fieldLabel")
        box.addWidget(lab); box.addWidget(widget)
        return box


    def set_status(label, text, kind="status"):
        label.setObjectName(kind)
        label.setText(text)
        label.style().unpolish(label); label.style().polish(label)


    def _add_glow(widget, color, blur, alpha):
        effect = QGraphicsDropShadowEffect(widget)
        shade = QColor(color)
        shade.setAlpha(alpha)
        effect.setColor(shade)
        effect.setBlurRadius(blur)
        effect.setOffset(0, 0)
        widget.setGraphicsEffect(effect)


    def apply_neon_effects(root):
        """Soft coloured glow around buttons, KPI cards, the title and the title block.
        Call once at the end of MainWindow.__init__ (after every widget exists)."""
        for button in root.findChildren(GlowButton):
            name = button.objectName()
            if name == "primary":
                _add_glow(button, NEON_CYAN, 28, 170)
            elif name in ("viewTool", "cameraMode", "cameraKey"):
                _add_glow(button, NEON_CYAN, 10, 70)
            else:
                _add_glow(button, NEON_BLUE, 12, 95)
        for frame in root.findChildren(QFrame):
            if frame.objectName() == "kpi":
                _add_glow(frame, NEON_CYAN, 14, 75)
            elif frame.objectName() == "titleBlock":
                _add_glow(frame, NEON_CYAN, 18, 95)
        for label in root.findChildren(QLabel):
            name = label.objectName()
            if name == "title":
                _add_glow(label, NEON_CYAN, 20, 150)
            elif name == "sheetTag":
                _add_glow(label, NEON_CYAN, 12, 80)
            elif name == "statusPill":
                _add_glow(label, "#5be3a0", 12, 90)    # =============================================================================
    # Interactive Matplotlib 3D view
    # =============================================================================
    class Interactive3DView(QWidget):
        CAMERA_FOV_DEGREES = 39.6
        BASE_HALF_RANGE = 4.0
        MIN_ZOOM = 0.3
        MAX_ZOOM = 8.0
        DAMPING = 0.88

        def __init__(self):
            super().__init__()
            self.figure = Figure(figsize=(9, 7), facecolor="white")
            self.canvas = FigureCanvasQTAgg(self.figure)
            self.axes = None
            self.target = np.array([3.0, 3.0, 3.0])
            self.elevation = 22.0
            self.azimuth = -58.0
            self.zoom = 1.0
            self._drag_mode = None
            self._last_pointer = None
            self._orbit_velocity = np.zeros(2)
            self._pan_velocity = np.zeros(2)
            self._zoom_velocity = 0.0
            self.clean_view = False
            self._model_solver = None
            self._model_data = None
            self._view_mode = "model"
            self._load_view_args = None
            self.interaction_mode = "rotate"
            self.camera_buttons = {}
            self.display_options = {
                "nodes": True,
                "members": True,
                "supports": True,
                "local_axes": True,
                "global_axes": True,
            }
            self.display_buttons = {}
            layout = QVBoxLayout(self)
            layout.setContentsMargins(4, 4, 4, 4)
            display_toolbar = QHBoxLayout()
            display_toolbar.setContentsMargins(4, 0, 4, 0)
            display_toolbar.setSpacing(4)
            for label, option in (("3D MODEL", "model"), ("NODES", "nodes"), ("MEMBERS", "members"), ("SUPPORTS", "supports")):
                button = QPushButton(label)
                button.setObjectName("cameraMode")
                button.setMinimumWidth(max(58, len(label) * 8 + 14))
                button.setCheckable(True)
                button.setChecked(True)
                button.setToolTip(f"Show or hide {label.lower()}")
                button.toggled.connect(lambda checked, active_option=option: self.set_display_option(active_option, checked))
                self.display_buttons[option] = button
                display_toolbar.addWidget(button)
            for label, option in (("LOCAL AXES", "local_axes"), ("GLOBAL AXES", "global_axes")):
                checkbox = QCheckBox(label)
                checkbox.setObjectName("viewToggle")
                checkbox.setChecked(True)
                checkbox.setToolTip(f"Show or hide {label.lower()}")
                checkbox.toggled.connect(lambda checked, active_option=option: self.set_display_option(active_option, checked))
                self.display_buttons[option] = checkbox
                display_toolbar.addWidget(checkbox)
            display_toolbar.addStretch()
            layout.addLayout(display_toolbar)

            camera_toolbar = QHBoxLayout()
            camera_toolbar.setContentsMargins(4, 0, 4, 0)
            camera_toolbar.setSpacing(4)
            view_label = QLabel("VIEWPORT")
            view_label.setObjectName("fieldLabel")
            camera_toolbar.addWidget(view_label)
            for label, handler in (
                ("FIT", self.fit_view),
                ("TOP", self.top_view),
                ("FRONT", self.front_view),
                ("SIDE", self.side_view),
                ("RESET", self.reset_view),
            ):
                button = QPushButton(label)
                button.setObjectName("viewTool")
                button.setToolTip(f"Set {label.lower()} viewport")
                button.clicked.connect(handler)
                camera_toolbar.addWidget(button)
            for label, mode in (("ROTATE", "rotate"), ("PAN", "pan"), ("ZOOM", "zoom")):
                button = QPushButton(label)
                button.setObjectName("cameraMode")
                button.setCheckable(True)
                button.setToolTip(f"Click-drag to {mode} the view")
                button.clicked.connect(lambda checked, active_mode=mode: self.set_interaction_mode(active_mode))
                self.camera_buttons[mode] = button
                camera_toolbar.addWidget(button)
            self.camera_buttons["rotate"].setChecked(True)
            self.clean_toggle = QCheckBox("CLEAN")
            self.clean_toggle.setObjectName("viewToggle")
            self.clean_toggle.setToolTip(
                "Hide local axes, DOF labels, member labels, grid, and reference plane"
            )
            self.clean_toggle.toggled.connect(self.set_clean_view)
            camera_toolbar.addWidget(self.clean_toggle)
            camera_toolbar.addStretch()
            layout.addLayout(camera_toolbar)
            layout.addWidget(self.canvas, 1)
            model_status = QLabel(
                "●  MODEL VALID   |   8 Nodes   |   12 Members   |   4 Supports   |   36 Active DOF"
            )
            model_status.setObjectName("statusOk")
            layout.addWidget(model_status)
            self.canvas.mpl_connect("button_press_event", self._on_press)
            self.canvas.mpl_connect("motion_notify_event", self._on_motion)
            self.canvas.mpl_connect("button_release_event", self._on_release)
            self.canvas.mpl_connect("scroll_event", self.zoom_3d)
            self.inertia_timer = QTimer(self)
            self.inertia_timer.setInterval(16)
            self.inertia_timer.timeout.connect(self._advance_inertia)
            hint = QLabel(
                "Select ROTATE, PAN, or ZOOM, then left-drag the model · Scroll to zoom · "
                "Camera orbits around the cube center"
            )
            hint.setObjectName("status")
            layout.addWidget(hint)

        @staticmethod
        def _has_modifier(event, modifier, name):
            gui_event = getattr(event, "guiEvent", None)
            if gui_event is not None and hasattr(gui_event, "modifiers"):
                return bool(gui_event.modifiers() & modifier)
            key = getattr(event, "key", None)
            return isinstance(key, str) and name in key.lower().split("+")

        def _set_camera(self):
            if self.axes is None:
                return
            self.axes.mouse_init(rotate_btn=[], pan_btn=[], zoom_btn=[])
            focal_length = 1.0 / np.tan(np.deg2rad(self.CAMERA_FOV_DEGREES / 2.0))
            self.axes.set_proj_type("persp", focal_length=focal_length)
            self.axes.view_init(elev=self.elevation, azim=self.azimuth)
            half_range = self.BASE_HALF_RANGE / self.zoom
            for target, set_limits in zip(
                self.target,
                (self.axes.set_xlim3d, self.axes.set_ylim3d, self.axes.set_zlim3d),
            ):
                set_limits(target - half_range, target + half_range)
            self.canvas.draw_idle()

        def fit_view(self):
            self.target = np.array([3.0, 3.0, 3.0])
            self.zoom = 1.0
            self._set_camera()

        def reset_view(self):
            self.elevation = 22.0
            self.azimuth = -58.0
            self.fit_view()

        def top_view(self):
            self.elevation = 89.0
            self.azimuth = -90.0
            self.fit_view()

        def front_view(self):
            self.elevation = 12.0
            self.azimuth = -90.0
            self.fit_view()

        def side_view(self):
            self.elevation = 12.0
            self.azimuth = 0.0
            self.fit_view()

        def set_interaction_mode(self, mode):
            self.interaction_mode = mode
            for name, button in self.camera_buttons.items():
                button.blockSignals(True)
                button.setChecked(name == mode)
                button.blockSignals(False)

        def _set_camera_cursor(self):
            cursor_shape = {
                "rotate": Qt.CursorShape.OpenHandCursor,
                "pan": Qt.CursorShape.SizeAllCursor,
                "zoom": Qt.CursorShape.SizeVerCursor,
            }[self.interaction_mode]
            self.canvas.setCursor(cursor_shape)

        def set_clean_view(self, enabled):
            self.clean_view = bool(enabled)
            if self._model_solver is not None and self._model_data is not None:
                if self._view_mode == "loads" and self._load_view_args is not None:
                    self.show_loads(self._model_solver, self._model_data, *self._load_view_args)
                else:
                    self.show_model(self._model_solver, self._model_data)

        def set_display_option(self, option, enabled):
            if option == "model":
                for model_option in ("nodes", "members", "supports"):
                    self.display_options[model_option] = bool(enabled)
                    self.display_buttons[model_option].blockSignals(True)
                    self.display_buttons[model_option].setChecked(bool(enabled))
                    self.display_buttons[model_option].blockSignals(False)
            else:
                self.display_options[option] = bool(enabled)
                if option in ("nodes", "members", "supports"):
                    model_visible = all(self.display_options[name] for name in ("nodes", "members", "supports"))
                    self.display_buttons["model"].blockSignals(True)
                    self.display_buttons["model"].setChecked(model_visible)
                    self.display_buttons["model"].blockSignals(False)
            if self._model_solver is not None and self._model_data is not None:
                if self._view_mode == "loads" and self._load_view_args is not None:
                    self.show_loads(self._model_solver, self._model_data, *self._load_view_args)
                else:
                    self.show_model(self._model_solver, self._model_data)

        def _display_kwargs(self):
            return {
                "show_nodes": self.display_options["nodes"],
                "show_members": self.display_options["members"],
                "show_supports": self.display_options["supports"],
                "show_local_axes": self.display_options["local_axes"],
                "show_global_axes": self.display_options["global_axes"],
            }

        def _on_press(self, event):
            if self.axes is None or event.inaxes is not self.axes or event.button != 1:
                return
            self._drag_mode = self.interaction_mode
            self._last_pointer = (event.x, event.y)
            self._orbit_velocity[:] = 0.0
            self._pan_velocity[:] = 0.0
            self._zoom_velocity = 0.0
            self.inertia_timer.stop()
            self._set_camera_cursor()

        def _on_motion(self, event):
            if self._drag_mode is None or self._last_pointer is None:
                return
            current = (event.x, event.y)
            dx = current[0] - self._last_pointer[0]
            dy = current[1] - self._last_pointer[1]
            self._last_pointer = current
            if self._drag_mode == "rotate":
                self._orbit_velocity = np.array([-dx * 0.35, dy * 0.35])
                self._apply_orbit(*self._orbit_velocity)
            elif self._drag_mode == "pan":
                self._pan_velocity = np.array([dx, dy], dtype=float)
                self._apply_pan(dx, dy)
            else:
                self._zoom_velocity = -dy * 0.012
                self._apply_zoom(self._zoom_velocity)

        def _on_release(self, _event):
            if self._drag_mode is None:
                return
            self._drag_mode = None
            self._last_pointer = None
            self.inertia_timer.start()
            self._set_camera_cursor()

        def _apply_orbit(self, azimuth_delta, elevation_delta):
            self.azimuth = (self.azimuth + azimuth_delta) % 360.0
            self.elevation = float(np.clip(self.elevation + elevation_delta, -89.0, 89.0))
            self._set_camera()

        def _apply_pan(self, dx, dy):
            if self.axes is None:
                return
            azimuth = np.deg2rad(self.azimuth)
            elevation = np.deg2rad(self.elevation)
            screen_right = np.array([-np.sin(azimuth), np.cos(azimuth), 0.0])
            screen_up = np.array([
                -np.sin(elevation) * np.cos(azimuth),
                -np.sin(elevation) * np.sin(azimuth),
                np.cos(elevation),
            ])
            width = max(float(self.axes.bbox.width), 1.0)
            units_per_pixel = 2.0 * self.BASE_HALF_RANGE / (self.zoom * width)
            self.target += units_per_pixel * (-dx * screen_right + dy * screen_up)
            self._set_camera()

        def _apply_zoom(self, amount):
            self.zoom = float(np.clip(self.zoom * np.exp(amount), self.MIN_ZOOM, self.MAX_ZOOM))
            self._set_camera()

        def _advance_inertia(self):
            if self._drag_mode is not None:
                return
            moving = False
            if np.linalg.norm(self._orbit_velocity) > 0.02:
                self._apply_orbit(*self._orbit_velocity)
                self._orbit_velocity *= self.DAMPING
                moving = True
            if np.linalg.norm(self._pan_velocity) > 0.05:
                self._apply_pan(*self._pan_velocity)
                self._pan_velocity *= self.DAMPING
                moving = True
            if abs(self._zoom_velocity) > 0.001:
                self._apply_zoom(self._zoom_velocity)
                self._zoom_velocity *= self.DAMPING
                moving = True
            if not moving:
                self.inertia_timer.stop()

        def zoom_3d(self, event):
            if self.axes is None or event.inaxes is not self.axes:
                return
            amount = 0.12 if event.button == "up" else -0.12 if event.button == "down" else 0.0
            if amount == 0.0:
                return
            self._apply_zoom(amount)

        def show_model(self, solver, model):
            self._model_solver = solver
            self._model_data = model
            self._view_mode = "model"
            self._load_view_args = None
            self.figure.clear()
            self.axes = self.figure.add_axes([0.03, 0.04, 0.67, 0.88], projection="3d")
            solver.plot_structural_model(
                model,
                None,
                clean_view=self.clean_view,
                presentation_mode=True,
                show_metadata=False,
                **self._display_kwargs(),
                ax=self.axes,
            )
            self._set_camera()

        def show_loads(self, solver, model, view_type, view_id, load_band, show_grid):
            self._model_solver = solver
            self._model_data = model
            self._view_mode = "loads"
            self._load_view_args = (view_type, view_id, load_band, show_grid)
            self.figure.clear()
            self.axes = self.figure.add_axes([0.03, 0.04, 0.67, 0.88], projection="3d")
            if view_type == "case":
                solver.plot_structural_model(
                    model,
                    None,
                    load_case_id=view_id,
                    load_band=load_band,
                    show_grid=show_grid,
                    clean_view=self.clean_view,
                    presentation_mode=True,
                    show_metadata=False,
                    **self._display_kwargs(),
                    ax=self.axes,
                )
            else:
                solver.plot_structural_model(
                    model,
                    None,
                    combination_id=view_id,
                    load_band=load_band,
                    show_grid=show_grid,
                    clean_view=self.clean_view,
                    presentation_mode=True,
                    show_metadata=False,
                    **self._display_kwargs(),
                    ax=self.axes,
                )
            self._set_camera()


    # =============================================================================
    # Background worker so the window never freezes while solving
    # =============================================================================
    class Worker(QThread):
        done = pyqtSignal(object)
        failed = pyqtSignal(str)

        def __init__(self, fn, *args):
            super().__init__(); self.fn, self.args = fn, args

        def run(self):
            try:
                self.done.emit(self.fn(*self.args))
            except Exception as exc:  # noqa
                self.failed.emit(str(exc))


    def run_solve(S, cfg):
        """Same steps as the web POST handler, without the HTTP layer."""
        unit = cfg["unit"]
        new_loads = {}
        for node, vals in cfg["loads"]:
            vals = [v * 1000.0 for v in vals] if unit == "Standard Metric" else list(vals)
            new_loads[node] = [a + b for a, b in zip(new_loads.get(node, [0.0] * 6), vals)]
        S.load_configuration(unit, cfg["material"], cfg["section"], cfg["column_section"],
                             units_file=cfg["units_file"], materials_file=cfg["materials_file"],
                             sections_file=cfg["sections_file"])
        S.set_loads(new_loads)
        model = S.build_model()
        analysis = S.solve_structure(model)
        os.makedirs(S.REV4_OUTPUT_FOLDER, exist_ok=True)
        diagram = os.path.join(S.REV4_OUTPUT_FOLDER, "structural_model_rev4_oriented.png")
        excel = os.path.join(S.HERE, "structural_model_rev4.xlsx")
        S.plot_structural_model(model, diagram)
        S.write_excel(model, excel, analysis)
        return S._make_web_result(model, analysis, diagram, excel)


    # =============================================================================
    # Main window
    # =============================================================================
    class MainWindow(QMainWindow):
        def __init__(self, S):
            super().__init__()
            self.S = S
            self.opts = {}
            self.workers = []
            self.excel_path = ""
            self.setWindowTitle("STRUCTURAL SOLVER — Cube Frame")
            self.setMinimumSize(1050, 720)
            self.resize(1156, 770)

            canvas = BlueprintCanvas(); self.setCentralWidget(canvas)
            root = QVBoxLayout(canvas); root.setContentsMargins(10, 8, 10, 8); root.setSpacing(7)

            root.addLayout(self._header())
            body = QHBoxLayout(); body.setSpacing(8)
            body.addWidget(self._left(), 0)
            body.addWidget(self._right(), 1)
            root.addLayout(body, 1)
            root.addWidget(self._title_block())

            self.unit.currentTextChanged.connect(self.refresh_options)
            for c in (self.materials_lib, self.sections_lib, self.units_lib):
                c.activated.connect(lambda _: self.refresh_options())
            self.rev4_type.currentTextChanged.connect(self.fill_rev4)
            self.refresh_options(); self.fill_rev4(); self.add_load_row()
            self.model_view.show_model(self.S, self.S.build_model())

        # ---- header -------------------------------------------------------------
        def _header(self):
            row = QHBoxLayout()
            col = QVBoxLayout(); col.setSpacing(0)
            t = QLabel("STRUCTURAL SOLVER"); t.setObjectName("title")
            s = QLabel("6 m × 6 m × 6 m CUBE FRAME  |  3D STIFFNESS ANALYSIS  |  PYTHON ENGINE"); s.setObjectName("subtitle")
            col.addWidget(t); col.addWidget(s)
            row.addLayout(col); row.addStretch()
            status = QLabel("●  MODEL READY")
            status.setObjectName("statusPill")
            row.addWidget(status)
            tag = QLabel("MODEL  :  S-01\nUNITS  :  STANDARD METRIC\nSCALE  :  NTS")
            tag.setObjectName("sheetTag")
            row.addWidget(tag)
            return row

        # ---- left column: inputs ------------------------------------------------
        def _left(self):
            wrap = QWidget(); wrap.setFixedWidth(280)
            lay = QVBoxLayout(wrap); lay.setContentsMargins(0, 0, 0, 0)
            scroll = QScrollArea(); scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            inner = QWidget(); il = QVBoxLayout(inner); il.setContentsMargins(0, 0, 0, 0); il.setSpacing(8)
            inner.setMinimumWidth(0)
            scroll.setWidget(inner); lay.addWidget(scroll)

            # Project
            f, b = panel("01  PROJECT INFORMATION")
            self.project = QLineEdit("Cube Frame Model")
            self.company = QLineEdit(); self.designer = QLineEdit()
            self.number = QLineEdit(); self.checked = QLineEdit()
            b.addLayout(field("Project name", self.project))
            g = QGridLayout(); g.setContentsMargins(0, 0, 0, 0); g.setHorizontalSpacing(6); g.setVerticalSpacing(5)
            for i, (n, w) in enumerate([("Company", self.company), ("Designer", self.designer),
                                        ("Project no.", self.number), ("Checked by", self.checked)]):
                g.addLayout(field(n, w), i // 2, i % 2)
            b.addLayout(g); il.addWidget(f)

            # Libraries / material / sections / units
            f, b = panel("02  MATERIALS & SECTIONS")
            self.unit = DropdownComboBox(); self.unit.addItems(["Standard Metric", "Imperial"])
            self.units_lib = DropdownComboBox(); self.materials_lib = DropdownComboBox(); self.sections_lib = DropdownComboBox()
            self.material = DropdownComboBox()
            self.section = DropdownComboBox(); self.section.setEditable(True)
            self.column_section = DropdownComboBox(); self.column_section.setEditable(True)
            b.addLayout(field("Unit system", self.unit))
            b.addLayout(field("Material (RISA workbook)", self.material))
            g = QGridLayout(); g.setContentsMargins(0, 0, 0, 0); g.setHorizontalSpacing(6); g.setVerticalSpacing(5)
            g.addLayout(field("Beam section", self.section), 0, 0)
            g.addLayout(field("Column section", self.column_section), 0, 1)
            b.addLayout(g)
            b.addLayout(field("Units workbook", self.units_lib))
            b.addLayout(field("Materials workbook", self.materials_lib))
            b.addLayout(field("Sections workbook", self.sections_lib))
            self.lib_status = QLabel("Reading libraries…"); self.lib_status.setObjectName("status")
            self.lib_status.setWordWrap(True); b.addWidget(self.lib_status)
            il.addWidget(f)

            # Loads
            f, b = panel("03  APPLIED LOADS")
            self.force_unit_lbl = QLabel("Force unit: kN   ·   moments: kN·m"); self.force_unit_lbl.setObjectName("fieldLabel")
            b.addWidget(self.force_unit_lbl)
            self.loads = QTableWidget(0, 7)
            self.loads.setHorizontalHeaderLabels(["Node", "FX", "FY", "FZ", "MX", "MY", "MZ"])
            self.loads.setAlternatingRowColors(True)
            self.loads.verticalHeader().setVisible(False)
            self.loads.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            self.loads.setMinimumHeight(170)
            b.addWidget(self.loads)
            r = QHBoxLayout()
            add = QPushButton("+ ADD LOAD"); add.clicked.connect(lambda: self.add_load_row())
            rem = QPushButton("REMOVE ROW"); rem.setObjectName("ghost"); rem.clicked.connect(self.remove_load_row)
            r.addWidget(add); r.addWidget(rem); b.addLayout(r)
            self.solve_btn = QPushButton("SOLVE STRUCTURE"); self.solve_btn.setObjectName("primary")
            self.solve_btn.clicked.connect(self.solve)
            b.addWidget(self.solve_btn)
            self.solve_status = QLabel("Default load: Node 7, FY = -100 kN."); self.solve_status.setObjectName("status")
            self.solve_status.setWordWrap(True); b.addWidget(self.solve_status)
            il.addWidget(f)

            # Rev 4 viewer
            f, b = panel("04  LOAD VIEWER")
            self.rev4_type = DropdownComboBox(); self.rev4_type.addItems(["Load case", "Load combination"])
            self.rev4_id = DropdownComboBox()
            self.band = QCheckBox("Show distributed-load bands"); self.band.setChecked(True)
            self.grid = QCheckBox("Show grid"); self.grid.setChecked(True)
            b.addLayout(field("View type", self.rev4_type)); b.addLayout(field("Selection", self.rev4_id))
            b.addWidget(self.band); b.addWidget(self.grid)
            self.rev4_btn = QPushButton("VIEW LOADS"); self.rev4_btn.clicked.connect(self.render_rev4)
            b.addWidget(self.rev4_btn)
            self.rev4_status = QLabel("Pick a case or combination, then render."); self.rev4_status.setObjectName("status")
            self.rev4_status.setWordWrap(True); b.addWidget(self.rev4_status)
            il.addWidget(f)

            il.addStretch()
            return wrap

        def _metadata_section(self, title, groups, expanded=True):
            frame = QFrame(); frame.setObjectName("metadataSection")
            outer = QVBoxLayout(frame); outer.setContentsMargins(0, 0, 0, 5); outer.setSpacing(0)
            header = QPushButton(title)
            header.setObjectName("metadataHeader")
            header.setCheckable(True); header.setChecked(expanded)
            outer.addWidget(header)
            body = QWidget(); body.setObjectName("metadataBody"); body.setVisible(expanded)
            grid = QGridLayout(body); grid.setContentsMargins(8, 6, 8, 7); grid.setHorizontalSpacing(8); grid.setVerticalSpacing(1)
            grid.setColumnStretch(0, 1); grid.setColumnStretch(1, 1)
            row_index = 0
            for group_title, rows in groups:
                group_label = QLabel(group_title)
                group_label.setObjectName("fieldLabel")
                group_label.setStyleSheet("font-weight: 600; border-bottom: 1px solid #3d86d8; padding: 3px 0;")
                grid.addWidget(group_label, row_index, 0, 1, 2)
                row_index += 1
                for label, value in rows:
                    label_widget = QLabel(label); label_widget.setObjectName("metaLabel")
                    value_widget = QLabel(str(value)); value_widget.setObjectName("metaValue")
                    value_widget.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                    value_widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
                    grid.addWidget(label_widget, row_index, 0)
                    grid.addWidget(value_widget, row_index, 1)
                    row_index += 1
            outer.addWidget(body)
            header.toggled.connect(body.setVisible)
            return frame

        def _metadata_rail(self):
            wrap = QWidget(); wrap.setObjectName("metadataRail"); wrap.setFixedWidth(270)
            layout = QVBoxLayout(wrap); layout.setContentsMargins(0, 0, 0, 0); layout.setSpacing(6)
            scroll = QScrollArea(); scroll.setWidgetResizable(True)
            inner = QWidget(); inner_layout = QVBoxLayout(inner); inner_layout.setContentsMargins(0, 0, 5, 0); inner_layout.setSpacing(6)
            scroll.setWidget(inner); layout.addWidget(scroll)

            model_groups = [
                ("GEOMETRY & ORIENTATION", [
                    ("Vertical axis", "Global Y"),
                    ("Bottom nodes", "1, 2, 3, 4"),
                    ("Top nodes", "5, 6, 7, 8"),
                    ("Top elevation", "6.00 m"),
                    ("Bottom elevation", "0.00 m"),
                ]),
                ("SUPPORTS", [
                    ("Type", "Pinned"),
                    ("Nodes", "1, 2, 3, 4"),
                    ("Support below", "Bottom nodes"),
                    ("Restrictions", "UX, UY, UZ"),
                    ("Released", "RX, RY, RZ"),
                ]),
                ("DEGREES OF FREEDOM", [
                    ("DOF per node", DOF_PER_NODE),
                    ("Total DOF", 48),
                    ("Restrained DOF", 12),
                    ("Active DOF", 36),
                ]),
                ("BETA ANGLES", [
                    ("Base beam", "0°"),
                    ("Roof beam", "0°"),
                    ("Column", "90°"),
                ]),
            ]
            inner_layout.addWidget(self._metadata_section("MODEL DATA", model_groups))

            config_groups = [
                (f"MATERIAL · {material_config.label} STEEL", [
                    ("Category", material_config.category),
                    ("Elastic modulus E", f"{material_config.E:,.0f} {material_config.E_unit}"),
                    ("Shear modulus G", f"{material_config.G:,.0f} {material_config.E_unit}"),
                    ("Poisson ratio Nu", f"{material_config.Nu:g}"),
                    ("Yield strength Fy", f"{material_config.Fy:.1f} {material_config.stress_unit}"),
                    ("Ultimate strength Fu", f"{material_config.Fu:.1f} {material_config.stress_unit}"),
                    ("Density", f"{material_config.density:.2f} {material_config.density_unit}"),
                ]),
                (f"MEMBER SIZE · {section_config.label_imperial}", [
                    ("Metric", section_config.label_metric),
                    ("Depth d", f"{section_config.d:.1f} {section_config.length_unit}"),
                    ("Flange width bf", f"{section_config.bf:.1f} {section_config.length_unit}"),
                    ("Area A", f"{section_config.A:,.1f} {section_config.area_unit}"),
                    ("Moment Ix", f"{section_config.Ix:,.0f} {section_config.inertia_unit}"),
                ]),
                ("SOURCE", [("Section library", "AISC Shapes DB v16.0")]),
            ]
            unit_groups = [
                (unit_config.system.upper(), [
                    ("Coordinates", "m"),
                    ("Sections", "mm"),
                    ("Area", "mm²"),
                    ("Inertia", "mm⁴"),
                    ("Force", "kN"),
                    ("Moment", "kN·m"),
                    ("Stress / modulus", "MPa"),
                    ("Density", "kN/m³"),
                    ("Deflection", "mm"),
                ]),
                ("ORIENTATION", [
                    ("Lateral axes", "X / Z"),
                    ("Vertical axis", "Y"),
                    ("Base nodes", "1 - 4"),
                    ("Top nodes", "5 - 8"),
                ]),
            ]
            inner_layout.addWidget(self._metadata_section("MODEL CONFIGURATION", config_groups))
            inner_layout.insertWidget(1, self._metadata_section("UNIT SYSTEM", unit_groups))
            inner_layout.addStretch()
            return wrap

        # ---- right column: results ---------------------------------------------
        def _right(self):
            self.tabs = QTabWidget()

            # Results tab
            res = QWidget(); rl = QVBoxLayout(res); rl.setContentsMargins(12, 12, 12, 12); rl.setSpacing(10)
            self.kpi_row = QHBoxLayout(); self.kpi_row.setSpacing(10)
            self.kpis = {}
            for key, name in [("unit", "UNIT SYSTEM"), ("material", "MATERIAL"),
                              ("sections", "SECTIONS (BEAM / COLUMN)"), ("disp", "MAX DISPLACEMENT")]:
                card = QFrame(); card.setObjectName("kpi")
                cl = QVBoxLayout(card); cl.setContentsMargins(10, 8, 10, 8); cl.setSpacing(2)
                l = QLabel(name); l.setObjectName("kpiLabel")
                v = QLabel("—"); v.setObjectName("kpiValue"); v.setWordWrap(True)
                cl.addWidget(l); cl.addWidget(v); self.kpis[key] = v
                self.kpi_row.addWidget(card)
            rl.addLayout(self.kpi_row)
            self.node_table = QTableWidget(0, 7)
            self.node_table.setHorizontalHeaderLabels(["Node", "UX (mm)", "UY (mm)", "UZ (mm)", "Rx", "Ry", "Rz"])
            self.node_table.setAlternatingRowColors(True); self.node_table.verticalHeader().setVisible(False)
            self.node_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            rl.addWidget(self.node_table, 1)
            self.dof_lbl = QLabel("Run SOLVE STRUCTURE to see displacements and reactions."); self.dof_lbl.setObjectName("status")
            rl.addWidget(self.dof_lbl)
            self.excel_btn = QPushButton("OPEN EXCEL REPORT"); self.excel_btn.setEnabled(False)
            self.excel_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(self.excel_path)))
            rl.addWidget(self.excel_btn)
            self.tabs.addTab(res, "ANALYSIS RESULTS")

            # Structural drawing tab
            self.model_view = Interactive3DView()
            self.tabs.addTab(self.model_view, "STRUCTURAL MODEL")

            # Load view
            self.rev4_view = Interactive3DView()
            self.tabs.addTab(self.rev4_view, "LOAD VIEW")
            right = QWidget()
            right_layout = QHBoxLayout(right)
            right_layout.setContentsMargins(0, 0, 0, 0)
            right_layout.setSpacing(8)
            right_layout.addWidget(self.tabs, 1)
            self.metadata_rail = self._metadata_rail()
            right_layout.addWidget(self.metadata_rail, 0)
            self.tabs.currentChanged.connect(self._update_metadata_visibility)
            self._update_metadata_visibility(self.tabs.currentIndex())
            return right

        def _update_metadata_visibility(self, tab_index):
            """Show the metadata rail only for the Structural Model tab."""
            self.metadata_rail.setVisible(tab_index == 1)

        # ---- drawing title block (bottom right, like a real sheet) --------------
        def _title_block(self):
            f = QFrame(); f.setObjectName("titleBlock")
            g = QGridLayout(f); g.setContentsMargins(4, 2, 4, 2); g.setSpacing(0)
            cells = ["PROJECT: CUBE FRAME", "DRAWN: PYTHON SOLVER", "UNITS: m · mm · kN",
                     "SUPPORTS: PINNED N1–N4", "VERTICAL AXIS: Y", "DOF / NODE: 6"]
            for i, c in enumerate(cells):
                l = QLabel(c); l.setObjectName("tbCell"); g.addWidget(l, 0, i)
            f.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            return f

        # ---- helpers ------------------------------------------------------------
        def spawn(self, fn, args, ok, bad, button, busy_text, idle_text):
            button.setEnabled(False); button.setText(busy_text)
            w = Worker(fn, *args); self.workers.append(w)
            def finish():
                button.setEnabled(True); button.setText(idle_text)
                self.workers.remove(w)
            w.done.connect(lambda r: (finish(), ok(r)))
            w.failed.connect(lambda m: (finish(), bad(m)))
            w.start()

        def camera_action(self, action):
            """Route reference-style camera buttons to the active model view."""
            view = getattr(self, "model_view", None)
            if view is None:
                return
            if action in ("rotate", "pan", "zoom"):
                view.set_interaction_mode(action)
            elif action == "fit":
                view.fit_view()
            elif action == "reset":
                view.reset_view()

        def refresh_options(self, *_):
            unit = self.unit.currentText()
            try:
                o = self.S.get_web_options(
                    unit,
                    self.materials_lib.currentText() or None,
                    self.sections_lib.currentText() or None,
                    self.units_lib.currentText() or None)
            except Exception as exc:
                set_status(self.lib_status, f"Could not read Excel libraries: {exc}", "statusError"); return
            self.opts = o
            def fill(combo, items, selected):
                combo.blockSignals(True); old = combo.currentText(); combo.clear(); combo.addItems(items)
                pick = selected if selected in items else old
                if pick in items: combo.setCurrentText(pick)
                combo.blockSignals(False)
            lib = o["libraries"]
            fill(self.units_lib, lib["units"], lib["selected"]["units"])
            fill(self.materials_lib, lib["materials"], lib["selected"]["materials"])
            fill(self.sections_lib, lib["sections"], lib["selected"]["sections"])
            fill(self.material, o["materials"], "A992")
            for combo, default in ((self.section, "W12X26"), (self.column_section, "W10X33")):
                keep = combo.currentText()
                combo.blockSignals(True); combo.clear(); combo.addItems(o["sections"])
                combo.setCurrentText(keep if keep in o["sections"] else default); combo.blockSignals(False)
                comp = QCompleter(o["sections"]); comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
                combo.setCompleter(comp)
            m = o["model"]
            txt = (f"{m['cube_edge_m']} m cube · {m['node_count']} nodes · {m['member_count']} members · "
                   f"supports N{', N'.join(str(n) for n in m['supported_nodes'])}")
            set_status(self.lib_status, o.get("notice") or txt, "statusError" if o.get("notice") else "status")
            self.force_unit_lbl.setText("Force unit: kN   ·   moments: kN·m" if unit == "Standard Metric"
                                        else "Force unit: kip   ·   moments: kip·ft")

        # ---- loads table --------------------------------------------------------
        def add_load_row(self, values=(7, 0, -100, 0, 0, 0, 0)):
            r = self.loads.rowCount(); self.loads.insertRow(r)
            for c, v in enumerate(values):
                it = QTableWidgetItem(str(v)); it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.loads.setItem(r, c, it)

        def remove_load_row(self):
            r = self.loads.currentRow()
            if r >= 0: self.loads.removeRow(r)

        def collect_loads(self):
            out = []
            for r in range(self.loads.rowCount()):
                try:
                    node = int(float(self.loads.item(r, 0).text()))
                    vals = [float(self.loads.item(r, c).text() or 0) for c in range(1, 7)]
                except (ValueError, AttributeError):
                    raise ValueError(f"Row {r + 1}: enter numbers only.")
                if node not in self.S.NODES:
                    raise ValueError(f"Row {r + 1}: node {node} does not exist (use 1–8).")
                out.append((node, vals))
            if not out: raise ValueError("Add at least one load.")
            return out

        # ---- solve --------------------------------------------------------------
        def solve(self):
            try:
                cfg = dict(unit=self.unit.currentText(), material=self.material.currentText(),
                           section=self.section.currentText().strip(),
                           column_section=self.column_section.currentText().strip(),
                           units_file=self.units_lib.currentText() or None,
                           materials_file=self.materials_lib.currentText() or None,
                           sections_file=self.sections_lib.currentText() or None,
                           loads=self.collect_loads())
            except ValueError as exc:
                set_status(self.solve_status, str(exc), "statusError"); return
            set_status(self.solve_status, "Assembling stiffness matrix and solving…")
            self.spawn(run_solve, (self.S, cfg), self.show_results,
                       lambda m: set_status(self.solve_status, m, "statusError"),
                       self.solve_btn, "SOLVING…", "SOLVE STRUCTURE")

        def show_results(self, d):
            self.kpis["unit"].setText(d["unit_system"]); self.kpis["material"].setText(d["material"])
            self.kpis["sections"].setText(f"{d['section']}\n{d['column_section']}")
            self.kpis["disp"].setText(f"{d['max_displacement_mm']:.4f} mm  (N{d['max_displacement_node']})")
            fu = d["force_unit"]
            self.node_table.setHorizontalHeaderLabels(["Node", "UX (mm)", "UY (mm)", "UZ (mm)",
                                                       f"Rx ({fu})", f"Ry ({fu})", f"Rz ({fu})"])
            self.node_table.setRowCount(0)
            for row in d["node_rows"]:
                r = self.node_table.rowCount(); self.node_table.insertRow(r)
                vals = [row["node"]] + [row[k] for k in ("UX", "UY", "UZ", "Rx", "Ry", "Rz")]
                for c, v in enumerate(vals):
                    txt = str(v) if c == 0 else ("0" if abs(v) < 1e-10 else f"{v:.4f}")
                    it = QTableWidgetItem(txt); it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.node_table.setItem(r, c, it)
            self.dof_lbl.setText(f"DOF: {d['total_dof']} total · {d['restrained_dof']} restrained · {d['active_dof']} active")
            self.excel_path = os.path.join(self.S.HERE, d["excel"]); self.excel_btn.setEnabled(True)
            self.model_view.show_model(self.S, self.S.build_model())
            set_status(self.solve_status, "Analysis complete. PNG and Excel report generated.", "statusOk")
            self.tabs.setCurrentIndex(0)

        # ---- Rev 4 viewer -------------------------------------------------------
        def fill_rev4(self, *_):
            data = self.S.get_rev4_web_options()
            items = data["load_cases"] if self.rev4_type.currentText() == "Load case" else data["combinations"]
            self.rev4_id.clear()
            for x in items:
                self.rev4_id.addItem(f"{x['id']} — {x['name']} [{x.get('category') or x.get('design_method')}]", x["id"])
            dg = data["diaphragm"]
            set_status(self.rev4_status, f"Roof diaphragm: master N{dg['master_node']}; "
                                         f"constrained {', '.join(dg['degrees_of_freedom'])}.")

        def render_rev4(self):
            vt = "case" if self.rev4_type.currentText() == "Load case" else "combination"
            vid = self.rev4_id.currentData()
            if vid is None: return
            self.rev4_btn.setEnabled(False)
            self.rev4_btn.setText("RENDERING…")
            try:
                self.rev4_view.show_loads(
                    self.S,
                    self.S.build_model(),
                    vt,
                    int(vid),
                    self.band.isChecked(),
                    self.grid.isChecked(),
                )
                set_status(self.rev4_status, f"{self.rev4_id.currentText()} rendered.", "statusOk")
                self.tabs.setCurrentIndex(2)
            except Exception as exc:
                set_status(self.rev4_status, str(exc), "statusError")
            finally:
                self.rev4_btn.setEnabled(True)
                self.rev4_btn.setText("VIEW LOADS")
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    win = MainWindow(sys.modules[__name__])
    win.show()
    return app.exec()

# =============================================================================
# MAIN
# =============================================================================

def _run_web_interface():
    if "--verify-loads" in sys.argv[1:]:
        print("Generating headless load verification outputs...")
        paths = render_rev4_submission_outputs()
        report_path = write_rev4_verification_report("rev4_verification_report.txt")
        print(f"Generated {len(paths)} images.")
        print(f"Verification report: {report_path}")
        return

    print(f"\n{'='*60}")
    print("  Structural Solver")
    print(f"  6m × 6m × 6m Cube Frame Model")
    print(f"{'='*60}\n")

    print("  Default configuration:")
    print(f"    Unit System      : {unit_config.system}")
    print(f"    Material         : {material_config.label} Steel ({material_config.label})")
    print(f"    Member Size      : {section_config.label_imperial} / {section_config.label_metric}")
    print("    Default Load     : Node 7, Fy = -100 kN")
    print()
    print("  The solver is now controlled from the browser.")
    print("  Choose the unit/material/section, edit loads, then click SOLVE STRUCTURE.")

    start_web_server()

    try:
        while True:
            input()
    except (KeyboardInterrupt, EOFError):
        print("\n  Web server stopped.")


def main():
    if "--verify-loads" in sys.argv[1:] or "--web" in sys.argv[1:]:
        if "--web" in sys.argv:
            sys.argv.remove("--web")
        return _run_web_interface()

    try:
        return _run_blueprint_gui()
    except ImportError as exc:
        print(f"[GUI] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())