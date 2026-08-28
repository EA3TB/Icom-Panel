"""
ic7610_dashboard.py — Panel de monitorización IC-7610
======================================================
Estilo: Oscuro moderno — dark UI contemporáneo, púrpura suave, barras finas.

Uso:
    python ic7610_dashboard.py
"""

import asyncio
import json
import logging
import logging.handlers
import math
import os
import threading
import time
from dataclasses import dataclass

import tkinter as tk
import customtkinter as ctk

# ---------------------------------------------------------------------------
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
PATH_CONFIG = os.path.join(BASE_DIR, "radio_config.json")
PATH_LOG    = os.path.join(BASE_DIR, "dashboard.log")

POLL_FAST   = 0.25
POLL_SLOW   = 2.0
POLL_METERS = 0.15

# ---------------------------------------------------------------------------
# Paleta — Oscuro moderno
# ---------------------------------------------------------------------------
C = {
    "bg":           "#0f0f12",
    "surface":      "#13131a",
    "card":         "#17171f",
    "card2":        "#1c1c28",
    "border":       "#2a2a3a",
    "border_hi":    "#3a3a55",

    # Acento principal — púrpura suave
    "accent":       "#7c6fff",
    "accent_dim":   "#3a3470",
    "accent_muted": "#2a2450",

    # Textos
    "text":         "#e0e0ff",
    "text_sub":     "#8080aa",
    "text_dim":     "#404060",

    # Semáforo
    "green":        "#4caf7d",
    "green_dim":    "#1a3528",
    "yellow":       "#d4a017",
    "yellow_dim":   "#352808",
    "red":          "#e05555",
    "red_dim":      "#3a1515",
    "blue":         "#4a9eff",
    "blue_dim":     "#0d2040",

    # Medidores
    "bar_track":    "#1e1e2a",
    "freq_color":   "#c8c0ff",
    "mode_color":   "#7c6fff",
}

FONT_FREQ   = ("Segoe UI Light", 34)
FONT_FREQ_S = ("Segoe UI Light", 22)
FONT_MODE   = ("Segoe UI", 12, "bold")
FONT_LABEL  = ("Segoe UI", 9)
FONT_VALUE  = ("Segoe UI", 11, "bold")
FONT_TITLE  = ("Segoe UI", 9, "bold")
FONT_PILL   = ("Segoe UI", 8, "bold")
FONT_MONO   = ("Consolas", 10)

# ---------------------------------------------------------------------------
# Estado compartido
# ---------------------------------------------------------------------------

@dataclass
class RadioState:
    freq_main:     int  = 0
    freq_sub:      int  = 0
    mode_main:     str  = "---"
    mode_sub:      str  = "---"
    filter_main:   int  = 0
    filter_sub:    int  = 0
    s_meter:       int  = 0
    rf_gain:       int  = 255
    af_level:      int  = 128
    power:         int  = 255
    power_meter:   int  = 0
    swr:           int  = 0
    alc:           int  = 0
    comp_meter:    int  = 0
    id_meter:      int  = 0
    vd_meter:      int  = 0
    preamp:        int  = 0
    attenuator:    int  = 0
    ip_plus:       bool = False
    agc:           str  = "---"
    nr:            bool = False
    nb:            bool = False
    nr_level:      int  = 0
    nb_level:      int  = 0
    auto_notch:    bool = False
    manual_notch:  bool = False
    compressor:    bool = False
    comp_level:    int  = 0
    vox:           bool = False
    vox_gain:      int  = 0
    rit:           bool = False
    rit_freq:      int  = 0
    dual_watch:    bool = False
    split:         bool = False
    ptt:           bool = False
    connected:     bool = False
    error:         str  = ""
    radio_time:    str  = "--:--"

state = RadioState()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def setup_logging():
    h = logging.handlers.RotatingFileHandler(
        PATH_LOG, maxBytes=500_000, backupCount=2, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[h])
    logging.getLogger("icom_lan").setLevel(logging.WARNING)


def load_config() -> dict:
    defaults = {"ip": "192.168.1.25", "user": "**",
                "pass": "**", "civ_addr": 0x98}
    if os.path.exists(PATH_CONFIG):
        try:
            with open(PATH_CONFIG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            defaults.update(cfg)
        except Exception:
            pass
    return defaults


# ---------------------------------------------------------------------------
# Widgets personalizados
# ---------------------------------------------------------------------------

class Pill(tk.Label):
    """Etiqueta tipo pill — activa/inactiva."""

    def __init__(self, parent, text, color_on=None, **kwargs):
        self._text = text
        self._color_on  = color_on or C["accent"]
        self._color_bg_on  = C["accent_muted"]
        self._color_bg_off = C["card2"]
        super().__init__(
            parent, text=text,
            font=FONT_PILL,
            padx=7, pady=2,
            relief="flat",
            **kwargs
        )
        self._state = False
        self._refresh()

    def _refresh(self):
        if self._state:
            self.configure(bg=self._color_bg_on, fg=self._color_on)
        else:
            self.configure(bg=self._color_bg_off, fg=C["text_dim"])

    def set(self, on: bool):
        if on != self._state:
            self._state = on
            self._refresh()


class ThinBar(tk.Canvas):
    """Barra fina de progreso con segmentos opcionales."""

    def __init__(self, parent, width=200, height=6,
                 color=None, segments=False, s_labels=False, **kwargs):
        super().__init__(parent, width=width, height=height,
                         bg=C["bg"], highlightthickness=0, **kwargs)
        self._bar_w = width
        self._bar_h = height
        self._color = color or C["accent"]
        self._segments = segments
        self._s_labels = s_labels
        self._value = 0
        self._total = 255
        self._draw()

    def _seg_color(self, pct, active_pct):
        if pct > active_pct:
            return C["bar_track"]
        if self._segments:
            if pct < 0.56: return C["green"]
            if pct < 0.78: return C["yellow"]
            return C["red"]
        return self._color

    def _draw(self):
        self.delete("all")
        pct = self._value / max(1, self._total)

        if self._segments:
            n = 20
            seg_w = (self._bar_w - (n - 1) * 2) / n
            for i in range(n):
                x0 = i * (seg_w + 2)
                x1 = x0 + seg_w
                sp = (i + 1) / n
                color = self._seg_color(sp, pct)
                self.create_rectangle(x0, 0, x1, self._bar_h,
                                      fill=color, outline="")
        else:
            # Fondo
            self.create_rectangle(0, 0, self._bar_w, self._bar_h,
                                  fill=C["bar_track"], outline="")
            # Relleno con degradado de color según nivel
            if pct > 0:
                fill_w = int(self._bar_w * pct)
                if pct > 0.85:
                    color = C["red"]
                elif pct > 0.65:
                    color = C["yellow"]
                else:
                    color = self._color
                self.create_rectangle(0, 0, fill_w, self._bar_h,
                                      fill=color, outline="")

    def set_value(self, v, total=255):
        self._value = max(0, min(total, v))
        self._total = total
        self._draw()


class CircleGauge(tk.Canvas):
    """Medidor circular fino estilo moderno."""

    def __init__(self, parent, size=70, label="", color=None,
                 min_val=0, max_val=100, fmt="{:.0f}", **kwargs):
        super().__init__(parent, width=size, height=size,
                         bg=C["bg"], highlightthickness=0, **kwargs)
        self._size = size
        self._label = label
        self._color = color or C["accent"]
        self._min = min_val
        self._max = max_val
        self._fmt = fmt
        self._value = min_val
        self._draw()

    def _draw(self):
        self.delete("all")
        s = self._size
        cx, cy = s // 2, s // 2
        r = s // 2 - 6
        pct = max(0, min(1, (self._value - self._min) / max(1, self._max - self._min)))

        # Track completo
        self.create_arc(cx - r, cy - r, cx + r, cy + r,
                        start=220, extent=-260,
                        style="arc", outline=C["bar_track"], width=5)

        # Arco de valor
        if pct > 0:
            color = (C["red"] if pct > 0.85 else
                     C["yellow"] if pct > 0.65 else self._color)
            self.create_arc(cx - r, cy - r, cx + r, cy + r,
                            start=220, extent=int(-260 * pct),
                            style="arc", outline=color, width=5)

        # Valor central
        val_str = self._fmt.format(self._value)
        self.create_text(cx, cy - 4, text=val_str,
                         fill=C["text"], font=("Segoe UI", 9, "bold"),
                         anchor="center")
        # Label inferior
        self.create_text(cx, cy + 10, text=self._label,
                         fill=C["text_dim"], font=("Segoe UI", 7),
                         anchor="center")

    def set_value(self, v):
        self._value = v
        self._draw()


class FreqDisplay(tk.Frame):
    """Display de frecuencia estilo oscuro moderno."""

    def __init__(self, parent, label="MAIN", small=False, **kwargs):
        super().__init__(parent, bg=C["card"], **kwargs)
        self.configure(highlightthickness=1,
                       highlightbackground=C["border"])
        self._small = small

        tk.Label(self, text=label.upper(),
                 bg=C["card"], fg=C["text_dim"],
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", padx=10, pady=(8, 0))

        row = tk.Frame(self, bg=C["card"])
        row.pack(fill="x", padx=10, pady=(2, 8))

        font = FONT_FREQ_S if small else FONT_FREQ
        self._freq_var = tk.StringVar(value="-- . --- , ---")
        tk.Label(row, textvariable=self._freq_var,
                 bg=C["card"], fg=C["freq_color"],
                 font=font).pack(side="left")

        right = tk.Frame(row, bg=C["card"])
        right.pack(side="right", anchor="s", pady=4)

        self._mode_var = tk.StringVar(value="---")
        self._filt_var = tk.StringVar(value="")
        tk.Label(right, textvariable=self._mode_var,
                 bg=C["card"], fg=C["mode_color"],
                 font=FONT_MODE).pack(anchor="e")
        tk.Label(right, textvariable=self._filt_var,
                 bg=C["card"], fg=C["text_dim"],
                 font=FONT_LABEL).pack(anchor="e")

    def set_freq(self, hz: int):
        if hz <= 0:
            self._freq_var.set("-- . --- , ---")
            return
        mhz = hz // 1_000_000
        khz = (hz % 1_000_000) // 1_000
        hzr = hz % 1_000
        self._freq_var.set(f"{mhz:>3d} . {khz:03d} , {hzr:03d}")

    def set_mode(self, mode: str, filt: int = 0):
        self._mode_var.set(mode or "---")
        self._filt_var.set(f"F{filt}" if filt else "")


class SectionFrame(tk.Frame):
    """Marco de sección con título."""

    def __init__(self, parent, title="", **kwargs):
        super().__init__(parent, bg=C["card"],
                         highlightthickness=1,
                         highlightbackground=C["border"],
                         **kwargs)
        if title:
            tk.Label(self, text=title.upper(),
                     bg=C["card"], fg=C["text_dim"],
                     font=("Segoe UI", 8, "bold")).pack(
                anchor="w", padx=10, pady=(8, 4))

    def row(self, pady=4):
        f = tk.Frame(self, bg=C["card"])
        f.pack(fill="x", padx=10, pady=pady)
        return f


class ValueCell(tk.Frame):
    """Celda de valor con etiqueta arriba y número grande."""

    def __init__(self, parent, label="", color=None, width=5, **kwargs):
        super().__init__(parent, bg=C["card2"],
                         highlightthickness=1,
                         highlightbackground=C["border"], **kwargs)
        self._color = color or C["text"]
        tk.Label(self, text=label.upper(),
                 bg=C["card2"], fg=C["text_dim"],
                 font=("Segoe UI", 7, "bold")).pack(pady=(5, 0))
        self._var = tk.StringVar(value="---")
        tk.Label(self, textvariable=self._var,
                 bg=C["card2"], fg=self._color,
                 font=("Segoe UI", 13, "bold"),
                 width=width).pack(pady=(0, 5))

    def set(self, v, color=None):
        self._var.set(str(v))
        if color:
            self.winfo_children()[1].configure(fg=color)


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class Dashboard(ctk.CTk):

    def __init__(self, cfg: dict):
        super().__init__()
        self._cfg = cfg
        self._closing = False
        self._loop = asyncio.new_event_loop()

        self.title("IC-7610 · Dashboard · EA3TB")
        self.geometry("1140x860+40+20")
        self.configure(fg_color=C["bg"])
        self.resizable(True, True)

        self._build_ui()
        self._start_async()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._schedule_refresh()

    # ------------------------------------------------------------------
    # Construcción de UI
    # ------------------------------------------------------------------

    def _build_ui(self):

        # ── Cabecera ──────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=C["surface"], height=36)
        hdr.pack(fill="x", padx=6, pady=(6, 0))
        hdr.pack_propagate(False)

        tk.Label(hdr, text="IC-7610  REMOTE DASHBOARD",
                 bg=C["surface"], fg=C["text_sub"],
                 font=("Segoe UI", 10, "bold")).pack(side="left", padx=14, pady=8)

        tk.Label(hdr, text="EA3TB",
                 bg=C["surface"], fg=C["accent"],
                 font=("Segoe UI", 10, "bold")).pack(side="left")

        self._conn_lbl = tk.Label(hdr, text="● DESCONECTADO",
                                  bg=C["surface"], fg=C["red"],
                                  font=("Segoe UI", 9))
        self._conn_lbl.pack(side="right", padx=14)

        self._time_lbl = tk.Label(hdr, text="--:--",
                                  bg=C["surface"], fg=C["text_dim"],
                                  font=FONT_MONO)
        self._time_lbl.pack(side="right", padx=6)

        # ── Zona VFO ──────────────────────────────────────────────────
        vfo = tk.Frame(self, bg=C["bg"])
        vfo.pack(fill="x", padx=6, pady=6)

        self._disp_main = FreqDisplay(vfo, label="MAIN · VFO-A")
        self._disp_main.pack(side="left", fill="x", expand=True, padx=(0, 3))

        self._disp_sub = FreqDisplay(vfo, label="SUB · VFO-B", small=True)
        self._disp_sub.pack(side="left", fill="x", expand=False,
                            ipadx=10, padx=(0, 3))

        # Pills de estado VFO
        pill_col = tk.Frame(vfo, bg=C["bg"])
        pill_col.pack(side="left", padx=4)
        self._pill_tx    = Pill(pill_col, "TX",    C["red"])
        self._pill_tx.pack(pady=2, fill="x")
        self._pill_split = Pill(pill_col, "SPLIT", C["yellow"])
        self._pill_split.pack(pady=2, fill="x")
        self._pill_dw    = Pill(pill_col, "D·WATCH", C["blue"])
        self._pill_dw.pack(pady=2, fill="x")
        self._pill_rit   = Pill(pill_col, "RIT",   C["accent"])
        self._pill_rit.pack(pady=2, fill="x")

        # ── S-Meter ───────────────────────────────────────────────────
        s_sec = SectionFrame(self, title="S · METER")
        s_sec.pack(fill="x", padx=6, pady=3)

        s_inner = s_sec.row(pady=6)
        self._s_bar = ThinBar(s_inner, width=540, height=10,
                              segments=True, s_labels=True)
        self._s_bar.pack(side="left", padx=(0, 12))

        self._s_label = tk.Label(s_inner, text="S 0",
                                 bg=C["card"], fg=C["green"],
                                 font=("Segoe UI", 14, "bold"), width=6)
        self._s_label.pack(side="left")

        self._rit_lbl = tk.Label(s_inner, text="RIT: ---",
                                 bg=C["card"], fg=C["text_dim"],
                                 font=FONT_MONO)
        self._rit_lbl.pack(side="right", padx=10)

        # ── Medidores TX ──────────────────────────────────────────────
        tx_sec = SectionFrame(self, title="TX · METERS")
        tx_sec.pack(fill="x", padx=6, pady=3)

        tx_inner = tx_sec.row(pady=8)

        # Medidores circulares
        self._g_power = CircleGauge(tx_inner, 80, "RF PWR %",
                                    C["accent"], 0, 100)
        self._g_power.pack(side="left", padx=8)

        self._g_swr = CircleGauge(tx_inner, 80, "SWR",
                                  C["yellow"], 1, 3, fmt="{:.1f}")
        self._g_swr.pack(side="left", padx=8)

        self._g_alc = CircleGauge(tx_inner, 80, "ALC",
                                  C["red"], 0, 100)
        self._g_alc.pack(side="left", padx=8)

        self._g_comp = CircleGauge(tx_inner, 80, "COMP dB",
                                   C["blue"], 0, 20)
        self._g_comp.pack(side="left", padx=8)

        self._g_vd = CircleGauge(tx_inner, 80, "Vd V",
                                 C["green"], 10, 16, fmt="{:.1f}")
        self._g_vd.pack(side="left", padx=8)

        self._g_id = CircleGauge(tx_inner, 80, "Id A",
                                 C["yellow"], 0, 25, fmt="{:.1f}")
        self._g_id.pack(side="left", padx=8)

        # Barra de potencia
        pwr_row = tx_sec.row(pady=(0, 8))
        tk.Label(pwr_row, text="PWR", bg=C["card"],
                 fg=C["text_dim"], font=FONT_LABEL).pack(side="left", padx=(0, 8))
        self._pwr_bar = ThinBar(pwr_row, width=480, height=6,
                                color=C["accent"])
        self._pwr_bar.pack(side="left")

        # ── Sección inferior: 3 columnas ──────────────────────────────
        bot = tk.Frame(self, bg=C["bg"])
        bot.pack(fill="both", expand=True, padx=6, pady=3)
        bot.columnconfigure(0, weight=1)
        bot.columnconfigure(1, weight=1)
        bot.columnconfigure(2, weight=1)
        bot.rowconfigure(0, weight=1)

        self._build_rf(bot)
        self._build_dsp(bot)
        self._build_sys(bot)

    def _build_rf(self, parent):
        sec = SectionFrame(parent, title="RF · ANTENA")
        sec.grid(row=0, column=0, sticky="nsew", padx=(0, 3), pady=0)

        # Preamp pills
        r = sec.row()
        tk.Label(r, text="PREAMP", bg=C["card"],
                 fg=C["text_dim"], font=FONT_LABEL).pack(side="left", padx=(0, 6))
        self._pill_p0 = Pill(r, "OFF",  C["text_sub"])
        self._pill_p0.pack(side="left", padx=2)
        self._pill_p1 = Pill(r, "P1",   C["green"])
        self._pill_p1.pack(side="left", padx=2)
        self._pill_p2 = Pill(r, "P2",   C["accent"])
        self._pill_p2.pack(side="left", padx=2)
        self._pill_ip = Pill(r, "IP+",  C["blue"])
        self._pill_ip.pack(side="left", padx=6)

        # Atenuador
        r2 = sec.row()
        tk.Label(r2, text="ATT", bg=C["card"],
                 fg=C["text_dim"], font=FONT_LABEL).pack(side="left", padx=(0, 6))
        self._att_lbl = tk.Label(r2, text="0 dB",
                                 bg=C["card"], fg=C["text"],
                                 font=FONT_VALUE)
        self._att_lbl.pack(side="left")

        # AGC
        r3 = sec.row()
        tk.Label(r3, text="AGC", bg=C["card"],
                 fg=C["text_dim"], font=FONT_LABEL).pack(side="left", padx=(0, 6))
        self._agc_lbl = tk.Label(r3, text="---",
                                 bg=C["card"], fg=C["accent"],
                                 font=FONT_VALUE)
        self._agc_lbl.pack(side="left")

        # RF Gain / AF Level barras
        for label, attr in [("RF GAIN", "_rfg_bar"), ("AF LEVEL", "_afl_bar"),
                             ("TX PWR SET", "_txp_bar")]:
            r = sec.row(pady=3)
            tk.Label(r, text=label, bg=C["card"],
                     fg=C["text_dim"], font=FONT_LABEL,
                     width=10, anchor="w").pack(side="left")
            bar = ThinBar(r, width=160, height=5, color=C["accent"])
            bar.pack(side="left", padx=6)
            setattr(self, attr, bar)

    def _build_dsp(self, parent):
        sec = SectionFrame(parent, title="DSP")
        sec.grid(row=0, column=1, sticky="nsew", padx=3, pady=0)

        # NR / NB / AN / MN pills
        r = sec.row()
        for attr, label, color in [
            ("_pill_nr", "NR",         C["green"]),
            ("_pill_nb", "NB",         C["green"]),
            ("_pill_an", "AUTO-N",     C["yellow"]),
            ("_pill_mn", "MAN-N",      C["yellow"]),
        ]:
            p = Pill(r, label, color)
            p.pack(side="left", padx=2)
            setattr(self, attr, p)

        # NR Level / NB Level
        for label, attr in [("NR LEVEL", "_nr_bar"), ("NB LEVEL", "_nb_bar")]:
            r = sec.row(pady=3)
            tk.Label(r, text=label, bg=C["card"],
                     fg=C["text_dim"], font=FONT_LABEL,
                     width=9, anchor="w").pack(side="left")
            bar = ThinBar(r, width=160, height=5, color=C["green"])
            bar.pack(side="left", padx=6)
            setattr(self, attr, bar)

        # Compressor
        r2 = sec.row()
        self._pill_comp = Pill(r2, "COMP", C["blue"])
        self._pill_comp.pack(side="left", padx=(0, 8))
        tk.Label(r2, text="LEVEL", bg=C["card"],
                 fg=C["text_dim"], font=FONT_LABEL).pack(side="left", padx=(0, 4))
        self._comp_bar = ThinBar(r2, width=120, height=5, color=C["blue"])
        self._comp_bar.pack(side="left")

        # VOX
        r3 = sec.row()
        self._pill_vox = Pill(r3, "VOX", C["accent"])
        self._pill_vox.pack(side="left", padx=(0, 8))
        tk.Label(r3, text="GAIN", bg=C["card"],
                 fg=C["text_dim"], font=FONT_LABEL).pack(side="left", padx=(0, 4))
        self._vox_bar = ThinBar(r3, width=120, height=5, color=C["accent"])
        self._vox_bar.pack(side="left")

    def _build_sys(self, parent):
        sec = SectionFrame(parent, title="SISTEMA")
        sec.grid(row=0, column=2, sticky="nsew", padx=(3, 0), pady=0)

        # Celdas de valores clave
        grid = tk.Frame(sec, bg=C["card"])
        grid.pack(fill="x", padx=8, pady=6)
        grid.columnconfigure((0, 1, 2), weight=1)

        self._cell_freq2 = ValueCell(grid, "SUB MHz",  C["freq_color"])
        self._cell_freq2.grid(row=0, column=0, padx=2, pady=2, sticky="ew")

        self._cell_mode  = ValueCell(grid, "MODO",     C["mode_color"])
        self._cell_mode.grid(row=0, column=1, padx=2, pady=2, sticky="ew")

        self._cell_filter = ValueCell(grid, "FILTRO",  C["text_sub"])
        self._cell_filter.grid(row=0, column=2, padx=2, pady=2, sticky="ew")

        self._cell_att   = ValueCell(grid, "ATT dB",   C["yellow"])
        self._cell_att.grid(row=1, column=0, padx=2, pady=2, sticky="ew")

        self._cell_agc   = ValueCell(grid, "AGC",      C["accent"])
        self._cell_agc.grid(row=1, column=1, padx=2, pady=2, sticky="ew")

        self._cell_rit   = ValueCell(grid, "RIT Hz",   C["blue"])
        self._cell_rit.grid(row=1, column=2, padx=2, pady=2, sticky="ew")

        # Info de conexión
        self._info_lbl = tk.Label(sec, text="Iniciando...",
                                  bg=C["card"], fg=C["text_dim"],
                                  font=FONT_LABEL, wraplength=240,
                                  justify="left", anchor="w")
        self._info_lbl.pack(fill="x", padx=10, pady=4)

    # ------------------------------------------------------------------
    # Refresco de UI
    # ------------------------------------------------------------------

    def _schedule_refresh(self):
        if not self._closing:
            self._refresh()
            self.after(180, self._schedule_refresh)

    def _refresh(self):
        s = state

        # Conexión
        if s.connected:
            self._conn_lbl.configure(text="● CONECTADO", fg=C["green"])
            self._info_lbl.configure(text=f"{self._cfg['ip']}  ·  {s.radio_time}")
        else:
            self._conn_lbl.configure(
                text=f"● {s.error[:36] if s.error else 'DESCONECTADO'}",
                fg=C["red"])

        self._time_lbl.configure(text=s.radio_time)

        # VFO
        self._disp_main.set_freq(s.freq_main)
        self._disp_main.set_mode(s.mode_main, s.filter_main)
        self._disp_sub.set_freq(s.freq_sub)
        self._disp_sub.set_mode(s.mode_sub, s.filter_sub)

        # Pills VFO
        self._pill_tx.set(s.ptt)
        self._pill_split.set(s.split)
        self._pill_dw.set(s.dual_watch)
        self._pill_rit.set(s.rit)

        # S-Meter
        self._s_bar.set_value(s.s_meter)
        s_str = self._s_label_str(s.s_meter)
        color = C["red"] if "+" in s_str else C["green"]
        self._s_label.configure(text=s_str, fg=color)
        self._rit_lbl.configure(
            text=f"RIT  {s.rit_freq:+d} Hz" if s.rit else "RIT  ---",
            fg=C["accent"] if s.rit else C["text_dim"])

        # TX Gauges
        self._g_power.set_value(s.power_meter / 255 * 100)
        self._g_swr.set_value(1 + s.swr / 255 * 2)
        self._g_alc.set_value(s.alc / 255 * 100)
        self._g_comp.set_value(s.comp_meter / 255 * 20)
        self._g_vd.set_value(10 + s.vd_meter / 255 * 6)
        self._g_id.set_value(s.id_meter / 255 * 25)
        self._pwr_bar.set_value(s.power_meter)

        # RF
        p = s.preamp
        self._pill_p0.set(p == 0)
        self._pill_p1.set(p == 1)
        self._pill_p2.set(p == 2)
        self._pill_ip.set(s.ip_plus)
        self._att_lbl.configure(text=f"{s.attenuator} dB")
        self._agc_lbl.configure(text=s.agc)
        self._rfg_bar.set_value(s.rf_gain)
        self._afl_bar.set_value(s.af_level)
        self._txp_bar.set_value(s.power)

        # DSP
        self._pill_nr.set(s.nr)
        self._pill_nb.set(s.nb)
        self._pill_an.set(s.auto_notch)
        self._pill_mn.set(s.manual_notch)
        self._nr_bar.set_value(s.nr_level, 15)
        self._nb_bar.set_value(s.nb_level)
        self._pill_comp.set(s.compressor)
        self._comp_bar.set_value(s.comp_level)
        self._pill_vox.set(s.vox)
        self._vox_bar.set_value(s.vox_gain)

        # Sistema
        self._cell_freq2.set(f"{s.freq_sub/1e6:.3f}" if s.freq_sub else "---")
        self._cell_mode.set(s.mode_main)
        self._cell_filter.set(f"F{s.filter_main}" if s.filter_main else "---")
        self._cell_att.set(s.attenuator)
        self._cell_agc.set(s.agc)
        self._cell_rit.set(f"{s.rit_freq:+d}" if s.rit else "---")

    def _s_label_str(self, raw: int) -> str:
        pct = raw / 255
        s = pct * 9
        if s < 9:
            return f"S {max(1, int(s))}"
        db_over = (pct - 1) * 60
        for db in [10, 20, 30, 40, 60]:
            if db_over < db:
                return f"S9+{db}"
        return "S9+60"

    # ------------------------------------------------------------------
    # Async
    # ------------------------------------------------------------------

    def _start_async(self):
        threading.Thread(target=self._run_loop, daemon=True).start()

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._connect_loop())

    async def _connect_loop(self):
        from icom_lan import IcomRadio
        cfg = self._cfg
        while not self._closing:
            try:
                state.error = ""
                async with IcomRadio(
                    cfg["ip"], username=cfg["user"],
                    password=cfg["pass"], radio_addr=cfg["civ_addr"]
                ) as radio:
                    state.connected = True
                    logging.info("Conectado.")
                    radio.set_state_change_callback(self._on_state_change)
                    tasks = [
                        self._loop.create_task(self._poll_fast(radio)),
                        self._loop.create_task(self._poll_slow(radio)),
                        self._loop.create_task(self._poll_meters(radio)),
                    ]
                    while not self._closing:
                        await asyncio.sleep(0.5)
                    for t in tasks:
                        t.cancel()
            except Exception as e:
                state.connected = False
                state.error = str(e)
                logging.error(f"Conexión: {e}")
                for _ in range(50):
                    if self._closing: return
                    await asyncio.sleep(0.1)

    def _on_state_change(self, key: str, data: dict):
        v = data.get("value")
        if   key == "ptt"        and v is not None: state.ptt = bool(v)
        elif key == "split"      and v is not None: state.split = bool(v)
        elif key == "dual_watch" and v is not None: state.dual_watch = bool(v)
        elif key in ("sub_frequency", "freq_sub") and v is not None:
            state.freq_sub = int(v)
        elif key in ("sub_mode", "mode_sub")      and v is not None:
            state.mode_sub = str(v)

    async def _poll_fast(self, radio):
        while not self._closing:
            try:
                state.freq_main   = await radio.get_frequency(receiver=0)
                m, f = await radio.get_mode_info(receiver=0)
                state.mode_main   = m.name if hasattr(m, "name") else str(m)
                state.filter_main = f or 0
                state.s_meter     = await radio.get_s_meter()
            except Exception as e:
                logging.warning(f"poll_fast: {e}")
            await asyncio.sleep(POLL_FAST)

    async def _poll_slow(self, radio):
        while not self._closing:
            try:
                state.rf_gain      = await radio.get_rf_gain()
                state.af_level     = await radio.get_af_level()
                state.power        = await radio.get_power()
                state.preamp       = await radio.get_preamp()
                state.attenuator   = await radio.get_attenuator_level()
                state.ip_plus      = await radio.get_ip_plus()
                state.agc          = str(await radio.get_agc()).split(".")[-1]
                state.nr           = await radio.get_nr()
                state.nb           = await radio.get_nb()
                state.nr_level     = await radio.get_nr_level()
                state.nb_level     = await radio.get_nb_level()
                state.auto_notch   = await radio.get_auto_notch()
                state.manual_notch = await radio.get_manual_notch()
                state.compressor   = await radio.get_compressor()
                state.comp_level   = await radio.get_compressor_level()
                state.vox          = await radio.get_vox()
                state.vox_gain     = await radio.get_vox_gain()
                state.rit          = await radio.get_rit_status()
                state.rit_freq     = await radio.get_rit_frequency()
                state.dual_watch   = await radio.get_dual_watch()
                h, m = await radio.get_system_time()
                state.radio_time   = f"{h:02d}:{m:02d}"
            except Exception as e:
                logging.warning(f"poll_slow: {e}")
            await asyncio.sleep(POLL_SLOW)

    async def _poll_meters(self, radio):
        while not self._closing:
            try:
                state.power_meter = await radio.get_power_meter()
                state.swr         = await radio.get_swr()
                state.alc         = await radio.get_alc()
                state.comp_meter  = await radio.get_comp_meter()
                state.vd_meter    = await radio.get_vd_meter()
                state.id_meter    = await radio.get_id_meter()
            except Exception as e:
                logging.warning(f"poll_meters: {e}")
            await asyncio.sleep(POLL_METERS if state.ptt else 1.0)

    # ------------------------------------------------------------------

    def _on_close(self):
        self._closing = True
        logging.info("Dashboard cerrado.")
        self.after(400, self.destroy)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    setup_logging()
    cfg = load_config()
    ctk.set_appearance_mode("dark")
    app = Dashboard(cfg)
    app.mainloop()
