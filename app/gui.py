"""SERVER GATE — Stress Test.  Main window and wiring."""
from __future__ import annotations

import datetime
import os
import platform
import queue
import tkinter as tk
from tkinter import filedialog, messagebox

import customtkinter as ctk

import assets
import theme as T
import sysinfo
import cpu_tests
import ram_tests
from configtab import ConfigTab
from engine import TestEngine
from monitor import MonitorPanel
from widgets import IntStepper, StatusPill, fmt_time

APP_TITLE = "SERVER GATE — Stress Test"
VERSION = "2.0"

DURATION_PRESETS = [
    ("30 секунд", 30), ("1 минута", 60), ("5 минут", 300), ("30 минут", 1800),
    ("1 час", 3600), ("2 часа", 7200), ("3 часа", 10800),
]
DURATION_CUSTOM = "Своё (сек)"


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("light")
        self.title(APP_TITLE)
        self.configure(fg_color=T.BG)

        # Adaptive geometry: never exceed the actual screen (server consoles /
        # iLO are often 1024x768), otherwise the WM cannot maximize the window.
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(1200, sw - 16), min(780, sh - 70)
        x, y = max(0, (sw - w) // 2), max(0, (sh - h) // 3)
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(min(940, sw - 16), min(560, sh - 80))

        self._set_window_icon()
        self.bind("<F11>", self._toggle_fullscreen)
        self.bind("<Escape>", lambda e: self._set_fullscreen(False))

        # Appliance / kiosk mode on the bootable Linux live image: start maximized.
        if os.environ.get("SERVERGATE_KIOSK"):
            self.after(200, self._kiosk_maximize)

        self.fonts = T.init_fonts()
        self.f = {k: ctk.CTkFont(family=v[0], size=v[1],
                                 weight=("bold" if v[2] == "bold" else "normal"))
                  for k, v in self.fonts.items()}
        self.sys = sysinfo.gather()
        self.engine = TestEngine()
        self.active_kind = None
        self._cores_primed = False
        self._ram_moved_total = 0.0
        self._ram_errors_total = 0
        self._last_summary = None
        self._last_results = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_header()
        self._build_tabs()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(80, self._poll_engine)
        self.after(700, self._poll_live)

    # =====================================================================
    # Window management (icons, maximize, fullscreen)
    # =====================================================================
    def _set_window_icon(self):
        try:
            if os.name == "nt":
                self.iconbitmap(assets.icon_path())
        except Exception:
            pass
        try:
            self._icon_img = tk.PhotoImage(file=assets.icon_png_path())
            self.iconphoto(True, self._icon_img)
        except Exception:
            pass

    def _kiosk_maximize(self):
        """Maximize reliably across window managers (xfwm4, Windows, ...)."""
        try:
            self.attributes("-zoomed", True)  # X11 WMs
            return
        except Exception:
            pass
        try:
            self.state("zoomed")  # Windows
            return
        except Exception:
            pass
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{sw}x{sh}+0+0")

    def _set_fullscreen(self, on: bool):
        try:
            self.attributes("-fullscreen", bool(on))
        except Exception:
            pass

    def _toggle_fullscreen(self, _e=None):
        try:
            cur = bool(self.attributes("-fullscreen"))
        except Exception:
            cur = False
        self._set_fullscreen(not cur)

    # =====================================================================
    # Header
    # =====================================================================
    def _build_header(self):
        bar = ctk.CTkFrame(self, fg_color=T.CARD, corner_radius=0)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)

        # brand logo (servergate.ru)
        mark = ctk.CTkFrame(bar, fg_color="transparent")
        mark.grid(row=0, column=0, sticky="w", padx=(24, 0), pady=16)
        try:
            img, size = assets.load_logo(42)
            self._logo_img = ctk.CTkImage(light_image=img, dark_image=img, size=size)
            ctk.CTkLabel(mark, image=self._logo_img, text="").grid(
                row=0, column=0, sticky="w")
        except Exception:
            ctk.CTkLabel(mark, text="SERVERGATE", font=self.f["wordmark"],
                         text_color=T.BLUE).grid(row=0, column=0, sticky="w")
        sep = ctk.CTkFrame(mark, fg_color=T.BORDER, width=1, height=38,
                           corner_radius=0)
        sep.grid(row=0, column=1, padx=16)
        ctk.CTkLabel(mark, text="СТРЕСС-ТЕСТ\nПРОЦЕССОРА И ПАМЯТИ",
                     font=self.f["small_bold"], text_color=T.INK_MUTED,
                     justify="left", anchor="w").grid(row=0, column=2, sticky="w")

        # system chips
        chips = ctk.CTkFrame(bar, fg_color="transparent")
        chips.grid(row=0, column=2, sticky="e", padx=(0, 22))
        cpu_txt = self.sys["cpu_short"] or self.sys["cpu_name"]
        if len(cpu_txt) > 36:
            cpu_txt = cpu_txt[:35] + "…"
        cpu_title = ("ПРОЦЕССОРЫ" if self.sys["sockets"] > 1 else "ПРОЦЕССОР")
        self._chip(chips, cpu_title, cpu_txt, 0)
        self._chip(chips, "ЯДРА / ПОТОКИ",
                   f'{self.sys["physical"]} / {self.sys["logical"]}', 1)
        ram_txt = f'{self.sys["ram_total_gb"]:g} ГБ' if self.sys["ram_total_gb"] else "—"
        self._chip(chips, "ОЗУ", ram_txt, 2)

        # brand accent stripe under the header
        stripe = ctk.CTkFrame(bar, fg_color=T.ORANGE, height=3, corner_radius=0)
        stripe.grid(row=1, column=0, columnspan=3, sticky="ew")

    def _chip(self, parent, title, value, col):
        f = ctk.CTkFrame(parent, fg_color=T.CARD_INSET, corner_radius=10,
                         border_width=1, border_color=T.BORDER)
        f.grid(row=0, column=col, padx=5, pady=10)
        ctk.CTkLabel(f, text=title, font=self.f["tiny"], text_color=T.INK_FAINT).grid(
            row=0, column=0, sticky="w", padx=14, pady=(8, 0))
        ctk.CTkLabel(f, text=value, font=self.f["small_bold"], text_color=T.NAVY).grid(
            row=1, column=0, sticky="w", padx=14, pady=(0, 8))

    # =====================================================================
    # Tabs
    # =====================================================================
    def _build_tabs(self):
        self.tabs = ctk.CTkTabview(
            self, fg_color="transparent",
            segmented_button_fg_color=T.BLUE_SOFT,
            segmented_button_selected_color=T.ORANGE,
            segmented_button_selected_hover_color=T.ORANGE_DK,
            segmented_button_unselected_color=T.BLUE,
            segmented_button_unselected_hover_color=T.BLUE_DK,
            text_color="#FFFFFF", text_color_disabled=T.INK_FAINT,
            border_width=0, corner_radius=12,
        )
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=18, pady=(12, 12))
        self.tabs._segmented_button.configure(font=self.f["h3"], height=36)

        self.tab_cpu = self.tabs.add("  ПРОЦЕССОР (CPU)  ")
        self.tab_ram = self.tabs.add("  ПАМЯТЬ (ОЗУ · Memtest)  ")
        self.tab_cfg = self.tabs.add("  КОНФИГУРАЦИЯ  ")

        self._build_cpu_tab(self.tab_cpu)
        self._build_ram_tab(self.tab_ram)
        self._build_cfg_tab(self.tab_cfg)

    def _build_cfg_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        self.cfg_tab = ConfigTab(tab, self.f)
        self.cfg_tab.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

    def _split(self, parent):
        parent.grid_columnconfigure(0, weight=0)
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        cfg = ctk.CTkScrollableFrame(parent, fg_color=T.CARD, corner_radius=14,
                                     border_width=1, border_color=T.BORDER, width=340)
        cfg.grid(row=0, column=0, sticky="nsw", padx=(2, 14), pady=2)
        cfg.grid_columnconfigure(0, weight=1)
        mon_wrap = ctk.CTkFrame(parent, fg_color="transparent")
        mon_wrap.grid(row=0, column=1, sticky="nsew", pady=2, padx=(0, 2))
        mon_wrap.grid_columnconfigure(0, weight=1)
        mon_wrap.grid_rowconfigure(0, weight=1)
        return cfg, mon_wrap

    # ---- shared config helpers ----
    def _cfg_title(self, parent, text, sub, row):
        ctk.CTkLabel(parent, text=text, font=self.f["h1"], text_color=T.NAVY,
                     anchor="w").grid(row=row, column=0, sticky="ew", padx=18, pady=(16, 0))
        ctk.CTkLabel(parent, text=sub, font=self.f["small"], text_color=T.INK_MUTED,
                     anchor="w", justify="left", wraplength=310).grid(
            row=row + 1, column=0, sticky="ew", padx=18, pady=(2, 8))

    def _section(self, parent, text, row):
        ctk.CTkLabel(parent, text=text, font=self.f["h3"], text_color=T.ORANGE_DK,
                     anchor="w").grid(row=row, column=0, sticky="ew", padx=18, pady=(10, 2))

    def _check(self, parent, text, var, row):
        cb = ctk.CTkCheckBox(parent, text=text, variable=var, font=self.f["body"],
                             text_color=T.INK, fg_color=T.ORANGE, hover_color=T.ORANGE_DK,
                             checkmark_color="#FFFFFF", border_color=T.BORDER_DK,
                             corner_radius=5, border_width=2)
        cb.grid(row=row, column=0, sticky="w", padx=18, pady=3)
        return cb

    def _select_buttons(self, parent, vars_dict, row):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=row, column=0, sticky="w", padx=15, pady=(4, 4))
        ctk.CTkButton(f, text="Выбрать все", width=110, height=28,
                      font=self.f["small_bold"], fg_color=T.BLUE_SOFT, text_color=T.BLUE,
                      hover_color="#D4E4FB", corner_radius=8,
                      command=lambda: [v.set(True) for v in vars_dict.values()]).grid(
            row=0, column=0, padx=(3, 6))
        ctk.CTkButton(f, text="Снять все", width=90, height=28,
                      font=self.f["small_bold"], fg_color=T.CARD_INSET, text_color=T.INK_MUTED,
                      hover_color=T.BORDER, corner_radius=8,
                      command=lambda: [v.set(False) for v in vars_dict.values()]).grid(
            row=0, column=1)

    # =====================================================================
    # CPU tab
    # =====================================================================
    def _build_cpu_tab(self, tab):
        cfg, mon_wrap = self._split(tab)
        r = 0
        self._cfg_title(cfg, "Тест процессора",
                        "Семь нагрузочных тестов из SERVER GATE: математика на всех "
                        "ядрах, архивация, Фибоначчи, SHA-512, BZip2, решето, Мандельброт.",
                        r); r += 2

        self._section(cfg, "ТЕСТЫ", r); r += 1
        self.cpu_vars = {}
        for key in cpu_tests.CPU_TEST_ORDER:
            name = cpu_tests.CPU_TESTS[key][0]
            var = ctk.BooleanVar(value=True)
            self.cpu_vars[key] = var
            self._check(cfg, name, var, r); r += 1
        self._select_buttons(cfg, self.cpu_vars, r); r += 1

        self._section(cfg, "ПАРАМЕТРЫ", r); r += 1
        # duration
        ctk.CTkLabel(cfg, text="Длительность одного теста", font=self.f["small_bold"],
                     text_color=T.INK, anchor="w").grid(row=r, column=0, sticky="ew",
                                                        padx=18, pady=(4, 2)); r += 1
        self.cpu_dur_var = ctk.StringVar(value="30 секунд")
        self.cpu_dur_menu = ctk.CTkOptionMenu(
            cfg, variable=self.cpu_dur_var,
            values=[p[0] for p in DURATION_PRESETS] + [DURATION_CUSTOM],
            command=self._cpu_dur_changed, font=self.f["body"],
            fg_color=T.CARD_INSET, button_color=T.NAVY, button_hover_color=T.BLUE_DK,
            text_color=T.INK, dropdown_fg_color=T.CARD, dropdown_text_color=T.INK,
            dropdown_hover_color=T.BLUE_SOFT, corner_radius=9, width=200)
        self.cpu_dur_menu.grid(row=r, column=0, sticky="w", padx=18, pady=(0, 4)); r += 1
        self.cpu_dur_custom = ctk.CTkEntry(cfg, placeholder_text="секунды", width=140,
                                           font=self.f["mono"], fg_color=T.CARD,
                                           border_color=T.BORDER, text_color=T.INK)
        self.cpu_dur_custom.grid(row=r, column=0, sticky="w", padx=18, pady=(0, 6))
        self.cpu_dur_custom.grid_remove(); r += 1

        # rounds
        self._labeled_stepper(cfg, "Количество кругов", r, "cpu_rounds",
                              value=1, minimum=1, maximum=999); r += 1
        # workers
        self._labeled_stepper(cfg, "Рабочих процессов (Математика)", r, "cpu_workers",
                              value=self.sys["logical"], minimum=1,
                              maximum=max(1, self.sys["logical"] * 2)); r += 1
        # mode
        ctk.CTkLabel(cfg, text="Режим запуска", font=self.f["small_bold"],
                     text_color=T.INK, anchor="w").grid(row=r, column=0, sticky="ew",
                                                        padx=18, pady=(4, 2)); r += 1
        self.cpu_mode = ctk.CTkSegmentedButton(
            cfg, values=["Последовательно", "Одновременно (экстрим)"],
            font=self.f["small_bold"], fg_color=T.CARD_INSET,
            selected_color=T.NAVY, selected_hover_color=T.BLUE_DK,
            unselected_color=T.CARD_INSET, unselected_hover_color=T.BLUE_SOFT,
            text_color="#FFFFFF", corner_radius=9)
        self.cpu_mode.set("Последовательно")
        self.cpu_mode.grid(row=r, column=0, sticky="ew", padx=18, pady=(0, 10)); r += 1

        self.cpu_start, self.cpu_stop = self._action_buttons(cfg, r, "cpu"); r += 1

        self.mon_cpu = MonitorPanel(mon_wrap, self.f, "cpu", self.sys["logical"])
        self.mon_cpu.grid(row=0, column=0, sticky="nsew")

    def _cpu_dur_changed(self, value):
        if value == DURATION_CUSTOM:
            self.cpu_dur_custom.grid()
        else:
            self.cpu_dur_custom.grid_remove()

    # =====================================================================
    # RAM tab
    # =====================================================================
    def _build_ram_tab(self, tab):
        cfg, mon_wrap = self._split(tab)
        r = 0
        self._cfg_title(cfg, "Тест памяти (ОЗУ)",
                        "Набор из 12 тестов в стиле memtest86: собственный адрес, бегущие "
                        "биты, движущиеся инверсии, шахматный порядок, перемещение блоков "
                        "и др. По умолчанию — все 12 тестов, 1 проход.",
                        r); r += 2

        self._section(cfg, "ТЕСТЫ ПАМЯТИ", r); r += 1
        self.ram_vars = {}
        for key in ram_tests.RAM_TEST_ORDER:
            name = ram_tests.RAM_TESTS[key][0]
            var = ctk.BooleanVar(value=True)
            self.ram_vars[key] = var
            self._check(cfg, name, var, r); r += 1
        self._select_buttons(cfg, self.ram_vars, r); r += 1

        self._section(cfg, "ПАРАМЕТРЫ", r); r += 1
        avail_mb = int(self.sys["ram_avail"] / (1024 * 1024)) if self.sys["ram_avail"] else 2048
        self.ram_max_mb = max(128, int(avail_mb * 0.9))
        default_mb = max(64, min(2048, int(avail_mb * 0.5)))
        ctk.CTkLabel(cfg, text=f"Объём тестируемой памяти · доступно ~{avail_mb} МБ",
                     font=self.f["small_bold"], text_color=T.INK, anchor="w").grid(
            row=r, column=0, sticky="ew", padx=18, pady=(4, 2)); r += 1
        row_mem = ctk.CTkFrame(cfg, fg_color="transparent")
        row_mem.grid(row=r, column=0, sticky="ew", padx=18, pady=(0, 2))
        row_mem.grid_columnconfigure(0, weight=1); r += 1
        self.ram_mb_var = ctk.IntVar(value=default_mb)
        self.ram_slider = ctk.CTkSlider(
            row_mem, from_=64, to=self.ram_max_mb, variable=self.ram_mb_var,
            command=self._ram_slider_moved, progress_color=T.ORANGE,
            button_color=T.NAVY, button_hover_color=T.BLUE_DK, fg_color=T.CARD_INSET)
        self.ram_slider.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.ram_mb_entry = ctk.CTkEntry(row_mem, width=84, justify="center",
                                         font=self.f["mono_bold"], fg_color=T.CARD,
                                         border_color=T.BORDER, text_color=T.INK)
        self.ram_mb_entry.insert(0, str(default_mb))
        self.ram_mb_entry.grid(row=0, column=1)
        self.ram_mb_entry.bind("<FocusOut>", self._ram_entry_changed)
        self.ram_mb_entry.bind("<Return>", self._ram_entry_changed)
        ctk.CTkLabel(cfg, text="МБ", font=self.f["tiny"], text_color=T.INK_FAINT,
                     anchor="e").grid(row=r - 1, column=0, sticky="e", padx=22)

        self._labeled_stepper(cfg, "Количество проходов (кругов)", r, "ram_rounds",
                              value=1, minimum=1, maximum=999); r += 1
        self._labeled_stepper(cfg, "Выдержка «Затухание битов», сек", r, "ram_fade",
                              value=5, minimum=0, maximum=600); r += 1

        ctk.CTkButton(cfg, text="↺  Стандартная вкладка (12 тестов · 1 проход)",
                      font=self.f["small_bold"], fg_color=T.BLUE_SOFT, text_color=T.BLUE,
                      hover_color="#D4E4FB", corner_radius=9, height=34,
                      command=self._ram_reset_default).grid(
            row=r, column=0, sticky="ew", padx=18, pady=(6, 8)); r += 1

        self.ram_start, self.ram_stop = self._action_buttons(cfg, r, "ram"); r += 1

        self.mon_ram = MonitorPanel(mon_wrap, self.f, "ram", self.sys["logical"])
        self.mon_ram.grid(row=0, column=0, sticky="nsew")

    def _ram_slider_moved(self, val):
        v = int(float(val))
        self.ram_mb_entry.delete(0, "end")
        self.ram_mb_entry.insert(0, str(v))

    def _ram_entry_changed(self, _e=None):
        try:
            v = int(float(self.ram_mb_entry.get()))
        except ValueError:
            v = self.ram_mb_var.get()
        v = max(64, min(self.ram_max_mb, v))
        self.ram_mb_var.set(v)
        self.ram_slider.set(v)
        self.ram_mb_entry.delete(0, "end")
        self.ram_mb_entry.insert(0, str(v))

    def _ram_reset_default(self):
        for k, v in self.ram_vars.items():
            v.set(True)
        self.ram_rounds.set(1)
        self.ram_fade.set(5)

    # ---- generic config widgets ----
    def _labeled_stepper(self, parent, label, row, attr, value, minimum, maximum):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=row, column=0, sticky="ew", padx=18, pady=(4, 2))
        f.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(f, text=label, font=self.f["small_bold"], text_color=T.INK,
                     anchor="w").grid(row=0, column=0, sticky="w")
        st = IntStepper(f, self.f, value=value, minimum=minimum, maximum=maximum)
        st.grid(row=0, column=1, sticky="e")
        setattr(self, attr, st)

    def _action_buttons(self, parent, row, kind):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.grid(row=row, column=0, sticky="ew", padx=16, pady=(6, 18))
        f.grid_columnconfigure(0, weight=1)
        f.grid_columnconfigure(1, weight=0)
        start = ctk.CTkButton(f, text="▶  Начать тест", font=self.f["h3"],
                              fg_color=T.ORANGE, hover_color=T.ORANGE_DK,
                              text_color="#FFFFFF", corner_radius=10, height=46,
                              command=lambda: self._start(kind))
        start.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        stop = ctk.CTkButton(f, text="■  Стоп", font=self.f["h3"], width=110,
                             fg_color=T.CARD, hover_color=T.RED_SOFT, text_color=T.RED,
                             border_width=2, border_color=T.RED, corner_radius=10,
                             height=46, command=self._stop, state="disabled")
        stop.grid(row=0, column=1, sticky="e")
        return start, stop

    # =====================================================================
    # Start / Stop
    # =====================================================================
    def _get_cpu_duration(self):
        if self.cpu_dur_var.get() == DURATION_CUSTOM:
            try:
                return max(1, int(float(self.cpu_dur_custom.get())))
            except ValueError:
                return 30
        for label, secs in DURATION_PRESETS:
            if label == self.cpu_dur_var.get():
                return secs
        return 30

    def _start(self, kind):
        if self.engine.is_running():
            return
        if kind == "cpu":
            tests = [k for k in cpu_tests.CPU_TEST_ORDER if self.cpu_vars[k].get()]
            if not tests:
                messagebox.showwarning(APP_TITLE, "Выберите хотя бы один тест CPU.")
                return
            mode = "concurrent" if "экстрим" in self.cpu_mode.get() else "sequential"
            job = {"kind": "cpu", "tests": tests, "rounds": self.cpu_rounds.get(),
                   "duration": self._get_cpu_duration(),
                   "num_workers": self.cpu_workers.get(), "mode": mode}
            self.mon_cpu.reset()
            self.tabs.set("  ПРОЦЕССОР (CPU)  ")
        else:
            tests = [k for k in ram_tests.RAM_TEST_ORDER if self.ram_vars[k].get()]
            if not tests:
                messagebox.showwarning(APP_TITLE, "Выберите хотя бы один тест ОЗУ.")
                return
            self._ram_entry_changed()
            job = {"kind": "ram", "tests": tests, "rounds": self.ram_rounds.get(),
                   "mb": self.ram_mb_var.get(), "bit_fade_wait": self.ram_fade.get()}
            self.mon_ram.reset()
            self.tabs.set("  ПАМЯТЬ (ОЗУ · Memtest)  ")

        self.active_kind = kind
        self._ram_moved_total = 0.0
        self._ram_errors_total = 0
        self._set_running_ui(True, kind)
        self.engine.start(job)

    def _stop(self):
        self.engine.stop()
        for b in (self.cpu_stop, self.ram_stop):
            b.configure(state="disabled", text="останавливаю…")

    def _set_running_ui(self, running, kind):
        # toggle start/stop for both tabs
        self.cpu_start.configure(state="disabled" if running else "normal")
        self.ram_start.configure(state="disabled" if running else "normal")
        if running:
            (self.cpu_stop if kind == "cpu" else self.ram_stop).configure(
                state="normal", text="■  Стоп")
        else:
            for b in (self.cpu_stop, self.ram_stop):
                b.configure(state="disabled", text="■  Стоп")

    # =====================================================================
    # Engine polling
    # =====================================================================
    def _mon(self):
        return self.mon_cpu if self.active_kind == "cpu" else self.mon_ram

    def _poll_engine(self):
        try:
            while True:
                ev = self.engine.queue.get_nowait()
                self._handle_event(ev)
        except queue.Empty:
            pass
        self.after(80, self._poll_engine)

    def _handle_event(self, ev):
        kind = ev.get("ev")
        mon = self._mon()
        if kind == "start":
            mon.log_line("═" * 46, "head")
        elif kind == "round":
            mon.set_round(ev["round"], ev["total"])
        elif kind == "test_start":
            mon.set_current(ev["name"], "RUNNING")
        elif kind == "progress":
            mon.set_progress(ev["overall_frac"], ev["test_frac"], ev.get("detail", ""),
                             ev.get("elapsed", 0))
        elif kind == "log":
            mon.log_line(ev["text"], ev.get("level", "info"))
        elif kind == "test_result":
            mon.add_result(ev)
            if self.active_kind == "ram":
                self._ram_moved_total += ev.get("bytes", 0)
                self._ram_errors_total += int(ev.get("errors", 0))
                mon.set_ram_live(ev.get("mbps", 0), self._ram_moved_total,
                                 self._ram_errors_total)
        elif kind == "done":
            self._on_done(ev)

    def _on_done(self, ev):
        mon = self._mon()
        summary = ev.get("summary", {})
        mon.overall.set(1.0 if summary.get("verdict") != "STOPPED" else mon.overall.get())
        mon.overall_pct.configure(text=f"{mon.overall.get()*100:.0f}%")
        verdict = summary.get("verdict", "FAILED")
        mon.set_current("Тестирование завершено" if verdict != "STOPPED"
                        else "Тестирование прервано", verdict)
        self._set_running_ui(False, self.active_kind)
        self._last_summary = summary
        self._last_results = ev.get("results", [])
        if ev.get("results"):
            self.after(200, lambda: self._show_report(summary, ev["results"]))

    # =====================================================================
    # Live meters (independent of a running test)
    # =====================================================================
    def _poll_live(self):
        vals = sysinfo.live_cpu_percent_percore()
        if vals:
            self.mon_cpu.set_live_cores(vals)
        self.after(800, self._poll_live)

    # =====================================================================
    # Report window
    # =====================================================================
    def _show_report(self, summary, results):
        ReportWindow(self, self.f, summary, results, self.sys)

    def _on_close(self):
        if self.engine.is_running():
            self.engine.stop()
        self.after(150, self.destroy)


def _aggregate_results(results):
    """Roll per-round records up to one row per test for the on-screen report.
    Detailed per-round data still goes to the saved .txt file."""
    agg, order = {}, []
    for r in results:
        k = r.get("key", r["name"])
        if k not in agg:
            agg[k] = {"name": r["name"], "kind": r.get("kind"), "rounds": 0,
                      "passed": 0, "failed": 0, "stopped": 0, "errors": 0,
                      "duration": 0.0, "metric": "", "mbps": 0.0}
            order.append(k)
        a = agg[k]
        a["rounds"] += 1
        st = r["status"]
        if st == "PASSED":
            a["passed"] += 1
        elif st in ("FAILED", "ERROR"):
            a["failed"] += 1
        else:
            a["stopped"] += 1
        a["errors"] += int(r.get("errors", 0) or 0)
        a["duration"] += r.get("duration", 0)
        if r.get("metric"):
            a["metric"] = r["metric"]
        if r.get("mbps"):
            a["mbps"] = r["mbps"]
    for a in agg.values():
        a["status"] = ("FAILED" if a["failed"] or a["errors"]
                       else ("STOPPED" if a["stopped"] else "PASSED"))
    return [agg[k] for k in order]


class ReportWindow(ctk.CTkToplevel):
    """Client-facing report: everything essential fits ONE window (no scroll)
    so a single screenshot captures the whole result."""

    def __init__(self, master, fonts, summary, results, sysdict):
        super().__init__(master)
        self.f = fonts
        self.summary = summary
        self.results = results
        self.agg = _aggregate_results(results)
        self.sys = sysdict
        self.title("SERVER GATE — Отчёт о тестировании")
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(1120, sw - 50), min(780, sh - 70)
        self.geometry(f"{w}x{h}+{max(0, (sw - w) // 2)}+{max(0, (sh - h) // 4)}")
        self.minsize(min(960, sw - 40), min(620, sh - 70))
        self.configure(fg_color=T.BG)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        self.transient(master)
        self.after(60, self.lift)
        self.after(120, self.focus_force)
        self.after(400, self._fix_icon)

        self._build_banner()
        self._build_tiles()
        self._build_body()
        self._build_actions()

    def _fix_icon(self):
        # CTkToplevel re-applies its own icon ~250ms after creation; override it.
        try:
            if os.name == "nt":
                self.iconbitmap(assets.icon_path())
            self._icon_img = tk.PhotoImage(file=assets.icon_png_path())
            self.iconphoto(False, self._icon_img)
        except Exception:
            pass

    def _build_banner(self):
        verdict = self.summary.get("verdict", "FAILED")
        vcolor = {"PASSED": T.GREEN, "FAILED": T.RED, "STOPPED": T.AMBER}.get(verdict, T.RED)
        vtext = {"PASSED": "ВСЕ ТЕСТЫ ПРОЙДЕНЫ", "FAILED": "ОБНАРУЖЕНЫ ОШИБКИ",
                 "STOPPED": "ТЕСТ ОСТАНОВЛЕН"}.get(verdict, verdict)
        kind_txt = ("процессора (CPU)" if self.summary.get("kind") == "cpu"
                    else "оперативной памяти (ОЗУ)")

        banner = ctk.CTkFrame(self, fg_color=T.CARD, corner_radius=0)
        banner.grid(row=0, column=0, sticky="ew")
        banner.grid_columnconfigure(1, weight=1)
        try:
            img, size = assets.load_logo(44)
            self._logo_img = ctk.CTkImage(light_image=img, dark_image=img, size=size)
            ctk.CTkLabel(banner, image=self._logo_img, text="").grid(
                row=0, column=0, padx=(22, 16), pady=14)
        except Exception:
            ctk.CTkLabel(banner, text="SERVERGATE",
                         font=ctk.CTkFont(family=T.UI_FAMILY, size=26, weight="bold"),
                         text_color=T.BLUE).grid(row=0, column=0, padx=(22, 16), pady=14)
        tcol = ctk.CTkFrame(banner, fg_color="transparent")
        tcol.grid(row=0, column=1, sticky="w")
        ctk.CTkLabel(tcol, text="ОТЧЁТ О СТРЕСС-ТЕСТИРОВАНИИ", font=self.f["h2"],
                     text_color=T.NAVY, anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(tcol, text=f"Тест {kind_txt} · "
                     + datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
                     font=self.f["small"], text_color=T.INK_MUTED,
                     anchor="w").grid(row=1, column=0, sticky="w")
        vb = ctk.CTkFrame(banner, fg_color=vcolor, corner_radius=10)
        vb.grid(row=0, column=2, padx=(12, 22))
        ctk.CTkLabel(vb, text=vtext, font=ctk.CTkFont(family=T.UI_FAMILY, size=16,
                     weight="bold"), text_color="#FFFFFF").grid(row=0, column=0,
                                                               padx=22, pady=8)
        stripe = ctk.CTkFrame(banner, fg_color=T.ORANGE, height=3, corner_radius=0)
        stripe.grid(row=1, column=0, columnspan=3, sticky="ew")

    def _build_tiles(self):
        tiles = ctk.CTkFrame(self, fg_color="transparent")
        tiles.grid(row=1, column=0, sticky="ew", padx=16, pady=(12, 4))
        for i in range(5):
            tiles.grid_columnconfigure(i, weight=1, uniform="t")
        n_pass = sum(1 for a in self.agg if a["status"] == "PASSED")
        n_fail = sum(1 for a in self.agg if a["status"] == "FAILED")
        errs = self.summary.get("errors", 0)
        self._tile(tiles, "ТЕСТОВ ПРОЙДЕНО", f"{n_pass}/{len(self.agg)}",
                   T.GREEN if n_pass == len(self.agg) else T.AMBER, 0)
        self._tile(tiles, "НЕ ПРОЙДЕНО", str(n_fail),
                   T.RED if n_fail else T.INK_MUTED, 1)
        self._tile(tiles, "ОШИБОК ПАМЯТИ", str(errs), T.RED if errs else T.GREEN, 2)
        self._tile(tiles, "КРУГОВ", str(self.summary.get("rounds", 1)), T.NAVY, 3)
        self._tile(tiles, "ОБЩЕЕ ВРЕМЯ", fmt_time(self.summary.get("elapsed", 0)),
                   T.NAVY, 4)

    def _build_body(self):
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.grid(row=2, column=0, sticky="nsew", padx=16, pady=(6, 4))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        # ---- results (left) ----
        card = ctk.CTkFrame(body, fg_color=T.CARD, corner_radius=12, border_width=1,
                            border_color=T.BORDER)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        card.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(card, text="Результаты тестов", font=self.f["h3"],
                     text_color=T.NAVY, anchor="w").grid(row=0, column=0, sticky="ew",
                                                         padx=16, pady=(10, 4))
        for i, a in enumerate(self.agg):
            self._result_row(card, a, i + 1)
        ctk.CTkLabel(card, text="", height=4).grid(row=len(self.agg) + 1, column=0)

        # ---- system (right) ----
        info = ctk.CTkFrame(body, fg_color=T.CARD, corner_radius=12, border_width=1,
                            border_color=T.BORDER, width=330)
        info.grid(row=0, column=1, sticky="ns")
        info.grid_propagate(True)
        info.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(info, text="Система", font=self.f["h3"], text_color=T.NAVY,
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=16,
                                      pady=(10, 4))
        cpu_line = self.sys.get("cpu_short") or self.sys["cpu_name"]
        lines = [("Процессор", cpu_line)]
        if self.sys.get("sockets", 1) > 1:
            lines.append(("Физических CPU", str(self.sys["sockets"])))
        lines.append(("Ядра / потоки",
                      f'{self.sys["physical"]} / {self.sys["logical"]}'))
        if self.sys.get("freq_ghz"):
            lines.append(("Частота", f'{self.sys["freq_ghz"]:g} ГГц'))
        lines.append(("ОЗУ", f'{self.sys["ram_total_gb"]:g} ГБ'
                      if self.sys["ram_total_gb"] else "—"))
        if self.sys.get("platform"):
            lines.append(("Платформа", self.sys["platform"]))
        lines.append(("ОС", f'{self.sys["os"]} ({self.sys["arch"]})'))
        if self.summary.get("params"):
            lines.append(("Параметры", self.summary["params"]))
        lines.append(("Дата", datetime.datetime.now().strftime("%d.%m.%Y %H:%M")))
        for i, (k, v) in enumerate(lines, start=1):
            rowf = ctk.CTkFrame(info, fg_color="transparent")
            rowf.grid(row=i, column=0, sticky="ew", padx=16, pady=2)
            rowf.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(rowf, text=k, font=self.f["small"], text_color=T.INK_MUTED,
                         width=110, anchor="nw", justify="left").grid(
                row=0, column=0, sticky="nw")
            ctk.CTkLabel(rowf, text=v, font=self.f["small_bold"], text_color=T.INK,
                         anchor="w", justify="left", wraplength=190).grid(
                row=0, column=1, sticky="w", padx=(6, 0))
        ctk.CTkLabel(info, text="", height=4).grid(row=len(lines) + 1, column=0)

    def _tile(self, parent, title, value, color, col):
        f = ctk.CTkFrame(parent, fg_color=T.CARD, corner_radius=12, border_width=1,
                         border_color=T.BORDER)
        f.grid(row=0, column=col, sticky="ew", padx=4)
        ctk.CTkLabel(f, text=title, font=self.f["tiny"], text_color=T.INK_MUTED).grid(
            row=0, column=0, padx=12, pady=(10, 0))
        ctk.CTkLabel(f, text=value, font=ctk.CTkFont(family=T.MONO_FAMILY, size=22,
                     weight="bold"), text_color=color).grid(row=1, column=0, padx=12,
                                                           pady=(0, 10))

    def _result_row(self, parent, a, idx):
        # compact zebra rows so up to 12 tests fit one screen for a screenshot
        row = ctk.CTkFrame(parent, corner_radius=6,
                           fg_color=(T.CARD_ALT if idx % 2 else "transparent"))
        row.grid(row=idx, column=0, sticky="ew", padx=10, pady=0)
        row.grid_columnconfigure(2, weight=1)
        dot_color = {"PASSED": T.GREEN, "FAILED": T.RED}.get(a["status"], T.AMBER)
        ctk.CTkLabel(row, text="●", font=self.f["small_bold"], text_color=dot_color,
                     width=20).grid(row=0, column=0, padx=(6, 0), pady=3)
        ctk.CTkLabel(row, text=a["name"], font=self.f["small_bold"], text_color=T.INK,
                     anchor="w").grid(row=0, column=1, sticky="w", padx=(0, 10))
        metric = a.get("metric", "")
        if a.get("kind") == "ram" and a.get("mbps"):
            metric = f"{metric} · {a['mbps']:,.0f} МБ/с".replace(",", " ")
        if a.get("errors"):
            metric = f"{metric} · ошибок: {a['errors']}"
        if len(metric) > 42:
            metric = metric[:41] + "…"
        ctk.CTkLabel(row, text=metric, font=self.f["mono_sm"], text_color=T.INK_MUTED,
                     anchor="e").grid(row=0, column=2, sticky="e", padx=(0, 8))
        if a["rounds"] > 1:
            ctk.CTkLabel(row, text=f'{a["passed"]}/{a["rounds"]} кр.',
                         font=self.f["mono_sm"], text_color=T.INK_FAINT,
                         width=54).grid(row=0, column=3, padx=(0, 4))
        StatusPill(row, self.f, a["status"]).grid(row=0, column=4, padx=(0, 6),
                                                  pady=2)

    def _build_actions(self):
        bar = ctk.CTkFrame(self, fg_color=T.CARD, corner_radius=0, height=64)
        bar.grid(row=3, column=0, sticky="ew")
        bar.grid_columnconfigure(0, weight=1)
        ctk.CTkButton(bar, text="💾  Сохранить отчёт (.txt)", font=self.f["h3"],
                      fg_color=T.NAVY, hover_color=T.BLUE_DK, text_color="#FFFFFF",
                      corner_radius=10, height=42, command=self._save).grid(
            row=0, column=0, sticky="e", padx=(0, 8), pady=11)
        ctk.CTkButton(bar, text="Закрыть", font=self.f["h3"], width=120,
                      fg_color=T.CARD_INSET, hover_color=T.BORDER, text_color=T.INK,
                      corner_radius=10, height=42, command=self.destroy).grid(
            row=0, column=1, sticky="e", padx=(0, 18), pady=11)

    def _report_text(self):
        s = self.summary
        L = []
        L.append("=" * 60)
        L.append(" SERVER GATE — ОТЧЁТ О СТРЕСС-ТЕСТИРОВАНИИ ".center(60))
        L.append("=" * 60)
        L.append(f"Дата:        {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        L.append(f"Тип теста:   {'ПРОЦЕССОР (CPU)' if s.get('kind')=='cpu' else 'ПАМЯТЬ (ОЗУ)'}")
        L.append(f"Вердикт:     {s.get('verdict')}")
        L.append("")
        L.append("СИСТЕМА")
        L.append(f"  Процессор:     {self.sys['cpu_name']}")
        if self.sys.get("sockets", 1) > 1:
            L.append(f"  Физических CPU: {self.sys['sockets']}")
            for i, p in enumerate(self.sys.get("packages", []), 1):
                L.append(f"    CPU {i}:       {p['name']} — "
                         f"{p['cores']} ядер / {p['threads']} потоков")
        L.append(f"  Ядра/потоки:   {self.sys['physical']} / {self.sys['logical']}")
        if self.sys.get("freq_ghz"):
            L.append(f"  Частота:       {self.sys['freq_ghz']:g} ГГц")
        L.append(f"  ОЗУ:           {self.sys['ram_total_gb']:g} ГБ")
        if self.sys.get("platform"):
            L.append(f"  Платформа:     {self.sys['platform']}")
        L.append(f"  ОС:            {self.sys['os']} ({self.sys['arch']})")
        if self.summary.get("params"):
            L.append(f"  Параметры:     {self.summary['params']}")
        L.append("")
        L.append("ИТОГИ")
        L.append(f"  Всего тестов:  {s.get('total',0)}")
        L.append(f"  Пройдено:      {s.get('passed',0)}")
        L.append(f"  Не пройдено:   {s.get('failed',0)}")
        L.append(f"  Остановлено:   {s.get('stopped',0)}")
        L.append(f"  Ошибок памяти: {s.get('errors',0)}")
        L.append(f"  Кругов:        {s.get('rounds',1)}")
        L.append(f"  Время:         {fmt_time(s.get('elapsed',0))}")
        L.append("")
        L.append("ПОДРОБНО")
        L.append("-" * 60)
        for r in self.results:
            L.append(f"  [Круг {r.get('round',1)}] {r['name']}")
            L.append(f"      Статус:   {r['status']}")
            if r.get("metric"):
                L.append(f"      Метрика:  {r['metric']}")
            if r.get("detail"):
                L.append(f"      Детали:   {r['detail']}")
            if r.get("kind") == "ram":
                L.append(f"      Ошибок:   {r.get('errors',0)}")
                if r.get("mbps"):
                    L.append(f"      Скорость: {r['mbps']:.0f} МБ/с")
            if r.get("error"):
                L.append(f"      Ошибка:   {r['error']}")
            L.append(f"      Время:    {fmt_time(r.get('duration',0))}")
            L.append("")
        L.append("=" * 60)
        L.append(" SERVER GATE ".center(60, " "))
        L.append(("Вердикт: " + str(s.get("verdict"))).center(60))
        L.append("=" * 60)
        return "\n".join(L)

    def _save(self):
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        default = f"SERVER_GATE_report_{ts}.txt"
        path = filedialog.asksaveasfilename(
            parent=self, title="Сохранить отчёт", defaultextension=".txt",
            initialfile=default, filetypes=[("Текстовый файл", "*.txt")])
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as fp:
                fp.write(self._report_text())
            messagebox.showinfo(APP_TITLE, f"Отчёт сохранён:\n{path}", parent=self)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror(APP_TITLE, f"Не удалось сохранить:\n{e}", parent=self)


def launch():
    app = App()
    app.mainloop()
