"""Plot median query latency comparison from results/benchmark.csv."""

import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path


def plot_benchmark():
    file_path = Path("results/benchmark.csv")
    if not file_path.exists():
        print(f"File {file_path} not found. Please run scripts/benchmark.py first.")
        return

    # Load benchmark measurements
    df = pd.read_csv(file_path)

    # Compute median latency per database
    summary = df.groupby('database')['latency_ms'].median().reset_index()

    # Initialize bar chart
    plt.figure(figsize=(8, 6))
    bars = plt.bar(summary['database'], summary['latency_ms'], color=['#3498db', '#e74c3c'])

    # Configure labels and title
    plt.title(
        'Median Latency Comparison: Cassandra vs ClickHouse\n'
        '(Note: The two workloads are completely different)',
        fontsize=14,
        pad=15,
    )
    plt.ylabel('Median Latency (ms)', fontsize=12)
    plt.xlabel('Database', fontsize=12)

    # Annotate exact values above each bar
    for bar in bars:
        yval = bar.get_height()
        plt.text(
            bar.get_x() + bar.get_width() / 2,
            yval + 0.05,
            f"{yval:.2f} ms",
            ha='center',
            va='bottom',
            fontsize=12,
            fontweight='bold',
        )

    # Save figure to results/
    out_dir = Path("results")
    out_dir.mkdir(exist_ok=True)
    out_path = out_dir / "latency_chart.png"
    plt.savefig(out_path, dpi=300, bbox_inches='tight')
    print(f"Done! Chart saved to: {out_path}")


if __name__ == "__main__":
    plot_benchmark()
