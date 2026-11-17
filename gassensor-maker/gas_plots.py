"""Figures of gas-sensor runs: stacked resistance, overlay, values against concentration, recovery.

Every builder returns a matplotlib Figure of the requested size; margins, fonts and line widths
of the frame come from figure_style (apply_mpl_style / export_figure), as in the other Maker apps.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import matplotlib as mpl
from matplotlib import font_manager
from matplotlib.figure import Figure
from matplotlib.ticker import AutoMinorLocator, MaxNLocator

import figure_style
from figure_style import font_rcparams, validate_style_settings
from gas_io import Run, Pulse, baseline, moving_mean, ohm_unit, pulse_metrics, sample_interval, window_median
from rich_text import rich


TIME_UNITS = {"min": 60.0, "s": 1.0, "h": 3600.0}
# Japanese labels: the bundled Liberation fonts have no kana or kanji, so a Japanese font installed
# on the computer (or fonts-noto-cjk on Streamlit Cloud, see packages.txt) is added as a fallback.
CJK_CANDIDATES = ("Noto Sans CJK JP", "Hiragino Sans", "Yu Gothic", "Meiryo", "IPAexGothic", "IPAGothic",
                  "Noto Sans JP", "MS Gothic")
METRICS = ("S_peak_pct", "S_end_pct", "t50_rec_s", "unrecovered_5min", "baseline_shift_pct")
SHADE = "#000000"
SHADE_ALPHA = 0.08


def cjk_font() -> str | None:
    for family in CJK_CANDIDATES:
        try:
            font_manager.findfont(font_manager.FontProperties(family=[family]), fallback_to_default=False)
            return family
        except (ValueError, OSError, RuntimeError):
            continue
    return None


def enable_cjk_fallback() -> str | None:
    """Let figure_style fall back to a Japanese font for characters the chosen font lacks."""
    family = cjk_font()
    extra = [family] if family else []
    figure_style.font_family_list = lambda chosen: list(dict.fromkeys([chosen, figure_style.GLYPH_FALLBACK, *extra]))
    return family


@dataclass
class Series:
    run: Run
    label: str
    color: str
    pulses: list[Pulse]


@dataclass
class Options:
    width: float = 88 / 25.4          # inches
    height: float = 70 / 25.4
    font_size: float = 7.0
    tick_font_size: float = 6.5
    legend_font_size: float = 6.5
    time_unit: str = "min"
    align: bool = True                # time from each run's first exposure
    lead: float = 10.0                # shown before the first exposure, in the time unit
    smooth_s: float = 30.0            # moving average for the drawn line; 0 = raw only
    show_raw: bool = True
    raw_alpha: float = 0.3
    shade: bool = True
    conc_labels: bool = True
    response_labels: bool = True
    show_legend: bool = True
    x_label: str = ""
    y_label: str = ""
    metric: str = "S_peak_pct"
    recovery_pulse: int = 1
    marker_size: float = 4.0


def _axes_style(ax, style, opts, last_row=True):
    direction = "in" if style["tick_direction"] in ("auto", "in") else "out"
    ax.tick_params(which="both", direction=direction, labelsize=opts.tick_font_size,
                   top=style["axes_box"], right=style["axes_box"])
    ax.xaxis.set_minor_locator(AutoMinorLocator(2))
    ax.yaxis.set_minor_locator(AutoMinorLocator(2))
    if not style["axes_box"]:
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)


def _time(series: Series, opts: Options):
    """(x, x of gas on/off per pulse, x range) of a run on the figure's time axis."""
    unit = TIME_UNITS[opts.time_unit]
    run, pulses = series.run, series.pulses
    origin = pulses[0].t_on if opts.align else 0.0
    x = (run.t - origin) / unit
    last = pulses[-1]
    stop = (last.t_purge_end - origin) / unit
    start = -opts.lead if opts.align else max(x[0], (pulses[0].t_on - origin) / unit - opts.lead)
    start = max(start, x[0])
    spans = [((p.t_on - origin) / unit, (p.t_off - origin) / unit) for p in pulses]
    return x, spans, (start, min(stop, x[-1]))


def _conc_text(value: float) -> str:
    return "" if not math.isfinite(value) else f"{value:g} ppm"


def _same_schedule(series: list[Series]) -> bool:
    return len({(s.run.gas, tuple(round(p.conc_ppm, 6) if math.isfinite(p.conc_ppm) else None for p in s.pulses))
                for s in series}) == 1


def _new_figure(opts: Options, style: dict) -> Figure:
    return Figure(figsize=(opts.width, opts.height))


def _finish(fig, style):
    figure_style.apply_mpl_style(fig, style)
    return fig


def stacked_resistance(series: list[Series], opts: Options, style_settings=None) -> Figure:
    """Raw resistance of each run in its own panel, joined by axis breaks; unit chosen per run."""
    style = validate_style_settings(style_settings, fill_defaults=True)
    with mpl.rc_context(font_rcparams(style)):
        fig = _new_figure(opts, style)
        n = len(series)
        same = _same_schedule(series)
        # Different gases or concentrations: each panel carries its own labels, in the gap above it.
        own_labels = opts.conc_labels and not same
        gap_in = (opts.tick_font_size * 1.5 + 2) / 72 if own_labels else 0.07
        panel_in = max(0.2, (opts.height * (style["margin_top"] - style["margin_bottom"]) - gap_in * (n - 1)) / n)
        grid = fig.add_gridspec(n, 1, hspace=gap_in / panel_in)
        ranges = [_time(s, opts) for s in series]
        x_min, x_max = min(r[2][0] for r in ranges), max(r[2][1] for r in ranges)
        for k, (s, (x, spans, _)) in enumerate(zip(series, ranges)):
            ax = fig.add_subplot(grid[k, 0])
            run = s.run
            visible = (x >= x_min) & (x <= x_max) & np.isfinite(run.r)
            values = run.r[visible]
            low, high = (np.percentile(values, [0.3, 99.7]) if len(values) else (0.0, 1.0))
            if not high > low:
                high = low + 1.0
            divisor, unit = ohm_unit(high) if run.in_ohm else (10.0 ** math.floor(math.log10(abs(high) or 1.0)), "a.u.")
            pad = 0.12 * (high - low)
            smooth = moving_mean(run.r, round(opts.smooth_s / sample_interval(run.t))) if opts.smooth_s > 0 else None
            if opts.shade:
                for a, b in spans:
                    ax.axvspan(a, b, color=SHADE, alpha=SHADE_ALPHA, lw=0)
            if smooth is None or opts.show_raw:
                ax.plot(x, run.r / divisor, color=s.color, lw=style["line_width"] * (0.6 if smooth is not None else 1.0),
                        alpha=opts.raw_alpha if smooth is not None else 1.0)
            if smooth is not None:
                ax.plot(x, smooth / divisor, color=s.color, lw=style["line_width"])
            ax.set_xlim(x_min, x_max)
            ax.set_ylim((low - pad) / divisor, (high + pad) / divisor)
            ax.yaxis.set_major_locator(MaxNLocator(4))
            _axes_style(ax, style, opts)
            ax.text(0.012, 0.95, rich(f"{s.label} ({unit})"), transform=ax.transAxes, ha="left", va="top",
                    fontsize=opts.legend_font_size, bbox={"facecolor": "white", "edgecolor": "none", "alpha": 0.75, "pad": 1.0})
            rows = pulse_metrics(run, s.pulses)
            for (a, b), row, p in zip(spans, rows, s.pulses):
                if opts.response_labels and math.isfinite(row["S_end_pct"]):
                    value = row["S_end_pct"]
                    ax.text(b, 0.04, f"{value:+.{0 if abs(value) >= 10 else 1}f}% ", transform=ax.get_xaxis_transform(),
                            ha="right", va="bottom", fontsize=opts.tick_font_size, color=s.color)
                if opts.conc_labels and (k == 0 or not same) and a >= x_min:
                    ax.text((a + b) / 2, 1.0, " " + _conc_text(p.conc_ppm), transform=ax.get_xaxis_transform(),
                            ha="center", va="bottom", fontsize=opts.tick_font_size, linespacing=0.9)
            marks = {"marker": [(-1, -0.6), (1, 0.6)], "markersize": 6, "linestyle": "none", "color": "k",
                     "mec": "k", "mew": style["axes_line_width"], "clip_on": False}
            if k < n - 1:
                ax.spines["bottom"].set_visible(False)
                ax.tick_params(which="both", bottom=False, labelbottom=False)
                ax.plot([0, 1], [0, 0], transform=ax.transAxes, **marks)
            if k > 0:
                ax.spines["top"].set_visible(False)
                ax.tick_params(which="both", top=False)
                ax.plot([0, 1], [1, 1], transform=ax.transAxes, **marks)
            if k == n - 1:
                ax.set_xlabel(rich(opts.x_label), fontsize=opts.font_size)
        fig.supylabel(rich(opts.y_label), fontsize=opts.font_size, x=0.015)
        return _finish(fig, style)


def overlay(series: list[Series], opts: Options, style_settings=None) -> Figure:
    """(R − R_b)/R_b of every run on one axis; R_b is the level before the first exposure."""
    style = validate_style_settings(style_settings, fill_defaults=True)
    with mpl.rc_context(font_rcparams(style)):
        fig = _new_figure(opts, style)
        ax = fig.add_subplot(111)
        ranges = [_time(s, opts) for s in series]
        x_min, x_max = min(r[2][0] for r in ranges), max(r[2][1] for r in ranges)
        if opts.shade:
            for (a, b), p in zip(ranges[0][1], series[0].pulses):
                ax.axvspan(a, b, color=SHADE, alpha=SHADE_ALPHA, lw=0)
                if opts.conc_labels and _same_schedule(series):
                    ax.text((a + b) / 2, 1.0, _conc_text(p.conc_ppm), transform=ax.get_xaxis_transform(),
                            ha="center", va="bottom", fontsize=opts.tick_font_size)
        ax.axhline(0, color="0.6", lw=style["axes_line_width"], zorder=0)
        for s, (x, _, (start, stop)) in zip(series, ranges):
            r_b = baseline(s.run, s.pulses)
            y = 100 * (s.run.r - r_b) / r_b
            keep = (x >= start) & (x <= stop)
            if opts.smooth_s > 0:
                smooth = moving_mean(y, round(opts.smooth_s / sample_interval(s.run.t)))
                if opts.show_raw:
                    ax.plot(x[keep], y[keep], color=s.color, lw=style["line_width"] * 0.6, alpha=opts.raw_alpha)
                ax.plot(x[keep], smooth[keep], color=s.color, lw=style["line_width"], label=rich(s.label))
            else:
                ax.plot(x[keep], y[keep], color=s.color, lw=style["line_width"], label=rich(s.label))
        ax.set_xlim(x_min, x_max)
        ax.set_xlabel(rich(opts.x_label), fontsize=opts.font_size)
        ax.set_ylabel(rich(opts.y_label), fontsize=opts.font_size)
        _axes_style(ax, style, opts)
        if opts.show_legend:
            ax.legend(frameon=False, fontsize=opts.legend_font_size, loc="upper left", handlelength=1.6)
        return _finish(fig, style)


def metric_plot(series: list[Series], opts: Options, style_settings=None, against: str = "conc") -> Figure:
    """A per-pulse value against concentration, or the baseline shift against time."""
    style = validate_style_settings(style_settings, fill_defaults=True)
    unit = TIME_UNITS[opts.time_unit]
    with mpl.rc_context(font_rcparams(style)):
        fig = _new_figure(opts, style)
        ax = fig.add_subplot(111)
        for s in series:
            rows = pulse_metrics(s.run, s.pulses)
            if against == "time":
                origin = s.pulses[0].t_on if opts.align else 0.0
                xs = [(row["t_on_s"] - origin) / unit for row in rows]
                ys = [row["baseline_shift_pct"] for row in rows]
                last = s.pulses[-1]
                r_b = baseline(s.run, s.pulses)
                end = window_median(s.run.t, s.run.r, last.t_purge_end - s.run.end_s, last.t_purge_end)
                xs.append((last.t_purge_end - origin) / unit)
                ys.append(100 * (end - r_b) / r_b if r_b else math.nan)
            else:
                xs = [row["conc_ppm"] for row in rows]
                ys = [row[opts.metric] for row in rows]
            ax.plot(xs, ys, "-o" if against == "conc" else "-s", color=s.color, lw=style["line_width"], ms=opts.marker_size,
                    mec="white", mew=0.6, label=rich(s.label))
        if against == "time" or opts.metric in ("baseline_shift_pct", "unrecovered_5min"):
            ax.axhline(0, color="0.6", lw=style["axes_line_width"], zorder=0)
        if against == "conc":
            ax.set_xlim(left=0)
            if opts.metric in ("S_peak_pct", "S_end_pct", "t50_rec_s") and ax.get_ylim()[0] >= 0:
                ax.set_ylim(bottom=0)
        ax.set_xlabel(rich(opts.x_label), fontsize=opts.font_size)
        ax.set_ylabel(rich(opts.y_label), fontsize=opts.font_size)
        _axes_style(ax, style, opts)
        if opts.show_legend:
            ax.legend(frameon=False, fontsize=opts.legend_font_size, handlelength=1.6)
        return _finish(fig, style)


def recovery(series: list[Series], opts: Options, style_settings=None) -> Figure:
    """Recovery after one pulse, with the response amplitude scaled to 1."""
    style = validate_style_settings(style_settings, fill_defaults=True)
    unit = TIME_UNITS[opts.time_unit]
    with mpl.rc_context(font_rcparams(style)):
        fig = _new_figure(opts, style)
        ax = fig.add_subplot(111)
        x_max = 0.0
        for s in series:
            if opts.recovery_pulse > len(s.pulses):
                continue
            p, run = s.pulses[opts.recovery_pulse - 1], s.run
            r0 = window_median(run.t, run.r, p.t_on - run.base_s, p.t_on)
            amplitude = window_median(run.t, run.r, p.t_off - run.end_s, p.t_off) - r0
            if not amplitude:
                continue
            lead = min(120.0, p.t_off - p.t_on)
            keep = (run.t >= p.t_off - lead) & (run.t < p.t_purge_end - 2 * sample_interval(run.t))
            x, y = (run.t[keep] - p.t_off) / unit, (run.r[keep] - r0) / amplitude
            x_max = max(x_max, x[-1] if len(x) else 0.0)
            if opts.smooth_s > 0:
                smooth = moving_mean(y, round(opts.smooth_s / sample_interval(run.t)))
                if opts.show_raw:
                    ax.plot(x, y, color=s.color, lw=style["line_width"] * 0.6, alpha=opts.raw_alpha)
                ax.plot(x, smooth, color=s.color, lw=style["line_width"], label=rich(s.label))
            else:
                ax.plot(x, y, color=s.color, lw=style["line_width"], label=rich(s.label))
        for level, line in ((0.0, "-"), (0.5, ":")):
            ax.axhline(level, color="0.6", lw=style["axes_line_width"], ls=line, zorder=0)
        ax.axvline(0, color="0.6", lw=style["axes_line_width"], zorder=0)
        if x_max > 0:
            ax.set_xlim(right=x_max)
        ax.set_xlabel(rich(opts.x_label), fontsize=opts.font_size)
        ax.set_ylabel(rich(opts.y_label), fontsize=opts.font_size)
        _axes_style(ax, style, opts)
        if opts.show_legend:
            ax.legend(frameon=False, fontsize=opts.legend_font_size, handlelength=1.6)
        return _finish(fig, style)


FIGURE_KINDS = ("stack", "overlay", "metric", "baseline", "recovery")


def build(kind: str, series: list[Series], opts: Options, style_settings=None) -> Figure:
    if not series:
        raise ValueError("No run is selected.")
    if kind == "stack":
        return stacked_resistance(series, opts, style_settings)
    if kind == "overlay":
        return overlay(series, opts, style_settings)
    if kind == "metric":
        return metric_plot(series, opts, style_settings, "conc")
    if kind == "baseline":
        return metric_plot(series, opts, style_settings, "time")
    if kind == "recovery":
        return recovery(series, opts, style_settings)
    raise ValueError("Unknown figure kind.")
