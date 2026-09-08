"""Exercise 2: evaluate (a^h - 1) / h as h approaches zero."""

import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


BASES = [2.0, math.e, 3.0]
H_VALUES = [0.1, 0.01, 0.001, 0.0001, 0.00001, 0.000001, 0.0000001]


def difference_quotient(a: float, h: float) -> float:
    """Evaluate the reference difference quotient."""
    return math.expm1(h * math.log(a)) / h


def main() -> None:
    output_dir = Path(__file__).resolve().parent / "results"
    output_dir.mkdir(exist_ok=True)

    series = []
    for a in BASES:
        limit = math.log(a)
        values = []
        for h in H_VALUES:
            value = difference_quotient(a, h)
            values.append(
                {
                    "h": h,
                    "value": value,
                    "absolute_error": abs(value - limit),
                    "h_unit": "dimensionless step",
                }
            )
        series.append(
            {
                "base": a,
                "limit": limit,
                "limit_formula": "ln(a)",
                "values": values,
                "base_unit": "dimensionless",
            }
        )

    print("Exercise 2: (a^h - 1) / h")
    print("h                  a=2                 a=e                 a=3")
    for index, h in enumerate(H_VALUES):
        values = [item["values"][index]["value"] for item in series]
        print(f"{h:<18g} {values[0]:.8f}          {values[1]:.8f}          {values[2]:.8f}")
    print("Limits:", ", ".join(f"ln({a:g}) = {math.log(a):.8f}" for a in BASES))
    print("Tolerance: 1e-6")
    print("Interpretation: as h shrinks, each difference quotient settles at ln(a).")

    positions = list(range(len(H_VALUES)))
    width = 0.25
    colors = ["#2f67d8", "#1aa34a", "#df2727"]
    figure, axis = plt.subplots(figsize=(12, 7))
    for index, (item, color) in enumerate(zip(series, colors)):
        offsets = [position + (index - 1) * width for position in positions]
        axis.bar(offsets, [row["value"] for row in item["values"]], width=width, color=color, label=f"a={item['base']:g} (ln a={item['limit']:.4f})")
        axis.axhline(item["limit"], color=color, linestyle="--")
    axis.set_xticks(positions)
    axis.set_xticklabels([f"h = {h:g}" for h in H_VALUES])
    axis.set_ylabel("(a^h - 1) / h")
    axis.set_title("Exercise 2: (a^h - 1)/h settling to ln(a)")
    axis.legend()
    axis.grid(axis="y", alpha=0.25)
    figure.tight_layout()
    figure.savefig(output_dir / "exercise_2.png", dpi=160)
    plt.close(figure)

    payload = {
        "exercise": 2,
        "formula": "(a^h - 1) / h",
        "inputs": {"bases": BASES, "h_values": H_VALUES},
        "variables": {"a": "positive base", "h": "dimensionless step approaching zero"},
        "units": {"a": "dimensionless", "h": "dimensionless", "result": "dimensionless"},
        "tolerance": 1e-6,
        "final_answer": {"formula": "ln(a)", "limits": {str(a): math.log(a) for a in BASES}},
        "interpretation": "As h approaches zero, the difference quotient approaches ln(a).",
        "series": series,
        "graph": {
            "path": "exercise_2.png",
            "type": "grouped bar chart",
            "x": "h values",
            "y": "(a^h - 1) / h",
            "reference_lines": "ln(a) for each base",
        },
        "plot": "exercise_2.png",
    }
    (output_dir / "exercise_2.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()