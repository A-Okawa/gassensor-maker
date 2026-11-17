"""Read sessions saved by the pulse-analysis app (gas-pulse-analyzer.html) and derive per-pulse values.

The HTML app does the interactive work (splitting a recording, placing the pulses); this module
takes its session .json as it is: time series, pulse times and conditions. Pulses are never
detected again here, so figures and the analysis tables agree. The response uses the same
definition as the HTML app: medians of the raw data in a window before gas on (R0) and before
gas off (R_end); smoothing is for drawing only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import math

import numpy as np


MAX_SESSION_BYTES = 200 * 1024 * 1024
OHM_UNITS = ((1e9, "GΩ"), (1e6, "MΩ"), (1e3, "kΩ"), (1.0, "Ω"))


class SessionError(ValueError):
    """The file is not a session of the pulse-analysis app, or is damaged."""


@dataclass
class Pulse:
    index: int
    t_on: float            # s, on the run's own clock
    t_off: float
    t_purge_end: float     # next gas on, or the end of the run
    conc_ppm: float        # nan when the cylinder concentration or the flow is unknown
    role: str = "test"


@dataclass
class Run:
    name: str
    gas: str
    sample_id: str
    t: np.ndarray          # s
    r: np.ndarray          # Ω, or 1/I (arbitrary units) when the bias voltage is unknown
    in_ohm: bool
    pulses: list[Pulse] = field(default_factory=list)
    base_s: float = 30.0
    end_s: float = 30.0

    @property
    def key(self) -> str:
        return self.name


def _number(value, default=math.nan) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _series(values, name: str) -> np.ndarray:
    if not isinstance(values, list):
        raise SessionError(f"{name} is missing.")
    return np.array([math.nan if v is None else v for v in values], dtype=float)


def _gas_name(cond: dict) -> str:
    gas = str(cond.get("gas") or "")
    return str(cond.get("gas_other") or "gas") if gas == "other" else gas


def load_session(raw: bytes) -> list[Run]:
    """Runs of one session file, in the file's order. Runs without pulses or data are left out."""
    if len(raw) > MAX_SESSION_BYTES:
        raise SessionError("The session file exceeds 200 MB.")
    try:
        document = json.loads(raw.decode("utf-8-sig"))
    except (ValueError, UnicodeError) as exc:
        raise SessionError("This is not a JSON file.") from exc
    if not isinstance(document, dict) or document.get("app") != "gpa" or not isinstance(document.get("runs"), list):
        raise SessionError("This is not a session saved by the pulse-analysis app.")
    params = document.get("params") if isinstance(document.get("params"), dict) else {}
    base_s = _number(params.get("base_s"), 30.0)
    end_s = _number(params.get("end_s"), 30.0)
    runs = []
    for entry in document["runs"]:
        if not isinstance(entry, dict) or entry.get("demo"):
            continue
        cond = entry.get("cond") if isinstance(entry.get("cond"), dict) else {}
        t, y = _series(entry.get("t"), "t"), _series(entry.get("y"), "y")
        if len(t) != len(y) or len(t) < 10:
            continue
        bias = _number(cond.get("bias_V"))
        if entry.get("ykind") == "R":
            r, in_ohm = y, True
        else:
            in_ohm = bias > 0
            with np.errstate(divide="ignore", invalid="ignore"):
                r = np.where(y > 0, (bias if in_ohm else 1.0) / y, np.nan)
        cylinder, total = _number(cond.get("cylinder_ppm")), _number(cond.get("flow_total"))
        raw_pulses = sorted((p for p in entry.get("pulses") or [] if isinstance(p, dict) and p.get("role") != "purge"),
                            key=lambda p: _number(p.get("t_on"), 0.0))
        pulses = []
        for k, p in enumerate(raw_pulses):
            t_on, t_off = _number(p.get("t_on")), _number(p.get("t_off"))
            if not (t_off > t_on):
                continue
            nxt = _number(raw_pulses[k + 1].get("t_on")) if k + 1 < len(raw_pulses) else float(t[-1])
            purge_end = _number(p.get("t_pe"))
            purge_end = min(purge_end, float(t[-1])) if purge_end > t_off else nxt
            conc = _number(p.get("ppm_override"))
            if not math.isfinite(conc):
                flow = _number(p.get("flow"))
                conc = cylinder * flow / total if cylinder > 0 and total > 0 and math.isfinite(flow) else math.nan
            pulses.append(Pulse(len(pulses) + 1, t_on, t_off, purge_end, conc, str(p.get("role") or "test")))
        if not pulses:
            continue
        runs.append(Run(str(entry.get("name") or cond.get("run_id") or f"run {len(runs) + 1}"), _gas_name(cond),
                        str(cond.get("sample_id") or ""), t, r, in_ohm, pulses, base_s, end_s))
    if not runs:
        raise SessionError("The session has no run with pulses.")
    return runs


def window_median(t: np.ndarray, r: np.ndarray, start: float, stop: float) -> float:
    mask = (t >= start) & (t < stop) & np.isfinite(r)
    return float(np.median(r[mask])) if mask.any() else math.nan


def moving_mean(values: np.ndarray, points: int) -> np.ndarray:
    """Centred moving average that skips missing values (for drawing only)."""
    points = int(points)
    if points <= 1:
        return values
    ok = np.isfinite(values)
    total = np.concatenate(([0.0], np.cumsum(np.where(ok, values, 0.0))))
    count = np.concatenate(([0], np.cumsum(ok)))
    half = points // 2
    index = np.arange(len(values))
    low, high = np.maximum(index - half, 0), np.minimum(index + half + 1, len(values))
    n = count[high] - count[low]
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(n > 0, (total[high] - total[low]) / n, np.nan)


def moving_median(values: np.ndarray, points: int) -> np.ndarray:
    points = max(1, int(points))
    if points == 1:
        return values
    half = points // 2
    padded = np.pad(values, half, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, 2 * half + 1)
    with np.errstate(all="ignore"):
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            return np.nanmedian(windows, axis=1)


def sample_interval(t: np.ndarray) -> float:
    steps = np.diff(t[:2000])
    steps = steps[steps > 0]
    return float(np.median(steps)) if len(steps) else 1.0


def ohm_unit(value: float) -> tuple[float, str]:
    """(divisor, unit) so that value / divisor reads comfortably: Ω, kΩ, MΩ or GΩ."""
    for divisor, unit in OHM_UNITS:
        if abs(value) >= divisor:
            return divisor, unit
    return 1.0, "Ω"


def baseline(run: Run, pulses: list[Pulse] | None = None) -> float:
    """R_b: the median over the minute before the first exposure."""
    first = (pulses or run.pulses)[0]
    return window_median(run.t, run.r, first.t_on - 60.0, first.t_on)


def pulse_metrics(run: Run, pulses: list[Pulse] | None = None) -> list[dict]:
    """One row per pulse; times in s, responses in %."""
    pulses = pulses or run.pulses
    t, r = run.t, run.r
    smooth = moving_median(r, 15)
    r_b = baseline(run, pulses)
    rows = []
    for p in pulses:
        r0 = window_median(t, r, p.t_on - run.base_s, p.t_on)
        r_end = window_median(t, r, p.t_off - run.end_s, p.t_off)
        amplitude = r_end - r0
        sign = 1.0 if amplitude >= 0 else -1.0
        inside = (t >= p.t_on) & (t < p.t_off) & np.isfinite(smooth)
        r_peak = float((smooth[inside] * sign).max() * sign) if inside.any() else math.nan
        purge = (t >= p.t_off) & (t < p.t_purge_end) & np.isfinite(smooth)
        t50 = math.nan
        if purge.any() and amplitude:
            remaining = (smooth[purge] - r0) / amplitude
            hit = np.nonzero(remaining <= 0.5)[0]
            if len(hit):
                t50 = float(t[purge][hit[0]] - p.t_off)
        after5 = window_median(t, r, p.t_off + 285.0, p.t_off + 315.0) if p.t_purge_end >= p.t_off + 315.0 else math.nan
        rows.append({
            "run": run.name, "gas": run.gas, "sample_id": run.sample_id, "pulse": p.index, "conc_ppm": p.conc_ppm,
            "t_on_s": p.t_on, "exposure_s": p.t_off - p.t_on, "R0": r0, "R_end": r_end, "R_peak": r_peak,
            "S_end_pct": 100 * amplitude / r0 if r0 else math.nan,
            "S_peak_pct": 100 * (r_peak - r0) / r0 if r0 else math.nan,
            "baseline_shift_pct": 100 * (r0 - r_b) / r_b if r_b else math.nan,
            "t50_rec_s": t50,
            "unrecovered_5min": (after5 - r0) / amplitude if amplitude else math.nan,
            "resistance_unit": "ohm" if run.in_ohm else "a.u.",
        })
    return rows
