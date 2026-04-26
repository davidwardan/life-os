from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

from backend.app.config import DATA_DIR

os.environ.setdefault("MPLCONFIGDIR", str(DATA_DIR / "matplotlib"))
os.environ.setdefault("XDG_CACHE_HOME", str(DATA_DIR / "cache"))

import matplotlib

matplotlib.use("Agg")
from matplotlib import pyplot as plt
from matplotlib.ticker import MaxNLocator

from backend.app.db import LifeDatabase


PLOTS_DIR = DATA_DIR / "plots"
INK = "#111111"
PAPER = "#f7f7f4"
MUTED = "#74746e"
GRID = "#d8d8d2"
RED = "#d9291c"


@dataclass(frozen=True)
class PlotRequest:
    metric: str
    days: int = 30


@dataclass(frozen=True)
class PlotResult:
    path: Path
    title: str
    detail: str


SUPPORTED_METRICS = {
    "energy": "Energy and stress",
    "stress": "Energy and stress",
    "workout": "Workout duration",
    "workouts": "Workout duration",
    "career": "Career hours",
    "work": "Career hours",
    "protein": "Protein",
    "calories": "Calories",
}


def parse_plot_request(text: str) -> PlotRequest | None:
    lower = text.lower()
    if not any(word in lower for word in ("plot", "chart", "graph", "show")):
        return None

    days = 30
    if "week" in lower or "7 day" in lower:
        days = 7
    elif "90" in lower or "3 month" in lower:
        days = 90

    for keyword, metric in (
        ("energy", "energy"),
        ("stress", "stress"),
        ("workout", "workout"),
        ("training", "workout"),
        ("career", "career"),
        ("work hours", "career"),
        ("deep work", "career"),
        ("protein", "protein"),
        ("calories", "calories"),
    ):
        if keyword in lower:
            return PlotRequest(metric=metric, days=days)

    return PlotRequest(metric="energy", days=days)


class PlotService:
    def __init__(self, db: LifeDatabase, plots_dir: Path = PLOTS_DIR):
        self.db = db
        self.plots_dir = plots_dir
        self.plots_dir.mkdir(parents=True, exist_ok=True)

    def generate(self, request: PlotRequest) -> PlotResult:
        metric = SUPPORTED_METRICS.get(request.metric, "Energy and stress")
        if request.metric in {"energy", "stress"}:
            return self._energy_stress(request.days)
        if request.metric in {"workout", "workouts"}:
            return self._workout_duration(request.days)
        if request.metric in {"career", "work"}:
            return self._career_hours(request.days)
        if request.metric == "protein":
            return self._nutrition_metric("protein_g", "Protein", "g", request.days)
        if request.metric == "calories":
            return self._nutrition_metric("calories", "Calories", "cal", request.days)
        raise ValueError(f"Unsupported metric: {metric}")

    def _energy_stress(self, days: int) -> PlotResult:
        rows = self._rows(
            """
            SELECT date, AVG(energy) AS energy, AVG(stress) AS stress
            FROM daily_checkins
            WHERE date >= ? AND (energy IS NOT NULL OR stress IS NOT NULL)
            GROUP BY date
            ORDER BY date
            """,
            (_start_date(days),),
        )
        path = self._path("energy_stress")
        fig, ax = _figure()
        dates = [row["date"] for row in rows]
        x_values = list(range(len(dates)))
        if rows:
            energy = [row["energy"] for row in rows]
            stress = [row["stress"] for row in rows]
            ax.plot(x_values, energy, marker="o", markersize=7, linewidth=2.6, color=INK, label="Energy")
            ax.plot(x_values, stress, marker="o", markersize=7, linewidth=2.6, color=RED, label="Stress")
            _annotate_last(ax, x_values, energy, "energy", INK)
            _annotate_last(ax, x_values, stress, "stress", RED)
        _style_axis(ax, "Energy / Stress", "Score", rows, kicker=f"Last {days} days")
        _set_date_ticks(ax, x_values, dates)
        ax.set_ylim(0, 10)
        ax.legend(loc="upper left", bbox_to_anchor=(0, 1.02), ncol=2, frameon=False)
        _save(fig, path)
        return PlotResult(path=path, title="Energy and stress", detail=f"{len(rows)} day(s)")

    def _workout_duration(self, days: int) -> PlotResult:
        rows = self._rows(
            """
            SELECT date, SUM(duration_min) AS duration_min
            FROM workout_logs
            WHERE date >= ? AND duration_min IS NOT NULL
            GROUP BY date
            ORDER BY date
            """,
            (_start_date(days),),
        )
        return self._bar_plot(rows, "Workout duration", "Minutes", "duration_min", "workout_duration")

    def _career_hours(self, days: int) -> PlotResult:
        rows = self._rows(
            """
            SELECT date, SUM(duration_hours) AS duration_hours
            FROM career_logs
            WHERE date >= ? AND duration_hours IS NOT NULL
            GROUP BY date
            ORDER BY date
            """,
            (_start_date(days),),
        )
        return self._bar_plot(rows, "Career hours", "Hours", "duration_hours", "career_hours")

    def _nutrition_metric(self, column: str, title: str, ylabel: str, days: int) -> PlotResult:
        rows = self._rows(
            f"""
            SELECT date, SUM({column}) AS value
            FROM nutrition_logs
            WHERE date >= ? AND {column} IS NOT NULL
            GROUP BY date
            ORDER BY date
            """,
            (_start_date(days),),
        )
        return self._bar_plot(rows, title, ylabel, "value", column)

    def _bar_plot(
        self,
        rows: list[sqlite3.Row],
        title: str,
        ylabel: str,
        value_key: str,
        filename: str,
    ) -> PlotResult:
        path = self._path(filename)
        fig, ax = _figure()
        dates = [row["date"] for row in rows]
        x_values = list(range(len(dates)))
        values = [row[value_key] for row in rows]
        if rows:
            bars = ax.bar(x_values, values, color=INK, width=0.58)
            if bars:
                bars[-1].set_color(RED)
                _annotate_last(ax, x_values, values, "latest", RED)
        _style_axis(ax, title, ylabel, rows, kicker="Life OS")
        _set_date_ticks(ax, x_values, dates)
        _save(fig, path)
        return PlotResult(path=path, title=title, detail=f"{len(rows)} day(s)")

    def _rows(self, query: str, params: tuple[str, ...]) -> list[sqlite3.Row]:
        with self.db.connect() as connection:
            return connection.execute(query, params).fetchall()

    def _path(self, name: str) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        return self.plots_dir / f"{name}_{stamp}.png"


def _figure():
    fig, ax = plt.subplots(figsize=(8.5, 4.8), facecolor=PAPER)
    ax.set_facecolor(PAPER)
    return fig, ax


def _style_axis(ax, title: str, ylabel: str, rows: list[sqlite3.Row], kicker: str) -> None:
    ax.text(
        0,
        1.14,
        kicker.upper(),
        transform=ax.transAxes,
        color=RED,
        fontsize=9,
        fontweight="bold",
    )
    ax.text(
        0,
        1.06,
        title,
        transform=ax.transAxes,
        color=INK,
        fontsize=22,
        fontweight="bold",
    )
    ax.set_ylabel(ylabel, color=MUTED)
    ax.set_xlabel("")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color(INK)
    ax.spines["bottom"].set_color(INK)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(axis="both", colors=INK, labelsize=9)
    ax.yaxis.set_major_locator(MaxNLocator(integer=True, nbins=5))
    if not rows:
        ax.text(
            0.5,
            0.5,
            "No data yet",
            ha="center",
            va="center",
            transform=ax.transAxes,
            color=MUTED,
            fontsize=14,
            fontweight="bold",
        )
        ax.set_xticks([])
    else:
        ax.tick_params(axis="x", labelrotation=35)


def _set_date_ticks(ax, x_values: list[int], dates: list[str]) -> None:
    if not x_values:
        return
    ax.set_xticks(x_values)
    ax.set_xticklabels(dates, rotation=35, ha="right")
    ax.margins(x=0.04)


def _annotate_last(ax, x_values: list[int], values: list[float | None], label: str, color: str) -> None:
    if not x_values or not values or values[-1] is None:
        return
    ax.annotate(
        f"{label}: {values[-1]:g}",
        xy=(x_values[-1], values[-1]),
        xytext=(8, 8),
        textcoords="offset points",
        color=color,
        fontsize=9,
        fontweight="bold",
    )


def _save(fig, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=170, facecolor=PAPER, edgecolor=PAPER)
    plt.close(fig)


def _start_date(days: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()
