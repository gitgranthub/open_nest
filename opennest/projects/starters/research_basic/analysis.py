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
    """One chart, with both axes labelled -- and said in words, because a chart nobody can
    read is not a result, and the words are what you (and Gary) can check."""
    CHART_DIR.mkdir(exist_ok=True)

    figure, axes = plt.subplots(figsize=(8, 4.5))

    # Along the bottom: the first column of words if there is one (a name, a date).
    labels = None
    for name in frame.columns:
        if name not in numbers.columns:
            labels = name
            break

    first_number = numbers.columns[0]
    others = [name for name in numbers.columns if name != first_number][:4]

    if labels is not None and len(frame) <= 30:
        shown, along = [first_number], labels
        axes.bar(frame[labels].astype(str), numbers[first_number])
        plt.setp(axes.get_xticklabels(), rotation=45, ha="right")
    elif labels is None and others and numbers[first_number].is_monotonic_increasing:
        # All numbers, and the first one only goes up -- week 1, 2, 3 -- so it is what
        # the others are measured against: one line for each of them.
        shown, along = others, first_number
        for name in others:
            axes.plot(numbers[first_number], numbers[name], marker="o", label=str(name))
        if len(others) > 1:
            axes.legend()
    else:
        shown, along = [first_number], None
        axes.plot(range(len(frame)), numbers[first_number], marker="o", markersize=3)

    what = " and ".join(str(name) for name in shown)
    by = f"by {along}" if along is not None else "row by row"
    axes.set_xlabel(str(along) if along is not None else "Row number")
    axes.set_ylabel(what if len(shown) == 1 else "value")
    axes.set_title(f"{what} {by}, from {table_name}")
    figure.tight_layout()

    chart = CHART_DIR / "chart.png"
    figure.savefig(chart, dpi=110)
    print(f"\nChart saved to {chart}: {what} {by}.")
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
