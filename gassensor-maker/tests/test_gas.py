"""Run with: python -m pytest tests"""
import json
import math
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from figure_style import STYLE_DEFAULTS, export_figure
from gas_io import SessionError, load_session, moving_mean, ohm_unit, pulse_metrics
from gas_plots import FIGURE_KINDS, Options, Series, build, enable_cjk_fallback
from style_templates import StyleError, decode_style_template, encode_style_template
from build_bundle import BUNDLE_FILES, create_bundle_bytes


def synthetic_session(n_pulses=3, bias=1.0, step=0.05):
    """10 kΩ sensor, 2 s sampling; each 600 s exposure raises R by step × pulse number, with full recovery."""
    t = np.arange(0, 600 + n_pulses * 1200 + 600, 2.0)
    r = np.full_like(t, 10_000.0)
    pulses = []
    for k in range(n_pulses):
        on = 600 + k * 1200
        r[(t >= on) & (t < on + 600)] *= 1 + step * (k + 1)
        pulses.append({"idx": k + 1, "role": "test", "flow": 40 * (k + 1), "ppm_override": None, "t_on": on, "t_off": on + 600, "t_pe": None})
    run = {"name": "synthetic", "ykind": "I", "t": t.tolist(), "y": (bias / r).tolist(), "pulses": pulses,
           "cond": {"gas": "NH3", "cylinder_ppm": 12.5, "flow_total": 200, "bias_V": bias, "sample_id": "S1"}}
    return json.dumps({"app": "gpa", "version": "gpa-0.6.0", "params": {"base_s": 30, "end_s": 30}, "runs": [run]}).encode()


def test_load_and_metrics():
    run, = load_session(synthetic_session())
    assert run.in_ohm and run.gas == "NH3" and len(run.pulses) == 3
    assert [p.conc_ppm for p in run.pulses] == pytest.approx([2.5, 5.0, 7.5])
    rows = pulse_metrics(run)
    assert [row["S_end_pct"] for row in rows] == pytest.approx([5.0, 10.0, 15.0])
    assert [row["S_peak_pct"] for row in rows] == pytest.approx([5.0, 10.0, 15.0])
    assert all(abs(row["baseline_shift_pct"]) < 1e-9 for row in rows)
    assert all(row["t50_rec_s"] <= 20 for row in rows)          # a step recovers at once (within the median window)


def test_current_without_bias_is_arbitrary_units():
    document = json.loads(synthetic_session())
    document["runs"][0]["cond"]["bias_V"] = None
    run, = load_session(json.dumps(document).encode())
    assert not run.in_ohm
    assert pulse_metrics(run)[0]["S_end_pct"] == pytest.approx(5.0)   # a ratio: no voltage needed


def test_missing_values_and_rejections():
    document = json.loads(synthetic_session())
    document["runs"][0]["y"][5] = None
    assert math.isnan(load_session(json.dumps(document).encode())[0].r[5])
    for raw in (b"not json", b'{"app": "other", "runs": []}', json.dumps({"app": "gpa", "runs": []}).encode()):
        with pytest.raises(SessionError):
            load_session(raw)


def test_helpers():
    assert ohm_unit(5.1e3) == (1e3, "kΩ") and ohm_unit(2.4e7) == (1e6, "MΩ") and ohm_unit(3e9) == (1e9, "GΩ") and ohm_unit(80) == (1.0, "Ω")
    values = np.array([1.0, np.nan, 3.0, 5.0])
    assert moving_mean(values, 3)[1] == pytest.approx(2.0)
    assert moving_mean(values, 1) is values


@pytest.mark.parametrize("kind", FIGURE_KINDS)
def test_every_figure_exports(kind):
    enable_cjk_fallback()
    run, = load_session(synthetic_session())
    series = [Series(run, "Nb_{2}CT_{<i>x</i>}", "#0072B2", run.pulses), Series(run, "second", "#D55E00", run.pulses[:2])]
    options = Options(x_label="Time (min)", y_label="(<i>R</i> − <i>R</i>_{b})/<i>R</i>_{b} (%)", recovery_pulse=2)
    figure = build(kind, series, options, dict(STYLE_DEFAULTS))
    assert tuple(figure.get_size_inches()) == pytest.approx((options.width, options.height))
    assert export_figure(figure, "png", 100, style=STYLE_DEFAULTS).startswith(b"\x89PNG")
    assert b"<svg" in export_figure(figure, "svg", 100, style=STYLE_DEFAULTS)
    assert export_figure(figure, "pdf", 100, style=STYLE_DEFAULTS).startswith(b"%PDF")


def test_style_template_round_trip():
    settings = {**STYLE_DEFAULTS, "fig_width": 7.0, "smooth_s": 30.0, "show_raw": True, "palette": "paper", "session_files": "ignored"}
    restored = decode_style_template(encode_style_template(settings))
    assert restored["fig_width"] == 7.0 and restored["palette"] == "paper" and "session_files" not in restored
    with pytest.raises(StyleError):
        decode_style_template(b'{"format": "xrd-maker-style", "version": 1, "settings": {}}')


def test_bundle_has_every_listed_file():
    root = Path(__file__).resolve().parents[1]
    assert all((root / name).is_file() for name in BUNDLE_FILES)
    assert create_bundle_bytes().startswith(b"PK")
