#!/usr/bin/env python3

from __future__ import annotations

import argparse
import datetime as dt
import html
import math
import re
import sys
from pathlib import Path


CELL_RE = re.compile(
    r'data-date="(?P<date>\d{4}-\d{2}-\d{2})"[^>]*class="ContributionCalendar-day"></td>\s*'
    r"<tool-tip[^>]*>(?P<tooltip>.*?)</tool-tip>",
    re.S,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a local SVG contribution graph from GitHub contribution calendar HTML."
    )
    parser.add_argument("--username", required=True)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--input", help="Path to saved contribution HTML. Reads stdin when omitted.")
    return parser.parse_args()


def read_html(args: argparse.Namespace) -> str:
    if args.input:
        return Path(args.input).read_text(encoding="utf-8")
    return sys.stdin.read()


def parse_count(tooltip: str) -> int:
    tooltip = html.unescape(" ".join(tooltip.split()))
    if tooltip.startswith("No contributions"):
        return 0
    match = re.match(r"(?P<count>\d+)\s+contribution", tooltip)
    if not match:
        raise ValueError(f"Could not parse contribution count from tooltip: {tooltip!r}")
    return int(match.group("count"))


def parse_contributions(source: str) -> dict[dt.date, int]:
    contributions: dict[dt.date, int] = {}
    for match in CELL_RE.finditer(source):
        day = dt.date.fromisoformat(match.group("date"))
        contributions[day] = parse_count(match.group("tooltip"))
    if not contributions:
        raise ValueError("No contribution cells were parsed from the supplied HTML.")
    return contributions


def daterange(start: dt.date, end: dt.date) -> list[dt.date]:
    span = (end - start).days
    return [start + dt.timedelta(days=offset) for offset in range(span + 1)]


def scale_value(count: int, scale_ceiling: float) -> float:
    if count <= 0 or scale_ceiling <= 0:
        return 0.0
    return math.sqrt(count) / math.sqrt(scale_ceiling)


def _endpoint_slope(
    first_step: float, second_step: float, first_secant: float, second_secant: float
) -> float:
    slope = (
        ((2 * first_step) + second_step) * first_secant
        - first_step * second_secant
    ) / (first_step + second_step)
    if slope * first_secant <= 0:
        return 0.0
    if first_secant * second_secant < 0 and abs(slope) > abs(3 * first_secant):
        return 3 * first_secant
    return slope


def _monotone_tangents(points: list[tuple[float, float]]) -> list[float]:
    if len(points) < 2:
        return [0.0 for _ in points]

    steps = [points[index + 1][0] - points[index][0] for index in range(len(points) - 1)]
    secants = [
        (points[index + 1][1] - points[index][1]) / steps[index]
        for index in range(len(points) - 1)
    ]

    if len(points) == 2:
        return [secants[0], secants[0]]

    tangents = [0.0] * len(points)
    tangents[0] = _endpoint_slope(steps[0], steps[1], secants[0], secants[1])
    tangents[-1] = _endpoint_slope(steps[-1], steps[-2], secants[-1], secants[-2])

    for index in range(1, len(points) - 1):
        previous_secant = secants[index - 1]
        next_secant = secants[index]
        if previous_secant == 0 or next_secant == 0 or previous_secant * next_secant < 0:
            tangents[index] = 0.0
            continue

        previous_step = steps[index - 1]
        next_step = steps[index]
        weight_previous = (2 * next_step) + previous_step
        weight_next = next_step + (2 * previous_step)
        tangents[index] = (weight_previous + weight_next) / (
            (weight_previous / previous_secant) + (weight_next / next_secant)
        )

    return tangents


def build_smooth_path(points: list[tuple[float, float]]) -> str:
    if not points:
        return ""
    if len(points) == 1:
        x, y = points[0]
        return f"M {x:.2f} {y:.2f}"

    tangents = _monotone_tangents(points)
    commands = [f"M {points[0][0]:.2f} {points[0][1]:.2f}"]
    for index in range(len(points) - 1):
        start_x, start_y = points[index]
        end_x, end_y = points[index + 1]
        step_x = end_x - start_x
        control_1_x = start_x + (step_x / 3)
        control_1_y = start_y + (tangents[index] * step_x / 3)
        control_2_x = end_x - (step_x / 3)
        control_2_y = end_y - (tangents[index + 1] * step_x / 3)
        commands.append(
            "C "
            f"{control_1_x:.2f} {control_1_y:.2f} "
            f"{control_2_x:.2f} {control_2_y:.2f} "
            f"{end_x:.2f} {end_y:.2f}"
        )
    return " ".join(commands)


def build_svg(
    username: str, start_date: dt.date, end_date: dt.date, counts_by_day: dict[dt.date, int]
) -> str:
    dates = daterange(start_date, end_date)
    counts = [counts_by_day.get(day, 0) for day in dates]
    total = sum(counts)
    max_count = max(counts) if counts else 0
    scale_ceiling = max_count * 1.15 if max_count else 1.0

    width = 1400
    height = 520
    margin_left = 110
    margin_right = 48
    margin_top = 92
    margin_bottom = 92
    plot_width = width - margin_left - margin_right
    plot_height = height - margin_top - margin_bottom
    baseline_y = margin_top + plot_height

    step_x = plot_width / max(len(dates) - 1, 1)
    points: list[tuple[float, float]] = []
    for index, count in enumerate(counts):
        x = margin_left + index * step_x
        y = baseline_y - scale_value(count, scale_ceiling) * plot_height
        points.append((x, y))

    line_path = build_smooth_path(points)
    area_path = (
        f"{line_path} L {points[-1][0]:.2f} {baseline_y:.2f} "
        f"L {points[0][0]:.2f} {baseline_y:.2f} Z"
    )

    tick_values = [0, 1, 5, 10, 20, max_count]
    seen: set[int] = set()
    y_ticks: list[int] = []
    for tick in tick_values:
        if tick in seen or tick > max_count:
            continue
        seen.add(tick)
        y_ticks.append(tick)
    if max_count not in seen:
        y_ticks.append(max_count)

    month_labels: list[tuple[float, str]] = []
    for index, day in enumerate(dates):
        if index == 0 or day.day == 1:
            month_labels.append((margin_left + index * step_x, day.strftime("%b")))

    week_lines = [margin_left + index * step_x for index, _ in enumerate(dates) if index % 7 == 0]

    point_titles = []
    for (x, y), day, count in zip(points, dates, counts):
        label = f"{count} contributions on {day.strftime('%B %-d, %Y')}"
        point_titles.append(
            f'<g><title>{html.escape(label)}</title><circle cx="{x:.2f}" cy="{y:.2f}" r="4.5" class="point" /></g>'
        )

    y_grid = []
    y_labels = []
    for tick in y_ticks:
        y = baseline_y - scale_value(tick, scale_ceiling) * plot_height if tick else baseline_y
        y_grid.append(
            f'<line x1="{margin_left}" y1="{y:.2f}" x2="{width - margin_right}" y2="{y:.2f}" class="grid-y" />'
        )
        y_labels.append(
            f'<text x="{margin_left - 14}" y="{y + 5:.2f}" text-anchor="end" class="axis-label">{tick}</text>'
        )

    x_grid = [
        f'<line x1="{x:.2f}" y1="{margin_top}" x2="{x:.2f}" y2="{baseline_y}" class="grid-x" />'
        for x in week_lines
    ]
    x_labels = [
        f'<text x="{x:.2f}" y="{baseline_y + 34}" text-anchor="middle" class="axis-label">{label}</text>'
        for x, label in month_labels
    ]

    subtitle = (
        f"{total} GitHub contributions from {start_date.strftime('%b %-d, %Y')} "
        f"to {end_date.strftime('%b %-d, %Y')}"
    )

    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title desc">
  <title id="title">{html.escape(username)}'s Contribution Graph</title>
  <desc id="desc">{html.escape(subtitle)}. Vertical spacing uses a compressed square-root scale with headroom so low-volume days remain visible and high-volume days are less spiky.</desc>
  <defs>
    <linearGradient id="areaFill" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0%" stop-color="#3B82F6" stop-opacity="0.35" />
      <stop offset="100%" stop-color="#3B82F6" stop-opacity="0.06" />
    </linearGradient>
  </defs>
  <style>
    .bg {{ fill: #020617; }}
    .panel {{ fill: #030d21; stroke: #0f2656; stroke-width: 1; }}
    .title {{ fill: #60A5FA; font-family: 'Segoe UI', sans-serif; font-size: 20px; font-weight: 700; }}
    .subtitle {{ fill: #93C5FD; font-family: 'Segoe UI', sans-serif; font-size: 12px; font-weight: 500; }}
    .axis-label {{ fill: #60A5FA; font-family: 'Segoe UI', sans-serif; font-size: 11px; font-weight: 600; }}
    .axis-title {{ fill: #60A5FA; font-family: 'Segoe UI', sans-serif; font-size: 13px; font-weight: 700; letter-spacing: 0.08em; }}
    .grid-x, .grid-y {{ stroke: #12306A; stroke-width: 1; stroke-dasharray: 2 4; }}
    .axis-line {{ stroke: #1D4ED8; stroke-width: 1.5; }}
    .area {{ fill: url(#areaFill); }}
    .line {{ fill: none; stroke: #3B82F6; stroke-width: 4; stroke-linecap: round; stroke-linejoin: round; }}
    .point {{ fill: #F8FAFC; stroke: #3B82F6; stroke-width: 2; }}
    .note {{ fill: #7DD3FC; font-family: 'Segoe UI', sans-serif; font-size: 11px; font-weight: 500; }}
  </style>
  <rect width="{width}" height="{height}" class="bg" rx="20" />
  <rect x="18" y="18" width="{width - 36}" height="{height - 36}" rx="18" class="panel" />
  <text x="{width / 2:.2f}" y="44" text-anchor="middle" class="title">{html.escape(username)}'s Contribution Graph</text>
  <text x="{width / 2:.2f}" y="68" text-anchor="middle" class="subtitle">{html.escape(subtitle)}</text>
  <text x="{width / 2:.2f}" y="{height - 24}" text-anchor="middle" class="note">Compressed scale keeps low-volume days visible and softens larger contribution spikes.</text>
  {''.join(y_grid)}
  {''.join(x_grid)}
  <line x1="{margin_left}" y1="{baseline_y}" x2="{width - margin_right}" y2="{baseline_y}" class="axis-line" />
  <line x1="{margin_left}" y1="{margin_top}" x2="{margin_left}" y2="{baseline_y}" class="axis-line" />
  <text x="{(margin_left + width - margin_right) / 2:.2f}" y="{baseline_y + 60}" text-anchor="middle" class="axis-title">Date</text>
  <text x="34" y="{margin_top + plot_height / 2:.2f}" text-anchor="middle" class="axis-title" transform="rotate(-90 34 {margin_top + plot_height / 2:.2f})">Contributions</text>
  {''.join(y_labels)}
  {''.join(x_labels)}
  <path d="{area_path}" class="area" />
  <path d="{line_path}" class="line" />
  {''.join(point_titles)}
</svg>
"""


def main() -> None:
    args = parse_args()
    html_source = read_html(args)
    start_date = dt.date.fromisoformat(args.start_date)
    end_date = dt.date.fromisoformat(args.end_date)
    contributions = parse_contributions(html_source)
    svg = build_svg(args.username, start_date, end_date, contributions)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(svg, encoding="utf-8")


if __name__ == "__main__":
    main()
