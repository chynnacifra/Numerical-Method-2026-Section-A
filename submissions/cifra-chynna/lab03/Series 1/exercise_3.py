"""Exercise 3: approximate e^x with a Taylor series."""

import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


X_VALUE = 1.0
MAX_TERMS = 10_000
SAMPLE_TERMS = [1, 2, 3, 5, 10, 20, 50, 100, 1_000, 10_000]


def partial_sums(x: float, max_terms: int) -> list[float]:
    """Build sums using term_n = term_(n-1) * x/n."""
    total = 0.0
    term = 1.0
    sums = []
    for n in range(max_terms):
        if n > 0:
            term *= x / n
        total += term
        sums.append(total)
    return sums


def main() -> None:
    output_dir = Path(__file__).resolve().parent / "results"
    output_dir.mkdir(exist_ok=True)

    all_sums = partial_sums(X_VALUE, MAX_TERMS)
    target = math.exp(X_VALUE)
    results = []
    for terms in SAMPLE_TERMS:
        value = all_sums[terms - 1]
        error = abs(value - target)
        correct_digits = max(0, int(-math.log10(error))) if error > 0 else 16
        results.append(
            {
                "terms": terms,
                "partial_sum": value,
                "absolute_error": error,
                "correct_decimal_digits": correct_digits,
                "terms_unit": "Taylor-series terms",
            }
        )

    print("Exercise 3: e^x = sum from n=0 to infinity of x^n/n!")
    print(f"x = {X_VALUE:g}; maximum terms = {MAX_TERMS}")
    print("terms              partial sum                 absolute error")
    for row in results:
        print(f"{row['terms']:<18} {row['partial_sum']:.12f}             {row['absolute_error']:.3e}")
    print(f"Reference value e^x = {target:.12f}")
    print("Interpretation: the partial sum rapidly approaches e, then floating-point precision limits further improvement.")

    labels = [str(row["terms"]) for row in results]
    values = [row["partial_sum"] for row in results]
    errors = [max(row["absolute_error"], 1e-16) for row in results]
    figure, axes = plt.subplots(1, 2, figsize=(15, 6))
    axes[0].bar(labels, values, color="#7b3fe4")
    axes[0].axhline(target, color="#df4d4d", linestyle="--", label=f"e = {target:.6f}")
    axes[0].set_title("Histogram of the partial sums")
    axes[0].set_xlabel("Number of terms N")
    axes[0].set_ylabel("Partial sum")
    axes[0].legend()

    axes[1].plot(SAMPLE_TERMS, errors, marker="o", color="#3065a8")
    axes[1].set_xscale("log")
    axes[1].set_yscale("log")
    axes[1].set_title("Error versus number of terms")
    axes[1].set_xlabel("Number of terms N (log scale)")
    axes[1].set_ylabel("|S_N - e^x| (log scale)")
    axes[1].grid(True, which="both", alpha=0.25)
    figure.suptitle("Exercise 3: e^x Taylor-series approximation")
    figure.tight_layout()
    figure.savefig(output_dir / "exercise_3.png", dpi=160)
    plt.close(figure)

    payload = {
        "exercise": 3,
        "formula": "sum(n=0 to infinity) x^n / n!",
        "inputs": {"x": X_VALUE, "maximum_terms": MAX_TERMS, "sample_terms": SAMPLE_TERMS},
        "variables": {"x": "input to e^x", "n": "Taylor-series term index"},
        "units": {"x": "dimensionless", "n": "Taylor-series terms", "partial_sum": "dimensionless"},
        "x": X_VALUE,
        "maximum_terms": MAX_TERMS,
        "reference_value": target,
        "final_answer": {"formula": "e^x", "x": X_VALUE, "value": target},
        "interpretation": "The Taylor partial sum approaches e^x quickly, then reaches floating-point precision limits.",
        "results": results,
        "graph": {
            "path": "exercise_3.png",
            "type": "bar chart and log-log line chart",
            "panels": ["partial sums", "absolute error versus number of terms"],
            "x": "number of terms N",
            "y": ["partial sum", "absolute error"],
        },
        "plot": "exercise_3.png",
    }
    (output_dir / "exercise_3.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()