from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
import plotly.graph_objects as go
from pydantic import BaseModel, Field

from backend.app._db_schema import SCHEMA
from backend.app.config import DATA_DIR, settings

from backend.app.db import LifeDatabase


PLOTS_DIR = DATA_DIR / "plots"
WHITE = "#ffffff"
BLACK = "#111111"
BLUE = "#1d4ed8"
BLUE_SOFT = "#dbeafe"
RED = "#dc2626"
GREEN = "#16a34a"
RGB_PALETTE = (BLUE, GREEN, RED)
IMAGE_WIDTH = 1530
IMAGE_HEIGHT = 867


@dataclass(frozen=True)
class PlotRequest:
    metric: str
    days: int = 30
    subject: str | None = None
    original_text: str | None = None


class PlotConfiguration(BaseModel):
    query: str = Field(
        description="SQLite query to fetch data. Always include a 'date' or 'label' column."
    )
    chart_type: Literal["line", "bar", "heatmap"] = Field(default="line")
    title: str
    ylabel: str
    kicker: str = Field(default="LIFE OS")
    series: list[str] = Field(description="Columns from the query to plot on the Y axis.")
    insight_prompt: str = Field(
        description="A prompt to generate a 1-sentence insight from the fetched data."
    )


PLOTTING_SYSTEM_PROMPT = f"""
You are the data scientist for Life OS. Your goal is to translate natural language requests into SQLite queries and visualization settings.

Schema Context:
{SCHEMA}

Rules:
1. Always generate valid SQLite code.
2. Group by date when appropriate to show trends.
3. For line charts, ensure multiple series have the same X axis (date).
4. Use 'label' as a column name if the X axis isn't a date (e.g. project names).
5. Limit the scope to the last N days as requested by the user.
6. Return JSON matching the PlotConfiguration schema.

Example:
User: "plot my sleep vs energy for the last 2 weeks"
Result: {{
    "query": "SELECT date, sleep_hours, energy FROM daily_checkins WHERE date >= date('now', '-14 days') ORDER BY date",
    "chart_type": "line",
    "title": "Sleep vs Energy",
    "ylabel": "Hours / Score",
    "series": ["sleep_hours", "energy"],
    "insight_prompt": "Compare how sleep hours relate to energy levels in this period."
}}
""".strip()


class PlottingAgent:
    def __init__(
        self,
        api_key: str,
        model: str = settings.openrouter_plotting_model,
        fallback_models: tuple[str, ...] = settings.openrouter_plotting_fallback_models,
    ):
        self.api_key = api_key
        self.model = model
        self.fallback_models = fallback_models

    async def plan(self, text: str) -> PlotConfiguration:
        errors: list[str] = []
        for model in (self.model, *self.fallback_models):
            try:
                return await self._plan_with_model(model, text)
            except (httpx.HTTPError, ValueError) as error:
                errors.append(f"{model}: {_format_error(error)}")
        raise ValueError("; ".join(errors))

    async def _plan_with_model(self, model: str, text: str) -> PlotConfiguration:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": PLOTTING_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0,
        }
        async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
            response = await client.post(
                f"{settings.openrouter_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()["choices"][0]["message"]["content"]
            return PlotConfiguration.model_validate_json(data)

    async def generate_insight(self, prompt: str, data: list[dict[str, Any]]) -> str:
        errors: list[str] = []
        for model in (self.model, *self.fallback_models):
            try:
                return await self._generate_insight_with_model(model, prompt, data)
            except (httpx.HTTPError, KeyError, ValueError) as error:
                errors.append(f"{model}: {_format_error(error)}")
        raise ValueError("; ".join(errors))

    async def _generate_insight_with_model(
        self, model: str, prompt: str, data: list[dict[str, Any]]
    ) -> str:
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a concise data analyst. Write a 1-sentence insight about the "
                        "provided data."
                    ),
                },
                {"role": "user", "content": f"Prompt: {prompt}\nData: {json.dumps(data[:30])}"},
            ],
            "temperature": 0.3,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                f"{settings.openrouter_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            return response.json()["choices"][0]["message"]["content"].strip()


@dataclass(frozen=True)
class PlotResult:
    path: Path
    title: str
    detail: str


SUPPORTED_METRICS = {
    "energy": "Energy and stress",
    "stress": "Energy and stress",
    "wellbeing": "Energy and stress",
    "sleep_energy": "Sleep vs energy",
    "stress_workout": "Stress vs workout load",
    "workout": "Workout duration",
    "workouts": "Workout duration",
    "workout_frequency": "Workout frequency",
    "exercise_history": "Exercise history",
    "career": "Career hours",
    "work": "Career hours",
    "career_projects": "Deep work by project",
    "protein": "Protein",
    "protein_consistency": "Protein consistency",
    "calories": "Calories",
    "habits": "Data completeness",
    "data_completeness": "Data completeness",
}


SUPPORTED_PLOTS = [
    {"metric": "energy", "title": "Energy and stress", "example": "plot my energy"},
    {"metric": "sleep_energy", "title": "Sleep vs energy", "example": "plot sleep vs energy"},
    {
        "metric": "stress_workout",
        "title": "Stress vs workout load",
        "example": "show stress vs workouts",
    },
    {"metric": "workout", "title": "Workout duration", "example": "plot my workouts"},
    {
        "metric": "workout_frequency",
        "title": "Workout frequency",
        "example": "show workout frequency",
    },
    {"metric": "exercise_history", "title": "Exercise history", "example": "plot squat history"},
    {"metric": "career", "title": "Career hours", "example": "show my career hours"},
    {
        "metric": "career_projects",
        "title": "Deep work by project",
        "example": "plot deep work by project",
    },
    {"metric": "protein", "title": "Protein", "example": "plot protein for the last week"},
    {
        "metric": "protein_consistency",
        "title": "Protein consistency",
        "example": "show protein consistency",
    },
    {"metric": "calories", "title": "Calories", "example": "plot calories"},
    {"metric": "data_completeness", "title": "Data completeness", "example": "show habit heatmap"},
]


def parse_plot_request(text: str) -> PlotRequest | None:
    lower = text.lower()
    if not any(word in lower for word in ("plot", "chart", "graph", "show")):
        return None

    days = _parse_days(lower)
    subject = _parse_exercise_subject(lower)

    # Always prefer original text for the agent if possible
    request = PlotRequest(metric="auto", days=days, subject=subject, original_text=text)

    if ("sleep" in lower and "energy" in lower) or "sleep" in lower:
        return PlotRequest(metric="sleep_energy", days=days, original_text=text)
    if "stress" in lower and any(word in lower for word in ("workout", "training", "load")):
        return PlotRequest(metric="stress_workout", days=days, original_text=text)
    if any(word in lower for word in ("habit", "habits", "heatmap", "completeness", "complete")):
        return PlotRequest(metric="data_completeness", days=days, original_text=text)
    if subject or "exercise" in lower:
        return PlotRequest(
            metric="exercise_history", days=days, subject=subject, original_text=text
        )
    if any(word in lower for word in ("frequency", "count")) and any(
        word in lower for word in ("workout", "workouts", "training")
    ):
        return PlotRequest(metric="workout_frequency", days=days, original_text=text)
    if any(word in lower for word in ("project", "projects")) and any(
        word in lower for word in ("career", "work", "deep work", "hours")
    ):
        return PlotRequest(metric="career_projects", days=days, original_text=text)
    if "protein" in lower and any(
        word in lower for word in ("consistency", "consistent", "target")
    ):
        return PlotRequest(metric="protein_consistency", days=days, original_text=text)

    for keyword, metric in (
        ("wellbeing", "wellbeing"),
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
            return PlotRequest(metric=metric, days=days, original_text=text)

    return request


def parse_plot_requests(text: str) -> list[PlotRequest]:
    parts = [part.strip() for part in text.splitlines() if part.strip()]
    if len(parts) <= 1:
        request = parse_plot_request(text)
        return [request] if request else []

    requests = [parse_plot_request(part) for part in parts]
    if any(request is None for request in requests):
        return []
    return [request for request in requests if request is not None]


class PlotService:
    def __init__(self, db: LifeDatabase, plots_dir: Path = PLOTS_DIR):
        self.db = db
        self.plots_dir = plots_dir
        self.plots_dir.mkdir(parents=True, exist_ok=True)
        self.agent = (
            PlottingAgent(settings.openrouter_api_key) if settings.openrouter_api_key else None
        )

    async def generate_smart(self, text: str) -> PlotResult:
        if not self.agent:
            # Fallback to legacy parser if no agent
            req = parse_plot_request(text)
            return self.generate(req) if req else self._energy_stress(30)

        try:
            config = await self.agent.plan(text)
            rows = self._rows(config.query, ())
        except Exception:
            # Fallback on planner error
            req = parse_plot_request(text)
            return self.generate(req) if req else self._energy_stress(30)

        if not rows:
            # Generate empty plot with legacy style
            path = self._path("empty")
            fig = _base_figure(config.title, config.ylabel, [], kicker=config.kicker)
            _save(fig, path)
            return PlotResult(path=path, title=config.title, detail="No data found")

        path = self._path(_slug(config.title))
        fig = _base_figure(config.title, config.ylabel, rows, kicker=config.kicker)

        # Determine X values (date or label)
        x_key = "date" if "date" in rows[0] else ("label" if "label" in rows[0] else None)
        if not x_key:
            # Guess first column if no date/label
            x_key = list(rows[0].keys())[0]

        x_labels = [str(row[x_key]) for row in rows]

        if config.chart_type == "line":
            for i, series_key in enumerate(config.series):
                if series_key not in rows[0]:
                    continue
                values = [row[series_key] for row in rows]
                color = _series_color(series_key, i)
                label = series_key.replace("_", " ")
                _add_line(fig, x_labels, values, label, color)
                _annotate_last(fig, x_labels, values, label, color)
        elif config.chart_type == "bar":
            series_key = (
                config.series[0]
                if config.series and config.series[0] in rows[0]
                else list(rows[0].keys())[1]
            )
            values = [row[series_key] for row in rows]
            _add_bar(fig, x_labels, values, _bar_colors(config.title, series_key, len(values)))
            _annotate_last(fig, x_labels, values, "latest", GREEN)
            _annotate_peak(fig, x_labels, values)
        elif config.chart_type == "heatmap":
            categories = [c for c in rows[0].keys() if c != x_key]
            matrix = [[int(row[cat]) for row in rows] for cat in categories]
            _add_heatmap(fig, x_labels, [c.title() for c in categories], matrix)

        # Generate insight
        try:
            insight = await self.agent.generate_insight(config.insight_prompt, rows)
        except Exception:
            insight = f"{len(rows)} data points analyzed"

        _save(fig, path)
        return PlotResult(path=path, title=config.title, detail=insight)

    def generate(self, request: PlotRequest) -> PlotResult:
        metric = SUPPORTED_METRICS.get(request.metric, "Energy and stress")
        if request.metric in {"energy", "stress", "wellbeing"}:
            return self._energy_stress(request.days)
        if request.metric == "sleep_energy":
            return self._sleep_energy(request.days)
        if request.metric == "stress_workout":
            return self._stress_workout(request.days)
        if request.metric in {"workout", "workouts"}:
            return self._workout_duration(request.days)
        if request.metric == "workout_frequency":
            return self._workout_frequency(request.days)
        if request.metric == "exercise_history":
            return self._exercise_history(request.days, request.subject)
        if request.metric in {"career", "work"}:
            return self._career_hours(request.days)
        if request.metric == "career_projects":
            return self._career_projects(request.days)
        if request.metric == "protein":
            return self._nutrition_metric("protein_g", "Protein", "g", request.days)
        if request.metric == "protein_consistency":
            return self._nutrition_metric("protein_g", "Protein consistency", "g", request.days)
        if request.metric == "calories":
            return self._nutrition_metric("calories", "Calories", "cal", request.days)
        if request.metric in {"habits", "data_completeness"}:
            return self._data_completeness(request.days)
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
        dates = [row["date"] for row in rows]
        fig = _base_figure("Energy / Stress", "Score", rows, kicker=f"Last {days} days")
        if rows:
            energy = [row["energy"] for row in rows]
            stress = [row["stress"] for row in rows]
            _add_line(fig, dates, energy, "Energy", GREEN)
            _add_line(fig, dates, stress, "Stress", RED)
            _annotate_last(fig, dates, energy, "energy", GREEN)
            _annotate_last(fig, dates, stress, "stress", RED)
        fig.update_yaxes(range=[0, 10])
        _save(fig, path)
        return PlotResult(path=path, title="Energy and stress", detail=f"{len(rows)} day(s)")

    def _sleep_energy(self, days: int) -> PlotResult:
        rows = self._rows(
            """
            SELECT date, AVG(sleep_hours) AS sleep_hours, AVG(energy) AS energy
            FROM daily_checkins
            WHERE date >= ? AND (sleep_hours IS NOT NULL OR energy IS NOT NULL)
            GROUP BY date
            ORDER BY date
            """,
            (_start_date(days),),
        )
        return self._dual_line_plot(
            rows=rows,
            title="Sleep / Energy",
            ylabel="Hours / score",
            left_key="sleep_hours",
            left_label="sleep",
            right_key="energy",
            right_label="energy",
            filename="sleep_energy",
            days=days,
        )

    def _stress_workout(self, days: int) -> PlotResult:
        rows = self._rows(
            """
            WITH dates AS (
                SELECT date FROM daily_checkins WHERE date >= ?
                UNION SELECT date FROM workout_logs WHERE date >= ?
            )
            SELECT dates.date AS date,
                   (SELECT AVG(stress) FROM daily_checkins d WHERE d.date = dates.date) AS stress,
                   (SELECT SUM(duration_min) FROM workout_logs w WHERE w.date = dates.date) AS duration_min
            FROM dates
            WHERE stress IS NOT NULL OR duration_min IS NOT NULL
            ORDER BY dates.date
            """,
            (_start_date(days), _start_date(days)),
        )
        return self._dual_line_plot(
            rows=rows,
            title="Stress / Training",
            ylabel="Score / min",
            left_key="stress",
            left_label="stress",
            right_key="duration_min",
            right_label="training",
            filename="stress_workout",
            days=days,
        )

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
        return self._bar_plot(
            rows, "Workout duration", "Minutes", "duration_min", "workout_duration"
        )

    def _workout_frequency(self, days: int) -> PlotResult:
        rows = self._rows(
            """
            SELECT date, COUNT(*) AS value
            FROM workout_logs
            WHERE date >= ?
            GROUP BY date
            ORDER BY date
            """,
            (_start_date(days),),
        )
        return self._bar_plot(rows, "Workout frequency", "Sessions", "value", "workout_frequency")

    def _exercise_history(self, days: int, subject: str | None) -> PlotResult:
        if subject:
            rows = self._rows(
                """
                SELECT w.date AS date,
                       SUM(COALESCE(e.sets, 1)) AS value
                FROM workout_exercises e
                JOIN workout_logs w ON w.id = e.workout_id
                WHERE w.date >= ? AND LOWER(e.name) LIKE ?
                GROUP BY w.date
                ORDER BY w.date
                """,
                (_start_date(days), f"%{subject.lower()}%"),
            )
            title = f"{subject.title()} history"
            filename = f"exercise_{_slug(subject)}"
        else:
            rows = self._rows(
                """
                SELECT e.name AS label,
                       COUNT(*) AS value
                FROM workout_exercises e
                JOIN workout_logs w ON w.id = e.workout_id
                WHERE w.date >= ?
                GROUP BY LOWER(e.name)
                ORDER BY value DESC, e.name
                LIMIT 8
                """,
                (_start_date(days),),
            )
            title = "Exercise history"
            filename = "exercise_history"
        return self._bar_plot(rows, title, "Sets / mentions", "value", filename)

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

    def _career_projects(self, days: int) -> PlotResult:
        rows = self._rows(
            """
            SELECT COALESCE(NULLIF(project, ''), 'unspecified') AS label,
                   SUM(duration_hours) AS value
            FROM career_logs
            WHERE date >= ? AND duration_hours IS NOT NULL
            GROUP BY COALESCE(NULLIF(project, ''), 'unspecified')
            ORDER BY value DESC
            LIMIT 8
            """,
            (_start_date(days),),
        )
        return self._bar_plot(rows, "Deep work by project", "Hours", "value", "career_projects")

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

    def _data_completeness(self, days: int) -> PlotResult:
        rows = self._rows(
            """
            WITH dates AS (
                SELECT date FROM daily_checkins WHERE date >= ?
                UNION SELECT date FROM nutrition_logs WHERE date >= ?
                UNION SELECT date FROM workout_logs WHERE date >= ?
                UNION SELECT date FROM career_logs WHERE date >= ?
                UNION SELECT date FROM journal_entries WHERE date >= ?
            )
            SELECT dates.date AS date,
                   EXISTS(SELECT 1 FROM daily_checkins d WHERE d.date = dates.date) AS wellbeing,
                   EXISTS(SELECT 1 FROM nutrition_logs n WHERE n.date = dates.date) AS nutrition,
                   EXISTS(SELECT 1 FROM workout_logs w WHERE w.date = dates.date) AS workout,
                   EXISTS(SELECT 1 FROM career_logs c WHERE c.date = dates.date) AS career,
                   EXISTS(SELECT 1 FROM journal_entries j WHERE j.date = dates.date) AS journal
            FROM dates
            ORDER BY dates.date
            """,
            tuple(_start_date(days) for _ in range(5)),
        )
        path = self._path("data_completeness")
        categories = ["wellbeing", "nutrition", "workout", "career", "journal"]
        dates = [row["date"] for row in rows]
        fig = _base_figure(
            "Data Completeness", "", rows, kicker=f"Last {days} days", integer_y=False
        )
        if rows:
            matrix = [[int(row[category]) for row in rows] for category in categories]
            _add_heatmap(fig, dates, [category.title() for category in categories], matrix)
        _save(fig, path)
        return PlotResult(path=path, title="Data completeness", detail=f"{len(rows)} day(s)")

    def _dual_line_plot(
        self,
        rows: list[sqlite3.Row],
        title: str,
        ylabel: str,
        left_key: str,
        left_label: str,
        right_key: str,
        right_label: str,
        filename: str,
        days: int,
    ) -> PlotResult:
        path = self._path(filename)
        dates = [row["date"] for row in rows]
        fig = _base_figure(title, ylabel, rows, kicker=f"Last {days} days")
        if rows:
            left_values = [row[left_key] for row in rows]
            right_values = [row[right_key] for row in rows]
            left_color = _series_color(left_label, 0)
            right_color = _series_color(right_label, 1)
            _add_line(fig, dates, left_values, left_label, left_color)
            _add_line(fig, dates, right_values, right_label, right_color)
            _annotate_last(fig, dates, left_values, left_label, left_color)
            _annotate_last(fig, dates, right_values, right_label, right_color)
        _save(fig, path)
        return PlotResult(path=path, title=title, detail=f"{len(rows)} day(s)")

    def _bar_plot(
        self,
        rows: list[sqlite3.Row],
        title: str,
        ylabel: str,
        value_key: str,
        filename: str,
    ) -> PlotResult:
        path = self._path(filename)
        if rows and "label" in rows[0].keys():
            dates = [row["label"] for row in rows]
        else:
            dates = [row["date"] for row in rows]
        values = [row[value_key] for row in rows]
        fig = _base_figure(title, ylabel, rows, kicker="Life OS")
        if rows:
            _add_bar(fig, dates, values, _bar_colors(title, value_key, len(values)))
            _annotate_last(fig, dates, values, "latest", GREEN)
            _annotate_peak(fig, dates, values)
        _save(fig, path)
        return PlotResult(path=path, title=title, detail=f"{len(rows)} day(s)")

    def _rows(self, query: str, params: tuple[str, ...]) -> list[dict[str, Any]]:
        with self.db.connect() as connection:
            cursor = connection.execute(query, params)
            rows = cursor.fetchall()
            if not rows:
                return []
            if isinstance(rows[0], sqlite3.Row):
                return [dict(row) for row in rows]

            columns = [column[0] for column in cursor.description]
            return [dict(zip(columns, row)) for row in rows]

    def _path(self, name: str) -> Path:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        return self.plots_dir / f"{name}_{stamp}.png"


def supported_plots() -> list[dict[str, Any]]:
    return SUPPORTED_PLOTS


def _parse_days(lower: str) -> int:
    if "week" in lower or "7 day" in lower:
        return 7
    if "90" in lower or "3 month" in lower or "quarter" in lower:
        return 90
    if "month" in lower or "30 day" in lower:
        return 30

    match = None
    for pattern in (r"last\s+(\d+)\s+days?", r"(\d+)\s+day"):
        match = re.search(pattern, lower)
        if match:
            break
    if match:
        return max(1, min(int(match.group(1)), 365))
    return 30


def _parse_exercise_subject(lower: str) -> str | None:
    candidates = (
        ("squats", "squat"),
        ("squat", "squat"),
        ("deadlifts", "deadlift"),
        ("deadlift", "deadlift"),
        ("rdl", "romanian deadlift"),
        ("romanian deadlift", "romanian deadlift"),
        ("lunges", "lunge"),
        ("lunge", "lunge"),
        ("chin ups", "chin up"),
        ("chin-ups", "chin up"),
        ("chin up", "chin up"),
        ("dumbbell press", "dumbbell press"),
        ("dumbell press", "dumbbell press"),
        ("metcon", "metcon"),
    )
    for marker, subject in candidates:
        if marker in lower:
            return subject
    return None


def _slug(value: str) -> str:
    return "_".join(part for part in value.lower().replace("-", " ").split() if part)


def _series_color(label: str, index: int) -> str:
    lower = label.lower()
    if any(word in lower for word in ("stress", "risk", "overdue", "missed", "calorie")):
        return RED
    if any(word in lower for word in ("energy", "protein", "mood", "complete", "consistency")):
        return GREEN
    if any(word in lower for word in ("sleep", "training", "workout", "duration", "career")):
        return BLUE
    return RGB_PALETTE[index % len(RGB_PALETTE)]


def _bar_colors(title: str, value_key: str, count: int) -> list[str]:
    base = _series_color(f"{title} {value_key}", 0)
    colors = [base for _ in range(count)]
    if colors:
        colors[-1] = GREEN
    return colors


def _base_figure(
    title: str,
    ylabel: str,
    rows: list[dict[str, Any]],
    kicker: str,
    integer_y: bool = True,
) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        width=IMAGE_WIDTH,
        height=IMAGE_HEIGHT,
        paper_bgcolor=WHITE,
        plot_bgcolor=WHITE,
        margin={"l": 78, "r": 54, "t": 132, "b": 105},
        font={"family": "Arial, sans-serif", "color": BLACK, "size": 16},
        title={
            "text": f"<span style='font-size:15px;color:{GREEN}'>{kicker.upper()}</span>"
            f"<br><span style='font-size:44px;color:{BLACK}'>{title}</span>",
            "x": 0.01,
            "xanchor": "left",
            "y": 0.96,
            "yanchor": "top",
        },
        legend={
            "orientation": "h",
            "x": 0.0,
            "y": 1.04,
            "xanchor": "left",
            "yanchor": "bottom",
            "font": {"color": BLACK, "size": 18},
        },
        hovermode=False,
    )
    fig.update_xaxes(
        showline=True,
        linecolor=BLACK,
        linewidth=1.4,
        tickfont={"color": BLACK, "size": 15},
        tickangle=-35,
        showgrid=False,
        automargin=True,
    )
    fig.update_yaxes(
        title={"text": ylabel, "font": {"color": BLACK, "size": 18}},
        showline=True,
        linecolor=BLACK,
        linewidth=1.4,
        gridcolor=BLUE_SOFT,
        griddash="solid",
        tickfont={"color": BLACK, "size": 15},
        automargin=True,
        dtick=1 if integer_y else None,
    )
    if not rows:
        fig.add_annotation(
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            text="No data yet",
            showarrow=False,
            font={"color": BLACK, "size": 22},
        )
    return fig


def _add_line(
    fig: go.Figure, x_values: list[str], values: list[float | None], label: str, color: str
) -> None:
    fig.add_trace(
        go.Scatter(
            x=x_values,
            y=values,
            mode="lines+markers",
            name=label,
            line={"color": color, "width": 4},
            marker={"color": color, "size": 12, "line": {"color": WHITE, "width": 1.5}},
            connectgaps=False,
        )
    )


def _add_bar(fig: go.Figure, x_values: list[str], values: list[float | None], colors: list[str]):
    fig.add_trace(
        go.Bar(
            x=x_values,
            y=values,
            marker={"color": colors, "line": {"color": BLUE, "width": 1}},
            width=0.62,
            showlegend=False,
        )
    )


def _add_heatmap(
    fig: go.Figure, x_values: list[str], y_values: list[str], matrix: list[list[int]]
) -> None:
    fig.add_trace(
        go.Heatmap(
            x=x_values,
            y=y_values,
            z=matrix,
            colorscale=[[0, WHITE], [1, GREEN]],
            showscale=False,
            xgap=4,
            ygap=4,
            hoverinfo="skip",
        )
    )
    fig.update_yaxes(autorange="reversed", dtick=None, gridcolor=WHITE)
    fig.update_xaxes(showgrid=False)


def _annotate_last(
    fig: go.Figure, x_values: list[str], values: list[float | None], label: str, color: str
) -> None:
    if not x_values or not values or values[-1] is None:
        return
    fig.add_annotation(
        x=x_values[-1],
        y=values[-1],
        text=f"{label}: {values[-1]:g}",
        showarrow=True,
        arrowhead=1,
        arrowcolor=color,
        ax=26,
        ay=-22,
        bgcolor=WHITE,
        bordercolor=color,
        borderwidth=2,
        borderpad=4,
        font={"color": color, "size": 16},
    )


def _annotate_peak(fig: go.Figure, x_values: list[str], values: list[float | None]) -> None:
    valid = [(x, value) for x, value in zip(x_values, values) if value is not None]
    if len(valid) < 3:
        return
    peak_x, peak_value = max(valid, key=lambda item: item[1])
    if peak_x == x_values[-1]:
        return
    fig.add_annotation(
        x=peak_x,
        y=peak_value,
        text=f"peak: {peak_value:g}",
        showarrow=False,
        yshift=18,
        bgcolor=WHITE,
        bordercolor=BLUE,
        borderwidth=1.5,
        borderpad=4,
        font={"color": BLUE, "size": 14},
    )


def _save(fig, path: Path) -> None:
    fig.write_image(str(path), format="png", width=IMAGE_WIDTH, height=IMAGE_HEIGHT, scale=1)


def _start_date(days: int) -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=days)).isoformat()


def _format_error(error: Exception) -> str:
    message = str(error).strip()
    return message or error.__class__.__name__
