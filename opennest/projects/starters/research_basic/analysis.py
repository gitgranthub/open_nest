"""Look at a table of data and draw a picture of it.

Drop a .csv file onto the project and press Run Analysis. This finds it, says what is
inside it, and draws a chart into the charts folder.

Then start changing it. The interesting questions are yours: which column matters, what
you expected to see, and whether the chart agrees with you.
"""

import matplotlib

# Pick the drawing engine before importing pyplot. "Agg" draws straight to a file
# instead of opening a window, which is what we want -- the chart appears in Open Nest.
matplotlib.use("Agg")

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

DATA_DIR = Path("data")
CHART_DIR = Path("charts")


def find_a_table():
    """The first .csv in the data folder, or None if there is not one yet."""
    tables = sorted(DATA_DIR.glob("*.csv"))
    if not tables:
        return None
    return tables[0]


def describe(table, frame):
    """Say what is actually in the file, before drawing any conclusions from it."""
    print(f"Reading {table.name}")
    print(f"  {len(frame)} rows, {len(frame.columns)} columns")
    print(f"  columns: {', '.join(str(c) for c in frame.columns)}")

    missing = frame.isna().sum()
    gaps = {name: int(count) for name, count in missing.items() if count}
    if gaps:
        print(f"  empty cells: {gaps}")
    else:
        print("  no empty cells")

    numbers = frame.select_dtypes("number")
    if not numbers.empty:
        print("\nThe number columns, summarised:")
        print(numbers.describe().to_string())
    return numbers


def draw(frame, numbers, table_name):
    """One chart, with both axes labelled. A chart nobody can read is not a result."""
    CHART_DIR.mkdir(exist_ok=True)

    figure, axes = plt.subplots(figsize=(8, 4.5))

    # Use the first non-numeric column as the labels along the bottom if there is one;
    # otherwise just count the rows.
    labels = None
    for name in frame.columns:
        if name not in numbers.columns:
            labels = frame[name].astype(str)
            break

    first_number = numbers.columns[0]
    values = numbers[first_number]

    if labels is not None and len(frame) <= 30:
        axes.bar(labels, values)
        axes.set_xlabel(str(frame.columns[0]))
        plt.setp(axes.get_xticklabels(), rotation=45, ha="right")
    else:
        axes.plot(range(len(values)), values, marker="o", markersize=3)
        axes.set_xlabel("Row number")

    axes.set_ylabel(str(first_number))
    axes.set_title(f"{first_number} from {table_name}")
    figure.tight_layout()

    chart = CHART_DIR / "chart.png"
    figure.savefig(chart, dpi=110)
    print(f"\nChart saved to {chart}")
    return chart


table = find_a_table()

if table is None:
    print("There is no data here yet.")
    print()
    print("Drag a .csv file onto the project and press Run Analysis again.")
    print("A .csv is just a table saved as text -- most spreadsheets can save one.")
else:
    frame = pd.read_csv(table)
    numbers = describe(table, frame)

    if numbers.empty:
        print("\nNo number columns to chart yet.")
        print("A chart needs at least one column of numbers.")
    else:
        draw(frame, numbers, table.name)
