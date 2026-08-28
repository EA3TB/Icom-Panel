import asyncio
import json
import logging
import logging.handlers
import threading
import os
import sys
import customtkinter as ctk
from pynput import keyboard
from icom_lan import IcomRadio, CONTROLLER_ADDR

# --- Rutas ---
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PATH_LABELS = os.path.join(BASE_DIR, "labels.json")
PATH_CONFIG = os.path.join(BASE_DIR, "radio_config.json")
PATH_LOG    = os.path.join(BASE_DIR, "voice_panel.log")

# --- Constantes CIV ---
CIV_PREAMBLE  = 0xFE
CIV_END       = 0xFD
CIV_CMD_VOICE = 0x28
CIV_CMD_CW    = 0x17
CIV_CMD_SUB   = 0x00
CIV_STOP      = 0x00
CIV_CMD_MODE  = 0x06   # Cambio de modo en la radio
CIV_CMD_PTT   = 0x1C   # PTT
CIV_SUB_PTT   = 0x00   # Sub-comando PTT
CIV_PTT_ON    = 0x01
CIV_PTT_OFF   = 0x00
CIV_CMD_BKIN  = 0x16   # Sub-comando para BK-IN
CIV_SUB_BKIN  = 0x47   # Sub-comando BK-IN
CIV_BKIN_OFF  = 0x00   # BK-IN OFF
CIV_BKIN_SEMI = 0x01   # Semi BK-IN ON
CIV_MODE_LSB  = 0x00
CIV_MODE_USB  = 0x01
CIV_MODE_CW   = 0x03
CIV_FILTER_1  = 0x01   # Filtro por defecto

PLAY_TIMEOUT_SECONDS = 30

# --- Modelos compatibles: nombre visible → CIV address ---
KNOWN_MODELS = {
    "Icom IC-7610":  0x98,
    "Icom IC-7851":  0x8E,
    "Icom IC-7800":  0x6A,
    "Icom IC-7700":  0x74,
    "Icom IC-9700":  0xA2,
    "Icom IC-705":   0xA4,
    "Manual (otro)": None,   # el usuario introduce la dirección a mano
}

# --- Colores ---
COLORS = {
    "bg":       "#0a0f1e",
    "card":     "#111e3a",
    "accent":   "#00b894",
    "stop":     "#e74c3c",
    "text":     "#ffffff",
    "border":   "#1a2f5a",
    "btn_exit": "#922b21",
    "setup_bg": "#0d1528",
    "input_bg": "#162040",
}

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def _default_config() -> dict:
    return {
        "model":    "Icom IC-7610",
        "ip":       "192.168.1.25",
        "user":     "",
        "pass":     "",
        "civ_addr": 0x98,
    }


def _load_radio_config() -> dict:
    if os.path.exists(PATH_CONFIG):
        try:
            with open(PATH_CONFIG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # Rellenar solo claves que falten
            for k, v in _default_config().items():
                cfg.setdefault(k, v)
            return cfg
        except (json.JSONDecodeError, IOError) as e:
            logging.error(f"radio_config.json ilegible: {e}")
    # Primera vez: devolver config vacía (sin credenciales) para forzar setup
    return {"model": "Icom IC-7610", "ip": "", "user": "", "pass": "", "civ_addr": 0x98}


def _save_radio_config(cfg: dict):
    try:
        with open(PATH_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except IOError as e:
        logging.error(f"No se pudo guardar radio_config.json: {e}")


# ---------------------------------------------------------------------------
# Log filter
# ---------------------------------------------------------------------------

class _IcomLogFilter(logging.Filter):
    _SKIP = ("overflow", "dropping", "ping")
    def filter(self, record):
        return not any(x in record.msg.lower() for x in self._SKIP)


# ---------------------------------------------------------------------------
# Diálogo de configuración — tk.Toplevel nativo (evita bug de render CTkToplevel en Windows)
# ---------------------------------------------------------------------------

import tkinter as tk
from tkinter import ttk

class SetupDialog:
    """
    Diálogo modal usando tk.Toplevel estándar.
    Siempre se renderiza correctamente en Windows.
    Devuelve config en self.result (None si canceló).
    """

    def __init__(self, parent, current_cfg: dict):
        self.result = None
        self._parent = parent

        self._top = tk.Toplevel(parent)
        self._top.title("Configuración de radio")
        self._top.configure(bg="#0d1528")
        self._top.resizable(False, True)
        self._top.grab_set()

        self._build(current_cfg)

        # Centrar sobre la ventana padre y ajustar altura al contenido real
        self._top.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        dw = 480
        # Medir altura real del contenido + margen
        dh = self._top.winfo_reqheight() + 20
        dh = max(dh, 480)   # mínimo 480
        x = px + (pw - dw) // 2
        y = py + (ph - dh) // 2
        self._top.geometry(f"{dw}x{dh}+{x}+{y}")

    def _lbl(self, parent, text, size=11, color="#aabbcc", bold=False):
        weight = "bold" if bold else "normal"
        tk.Label(parent, text=text, bg="#0d1528", fg=color,
                 font=("Segoe UI", size, weight)).pack(anchor="w", padx=28, pady=(8, 1))

    def _entry(self, parent, value="", show=""):
        e = tk.Entry(parent, bg="#162040", fg="#ffffff", insertbackground="#ffffff",
                     relief="flat", font=("Segoe UI", 12),
                     highlightthickness=1, highlightbackground="#1a2f5a",
                     highlightcolor="#00b894", show=show)
        e.insert(0, value)
        e.pack(fill="x", padx=28, ipady=6)
        return e

    def _build(self, cfg: dict):
        bg = "#0d1528"

        # Título
        tk.Label(self._top, text="Configuración de radio", bg=bg, fg="#00b894",
                 font=("Segoe UI", 15, "bold")).pack(pady=(18, 2))
        tk.Label(self._top, text="Selecciona modelo e introduce los datos de conexión:",
                 bg=bg, fg="#7a8aaa", font=("Segoe UI", 10)).pack(pady=(0, 6))

        # Separador
        tk.Frame(self._top, bg="#1a2f5a", height=1).pack(fill="x", padx=20, pady=(0, 4))

        # Modelo
        self._lbl(self._top, "Modelo")
        model_names = list(KNOWN_MODELS.keys())
        current_model = cfg.get("model", model_names[0])
        if current_model not in model_names:
            current_model = "Manual (otro)"
        self._model_var = tk.StringVar(value=current_model)

        opt_frame = tk.Frame(self._top, bg=bg)
        opt_frame.pack(fill="x", padx=28)
        opt = ttk.Combobox(opt_frame, textvariable=self._model_var,
                           values=model_names, state="readonly",
                           font=("Segoe UI", 14))
        opt.pack(fill="x", ipady=6)
        opt.bind("<<ComboboxSelected>>", lambda e: self._on_model_change())
        # Fuente de la lista desplegable (el popdown usa option_add)
        self._top.option_add("*TCombobox*Listbox.font", ("Segoe UI", 14))
        self._top.option_add("*TCombobox*Listbox.background", "#162040")
        self._top.option_add("*TCombobox*Listbox.foreground", "white")
        self._top.option_add("*TCombobox*Listbox.selectBackground", "#0e6040")
        self._top.option_add("*TCombobox*Listbox.selectForeground", "white")

        # Estilo del combobox — fondo oscuro, sin resalte gris
        style = ttk.Style()
        style.theme_use("default")
        style.configure("TCombobox",
                        fieldbackground="#162040", background="#1a3060",
                        foreground="white", selectbackground="#162040",
                        selectforeground="white", borderwidth=0,
                        relief="flat", padding=6)
        style.map("TCombobox",
                  fieldbackground=[("readonly", "#162040")],
                  selectbackground=[("readonly", "#162040")],
                  foreground=[("readonly", "white")])

        # IP, Usuario, Contraseña
        self._lbl(self._top, "IP de la radio")
        self._ip = self._entry(self._top, cfg.get("ip", ""))

        self._lbl(self._top, "Usuario")
        self._user = self._entry(self._top, cfg.get("user", ""))

        self._lbl(self._top, "Contraseña")
        self._pass = self._entry(self._top, cfg.get("pass", ""), show="●")

        # CIV Address — siempre visible, editable, se rellena al cambiar modelo
        self._lbl(self._top, "CIV Address (hex)")
        self._civ = self._entry(self._top, "")
        self._civ_frame = None  # no se usa ocultación

        self._on_model_change()  # rellena CIV según modelo inicial

        # Separador
        tk.Frame(self._top, bg="#1a2f5a", height=1).pack(fill="x", padx=20, pady=(10, 0))

        # Botones centrados
        btn_frame = tk.Frame(self._top, bg=bg)
        btn_frame.pack(pady=14)

        tk.Button(btn_frame, text="✔  Guardar y conectar",
                  bg="#0e6040", fg="#ffffff", activebackground="#0a8050",
                  activeforeground="#ffffff", relief="flat",
                  font=("Segoe UI", 12, "bold"), cursor="hand2",
                  padx=16, pady=9,
                  command=self._save).pack(side="left", padx=(0, 10))

        tk.Button(btn_frame, text="Cancelar",
                  bg="#2a1a1a", fg="#cc8888", activebackground="#3a2a2a",
                  activeforeground="#ff9999", relief="flat",
                  font=("Segoe UI", 11), cursor="hand2",
                  padx=16, pady=9,
                  command=self._top.destroy).pack(side="left")

    def _on_model_change(self):
        model = self._model_var.get()
        # Rellenar CIV con el valor por defecto del modelo (siempre editable)
        addr = KNOWN_MODELS.get(model)
        if addr is not None:
            self._civ.delete(0, "end")
            self._civ.insert(0, hex(addr))
        # Para Manual, dejar el campo en blanco si no hay valor
        elif not self._civ.get().strip():
            self._civ.delete(0, "end")
            self._civ.insert(0, "0x")
        self._top.update_idletasks()
        dh = self._top.winfo_reqheight() + 20
        dh = max(dh, 480)
        self._top.geometry(f"480x{dh}")

    def _save(self):
        model = self._model_var.get()
        ip    = self._ip.get().strip()
        user  = self._user.get().strip()
        pwd   = self._pass.get()

        if not ip:
            self._ip.configure(highlightbackground="#e74c3c", highlightcolor="#e74c3c")
            return

        raw = self._civ.get().strip()
        try:
            civ = int(raw, 16) if raw.lower().startswith("0x") else int(raw, 0)
        except ValueError:
            self._civ.configure(highlightbackground="#e74c3c", highlightcolor="#e74c3c")
            return

        self.result = {"model": model, "ip": ip, "user": user,
                       "pass": pwd, "civ_addr": civ}
        self._top.destroy()


# ---------------------------------------------------------------------------
# Panel principal
# ---------------------------------------------------------------------------

class VoicePanel(ctk.CTk):

    def __init__(self):
        super().__init__()

        self._setup_logging()
        self._radio_config = _load_radio_config()
        self.labels_data   = self._load_labels()

        geo = self.labels_data.get("window_geometry", "1000x640+100+100")
        self.geometry(geo)
        self.configure(fg_color=COLORS["bg"])
        self._update_title()

        self._radio      = None
        self._loop       = asyncio.new_event_loop()
        self._state_lock = threading.Lock()
        self.active_idx  = None
        self._play_task  = None
        self.is_editing  = False
        self._closing    = False
        self._mode       = "voice"   # "voice" | "cw"
        self._cw_texts   = self._load_cw_texts()  # texto CW por memoria

        self._build_ui()

        self.thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.thread.start()

        self.listener = keyboard.Listener(on_press=self._on_keypress)
        self.listener.start()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Abrir setup si no hay credenciales configuradas
        if not self._radio_config.get("user") or not self._radio_config.get("ip"):
            self.after(200, self._open_setup)

    # ------------------------------------------------------------------

    def _update_title(self):
        self.title("ICOM - Memory Panel")

    def _setup_logging(self):
        handler = logging.handlers.RotatingFileHandler(
            PATH_LOG, maxBytes=500_000, backupCount=3, encoding="utf-8"
        )
        logging.basicConfig(level=logging.INFO, handlers=[handler],
                            format="%(asctime)s %(levelname)s %(message)s")
        logging.getLogger("icom_lan").addFilter(_IcomLogFilter())

    # ------------------------------------------------------------------
    # Persistencia
    # ------------------------------------------------------------------

    def _load_labels(self) -> dict:
        if os.path.exists(PATH_LABELS):
            try:
                with open(PATH_LABELS, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Rellenar solo claves que falten, sin machacar las existentes
                for i in range(1, 9):
                    data.setdefault(str(i), f"Memoria {i}")
                return data
            except (json.JSONDecodeError, IOError) as e:
                logging.warning(f"labels.json ilegible: {e}")
        # Primera vez: fichero vacío, etiquetas por defecto
        return {str(i): f"Memoria {i}" for i in range(1, 9)}

    def _save_state(self):
        try:
            self.labels_data["window_geometry"] = self.geometry()
            with open(PATH_LABELS, "w", encoding="utf-8") as f:
                json.dump(self.labels_data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logging.error(f"Error guardando estado: {e}")

    def _load_cw_texts(self) -> dict:
        """Carga textos CW desde labels.json (clave cw_1..cw_8)."""
        defaults = {
            "cw_1": "CQ DX DE EA*XXX",
            "cw_2": "599 599",
            "cw_3": "QSL TU 73",
            "cw_4": "EA*XXX EA*XXX",
            "cw_5": "CQ TEST DE EA*XXX",
            "cw_6": "NR",
            "cw_7": "73 DE EA*XXX SK",
            "cw_8": "QRZ?",
        }
        data = {}
        for k, v in defaults.items():
            data[k] = self.labels_data.get(k, v)
        return data

    def _save_cw_texts(self):
        for k, v in self._cw_texts.items():
            self.labels_data[k] = v
        self._save_state()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        self.grid_columnconfigure((0, 1, 2, 3), weight=1)
        self.grid_rowconfigure(0, weight=0)   # cabecera
        self.grid_rowconfigure((1, 2), weight=1)  # tarjetas
        self.grid_rowconfigure(3, weight=0)   # botones inferiores
        self.grid_rowconfigure(4, weight=0)   # status bar

        # ── Cabecera con toggle centrado ─────────────────────────────
        header = ctk.CTkFrame(self, fg_color="#0d1528", corner_radius=8, height=48)
        header.grid(row=0, column=0, columnspan=4, sticky="ew", padx=8, pady=(8, 4))
        header.grid_propagate(False)

        toggle_wrap = ctk.CTkFrame(header, fg_color="#06090f", corner_radius=20)
        toggle_wrap.place(relx=0.5, rely=0.5, anchor="center")
        self._btn_voice = ctk.CTkButton(
            toggle_wrap, text="VOICE", width=90, height=34,
            corner_radius=16, border_width=0,
            font=("Segoe UI", 12, "bold"),
            command=lambda: self._set_mode("voice")
        )
        self._btn_voice.pack(side="left", padx=3, pady=3)
        self._btn_cw = ctk.CTkButton(
            toggle_wrap, text="CW", width=70, height=34,
            corner_radius=16, border_width=0,
            font=("Segoe UI", 12, "bold"),
            command=lambda: self._set_mode("cw")
        )
        self._btn_cw.pack(side="left", padx=(0, 3), pady=3)
        self._refresh_toggle()

        # ── Tarjetas ──────────────────────────────────────────────────
        self.buttons = []
        for i in range(8):
            idx_str = str(i + 1)
            row, col = divmod(i, 4)

            frame = ctk.CTkFrame(self, fg_color=COLORS["card"],
                                 corner_radius=12, border_width=2,
                                 border_color=COLORS["border"])
            frame.grid(row=row + 1, column=col, padx=8, pady=8, sticky="nsew")

            frame.grid_rowconfigure(0, weight=0)
            frame.grid_rowconfigure(1, weight=1)
            frame.grid_rowconfigure(2, weight=0)
            frame.grid_columnconfigure(0, weight=1)

            num_lbl = ctk.CTkLabel(frame, text=f"T{idx_str}",
                              font=("Segoe UI", 16), text_color="#3a5a8a")
            num_lbl.grid(row=0, column=0, pady=(10, 0))

            txt = self.labels_data.get(idx_str, f"Memoria {idx_str}")
            lbl = ctk.CTkLabel(frame, text=txt,
                               font=("Segoe UI", 18, "bold"),
                               wraplength=180, text_color="white")
            lbl.grid(row=1, column=0, sticky="nsew", padx=10)
            lbl.bind("<Double-Button-1>",
                     lambda e, idx=i + 1: self._edit_label(idx))

            btn = ctk.CTkButton(
                frame, text="▶  PLAY",
                fg_color="#0b2240", hover_color="#0e3060",
                text_color=COLORS["accent"],
                font=("Segoe UI", 14, "bold"), height=42,
                command=lambda idx=i + 1: self._toggle_voice(idx)
            )
            btn.grid(row=2, column=0, pady=(0, 15), padx=20, sticky="ew")
            self.buttons.append({"btn": btn, "lbl": lbl, "num": num_lbl, "frame": frame})

        # Fila de botones inferiores
        bottom = ctk.CTkFrame(self, fg_color="transparent")
        bottom.grid(row=3, column=0, columnspan=4, pady=16)

        ctk.CTkButton(
            bottom, text="⚙  Configuración", width=180, height=40,
            fg_color="#0d2040", hover_color="#0e3060",
            text_color="#6699cc", font=("Segoe UI", 13),
            command=self._open_setup
        ).pack(side="left", padx=12)

        ctk.CTkButton(
            bottom, text="SALIR", width=160, height=40,
            fg_color=COLORS["btn_exit"], hover_color="#e74c3c",
            text_color="white", font=("Segoe UI", 14, "bold"),
            command=self._confirm_close
        ).pack(side="left", padx=12)

        # Barra de estado
        self.status_bar = ctk.CTkLabel(
            self, text="Conectando...", anchor="w", padx=20,
            font=("Segoe UI", 12), text_color=COLORS["accent"]
        )
        self.status_bar.grid(row=4, column=0, columnspan=4,
                             sticky="ew", pady=(0, 5))

    def _set_mode(self, mode: str):
        if self._mode == mode:
            return
        self._mode = mode
        # Detener cualquier reproducción activa al cambiar modo
        if self.active_idx is not None:
            asyncio.run_coroutine_threadsafe(self._async_stop(), self._loop)
        # Cambiar modo en la radio vía CI-V
        asyncio.run_coroutine_threadsafe(self._send_radio_mode(mode), self._loop)
        self._refresh_toggle()
        self._update_card_labels()

    def _refresh_toggle(self):
        if self._mode == "voice":
            self._btn_voice.configure(fg_color=COLORS["accent"], text_color="#04342c",
                                      hover_color="#00a882")
            self._btn_cw.configure(fg_color="transparent", text_color="#446655",
                                   hover_color="#0d2040")
        else:
            self._btn_cw.configure(fg_color=COLORS["accent"], text_color="#04342c",
                                   hover_color="#00a882")
            self._btn_voice.configure(fg_color="transparent", text_color="#446655",
                                      hover_color="#0d2040")

    def _update_card_labels(self):
        """Actualiza prefijo y contenido de las tarjetas al cambiar de modo."""
        prefix = "T" if self._mode == "voice" else "M"
        for i, item in enumerate(self.buttons):
            idx_str = str(i + 1)
            item["num"].configure(text=f"{prefix}{idx_str}")
            if self._mode == "cw":
                # Mostrar el texto CW configurado
                cw_text = self._cw_texts.get(f"cw_{idx_str}", "")
                item["lbl"].configure(text=cw_text or "—",
                                       font=("Consolas", 13, "bold"))
            else:
                # Restaurar etiqueta de voz
                item["lbl"].configure(text=self.labels_data.get(idx_str, f"Memoria {idx_str}"),
                                       font=("Segoe UI", 18, "bold"))
        self._update_ui_state()

    def _edit_label(self, idx: int):
        """Doble clic: edita etiqueta (VOICE) o texto CW (CW)."""
        self.is_editing = True
        target = self.buttons[idx - 1]

        if self._mode == "cw":
            # Editar texto CW
            current = self._cw_texts.get(f"cw_{idx}", "")
            entry = ctk.CTkEntry(target["frame"],
                                 font=("Consolas", 13), justify="center",
                                 placeholder_text="Texto CW...")
        else:
            current = target["lbl"].cget("text")
            entry = ctk.CTkEntry(target["frame"],
                                 font=("Segoe UI", 16, "bold"), justify="center")

        entry.insert(0, current)
        target["lbl"].grid_remove()
        entry.grid(row=1, column=0, sticky="ew", padx=15, pady=(5, 10))
        entry.focus_set()

        def save(e=None):
            val = entry.get()
            if self._mode == "cw":
                self._cw_texts[f"cw_{idx}"] = val.upper()
                self._save_cw_texts()
            else:
                self.labels_data[str(idx)] = val
                target["lbl"].configure(text=val)
                self._save_state()
            entry.destroy()
            target["lbl"].grid(row=1, column=0, sticky="nsew", padx=10)
            self.is_editing = False

        def cancel(e=None):
            entry.destroy()
            target["lbl"].grid(row=1, column=0, sticky="nsew", padx=10)
            self.is_editing = False

        entry.bind("<Return>", save)
        entry.bind("<Escape>", cancel)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _open_setup(self):
        dlg = SetupDialog(self, self._radio_config)
        self.wait_window(dlg._top)
        if dlg.result:
            self._radio_config = dlg.result
            _save_radio_config(self._radio_config)
            self._update_title()
            self._reconnect()

    def _reconnect(self):
        """Fuerza reconexión con la nueva config cerrando la sesión actual."""
        self._radio = None
        self.after(0, lambda: self.status_bar.configure(
            text=f"Reconectando a {self._radio_config['ip']}..."
        ))
        logging.info(f"Reconectando a {self._radio_config['ip']} "
                     f"(modelo: {self._radio_config.get('model','?')})")

    # ------------------------------------------------------------------
    # Lógica de radio
    # ------------------------------------------------------------------

    async def _sync_mode_from_radio(self):
        """Lee el modo actual de la radio y actualiza el toggle del panel."""
        try:
            result = await self._radio.get_mode_info(receiver=0)
            mode_obj = result[0] if isinstance(result, tuple) else result
            mode_str = mode_obj.name if hasattr(mode_obj, "name") else str(mode_obj)
            is_cw = "CW" in mode_str.upper()
            new_mode = "cw" if is_cw else "voice"
            logging.info(f"Modo leído de la radio: {mode_str} → panel={new_mode}")
            self._mode = new_mode
            self.after(0, self._refresh_toggle)
            self.after(0, self._update_card_labels)
        except Exception as e:
            logging.warning(f"No se pudo leer el modo de la radio: {e}")

    async def _send_radio_mode(self, mode: str):
        """Cambia el modo en la radio.
        CW  → modo CW  (0x03)
        Voice → LSB (0x00) si freq < 10 MHz, USB (0x01) si freq >= 10 MHz.
        Si no hay frecuencia disponible, usa USB por defecto.
        """
        if not self._radio:
            return
        if mode == "cw":
            radio_mode = CIV_MODE_CW
            mode_name  = "CW"
        else:
            try:
                freq = await self._radio.get_frequency(receiver=0)
            except Exception:
                freq = 0
            if freq > 0 and freq < 10_000_000:
                radio_mode = CIV_MODE_LSB
                mode_name  = "LSB"
            else:
                radio_mode = CIV_MODE_USB
                mode_name  = "USB"
        frame = bytes([
            CIV_PREAMBLE, CIV_PREAMBLE,
            self._radio_config["civ_addr"], CONTROLLER_ADDR,
            CIV_CMD_MODE, radio_mode, CIV_FILTER_1,
            CIV_END
        ])
        logging.info(f"CIV MODE → {mode_name} (freq={freq if mode != 'cw' else 'n/a'})")
        await self._radio._send_civ_raw(frame, wait_response=False)

    async def _send_voice_cmd(self, n: int):
        """Lanza memoria.
        VOICE: FE FE addr E0 28 00 <n> FD
        CW:    FE FE addr E0 17 <ascii_text> FD  (texto CI-V directo)
               El IC-7610 transmite el texto en CW si Break-in está ON.
        n=0 → stop (solo voz; CW para solo cuando acaba el texto)
        """
        if not self._radio:
            logging.warning("Intento de envío sin conexión activa.")
            return

        addr = self._radio_config["civ_addr"]

        if self._mode == "cw":
            if n == 0:
                # STOP: vaciar buffer CW + PTT OFF
                # Enviar texto vacío limpia el buffer de transmisión CW
                clear_frame = bytes([CIV_PREAMBLE, CIV_PREAMBLE, addr, CONTROLLER_ADDR,
                                     CIV_CMD_CW, CIV_END])
                await self._radio._send_civ_raw(clear_frame, wait_response=False)
                await asyncio.sleep(0.05)
                ptt_off = bytes([CIV_PREAMBLE, CIV_PREAMBLE, addr, CONTROLLER_ADDR,
                                 CIV_CMD_PTT, CIV_SUB_PTT, CIV_PTT_OFF, CIV_END])
                await self._radio._send_civ_raw(ptt_off, wait_response=False)
                logging.info("CIV CW STOP: buffer limpiado + PTT OFF")
                return
            # Recuperar texto CW configurado en el panel
            text = self._cw_texts.get(f"cw_{n}", "").strip()
            if not text:
                logging.warning(f"M{n}: texto CW vacío. Configúralo con doble clic.")
                return
            text_upper = text.upper()
            ascii_bytes = [ord(c) for c in text_upper if 0x20 <= ord(c) <= 0x7E]
            # PTT ON
            ptt_on = bytes([CIV_PREAMBLE, CIV_PREAMBLE, addr, CONTROLLER_ADDR,
                            CIV_CMD_PTT, CIV_SUB_PTT, CIV_PTT_ON, CIV_END])
            await self._radio._send_civ_raw(ptt_on, wait_response=False)
            logging.info("CIV PTT → ON")
            await asyncio.sleep(0.1)
            # Enviar texto CW (cmd 0x17)
            frame = bytes([CIV_PREAMBLE, CIV_PREAMBLE, addr, CONTROLLER_ADDR,
                           CIV_CMD_CW] + ascii_bytes + [CIV_END])
            logging.info(f"CIV CW → M{n} '{text_upper}'")
            await self._radio._send_civ_raw(frame, wait_response=False)
            # PTT OFF tras estimar duración (20 WPM ≈ 60ms/carácter + margen)
            wpm = 20
            duration = max(2.0, len(text_upper) * (60 / wpm) * 0.06 + 1.5)
            await asyncio.sleep(duration)
            ptt_off = bytes([CIV_PREAMBLE, CIV_PREAMBLE, addr, CONTROLLER_ADDR,
                             CIV_CMD_PTT, CIV_SUB_PTT, CIV_PTT_OFF, CIV_END])
            await self._radio._send_civ_raw(ptt_off, wait_response=False)
            logging.info(f"CIV PTT → OFF (tras {duration:.1f}s)")
        else:
            # VOICE: comando estándar 0x28 0x00 <n>
            frame = bytes([CIV_PREAMBLE, CIV_PREAMBLE, addr, CONTROLLER_ADDR,
                           CIV_CMD_VOICE, CIV_CMD_SUB, n, CIV_END])
            hex_str = " ".join(f"{b:02X}" for b in frame)
            logging.info(f"CIV VOICE → {'PLAY T' + str(n) if n > 0 else 'STOP'} "
                         f"trama: {hex_str}")
            await self._radio._send_civ_raw(frame, wait_response=False)

    async def _async_stop(self):
        """Para la reproducción activa inmediatamente."""
        if self._play_task:
            self._play_task.cancel()
        await self._send_voice_cmd(CIV_STOP)
        with self._state_lock:
            self.active_idx = None
        self.after(0, self._update_ui_state)

    def _toggle_voice(self, n: int):
        asyncio.run_coroutine_threadsafe(self._async_toggle(n), self._loop)

    async def _async_toggle(self, n: int):
        if self._play_task:
            self._play_task.cancel()
        with threading.Lock():
            current = self.active_idx
        if current == n:
            await self._send_voice_cmd(CIV_STOP)
            with self._state_lock:
                self.active_idx = None
        else:
            with self._state_lock:
                self.active_idx = n
            self._play_task = self._loop.create_task(
                self._play_with_timeout(n))
        self.after(0, self._update_ui_state)

    async def _play_with_timeout(self, n: int):
        try:
            await self._send_voice_cmd(n)
            await asyncio.sleep(PLAY_TIMEOUT_SECONDS)
        except asyncio.CancelledError:
            pass
        finally:
            with self._state_lock:
                if self.active_idx == n:
                    self.active_idx = None
            self.after(0, self._update_ui_state)

    def _update_ui_state(self):
        with self._state_lock:
            current = self.active_idx
        btn_txt_idle = "▶  PLAY" if self._mode == "voice" else "▶  SEND"
        for i, item in enumerate(self.buttons, 1):
            if i == current:
                item["btn"].configure(text="■  STOP",
                                      fg_color="#e05555",
                                      hover_color="#c03030",
                                      text_color="#ffffff")
                item["frame"].configure(fg_color="#3a0a0a",
                                        border_color="#e05555")
            else:
                item["btn"].configure(text=btn_txt_idle,
                                      fg_color="#0b2240",
                                      hover_color="#0e3060",
                                      text_color=COLORS["accent"])
                item["frame"].configure(fg_color=COLORS["card"],
                                        border_color=COLORS["border"])

    # ------------------------------------------------------------------
    # Callback de estado de la radio
    # ------------------------------------------------------------------

    async def _watch_ptt_loop(self, radio):
        """Detecta fin de memoria de voz consultando el PTT activamente.
        El IC-7610 no notifica el fin de memoria por CI-V, por lo que
        se consulta get_ptt() cada 500ms mientras hay una memoria activa.
        """
        import time
        try:
            while not self._closing:
                await asyncio.sleep(0.5)
                with self._state_lock:
                    active = self.active_idx
                if active is None or self._mode != "voice":
                    continue
                # Hay una memoria activa — consultar PTT a la radio
                try:
                    ptt = await asyncio.wait_for(
                        radio.get_ptt() if hasattr(radio, 'get_ptt')
                        else self._query_ptt(radio),
                        timeout=0.8
                    )
                    if not ptt:
                        logging.info(f"PTT OFF (consulta activa) — T{active} finalizada")
                        self._finish_active(active)
                except asyncio.TimeoutError:
                    pass
                except Exception as e:
                    logging.debug(f"_watch_ptt_loop: {e}")
        except asyncio.CancelledError:
            pass

    async def _query_ptt(self, radio) -> bool:
        """Consulta el estado PTT via CI-V 0x1C 0x00."""
        from icom_lan import CONTROLLER_ADDR
        frame = bytes([CIV_PREAMBLE, CIV_PREAMBLE,
                       self._radio_config["civ_addr"], CONTROLLER_ADDR,
                       CIV_CMD_PTT, CIV_SUB_PTT, CIV_END])
        resp = await radio._send_civ_raw(frame, wait_response=True)
        if resp and resp.data:
            return bool(resp.data[0])
        return False

    def _finish_active(self, n: int):
        """Cancela la tarea activa y vuelve la tarjeta a reposo."""
        if self._play_task:
            self._play_task.cancel()
        with self._state_lock:
            if self.active_idx == n:
                self.active_idx = None
        self.after(0, self._update_ui_state)

    def _on_radio_state_change(self, key: str, data: dict):
        """Llamado por icom_lan cuando la radio notifica un cambio de estado.
        Nota: icom_lan no emite evento PTT via callback — se usa _watch_ptt_loop.
        Este callback se mantiene para futuros eventos de estado.
        """
        pass

    # ------------------------------------------------------------------
    # Teclado
    # ------------------------------------------------------------------

    def _on_keypress(self, key):
        if self.is_editing:
            return
        # Bloquear teclas si hay algún diálogo modal abierto
        try:
            if any(isinstance(w, tk.Toplevel) for w in self.winfo_children()):
                return
        except Exception:
            return
        try:
            f_keys = {
                keyboard.Key.f1: 1, keyboard.Key.f2: 2,
                keyboard.Key.f3: 3, keyboard.Key.f4: 4,
                keyboard.Key.f5: 5, keyboard.Key.f6: 6,
                keyboard.Key.f7: 7, keyboard.Key.f8: 8,
            }
            k = None
            if key in f_keys:
                k = f_keys[key]
            elif hasattr(key, "vk") and 97 <= key.vk <= 104:
                k = key.vk - 96
            if k:
                self._toggle_voice(k)
        except Exception as e:
            logging.debug(f"keypress error: {e}")

    # ------------------------------------------------------------------
    # Loop async
    # ------------------------------------------------------------------

    def _run_async_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._connect_loop())

    async def _connect_loop(self):
        while not self._closing:
            cfg = self._radio_config
            try:
                logging.info(f"Conectando a {cfg['ip']} "
                             f"(modelo: {cfg.get('model','?')}, "
                             f"CIV: {hex(cfg['civ_addr'])})...")
                async with IcomRadio(
                    cfg["ip"],
                    username=cfg["user"],
                    password=cfg["pass"],
                    radio_addr=cfg["civ_addr"]
                ) as radio:
                    self._radio = radio
                    logging.info("Conexión establecida.")
                    model = cfg.get("model", "Radio")
                    self.after(0, lambda m=model, ip=cfg["ip"]:
                               self.status_bar.configure(
                                   text=f"Conectado  |  {m}  |  {ip}"))
                    # Registrar callback para eventos de estado
                    radio.set_state_change_callback(self._on_radio_state_change)
                    # Leer modo actual de la radio y sincronizar el panel
                    await self._sync_mode_from_radio()
                    # Vigilar PTT para detectar fin de memoria de voz
                    ptt_task = self._loop.create_task(self._watch_ptt_loop(radio))
                    try:
                        while not self._closing and self._radio is radio:
                            await asyncio.sleep(0.5)
                    finally:
                        ptt_task.cancel()
            except Exception as e:
                self._radio = None
                if not self._closing:
                    logging.error(f"Error de conexión: {e}. Reintentando en 5s...")
                    self.after(0, lambda: self.status_bar.configure(
                        text="Error de conexión — Reintentando..."))
                    await asyncio.sleep(5)

    # ------------------------------------------------------------------
    # Cierre
    # ------------------------------------------------------------------

    def _confirm_close(self):
        with self._state_lock:
            active = self.active_idx
        if active:
            dlg = ctk.CTkToplevel(self)
            dlg.title("Confirmar salida")
            dlg.geometry("320x140")
            dlg.resizable(False, False)
            dlg.grab_set()
            ctk.CTkLabel(dlg,
                         text=f"T{active} está reproduciéndose.\n¿Salir igualmente?",
                         font=("Segoe UI", 14)).pack(pady=20)
            bf = ctk.CTkFrame(dlg, fg_color="transparent")
            bf.pack()
            ctk.CTkButton(bf, text="Sí, salir", width=120,
                          fg_color=COLORS["btn_exit"],
                          command=lambda: [dlg.destroy(), self._on_close()]
                          ).pack(side="left", padx=10)
            ctk.CTkButton(bf, text="Cancelar", width=120,
                          command=dlg.destroy).pack(side="left", padx=10)
        else:
            self._on_close()

    def _on_close(self):
        self._closing = True
        self._save_state()
        if hasattr(self, "listener"):
            self.listener.stop()
        logging.info("Aplicación cerrada.")
        self.after(300, self._shutdown)

    def _shutdown(self):
        try:
            self.destroy()
        except Exception:
            pass
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    ctk.set_appearance_mode("dark")
    app = VoicePanel()
    app.mainloop()
