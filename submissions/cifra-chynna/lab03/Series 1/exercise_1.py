"""Exercise 1: approximate e with (1 + 1/n)^n."""

import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


E_VALUE = math.e
FREQUENCIES = [
    ("yearly", 1),
    ("twice a year", 2),
    ("quarterly", 4),
    ("monthly", 12),
    ("weekly", 52),
    ("daily", 365),
    ("hourly", 365 * 24),
    ("every minute", 365 * 24 * 60),
    ("every second", 365 * 24 * 60 * 60),
    ("every millisecond", 365 * 24 * 60 * 60 * 1000),
    ("every microsecond", 365 * 24 * 60 * 60 * 1_000_000),
    ("every nanosecond", 365 * 24 * 60 * 60 * 1_000_000_000),
]


def approximation(n: int) -> float:
    """Evaluate the reference formula while retaining precision for large n."""
    return math.exp(n * math.log1p(1 / n))


def main() -> None:
    output_dir = Path(__file__).resolve().parent / "results"
    output_dir.mkdir(exist_ok=True)

    results = []
    for label, n in FREQUENCIES:
        value = approximation(n)
        results.append(
            {
                "frequency": label,
                "n": n,
                "value": value,
                "absolute_error": abs(value - E_VALUE),
                "error_reference": E_VALUE / (2 * n),
                "n_unit": "compounding periods per year",
            }
        )

    print("Exercise 1: (1 + 1/n)^n")
    print(f"Reference value e = {E_VALUE:.12f}")
    print("frequency             n                  (1 + 1/n)^n")
    for row in results:
        print(f"{row['frequency']:<20} {row['n']:>17} {row['value']:.12f}")
    print("Interpretation: increasing the number of compounding periods makes the value approach e.")

    labels = [row["frequency"] for row in results]
    values = [row["value"] for row in results]
    errors = [row["absolute_error"] for row in results]
    figure, axes = plt.subplots(1, 2, figsize=(16, 6))
    axes[0].bar(labels, values, color="#2f67d8")
    axes[0].axhline(E_VALUE, color="#df4d4d", linestyle="--", label=f"e = {E_VALUE:.6f}")
    axes[0].set_title("Value per compounding period")
    axes[0].set_ylabel("(1 + 1/n)^n")
    axes[0].tick_params(axis="x", rotation=45)
    axes[0].legend()

    axes[1].bar(labels, errors, color="#f39a0b")
    axes[1].set_yscale("log")
    axes[1].set_title("Absolute error")
    axes[1].set_ylabel("|(1 + 1/n)^n - e| (log scale)")
    axes[1].tick_params(axis="x", rotation=45)
    figure.suptitle("Exercise 1: Convergence of (1 + 1/n)^n to e")
    figure.tight_layout()
    figure.savefig(output_dir / "exercise_1.png", dpi=160)
    plt.close(figure)

    payload = {
        "exercise": 1,
        "formula": "(1 + 1/n)^n",
        "inputs": {"frequencies": [label for label, _ in FREQUENCIES]},
        "variables": {"n": "number of compounding periods per year"},
        "units": {"n": "compounding periods per year", "value": "dimensionless"},
        "reference_value": E_VALUE,
        "final_answer": {"name": "e", "value": E_VALUE},
        "interpretation": "Increasing n makes the compound-interest expression approach e.",
        "results": results,
        "graph": {
            "path": "exercise_1.png",
            "type": "bar charts",
            "panels": ["value per compounding period", "absolute error on a log scale"],
            "x": "compounding frequency",
            "y": ["(1 + 1/n)^n", "absolute error"],
        },
        "plot": "exercise_1.png",
    }
    (output_dir / "exercise_1.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()