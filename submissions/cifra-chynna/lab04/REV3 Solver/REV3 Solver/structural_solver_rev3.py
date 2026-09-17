"""
Structural Solver - Rev. 3
6m x 6m x 6m Cube Frame Model

REV3 changes from REV2/REV1:
  - Unit system loaded from units/Units_Imperial_Metric.xlsx
  - Material properties loaded from materials/RISA_Materials_Library_[Metric|Imperial].xlsx
  - Section properties loaded from sections/aisc-shapes-database-v160-2.xlsx
  - Default unit system: Standard Metric (project is for the Philippines)
  - Material: ASTM A36 Steel (A36 Gr.36)
  - Initial member size: W6X25 (Imperial designation) / W150x37 (metric equivalent)
  - Matplotlib visualization shows material, member size, and unit system
  - Excel output includes a "configuration" sheet

All REV1 geometry, DOF, local-axes, and Excel-output logic is preserved unchanged.
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
from dataclasses import dataclass, field
from typing import Dict, Optional

HERE = os.path.dirname(os.path.abspath(__file__))


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
# BLOCK A — UNIT LOADER
# =============================================================================

def load_units(units_folder: str, system: str = "Standard Metric") -> UnitConfig:
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
    xlsx_path = files[0]
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
    label: str = "A36 Gr.36",
    system: str = "Standard Metric",
    unit_config: Optional[UnitConfig] = None,
) -> MaterialConfig:
    """
    Locate the correct RISA Materials Library .xlsx for the given system,
    read the 'All Materials' flat table, and return a MaterialConfig for
    the requested label.
    """
    folder_path = os.path.join(HERE, materials_folder)

    # Pick the correct file
    if system == "Standard Metric":
        candidates = glob.glob(os.path.join(folder_path, "*Metric*.xlsx"))
    else:
        candidates = glob.glob(os.path.join(folder_path, "*Imperial*.xlsx"))

    if not candidates:
        # Fallback: any materials library file
        candidates = glob.glob(os.path.join(folder_path, "*Materials*Library*.xlsx"))
    if not candidates:
        candidates = glob.glob(os.path.join(folder_path, "*.xlsx"))
    if not candidates:
        raise FileNotFoundError(
            f"No materials .xlsx found in: {folder_path}"
        )

    # Prefer the more specific file
    candidates.sort()
    xlsx_path = candidates[0]
    print(f"  [Material] Loading from: {os.path.basename(xlsx_path)}")

    # 'All Materials' sheet has 3 header rows; row index 3 is the column header
    df = pd.read_excel(xlsx_path, sheet_name="All Materials", header=3)
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
    label: str = "W6X25",
    system: str = "Standard Metric",
    unit_config: Optional[UnitConfig] = None,
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

    xlsx_path = candidates[0]
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
    print(f"  [Section]  Imperial: {label}  →  Metric: {cfg.label_metric}")
    print(f"  [Section]  d={cfg.d:.1f} {cfg.length_unit}, "
          f"bf={cfg.bf:.1f} {cfg.length_unit}, "
          f"A={cfg.A:.1f} {cfg.area_unit}")
    return cfg


# =============================================================================
# CONFIGURATION
# =============================================================================

UNIT_SYSTEM     = "Standard Metric"
MATERIAL_LABEL  = "A36 Gr.36"
SECTION_LABEL   = "W6X25"

unit_config = None
material_config = None
section_config = None

def load_configuration(unit_system="Standard Metric",
                       material_label="A36 Gr.36",
                       section_label="W6X25"):
    """Load the same Excel-driven configuration used by REV3."""
    global UNIT_SYSTEM, MATERIAL_LABEL, SECTION_LABEL
    global unit_config, material_config, section_config

    UNIT_SYSTEM = unit_system
    MATERIAL_LABEL = material_label
    SECTION_LABEL = section_label

    print(f"\n{'='*60}")
    print(f"  Structural Solver — Rev. 3")
    print(f"  Loading configuration from Excel files …")
    print(f"{'='*60}")

    unit_config = load_units("units/", system=UNIT_SYSTEM)
    material_config = load_material(
        "materials/", label=MATERIAL_LABEL,
        system=UNIT_SYSTEM, unit_config=unit_config
    )
    section_config = load_section(
        "sections/", label=SECTION_LABEL,
        system=UNIT_SYSTEM, unit_config=unit_config
    )

    print(f"{'='*60}\n")


# Original REV3 defaults.
load_configuration()


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
    A = section_config.A
    Iy = section_config.Iy
    Iz = section_config.Ix
    J = section_config.J

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


def draw_local_axes(ax, ni, nj, mtype, beta_deg, scale=0.70):
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
            linewidth=1.1
        )


def plot_structural_model(model, output_path):
    """Generate the Rev. 3 cube with Nodes 1–4 explicitly at the bottom.

    The model uses global Y as the vertical direction. The plotting coordinate
    system is X-Z-Y so that the global Y axis is the displayed vertical axis.
    Nodes 1, 2, 3 and 4 are at Y=0 and therefore form the bottom support plane.
    Nodes 5, 6, 7 and 8 are at Y=6 m and form the top/roof plane.
    """
    sc = section_config
    mc = material_config
    uc = unit_config

    if uc.system == "Standard Metric":
        section_display = f"{sc.label_metric} [{sc.label_imperial}]"
    else:
        section_display = sc.label_imperial

    fig = plt.figure(figsize=(22, 11), facecolor="white")
    ax = fig.add_axes([0.03, 0.04, 0.58, 0.88], projection="3d")
    ax.set_facecolor("#f0f4f8")

    fig.suptitle(
        f"6 m × 6 m × 6 m Cube Frame — Structural Model, {REVISION}\n"
        f"Nodes 1–4 at bottom supports | Material: ASTM A36 Steel | "
        f"Member Size: {section_display} | Units: {uc.system}",
        fontsize=10.5, fontweight="bold", y=0.995,
    )

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

        ax.plot(
            [pi[0], pj[0]],
            [pi[1], pj[1]],
            [pi[2], pj[2]],
            color=color, linewidth=linewidth, zorder=3
        )

        draw_local_axes(
            ax, ni, nj, mtype, md["beta"], scale=0.62
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

        ax.scatter(
            [p[0]], [p[1]], [p[2]],
            color="red" if is_supported else "salmon",
            s=75 if is_supported else 60,
            zorder=8,
            depthshade=False
        )

        if is_supported:
            # Supports are drawn below Nodes 1–4, not beside or above them.
            draw_pinned_symbol(ax, p, size=0.22)

        ox, oy, oz = offsets[nid]
        ax.text(
            p[0] + ox, p[1] + oy, p[2] + oz,
            f"N{nid}\n{dof_label}",
            fontsize=6.8,
            ha="left",
            va="center",
            fontweight="bold",
            color="navy",
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

        ax.text(
            p[0], p[1], p[2],
            label,
            fontsize=6.2,
            color="#333333",
            ha="center",
            va="bottom",
        )

    # -------------------------------------------------------------------------
    # Global axes
    # -------------------------------------------------------------------------
    origin = np.array([0.0, 0.0, 0.0])
    ax.scatter(
        [origin[0]], [origin[1]], [origin[2]],
        marker="*", color="black", s=110, zorder=10, depthshade=False
    )

    global_axes = [
        ("Global X", np.array([1.6, 0.0, 0.0]), "red"),
        ("Global Y", np.array([0.0, 0.0, 1.6]), "blue"),
        ("Global Z", np.array([0.0, 1.6, 0.0]), "green"),
    ]

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
        Line2D([0], [0], color="red", lw=1.5, label="Local x axis"),
        Line2D([0], [0], color="limegreen", lw=1.5, label="Local y axis"),
        Line2D([0], [0], color="mediumpurple", lw=1.5, label="Local z axis"),
    ]

    ax.legend(
        handles=legend_elements,
        loc="upper left",
        fontsize=7,
        framealpha=0.9,
        bbox_to_anchor=(-0.02, 1.0),
    )

    # -------------------------------------------------------------------------
    # Right panel: model data
    # -------------------------------------------------------------------------
    info_ax = fig.add_axes([0.63, 0.38, 0.17, 0.58])
    info_ax.axis("off")

    info_lines = [
        ("MODEL DATA — REV. 3", True),
        ("", False),
        ("ORIENTATION", True),
        ("  Vertical axis   global Y", False),
        ("  Bottom nodes    1, 2, 3, 4", False),
        ("  Bottom elevation Y = 0 m", False),
        ("  Top nodes       5, 6, 7, 8", False),
        ("  Top elevation   Y = 6 m", False),
        ("", False),
        ("SUPPORTS", True),
        ("  Type            Pinned", False),
        ("  Nodes           1, 2, 3, 4", False),
        ("  Support below   bottom nodes", False),
        ("  Restrained      UX, UY, UZ", False),
        ("  Released        RX, RY, RZ", False),
        ("", False),
        ("DEGREES OF FREEDOM", True),
        (f"  DOF per node    {DOF_PER_NODE}", False),
        (f"  Total DOF       {model['total_dof']}", False),
        (f"  Restrained DOF  {model['restrained_dof']}", False),
        (f"  Active DOF      {model['active_dof']}", False),
        ("", False),
        ("BETA ANGLES", True),
        ("  Base Beam       0°", False),
        ("  Roof Beam       0°", False),
        ("  Column          90°", False),
    ]

    y_pos = 0.98
    for line, bold in info_lines:
        info_ax.text(
            0.04, y_pos, line,
            transform=info_ax.transAxes,
            fontsize=6.8,
            va="top",
            fontweight="bold" if bold else "normal",
            fontfamily="monospace",
        )
        y_pos -= 0.035

    rect1 = mpatches.FancyBboxPatch(
        (0, 0), 1, 1,
        boxstyle="round,pad=0.01",
        linewidth=1.2,
        edgecolor="#555",
        facecolor="#fafafa",
        transform=info_ax.transAxes,
        zorder=-1,
    )
    info_ax.add_patch(rect1)

    # -------------------------------------------------------------------------
    # Right panel: configuration
    # -------------------------------------------------------------------------
    cfg_ax = fig.add_axes([0.63, 0.04, 0.36, 0.32])
    cfg_ax.axis("off")

    Ix_fmt = f"{sc.Ix:,.0f}" if sc.Ix > 1e6 else f"{sc.Ix:.1f}"

    cfg_lines = [
        ("MODEL CONFIGURATION — REV. 3", True),
        ("", False),
        (f"  Unit System:    {uc.system}", False),
        ("", False),
        ("  Material:       ASTM A36 Steel", True),
        (f"    Label:        {mc.label}", False),
        (f"    Category:     {mc.category}", False),
        (f"    E:            {mc.E:,.0f} {mc.E_unit}", False),
        (f"    G:            {mc.G:,.0f} {mc.E_unit}", False),
        (f"    Nu:           {mc.Nu}", False),
        (f"    Fy:           {mc.Fy:.1f} {mc.stress_unit}", False),
        (f"    Fu:           {mc.Fu:.1f} {mc.stress_unit}", False),
        (f"    Density:      {mc.density:.2f} {mc.density_unit}", False),
        ("", False),
        (f"  Member Size:    {section_display}", True),
        (f"    Imperial:     {sc.label_imperial}", False),
        (f"    Metric:       {sc.label_metric}", False),
        (f"    d:            {sc.d:.1f} {sc.length_unit}", False),
        (f"    bf:           {sc.bf:.1f} {sc.length_unit}", False),
        (f"    A:            {sc.A:,.1f} {sc.area_unit}", False),
        (f"    Ix:           {Ix_fmt} {sc.inertia_unit}", False),
        ("  Source: AISC Shapes DB v16.0", False),
    ]

    y_pos = 0.97
    for line, bold in cfg_lines:
        cfg_ax.text(
            0.02, y_pos, line,
            transform=cfg_ax.transAxes,
            fontsize=6.8,
            va="top",
            fontweight="bold" if bold else "normal",
            fontfamily="monospace",
        )
        y_pos -= 0.040

    cfg_ax.plot(
        [0.005, 0.005], [0, 1],
        color="#1F3864",
        linewidth=5,
        transform=cfg_ax.transAxes,
        solid_capstyle="round",
        clip_on=False,
    )

    rect2 = mpatches.FancyBboxPatch(
        (0, 0), 1, 1,
        boxstyle="round,pad=0.01",
        linewidth=1.5,
        edgecolor="#1F3864",
        facecolor="#EDF2FB",
        transform=cfg_ax.transAxes,
        zorder=-1,
    )
    cfg_ax.add_patch(rect2)

    # -------------------------------------------------------------------------
    # Right panel: unit summary
    # -------------------------------------------------------------------------
    unit_ax = fig.add_axes([0.82, 0.38, 0.17, 0.58])
    unit_ax.axis("off")

    unit_lines = [
        ("UNIT SYSTEM", True),
        (f"  {uc.system}", False),
        ("", False),
        ("  Quantity         Unit", True),
        ("  Coordinates      m", False),
        ("  Sections         mm", False),
        ("  Area             mm²", False),
        ("  Inertia          mm⁴", False),
        ("  Force            kN", False),
        ("  Moment           kN·m", False),
        ("  Stress/Modulus   MPa", False),
        ("  Density          kN/m³", False),
        ("  Deflection       mm", False),
        ("", False),
        ("  Orientation:", True),
        ("  X/Z = lateral", False),
        ("  Y = vertical", False),
        ("  Nodes 1–4 = base", False),
        ("  Nodes 5–8 = top", False),
    ]

    y_pos = 0.98
    for line, bold in unit_lines:
        unit_ax.text(
            0.04, y_pos, line,
            transform=unit_ax.transAxes,
            fontsize=6.8,
            va="top",
            fontweight="bold" if bold else "normal",
            fontfamily="monospace",
        )
        y_pos -= 0.043

    rect3 = mpatches.FancyBboxPatch(
        (0, 0), 1, 1,
        boxstyle="round,pad=0.01",
        linewidth=1.2,
        edgecolor="#375623",
        facecolor="#EEF7EE",
        transform=unit_ax.transAxes,
        zorder=-1,
    )
    unit_ax.add_patch(rect3)

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
        ("── Material: ASTM A36 Steel ──",    ""),
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
    c = ws1.cell(row=1, column=1, value=f"Structural Model Summary — {REVISION}")
    c.font      = Font(bold=True, size=13, name='Arial', color='1F3864')
    c.alignment = Alignment(horizontal='center', vertical='center')
    c.fill      = PatternFill("solid", fgColor='D6E4F7')

    _apply_header(ws1, 2, 1, "Item",  bg='2E5FA3')
    _apply_header(ws1, 2, 2, "Value", bg='2E5FA3')

    if analysis is not None:
        rows = [
            ("Revision",                    REVISION),
            ("Unit System",                  uc.system),
            ("Material",                     f"ASTM A36 Steel ({mc.label})"),
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
            ("Material",                     f"ASTM A36 Steel ({mc.label})"),
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
    if system == "Standard Metric":
        candidates = glob.glob(os.path.join(folder_path, "**Metric**.xlsx"))
    else:
        candidates = glob.glob(os.path.join(folder_path, "**Imperial**.xlsx"))
    if not candidates:
        candidates = glob.glob(os.path.join(folder_path, "**Materials*Library**.xlsx"))
    if not candidates:
        candidates = glob.glob(os.path.join(folder_path, "*.xlsx"))
    candidates.sort()
    return candidates


def get_material_options(system):
    """Read material names from the same RISA Excel library used by the solver."""
    candidates = _material_candidates(system)
    if not candidates:
        return []
    df = pd.read_excel(candidates[0], sheet_name="All Materials", header=3)
    df = df[df["Label"].notna()].copy()
    return sorted({str(x).strip() for x in df["Label"].tolist()})


def get_section_options():
    """Read AISC section labels from the same Excel database used by REV3."""
    folder_path = os.path.join(HERE, "sections")
    candidates = glob.glob(os.path.join(folder_path, "aisc*.xlsx"))
    if not candidates:
        candidates = glob.glob(os.path.join(folder_path, "*.xlsx"))
    if not candidates:
        return []
    candidates.sort()
    df = pd.read_excel(candidates[0], sheet_name="Database v16.0", header=0)
    return sorted({str(x).strip() for x in df["AISC_Manual_Label"].dropna().tolist()})


_OPTIONS_CACHE = {}


def get_web_options(system):
    key = str(system)
    if key not in _OPTIONS_CACHE:
        _OPTIONS_CACHE[key] = {
            "materials": get_material_options(system),
            "sections": get_section_options(),
        }
    return _OPTIONS_CACHE[key]


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
        "material": f"ASTM A36 Steel ({material_config.label})",
        "section": (
            f"{section_config.label_metric} [{section_config.label_imperial}]"
            if unit_config.system == "Standard Metric"
            else section_config.label_imperial
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
<title>Structural Solver — Rev. 3</title>
<style>
:root{--bg:#0b1220;--panel:#121b2e;--panel2:#1a2540;--line:#2a3654;--text:#e2e8f0;--muted:#94a3b8;--accent:#38bdf8;--good:#22c55e;--danger:#ef4444}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:14px}
header{padding:18px 24px;border-bottom:1px solid var(--line);background:var(--panel);display:flex;align-items:center;gap:16px}h1{font-size:21px;margin:0}.sub{color:var(--muted);font-size:12px;margin-top:3px}.grow{flex:1}
main{max-width:1450px;margin:auto;padding:22px}.layout{display:grid;grid-template-columns:360px 1fr;gap:22px}.panel{background:var(--panel);border:1px solid var(--line);padding:18px;margin-bottom:18px}.panel h2{font-size:14px;margin:0 0 15px;text-transform:uppercase;letter-spacing:.08em;color:var(--accent)}
label{display:block;color:var(--muted);font-size:12px;margin:12px 0 6px}select,input{width:100%;padding:9px 10px;border:1px solid var(--line);background:#0f172a;color:var(--text);border-radius:5px}input:focus,select:focus{outline:1px solid var(--accent)}
button{padding:10px 15px;border:1px solid var(--line);border-radius:5px;background:var(--panel2);color:var(--text);cursor:pointer;font-weight:600}button:hover{border-color:var(--accent)}button.primary{background:var(--accent);color:#06202f;border-color:var(--accent);width:100%;margin-top:16px}.danger{color:#fca5a5}
.load-scroll{overflow-x:auto;padding-bottom:4px}.load-labels,.row{display:grid;grid-template-columns:70px repeat(6,minmax(58px,1fr)) 34px;gap:6px;min-width:500px}.load-labels{margin-bottom:4px;color:var(--muted);font-size:10px;font-weight:700;text-align:center;letter-spacing:.05em}.load-labels span:first-child{text-align:left}.row{align-items:end;margin-bottom:8px}.row input,.row select{min-width:0;padding:7px 6px;font-size:12px;text-align:center}.remove{padding:7px 0}
.status{padding:10px;border-left:3px solid var(--accent);background:#0f172a;color:var(--muted);margin-top:12px}.error{border-left-color:var(--danger);color:#fecaca}.success{border-left-color:var(--good);color:#bbf7d0}
.results{min-height:300px}.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:18px}.kpi{border-left:3px solid var(--accent);padding:12px;background:#0f172a}.kpi .v{font-size:19px;font-weight:700;margin-top:5px}.kpi .l{font-size:11px;color:var(--muted)}
table{width:100%;border-collapse:collapse;font-size:12px}th,td{border-bottom:1px solid var(--line);padding:8px;text-align:right}th{color:var(--muted);font-weight:600}th:first-child,td:first-child{text-align:left}.table-wrap{overflow:auto;max-height:430px}.outputs{display:flex;gap:10px;flex-wrap:wrap;margin-top:15px}.outputs a{color:var(--accent);text-decoration:none;border:1px solid var(--line);padding:9px 12px;background:#0f172a}.diagram{width:100%;display:block;margin-top:15px;border:1px solid var(--line);background:white}
@media(max-width:900px){.layout{grid-template-columns:1fr}.kpis{grid-template-columns:1fr 1fr}.row{min-width:760px}.load-scroll{overflow:auto}}
</style>
</head>
<body>
<header><div><h1>Structural Solver — Rev. 3</h1><div class="sub">6 m × 6 m × 6 m Cube Frame · Excel-driven configuration · Python solver</div></div><div class="grow"></div><div class="sub">Local browser interface</div></header>
<main><div class="layout"><section>
<div class="panel"><h2>Model Configuration</h2>
<label for="unit">Unit System</label><select id="unit"><option>Standard Metric</option><option>Imperial</option></select>
<label for="material">Material — from RISA Excel library</label><select id="material"></select>
<label for="section">Member Size — from AISC Excel database</label><input id="section" list="sectionList" value="W6X25"><datalist id="sectionList"></datalist>
<div class="status" id="source">Materials and sections are loaded from the Excel files in the REV3 folder.</div>
</div>
<div class="panel"><h2>Applied Loads</h2><div class="sub">Force unit: <span id="forceUnit">kN</span>. Enter one or more loads. Moments use the corresponding force-length unit.</div>
<div class="load-scroll"><div class="load-labels"><span>NODE</span><span>FX</span><span>FY</span><span>FZ</span><span>MX</span><span>MY</span><span>MZ</span><span></span></div><div id="loadRows"></div></div>
<button type="button" onclick="addLoad()">+ Add Load</button><button type="button" class="primary" id="solve" onclick="solve()">SOLVE STRUCTURE</button>
<div class="status" id="message">Default load: Node 7, Fy = -100 kN.</div></div>
</section><section class="results"><div class="panel"><h2>Analysis Results</h2><div id="results"><div class="status">Change the inputs if needed, then click <b>SOLVE STRUCTURE</b>.</div></div></div></section></div></main>
<script>
let options={materials:[],sections:[]};const $=id=>document.getElementById(id);
function fmt(v){if(v===null||v===undefined)return '—';if(Math.abs(v)<1e-10)return '0';return Number(v).toFixed(4)}
function forceUnit(){return $('unit').value==='Standard Metric'?'kN':'kip'}
function refreshUnitLabel(){$('forceUnit').textContent=forceUnit()}
function materialSelect(){const el=$('material');const old=el.value;el.innerHTML='';options.materials.forEach(x=>{const o=document.createElement('option');o.value=x;o.textContent=x;el.appendChild(o)});if(options.materials.includes(old))el.value=old;else if(options.materials.includes('A36 Gr.36'))el.value='A36 Gr.36'}
function sectionList(){const dl=$('sectionList');dl.innerHTML='';options.sections.forEach(x=>{const o=document.createElement('option');o.value=x;dl.appendChild(o)})}
async function refreshOptions(){const unit=$('unit').value;try{const r=await fetch('/api/options?unit='+encodeURIComponent(unit));if(!r.ok)throw new Error(await r.text());options=await r.json();materialSelect();sectionList();$('source').textContent='Materials and sections are read from the Excel files in the REV3 folder.';refreshUnitLabel()}catch(e){$('source').textContent='Could not load Excel options: '+e.message;$('source').className='status error'}}
function makeInput(field,value){const i=document.createElement('input');i.type='number';i.step='any';i.dataset.field=field;i.value=value;return i}
function addLoad(data){const wrap=document.createElement('div');wrap.className='row load-row';const node=document.createElement('select');node.dataset.field='node';for(let n=1;n<=8;n++){const o=document.createElement('option');o.value=n;o.textContent=n;node.appendChild(o)}const values=data||{node:7,Fx:0,Fy:-100,Fz:0,Mx:0,My:0,Mz:0};node.value=values.node;wrap.appendChild(node);['Fx','Fy','Fz','Mx','My','Mz'].forEach(f=>wrap.appendChild(makeInput(f,values[f]??0)));const b=document.createElement('button');b.type='button';b.className='remove danger';b.textContent='×';b.onclick=()=>wrap.remove();wrap.appendChild(b);$('loadRows').appendChild(wrap)}
function collect(){const loads=[];document.querySelectorAll('.load-row').forEach(row=>{const obj={node:Number(row.querySelector('[data-field="node"]').value)};row.querySelectorAll('input').forEach(i=>obj[i.dataset.field]=Number(i.value)||0);loads.push(obj)});return {unit:$('unit').value,material:$('material').value,section:$('section').value,loads}}
async function solve(){const btn=$('solve');btn.disabled=true;btn.textContent='SOLVING…';$('message').className='status';$('message').textContent='Running the existing REV3 Python solver and generating the existing PNG/Excel deliverables…';try{const r=await fetch('/api/solve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(collect())});const data=await r.json();if(!r.ok)throw new Error(data.error||'Solve failed');render(data);$('message').className='status success';$('message').textContent='Analysis completed. The existing structural PNG and Excel report were generated.'}catch(e){$('message').className='status error';$('message').textContent=e.message}finally{btn.disabled=false;btn.textContent='SOLVE STRUCTURE'}}
function render(d){let html=`<div class="kpis"><div class="kpi"><div class="l">Unit System</div><div class="v">${d.unit_system}</div></div><div class="kpi"><div class="l">Material</div><div class="v" style="font-size:14px">${d.material}</div></div><div class="kpi"><div class="l">Member Size</div><div class="v" style="font-size:14px">${d.section}</div></div><div class="kpi"><div class="l">Maximum Displacement</div><div class="v">${fmt(d.max_displacement_mm)} mm</div><div class="l">Node ${d.max_displacement_node}</div></div></div>`;html+=`<h3>Applied Loads</h3><div class="table-wrap"><table><thead><tr><th>Node</th><th>Fx (${d.force_unit})</th><th>Fy (${d.force_unit})</th><th>Fz (${d.force_unit})</th><th>Mx</th><th>My</th><th>Mz</th></tr></thead><tbody>`;d.load_rows.forEach(x=>html+=`<tr><td>${x.node}</td><td>${fmt(x.Fx)}</td><td>${fmt(x.Fy)}</td><td>${fmt(x.Fz)}</td><td>${fmt(x.Mx)}</td><td>${fmt(x.My)}</td><td>${fmt(x.Mz)}</td></tr>`);html+='</tbody></table></div>';html+=`<h3>Node Results</h3><div class="table-wrap"><table><thead><tr><th>Node</th><th>UX (mm)</th><th>UY (mm)</th><th>UZ (mm)</th><th>Rx (${d.force_unit})</th><th>Ry (${d.force_unit})</th><th>Rz (${d.force_unit})</th></tr></thead><tbody>`;d.node_rows.forEach(x=>html+=`<tr><td>${x.node}</td><td>${fmt(x.UX)}</td><td>${fmt(x.UY)}</td><td>${fmt(x.UZ)}</td><td>${fmt(x.Rx)}</td><td>${fmt(x.Ry)}</td><td>${fmt(x.Rz)}</td></tr>`);html+='</tbody></table></div>';html+=`<div class="status">DOF: ${d.total_dof} total · ${d.restrained_dof} restrained · ${d.active_dof} active</div><div class="outputs"><a href="/${encodeURIComponent(d.excel)}" download>Open / Download Excel Report</a><a href="/${encodeURIComponent(d.diagram)}" target="_blank">Open Structural PNG</a></div><img class="diagram" src="/${encodeURIComponent(d.diagram)}?t=${Date.now()}" alt="Structural model">`;$('results').innerHTML=html}
$('unit').addEventListener('change',async()=>{await refreshOptions();$('loadRows').innerHTML='';addLoad({node:7,Fx:0,Fy:-100,Fz:0,Mx:0,My:0,Mz:0});});refreshOptions();addLoad({node:7,Fx:0,Fy:-100,Fz:0,Mx:0,My:0,Mz:0});
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
                self._send(200, json.dumps(get_web_options(system)), "application/json; charset=utf-8")
            except Exception as exc:
                self._send(500, json.dumps({"error": str(exc)}), "application/json; charset=utf-8")
            return
        if path in ("/structural_model_rev3_oriented.png", "/structural_model_rev3.xlsx"):
            filename = os.path.basename(path)
            filepath = os.path.join(HERE, filename)
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
            material_label = config.get("material", "A36 Gr.36")
            section_label = config.get("section", "W6X25")
            if unit_system not in ("Standard Metric", "Imperial"):
                raise ValueError("Unit System must be Standard Metric or Imperial.")
            if not material_label:
                raise ValueError("Please select a material.")
            if not section_label:
                raise ValueError("Please enter/select a member size.")
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

            load_configuration(unit_system, material_label, section_label)
            set_loads(new_loads)

            model = build_model()
            analysis = solve_structure(model)
            diagram_path = os.path.join(HERE, "structural_model_rev3_oriented.png")
            excel_path = os.path.join(HERE, "structural_model_rev3.xlsx")
            plot_structural_model(model, diagram_path)
            write_excel(model, excel_path, analysis)
            result = _make_web_result(model, analysis, diagram_path, excel_path)
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
# MAIN
# =============================================================================

def main():
    print(f"\n{'='*60}")
    print(f"  Structural Solver — {REVISION}")
    print(f"  6m × 6m × 6m Cube Frame Model")
    print(f"{'='*60}\n")

    print("  Default configuration:")
    print(f"    Unit System      : {unit_config.system}")
    print(f"    Material         : ASTM A36 Steel ({material_config.label})")
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


if __name__ == "__main__":
    main()
