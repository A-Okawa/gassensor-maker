import streamlit as st
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import inspect
import math
import os
from pathlib import Path

from figure_style import (
    STYLE_DEFAULTS, STYLE_KEYS, FIGURE_PRESETS_MM, FONT_FAMILIES, METRIC_COMPATIBLE, mm_to_inches, inches_to_mm,
    export_figure, resolve_font, validate_style_settings,
)
from palettes import PALETTES, PALETTE_NAMES, DEFAULT_PALETTE, palette_colors, load_colors, color_emoji
from i18n import LANGUAGES
from style_templates import encode_style_template, decode_style_template, clean_settings, StyleError
from gas_io import SessionError, load_session, pulse_metrics
from gas_plots import FIGURE_KINDS, METRICS, TIME_UNITS, Options, Series, build, enable_cjk_fallback


LOCAL_MODE = os.environ.get("GASSENSOR_MAKER_LOCAL") == "1"
COLORS_FILE = Path(__file__).resolve().parent / "colors.csv"

st.set_page_config(page_title="Gas Sensor Maker", page_icon="📈", layout="wide")
_IMAGE_PARAMETERS = inspect.signature(st.image).parameters
FULL_WIDTH_IMAGE = ({"width": "stretch"} if "int" not in str(_IMAGE_PARAMETERS["width"].annotation)
                    else {"use_container_width": True} if "use_container_width" in _IMAGE_PARAMETERS
                    else {"use_column_width": True})


def _full_width(widget):
    width = inspect.signature(widget).parameters.get("width")
    return {"width": "stretch"} if width is not None and isinstance(width.default, str) else {"use_container_width": True}


FULL_WIDTH = {name: _full_width(getattr(st, name)) for name in ("button", "download_button", "dataframe")}

# ===== 言語選択 / Language selection =====
_lang_option = st.sidebar.radio("🌐 Language / 言語", list(LANGUAGES), horizontal=True, key="lang_radio")
_lang_code = LANGUAGES.get(_lang_option, "ja")


def ui(ja, en):
    return ja if _lang_code == "ja" else en


# ===== パスワード認証（secrets に password があるときだけ） =====
def check_password():
    if LOCAL_MODE or st.session_state.get("authenticated"):
        return True
    try:
        password = st.secrets.get("password", "")
    except Exception:
        password = ""
    if not password:
        return True
    st.title("📈 Gas Sensor Maker")
    entered = st.text_input(ui("パスワードを入力してください", "Enter the password"), type="password")
    if st.button(ui("ログイン", "Log in")):
        if entered == password:
            st.session_state["authenticated"] = True
            st.rerun()
        else:
            st.error(ui("パスワードが違います", "Wrong password"))
    return False


if not check_password():
    st.stop()

st.title("Gas Sensor Maker")
st.caption(ui("パルス解析アプリのセッションから論文用の図を作成 · 抵抗値の積み上げ・重ね合わせ・濃度依存・回復 · PDF / SVG / TIFF / PNG",
              "Publication figures from pulse-analysis sessions · stacked resistance, overlay, concentration dependence, recovery · PDF / SVG / TIFF / PNG"))
if LOCAL_MODE:
    st.caption(ui("PC 版 · データはこの PC の中だけで扱います。", "Desktop edition · data stay on this computer."))

_cjk = enable_cjk_fallback()

# ===== 既定値 =====
DEFAULTS = {"fig_width": mm_to_inches(180.0), "fig_height": mm_to_inches(120.0), "dpi_export": 300,
            "font_size": 11.0, "tick_font_size": 11.0, "legend_font_size": 11.0, "figure_kind": "stack",
            "figure_language": "en", "time_unit": "min", "align": True, "lead": 10.0, "n_pulses": 0, "smooth_s": 30.0,
            "show_raw": True, "raw_alpha": 0.3, "shade": True, "conc_labels": True, "response_labels": True,
            "show_legend": True, "metric": "S_peak_pct", "recovery_pulse": 1, "marker_size": 5.0,
            "palette": DEFAULT_PALETTE, "palette_reverse": False, "x_label": "", "y_label": "", "figure_preset": "double"}
for _key, _value in {**STYLE_DEFAULTS, **DEFAULTS}.items():
    st.session_state.setdefault(_key, _value)


def _apply_figure_preset():
    name = st.session_state["figure_preset"]
    preset = FIGURE_PRESETS_MM.get(name)
    if preset:
        st.session_state["fig_width"], st.session_state["fig_height"] = map(mm_to_inches, preset)
        if name == "figapp":
            st.session_state.update(font_family="Arial", font_size=7.0, tick_font_size=6.5, legend_font_size=6.5,
                line_width=0.9, axes_line_width=0.5, tick_length=2.5, tick_direction="out", axes_box=False,
                marker_size=3.5, margin_left=.13, margin_right=.98, margin_bottom=.14, margin_top=.95)
        else:
            compact = name == "single"
            size = 9.0 if compact else 11.0
            st.session_state.update(font_size=size, tick_font_size=size, legend_font_size=size,
                marker_size=4.0 if compact else 5.0,
                margin_left=.17 if compact else .10, margin_bottom=.18 if compact else .12, margin_top=.93 if compact else .95)
    st.session_state.pop("_size_signature", None)


def _update_figure_dimension(axis):
    value = st.session_state[f"_figure_{axis}"]
    st.session_state[f"fig_{axis}"] = mm_to_inches(value) if st.session_state["size_unit"] == "mm" else value
    st.session_state["figure_preset"] = "custom"


def _update_margin(key):
    value = st.session_state[f"_percent_{key}"] / 100
    st.session_state[key] = 1 - value if key in ("margin_right", "margin_top") else value


def _open_style_template():
    upload = st.session_state.get("_style_upload")
    if upload is None:
        return
    try:
        settings = decode_style_template(upload.getvalue())
        clean_settings({**{key: st.session_state[key] for key in STYLE_KEYS if key in st.session_state}, **settings})
        st.session_state.update(settings)
        st.session_state["figure_preset"] = "custom"
        st.session_state.pop("_size_signature", None)
        st.session_state["_style_loaded"] = True
        st.session_state.pop("_style_error", None)
    except (StyleError, ValueError) as exc:
        st.session_state["_style_error"] = str(exc)


@st.cache_data(show_spinner=False)
def read_session(raw: bytes):
    return load_session(raw)


# ===== データ =====
st.sidebar.header(ui("📂 データ", "📂 Data"))
uploads = st.sidebar.file_uploader(
    ui("セッション (.json)", "Session (.json)"), type=["json"], accept_multiple_files=True, key="session_files",
    help=ui("パルス解析アプリ（gas-pulse-analyzer.html）の「セッション保存」で書き出したファイル。複数可。",
            "Files written by 'Save session' of the pulse-analysis app (gas-pulse-analyzer.html). Several files are accepted."))
runs = []
for _upload in uploads or []:
    try:
        for _run in read_session(_upload.getvalue()):
            _name, _n = _run.name, 2
            while any(r.name == _name for r in runs):
                _name, _n = f"{_run.name} ({_n})", _n + 1
            _run.name = _name
            runs.append(_run)
    except SessionError as _error:
        st.sidebar.error(f"{_upload.name}: " + ui("セッションを読み込めません。", "Could not read the session.") + f" {_error}")

# ===== 図の種類 =====
KIND_NAMES = {"stack": ui("抵抗値の積み上げ（生データ）", "Stacked resistance (raw data)"),
              "overlay": ui("抵抗変化率の重ね合わせ", "Overlay of relative resistance change"),
              "metric": ui("濃度に対する値", "Value against concentration"),
              "baseline": ui("ベースライン変化", "Baseline shift"),
              "recovery": ui("回復曲線", "Recovery curve")}
METRIC_NAMES = {"S_peak_pct": ui("最大応答 (%)", "Peak response (%)"), "S_end_pct": ui("導入終了時の応答 S (%)", "Response at gas off, S (%)"),
                "t50_rec_s": ui("回復時間 t50 (s)", "Recovery time t50 (s)"),
                "unrecovered_5min": ui("5 min 後の未回復率", "Unrecovered fraction after 5 min"),
                "baseline_shift_pct": ui("ベースライン変化 (%)", "Baseline shift (%)")}
st.sidebar.header(ui("📊 図の種類", "📊 Figure"))
kind = st.sidebar.selectbox(ui("図の種類", "Figure type"), list(FIGURE_KINDS), format_func=KIND_NAMES.get, key="figure_kind")
if kind == "metric":
    st.sidebar.selectbox(ui("縦軸の値", "Value"), list(METRICS), format_func=METRIC_NAMES.get, key="metric")
if kind == "recovery":
    st.sidebar.number_input(ui("何本目のパルスの回復か", "Recovery after pulse no."), 1, 50, step=1, key="recovery_pulse")
st.sidebar.number_input(ui("使うパルス数（先頭から。0 = すべて）", "Pulses used (from the first; 0 = all)"), 0, 50, step=1, key="n_pulses")

st.sidebar.header(ui("⚙️ 表示", "⚙️ Display"))
st.sidebar.radio(ui("図の中の言語（軸ラベルの初期値）", "Language in the figure (default axis titles)"), ["en", "ja"],
                 format_func={"en": "English", "ja": "日本語"}.get, horizontal=True, key="figure_language")
if st.session_state["figure_language"] == "ja" and not _cjk:
    st.sidebar.warning(ui("この環境には日本語フォントがありません。日本語の文字は表示されません。",
                          "No Japanese font is installed here; Japanese characters will not be drawn."))
if kind != "metric":
    st.sidebar.radio(ui("時間の単位", "Time unit"), list(TIME_UNITS), horizontal=True, key="time_unit")
if kind in ("stack", "overlay", "baseline"):
    st.sidebar.checkbox(ui("初回導入を 0 に揃える", "Start time at the first exposure"), key="align")
if kind in ("stack", "overlay"):
    st.sidebar.number_input(ui("初回導入の前に表示する時間", "Time shown before the first exposure"), 0.0, 600.0, step=1.0, key="lead")
if kind in ("stack", "overlay", "recovery"):
    st.sidebar.number_input(ui("平滑化の窓幅 (s)（0 = なし）", "Smoothing window (s) (0 = none)"), 0.0, 600.0, step=2.0, key="smooth_s",
                            help=ui("表示用の移動平均です。応答 % などの値は平滑化前のデータから計算します。",
                                    "A moving average for display. Response values are computed from the unsmoothed data."))
    st.sidebar.checkbox(ui("生データを半透明で重ねる", "Draw the raw data underneath"), key="show_raw")
    st.sidebar.slider(ui("生データの濃さ", "Raw data opacity"), 0.05, 1.0, step=0.05, key="raw_alpha")
if kind in ("stack", "overlay"):
    st.sidebar.checkbox(ui("導入区間に網掛け", "Shade the exposures"), key="shade")
    st.sidebar.checkbox(ui("濃度ラベル", "Concentration labels"), key="conc_labels")
if kind == "stack":
    st.sidebar.checkbox(ui("応答 % のラベル", "Response % labels"), key="response_labels")
if kind != "stack":
    st.sidebar.checkbox(ui("凡例", "Legend"), key="show_legend")
if kind in ("metric", "baseline"):
    st.sidebar.number_input(ui("マーカーの大きさ (pt)", "Marker size (pt)"), 1.0, 12.0, step=0.5, key="marker_size")

st.sidebar.subheader(ui("色", "Colours"))
st.sidebar.selectbox(ui("色の組み合わせ", "Palette"), list(PALETTES), format_func=PALETTE_NAMES[_lang_code].get, key="palette")
st.sidebar.checkbox(ui("順番を逆にする", "Reverse the order"), key="palette_reverse")


def default_labels(kind, language):
    unit = st.session_state["time_unit"]
    ja = language == "ja"
    time = ((f"初回暴露からの時間 ({unit})" if ja else f"Time from first exposure ({unit})") if st.session_state["align"]
            else (f"時間 ({unit})" if ja else f"Time ({unit})"))
    conc = "濃度 (ppm)" if ja else "Concentration (ppm)"
    delta = "(<i>R</i> − <i>R</i>_{b})/<i>R</i>_{b} (%)"
    metric = {"S_peak_pct": ("最大応答 (%)", "Peak response (%)"), "S_end_pct": ("応答 (%)", "Response (%)"),
              "t50_rec_s": ("回復時間 <i>t</i>_{50} (s)", "Recovery time <i>t</i>_{50} (s)"),
              "unrecovered_5min": ("5 min 後の未回復率", "Unrecovered fraction after 5 min"),
              "baseline_shift_pct": ("ベースライン変化 (%)", "Baseline shift (%)")}[st.session_state["metric"]][0 if ja else 1]
    return {"stack": (time, "抵抗" if ja else "Resistance"), "overlay": (time, delta), "metric": (conc, metric),
            "baseline": (time, "ベースライン変化 (%)" if ja else "Baseline shift (%)"),
            "recovery": (f"ガス停止からの時間 ({unit})" if ja else f"Time after gas off ({unit})",
                         "(<i>R</i> − <i>R</i>_{0})/(<i>R</i>_{off} − <i>R</i>_{0})")}[kind]


_default_x, _default_y = default_labels(kind, st.session_state["figure_language"])
st.sidebar.subheader(ui("軸のラベル", "Axis labels"))
st.sidebar.text_input(ui("横軸（空欄 = 初期値）", "x axis (empty = default)"), key="x_label", placeholder=_default_x)
st.sidebar.text_input(ui("縦軸（空欄 = 初期値）", "y axis (empty = default)"), key="y_label", placeholder=_default_y)
st.sidebar.caption(ui("書き方：`<i>R</i>` 斜体、`_{2}` 下付き、`^{3+}` 上付き。", "Markup: `<i>R</i>` italic, `_{2}` subscript, `^{3+}` superscript."))

# ===== 図の大きさ =====
st.sidebar.header(ui("📐 図の大きさ", "📐 Figure size"))
st.sidebar.selectbox(ui("論文図のひな形", "Publication figure preset"), list(FIGURE_PRESETS_MM),
    format_func=lambda key: {"custom": ui("自由指定", "Custom"),
        "single": ui("1段幅の例 · 85 × 70 mm", "Single column example · 85 × 70 mm"),
        "double": ui("2段幅の例 · 180 × 120 mm", "Double column example · 180 × 120 mm"),
        "figapp": ui("グラフ描画appと同じ体裁 · 88 × 70 mm", "Graph app look · 88 × 70 mm")}[key],
    key="figure_preset", on_change=_apply_figure_preset)
size_unit = st.sidebar.radio(ui("寸法の単位", "Size unit"), ["mm", "inch"], horizontal=True, key="size_unit")
_signature = (size_unit, st.session_state["fig_width"], st.session_state["fig_height"])
if st.session_state.get("_size_signature") != _signature:
    for _axis in ("width", "height"):
        _value = st.session_state[f"fig_{_axis}"]
        st.session_state[f"_figure_{_axis}"] = inches_to_mm(_value) if size_unit == "mm" else _value
    st.session_state["_size_signature"] = _signature
for _axis, _label in (("width", ui("図の幅", "Figure width")), ("height", ui("図の高さ", "Figure height"))):
    st.sidebar.number_input(f"{_label} ({size_unit})", min_value=25.0 if size_unit == "mm" else 25 / 25.4,
        max_value=508.0 if size_unit == "mm" else 20.0, step=1.0 if size_unit == "mm" else 0.1,
        format="%.2f", key=f"_figure_{_axis}", on_change=_update_figure_dimension, args=(_axis,))
fig_width, fig_height = st.session_state["fig_width"], st.session_state["fig_height"]
dpi_export = st.sidebar.selectbox(ui("出力 DPI", "Output DPI"), [300, 600], key="dpi_export")
st.sidebar.caption(ui("文字の大きさ (pt)", "Text sizes (pt)"))
_size_columns = st.sidebar.columns(3)
for _column, _key, _label in ((_size_columns[0], "font_size", ui("軸ラベル", "Axis labels")),
                              (_size_columns[1], "tick_font_size", ui("目盛り", "Ticks")),
                              (_size_columns[2], "legend_font_size", ui("凡例", "Legend"))):
    _column.number_input(_label, min_value=4.0, max_value=28.0, step=0.5, format="%.1f", key=_key)
with st.sidebar.expander(ui("線・フォント・余白", "Lines, fonts and margins")):
    st.selectbox(ui("フォント", "Font family"), list(FONT_FAMILIES), key="font_family")
    _actual_font = resolve_font(st.session_state["font_family"])
    if _actual_font != st.session_state["font_family"]:
        if _actual_font in METRIC_COMPATIBLE.get(st.session_state["font_family"], ()):
            st.caption(ui("この環境には {requested} がないため、字幅が同じ {actual} で描きます。SVG には {requested} と書き込みます。",
                          "{requested} is not installed here, so {actual} (same character widths) is used. SVG files name {requested}.")
                       .format(requested=st.session_state["font_family"], actual=_actual_font))
        else:
            st.caption(ui("この環境では {actual} を使用します。", "This environment uses {actual}.").format(actual=_actual_font))
    for _key, _label in (("line_width", ui("曲線の線幅 (pt)", "Curve line width (pt)")),
                        ("axes_line_width", ui("軸・目盛りの線幅 (pt)", "Axes and tick width (pt)"))):
        st.number_input(_label, .1, 5., step=.1, key=_key)
    st.number_input(ui("目盛りの長さ (pt)", "Tick length (pt)"), .5, 10., step=.5, key="tick_length")
    st.selectbox(ui("目盛りの向き", "Tick direction"), ["auto", "in", "out"], key="tick_direction",
                 format_func=lambda value: {"auto": ui("内向き（初期値）", "Inward (default)"), "in": ui("内向き", "Inward"), "out": ui("外向き", "Outward")}[value])
    st.checkbox(ui("上と右の枠線を描く", "Draw the top and right frame"), key="axes_box")
    for _key, _label in (("margin_left", ui("左余白 (%)", "Left margin (%)")), ("margin_right", ui("右余白 (%)", "Right margin (%)")),
                        ("margin_bottom", ui("下余白 (%)", "Bottom margin (%)")), ("margin_top", ui("上余白 (%)", "Top margin (%)"))):
        _fraction = st.session_state[_key]
        st.session_state[f"_percent_{_key}"] = round(100 * (1 - _fraction if _key in ("margin_right", "margin_top") else _fraction), 8)
        st.number_input(_label, 0., 100., step=1., key=f"_percent_{_key}", on_change=_update_margin, args=(_key,))
    st.checkbox(ui("背景を透明にする", "Transparent background"), key="transparent_background")
    st.checkbox(ui("SVGの文字を編集可能にする", "Keep SVG text editable"), key="svg_text_editable")
plot_style = {key: st.session_state[key] for key in STYLE_KEYS}
try:
    plot_style = validate_style_settings(plot_style, fill_defaults=True)
except ValueError:
    st.sidebar.error(ui("余白の合計が100%未満になるよう調整してください。", "Adjust opposing margins so their sum is below 100%."))
    st.stop()

with st.sidebar.expander(ui("作図スタイルの保存・読み込み", "Save and load figure styles")):
    st.caption(ui("寸法・線・フォント・表示の設定を再利用できます。データやラベルは含みません。",
                  "Reuse dimensions, lines, fonts and display settings. Styles do not include data or labels."))
    st.file_uploader(ui("スタイルを開く (.json)", "Open figure style (.json)"), type=["json"], key="_style_upload", on_change=_open_style_template)
    if st.session_state.pop("_style_loaded", False):
        st.success(ui("作図スタイルを読み込みました。", "Figure style loaded."))
    if st.session_state.get("_style_error"):
        st.error(st.session_state["_style_error"])
    st.download_button(ui("スタイルを保存 (.json)", "Save figure style (.json)"), encode_style_template(dict(st.session_state)),
                       file_name="gassensor_figure_style.json", mime="application/json", **FULL_WIDTH["download_button"])

# ===== 本体 =====
if not runs:
    st.info(ui("左のサイドバーから、パルス解析アプリで保存したセッション (.json) を読み込んでください。\n\n"
               "手順：① gas-pulse-analyzer.html で生データを読み、分割とパルスの確認をする → ② 右上の「セッション保存 (.json)」→ ③ そのファイルをここに入れる。",
               "Load a session (.json) saved by the pulse-analysis app from the sidebar.\n\n"
               "Steps: ① read the raw data in gas-pulse-analyzer.html, split the recording and check the pulses → ② 'Save session (.json)' → ③ load that file here."))
    st.stop()

col_graph, col_runs = st.columns([3, 1.5])
named = load_colors(COLORS_FILE)
with col_runs:
    st.subheader(ui("ラン", "Runs"))
    st.caption(ui("表示するランを選び、順番（上から）・ラベル・色を決めます。", "Choose the runs, their order (top first), labels and colours."))
    names = [run.name for run in runs]
    st.session_state["selected_runs"] = [n for n in st.session_state.get("selected_runs", names[:4]) if n in names]
    selected = st.multiselect(ui("表示するラン（選んだ順に並びます）", "Runs shown (in the order chosen)"), names, key="selected_runs")
    palette = palette_colors(st.session_state["palette"], max(len(selected), 1), st.session_state["palette_reverse"])
    series = []
    for i, name in enumerate(selected):
        run = next(r for r in runs if r.name == name)
        with st.expander(f"**{i + 1}. {name}**", expanded=len(selected) <= 4):
            default_label = run.sample_id or name
            if len({r.gas for r in runs if r.name in selected}) > 1 and run.gas:
                default_label = f"{default_label}, {run.gas}"
            label = st.text_input(ui("ラベル", "Label"), value=default_label, key=f"label::{name}")
            custom = st.checkbox(ui("色を個別に指定", "Set the colour individually"), key=f"custom::{name}")
            color = st.color_picker(ui("色", "Colour"), palette[i], key=f"color::{name}") if custom else palette[i]
            if not custom:
                st.caption(f"{color_emoji(color)} {color}")
            n_use = st.session_state["n_pulses"] or len(run.pulses)
            st.caption(ui("{gas} · {n} パルス（使用 {m}）", "{gas} · {n} pulses ({m} used)").format(gas=run.gas, n=len(run.pulses), m=min(n_use, len(run.pulses))))
        series.append(Series(run, label, color, run.pulses[:n_use]))

with col_graph:
    if not series:
        st.info(ui("右の一覧でランを選んでください。", "Choose runs in the list on the right."))
        st.stop()
    options = Options(
        width=fig_width, height=fig_height, font_size=st.session_state["font_size"], tick_font_size=st.session_state["tick_font_size"],
        legend_font_size=st.session_state["legend_font_size"], time_unit=st.session_state["time_unit"],
        align=st.session_state["align"], lead=st.session_state["lead"], smooth_s=st.session_state["smooth_s"],
        show_raw=st.session_state["show_raw"], raw_alpha=st.session_state["raw_alpha"], shade=st.session_state["shade"],
        conc_labels=st.session_state["conc_labels"], response_labels=st.session_state["response_labels"],
        show_legend=st.session_state["show_legend"], x_label=st.session_state["x_label"].strip() or _default_x,
        y_label=st.session_state["y_label"].strip() or _default_y, metric=st.session_state["metric"],
        recovery_pulse=int(st.session_state["recovery_pulse"]), marker_size=st.session_state["marker_size"])
    fig = build(kind, series, options, plot_style)
    png_bytes = export_figure(fig, "png", 150, style=plot_style)
    pdf_bytes = export_figure(fig, "pdf", dpi_export, style=plot_style)
    svg_bytes = export_figure(fig, "svg", dpi_export, style=plot_style)
    _raster_ok = fig_width * fig_height * dpi_export ** 2 <= 36_000_000
    png_export_bytes = export_figure(fig, "png", dpi_export, style=plot_style) if _raster_ok else None
    tiff_bytes = export_figure(fig, "tiff", dpi_export, style=plot_style) if _raster_ok else None
    st.image(png_bytes, **FULL_WIDTH_IMAGE)
    st.caption(ui("図サイズ: {width:.1f} × {height:.1f} mm · PNG / TIFF: {dpi} DPI（プレビューは150 DPI）",
                  "Figure size: {width:.1f} × {height:.1f} mm · PNG / TIFF: {dpi} DPI (preview: 150 DPI)")
               .format(width=inches_to_mm(fig_width), height=inches_to_mm(fig_height), dpi=dpi_export))
    st.caption(ui("軸や文字が端で切れる場合は、余白または文字サイズを調整してください。", "If text or axes are clipped, adjust the margins or font sizes."))
    if kind in ("stack", "overlay", "recovery") and st.session_state["smooth_s"] > 0:
        st.caption(ui("太線は {s:g} s の移動平均です（表示用）。図の説明に窓幅を書いてください。",
                      "The bold line is a {s:g} s moving average (display only). State the window in the figure caption.").format(s=st.session_state["smooth_s"]))

    rows = [row for s in series for row in pulse_metrics(s.run, s.pulses)]
    table = pd.DataFrame(rows)
    with st.expander(ui("パルスごとの値（図に使った数値）", "Values per pulse (the numbers behind the figure)")):
        st.dataframe(table.round(4), hide_index=True, **FULL_WIDTH["dataframe"])
        st.caption(ui("R0・R_end は導入前・導入終了前の窓の中央値、最大応答は 15 点の移動中央値のピーク、ベースライン変化は初回導入前 1 min を基準にした R0 のずれです。",
                      "R0 and R_end are window medians before gas on and gas off; the peak uses a 15-point moving median; the baseline shift is R0 against the minute before the first exposure."))

st.sidebar.header(ui("💾 保存", "💾 Save"))
_name = f"gassensor_{kind}"
st.sidebar.download_button(ui("📥 PDF として保存", "📥 Save as PDF"), data=pdf_bytes, file_name=f"{_name}.pdf", mime="application/pdf", **FULL_WIDTH["download_button"])
st.sidebar.download_button(ui("📥 SVG として保存", "📥 Save as SVG"), data=svg_bytes, file_name=f"{_name}.svg", mime="image/svg+xml", **FULL_WIDTH["download_button"])
if _raster_ok:
    st.sidebar.download_button(ui("📥 TIFF として保存 ({dpi} DPI)", "📥 Save as TIFF ({dpi} DPI)").format(dpi=dpi_export), data=tiff_bytes,
                               file_name=f"{_name}.tiff", mime="image/tiff", **FULL_WIDTH["download_button"])
    st.sidebar.download_button(ui("📥 PNG として保存 ({dpi} DPI)", "📥 Save as PNG ({dpi} DPI)").format(dpi=dpi_export), data=png_export_bytes,
                               file_name=f"{_name}.png", mime="image/png", **FULL_WIDTH["download_button"])
else:
    st.sidebar.warning(ui("PNG / TIFFは3,600万画素までです。図の寸法またはDPIを下げてください。", "For PNG / TIFF, reduce the dimensions or DPI to stay within 36 megapixels."))
st.sidebar.download_button(ui("📥 パルスごとの値 (.csv)", "📥 Values per pulse (.csv)"), data=table.to_csv(index=False).encode("utf-8-sig"),
                           file_name="gassensor_pulse_values.csv", mime="text/csv", **FULL_WIDTH["download_button"])

st.sidebar.divider()
try:
    from build_bundle import create_bundle_bytes
    st.sidebar.download_button(ui("💻 PC 版をダウンロード (.zip)", "💻 Download the desktop edition (.zip)"), data=create_bundle_bytes(),
                               file_name="GasSensor-Maker-PC.zip", mime="application/zip", **FULL_WIDTH["download_button"])
    st.sidebar.caption(ui("PC にダウンロードして、インターネットなしで使えます（初回のみセットアップが必要）。",
                          "Run it on your own computer without the internet (a one-time setup is needed)."))
except (ImportError, FileNotFoundError):
    pass
