"""Inspect seeded FDD history in RAM and display an AHU time-series plot.

Run from a repo checkout after installing the tutorial dependencies:
    python tutorials/duckdb_sql_parity/explore_data.py
"""
from __future__ import annotations

import io

import duckdb
import matplotlib.pyplot as plt
import pandas as pd
from open_fdd.parity import generate


def main() -> None:
    ds = generate(seed=0, equips=2, days=3, profile="basic")
    df = pd.DataFrame(ds.to_engine_input()["history"])
    df["timestamp_utc"] = pd.to_datetime(df.pop("ts"), unit="ms", utc=True)
    df = df.sort_values(["equipment_id", "timestamp_utc"]).reset_index(drop=True)

    print("\n=== DataFrame.head() ===")
    print(df.head().to_string(index=False))
    print("\n=== DataFrame.info(memory_usage='deep') ===")
    buffer = io.StringIO()
    df.info(buf=buffer, memory_usage="deep", show_counts=True)
    print(buffer.getvalue())
    print("\n=== DataFrame.describe() (numeric values, SI units) ===")
    summary = df.describe(include="number").transpose()
    print(summary.to_string())
    print("\n=== Nulls per column (nonzero) ===")
    nulls = df.isna().sum()
    print(nulls[nulls > 0].to_string() if (nulls > 0).any() else "None")
    print("\n=== Equipment and timestamp coverage ===")
    print(df.groupby("equipment_id")["timestamp_utc"].agg(["min", "max", "count"]).to_string())

    # Demonstrate round-tripping the in-memory pandas frame through DuckDB.
    with duckdb.connect(":memory:") as conn:
        conn.register("fdd_df", df)
        result = conn.execute(
            "SELECT equipment_id, COUNT(*) AS samples "
            "FROM fdd_df GROUP BY equipment_id ORDER BY equipment_id"
        ).df()
    print("\n=== DuckDB SQL query over DataFrame ===")
    print(result.to_string(index=False))

    # Plot measurable series individually, without mixing Pa and degrees C on one axis.
    columns = [("sat", "Supply air temperature (°C)"),
               ("duct_static", "Duct static pressure (Pa)")]
    fig, axes = plt.subplots(len(columns), 1, figsize=(12, 7), sharex=True)
    for ax, (field, label) in zip(axes, columns):
        if field not in df.columns:
            raise SystemExit(f"Expected tutorial history column missing: {field}")
        for equipment, part in df.groupby("equipment_id", sort=True):
            ax.plot(part["timestamp_utc"], pd.to_numeric(part[field], errors="coerce"),
                    label=str(equipment), linewidth=1)
        ax.set_ylabel(label)
        ax.grid(True, alpha=0.25)
        ax.legend()
    axes[-1].set_xlabel("Timestamp (UTC)")
    fig.suptitle("Open-FDD seeded 5-minute AHU history (2 AHUs × 3 days)")
    fig.autofmt_xdate()
    fig.tight_layout()
    # Show only on an interactive desktop. Nothing is saved to disk.
    # CI sets MPLBACKEND=Agg so show() is a no-op there.
    plt.show()
    plt.close(fig)


if __name__ == "__main__":
    main()
