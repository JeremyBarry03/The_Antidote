"""Plot saved results only; no inference, fitting or threshold changes."""

import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    protocol = json.loads((args.directory / "protocol.json").read_text())
    rows = {row["scenario"]: row for row in json.loads((args.directory / "summary.json").read_text())}
    keys = [case["id"] for case in protocol["scenarios"] if case["kind"] == "single"]
    labels = ["Reporting gap", "Missing speed", "Missing course", "Missing class",
              "Speed drift", "Location drift", "Sensor noise", "Position jumps"]
    matrix = np.full((8, 8), np.nan)
    for i, first in enumerate(keys):
        matrix[i, i] = rows[first]["delta_mae"]
        for j in range(i):
            matrix[i, j] = rows[f"{keys[j]}__{first}"]["delta_mae"]

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False,
                         "svg.fonttype": "none"})
    fig = plt.figure(figsize=(14, 8.5), facecolor="white")
    grid = fig.add_gridspec(1, 2, width_ratios=[1.8, 1], left=.135, right=.96,
                           top=.80, bottom=.24, wspace=.40)
    ax = fig.add_subplot(grid[0])
    cmap = plt.colormaps["RdBu_r"].copy()
    cmap.set_bad("white")
    chart = ax.imshow(matrix, vmin=-3.2, vmax=3.2, cmap=cmap, aspect="equal")
    ax.set_xticks(range(8), labels, rotation=43, ha="right", rotation_mode="anchor")
    ax.set_yticks(range(8), labels)
    ax.tick_params(length=0)
    ax.set_xticks(np.arange(-.5, 8, 1), minor=True)
    ax.set_yticks(np.arange(-.5, 8, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="minor", length=0)
    for i in range(8):
        for j in range(i + 1):
            value = matrix[i, j]
            ax.text(j, i, f"{value:.2f}", ha="center", va="center", fontsize=9,
                    color="white" if abs(value) > 1.8 else "#202020")
    ax.set_title("Change in ETA mean absolute error (minutes)", loc="left", pad=17, fontsize=12)
    bar = fig.colorbar(chart, ax=ax, orientation="horizontal", fraction=.045, pad=.32,
                       ticks=[-3, -1.5, 0, 1.5, 3])
    bar.set_label("Lower error  ←  additional mitigation effect  →  Higher error", fontsize=9)
    bar.outline.set_visible(False)

    bx = fig.add_subplot(grid[1])
    choices = ["nominal", "all_eight_50", "all_eight_100"]
    y = np.arange(3)
    bx.barh(y - .16, [rows[key]["C_guard_mae"] for key in choices], height=.29,
            color="#b9bfc4", label="Frozen C + original guard")
    bx.barh(y + .16, [rows[key]["Antidote_mae"] for key in choices], height=.29,
            color="#20282d", label="With additional strategies")
    for i, key in enumerate(choices):
        bx.text(rows[key]["Antidote_mae"] + .25, i + .16,
                f"{rows[key]['Antidote_mae']:.2f}", va="center", fontsize=10)
    bx.set_yticks(y, ["Original\nrecords", "All eight\nmoderate", "All eight\nsevere"])
    bx.invert_yaxis()
    bx.set_xlim(0, 18)
    bx.set_ylim(4.7, -.6)
    bx.set_xlabel("ETA mean absolute error (minutes)")
    bx.set_title("Stacking all eight: little extra recovery", loc="left", pad=17, fontsize=12)
    bx.legend(loc="lower left", bbox_to_anchor=(-.04, -.19), frameon=False, fontsize=9)
    bx.text(0, 3.0, "Limits exposed in this screen", fontsize=11, weight="bold")
    review_rate = rows["nominal"]["review_fraction"]
    course_mse_change = rows["missing_course"]["Antidote_mse"] / rows["missing_course"]["C_guard_mse"] - 1
    bx.text(0, 3.3,
            f"• Review status on {review_rate:.0%} of original clocks\n"
            f"• Missing-course MSE changes {course_mse_change:+.1%}\n"
            "  despite lower mean absolute error\n"
            "• No verified location correction feed", va="top", fontsize=10, linespacing=1.6)
    bx.spines["left"].set_visible(False)
    bx.tick_params(axis="y", length=0)

    fig.text(.065, .94, "Antidote: first combination screen", fontsize=23, weight="bold")
    fig.text(.065, .895,
             f"{protocol['approaches']} approaches · {protocol['decision_clocks']} decision times per setting · "
             f"{len(protocol['scenarios'])} settings · one simulated fault seed", fontsize=12, color="#4b5157")
    fig.text(.065, .08,
             "Pairs: 50% sliders and a 15-minute reporting gap. Diagonal: single attacks. No verified position fixes.\n"
             "Zero means no additional accuracy gain; several mixed faults deliberately pause repairs. "
             "Exploratory results on previously inspected April data.", fontsize=9, color="#4b5157", linespacing=1.6)
    fig.savefig(args.directory / "combination_screen.png", dpi=180)
    fig.savefig(args.directory / "combination_screen.svg")


if __name__ == "__main__":
    main()
