"""Live monitoring panel (shared by the CPU and RAM tabs)."""
from __future__ import annotations

import customtkinter as ctk

import theme as T
from widgets import StatusPill, CoreMeter, Card, fmt_time


class StatTile(ctk.CTkFrame):
    def __init__(self, master, fonts, title, value="—", accent=T.BLUE):
        super().__init__(master, fg_color=T.CARD_INSET, corner_radius=10,
                         border_width=1, border_color=T.BORDER)
        self.grid_columnconfigure(0, weight=1)
        self.title = ctk.CTkLabel(self, text=title, font=fonts["tiny"],
                                  text_color=T.INK_MUTED, anchor="w")
        self.title.grid(row=0, column=0, sticky="ew", padx=12, pady=(9, 0))
        self.value = ctk.CTkLabel(self, text=value, font=fonts["mono_lg"],
                                  text_color=accent, anchor="w")
        self.value.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 9))

    def set(self, value, accent=None):
        self.value.configure(text=value)
        if accent:
            self.value.configure(text_color=accent)


class MonitorPanel(ctk.CTkScrollableFrame):
    """Right-hand live panel.  The whole column scrolls vertically so every
    test result and the full log stay reachable even on small server consoles
    (1024x768 via VGA / iLO)."""

    def __init__(self, master, fonts, kind, ncores):
        super().__init__(master, fg_color="transparent")
        self.fonts = fonts
        self.kind = kind
        self.ncores = ncores
        self.core_meters = []
        self._result_rows = 0
        self.grid_columnconfigure(0, weight=1)

        self._build_status_card()
        if kind == "cpu":
            self._build_cores()
        else:
            self._build_ram_stats()
        self._build_results()
        self._build_log()

    # ---- status / progress ----
    def _build_status_card(self):
        c = Card(self)
        c.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        c.grid_columnconfigure(0, weight=1)

        top = ctk.CTkFrame(c, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=18, pady=(16, 6))
        top.grid_columnconfigure(0, weight=1)
        self.current = ctk.CTkLabel(top, text="Готов к запуску", font=self.fonts["h2"],
                                    text_color=T.INK, anchor="w")
        self.current.grid(row=0, column=0, sticky="w")
        self.pill = StatusPill(top, self.fonts, "WAITING")
        self.pill.grid(row=0, column=1, sticky="e")

        self.detail = ctk.CTkLabel(c, text="Выберите тесты и нажмите «Начать тест».",
                                   font=self.fonts["small"], text_color=T.INK_MUTED,
                                   anchor="w")
        self.detail.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 8))

        # overall progress
        self.overall = ctk.CTkProgressBar(c, height=16, corner_radius=8,
                                          progress_color=T.ORANGE, fg_color=T.CARD_INSET)
        self.overall.set(0)
        self.overall.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 4))
        row = ctk.CTkFrame(c, fg_color="transparent")
        row.grid(row=3, column=0, sticky="ew", padx=18, pady=(0, 6))
        row.grid_columnconfigure(1, weight=1)
        self.overall_pct = ctk.CTkLabel(row, text="0%", font=self.fonts["mono_bold"],
                                        text_color=T.ORANGE_DK)
        self.overall_pct.grid(row=0, column=0, sticky="w")
        self.round_lbl = ctk.CTkLabel(row, text="", font=self.fonts["small_bold"],
                                      text_color=T.NAVY)
        self.round_lbl.grid(row=0, column=1)
        self.timers = ctk.CTkLabel(row, text="прошло 00:00 · осталось —:—",
                                   font=self.fonts["mono_sm"], text_color=T.INK_MUTED)
        self.timers.grid(row=0, column=2, sticky="e")

        # per-test progress
        self.testbar = ctk.CTkProgressBar(c, height=8, corner_radius=6,
                                          progress_color=T.BLUE, fg_color=T.CARD_INSET)
        self.testbar.set(0)
        self.testbar.grid(row=4, column=0, sticky="ew", padx=18, pady=(0, 16))

    # ---- cpu per-core ----
    def _build_cores(self):
        c = Card(self)
        c.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        c.grid_columnconfigure(0, weight=1)
        head = ctk.CTkFrame(c, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 6))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text="Загрузка ядер", font=self.fonts["h3"],
                     text_color=T.NAVY).grid(row=0, column=0, sticky="w")
        self.cpu_total = ctk.CTkLabel(head, text="ЦП: 0%", font=self.fonts["mono_bold"],
                                      text_color=T.BLUE)
        self.cpu_total.grid(row=0, column=1, sticky="e")

        sf = ctk.CTkScrollableFrame(c, fg_color="transparent", height=138)
        sf.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 12))
        cols = 2 if self.ncores > 8 else 1
        for i in range(cols):
            sf.grid_columnconfigure(i, weight=1, uniform="core")
        for i in range(self.ncores):
            m = CoreMeter(sf, self.fonts, i)
            m.grid(row=i // cols, column=i % cols, sticky="ew", padx=8, pady=3)
            self.core_meters.append(m)

    def _build_ram_stats(self):
        wrap = ctk.CTkFrame(self, fg_color="transparent")
        wrap.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        for i in range(3):
            wrap.grid_columnconfigure(i, weight=1, uniform="stat")
        self.tile_err = StatTile(wrap, self.fonts, "ОШИБОК ПАМЯТИ", "0", accent=T.GREEN)
        self.tile_err.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.tile_moved = StatTile(wrap, self.fonts, "ПРОВЕРЕНО ДАННЫХ", "0 МБ", accent=T.NAVY)
        self.tile_moved.grid(row=0, column=1, sticky="ew", padx=8)
        self.tile_speed = StatTile(wrap, self.fonts, "СКОРОСТЬ", "0 МБ/с", accent=T.BLUE)
        self.tile_speed.grid(row=0, column=2, sticky="ew", padx=(8, 0))
        self._ram_errors = 0
        self._ram_moved = 0.0

    # ---- results list ----
    def _build_results(self):
        c = Card(self)
        c.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        c.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(c, text="Результаты тестов", font=self.fonts["h3"],
                     text_color=T.NAVY, anchor="w").grid(row=0, column=0, sticky="ew",
                                                         padx=16, pady=(12, 4))
        # plain frame: rows grow downward, the whole panel scrolls
        self.results = ctk.CTkFrame(c, fg_color="transparent")
        self.results.grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 10))
        self.results.grid_columnconfigure(0, weight=1)
        self._empty = ctk.CTkLabel(self.results, text="Пока нет результатов.",
                                   font=self.fonts["small"], text_color=T.INK_FAINT)
        self._empty.grid(row=0, column=0, pady=16)

    # ---- log ----
    def _build_log(self):
        c = Card(self)
        c.grid(row=3, column=0, sticky="ew")
        c.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(c, text="Журнал", font=self.fonts["h3"], text_color=T.NAVY,
                     anchor="w").grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
        self.log = ctk.CTkTextbox(c, fg_color="#0B1220", text_color="#D6E2F5",
                                  font=self.fonts["mono_sm"], corner_radius=10,
                                  border_width=0, wrap="word", height=210)
        self.log.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 12))
        self.log.configure(state="disabled")
        self._tags_ready = False

    def _ensure_tags(self):
        if self._tags_ready:
            return
        tb = getattr(self.log, "_textbox", None)
        if tb is not None:
            tb.tag_configure("head", foreground="#FFB169")
            tb.tag_configure("round", foreground="#7FB2FF")
            tb.tag_configure("test", foreground="#9FE7FF")
            tb.tag_configure("pass", foreground="#5EE0A6")
            tb.tag_configure("fail", foreground="#FF8080")
            tb.tag_configure("warn", foreground="#FFCB6B")
            tb.tag_configure("info", foreground="#B9C6DE")
            tb.tag_configure("error", foreground="#FF8080")
        self._tags_ready = True

    # ---- public API ----
    def log_line(self, text, level="info"):
        self._ensure_tags()
        self.log.configure(state="normal")
        tb = getattr(self.log, "_textbox", None)
        if tb is not None:
            tb.insert("end", text + "\n", (level,))
        else:
            self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def set_current(self, name, status="RUNNING"):
        self.current.configure(text=name)
        self.pill.set_status(status)

    def set_detail(self, text):
        self.detail.configure(text=text)

    def set_round(self, r, total):
        self.round_lbl.configure(text=f"круг {r} / {total}")

    def set_progress(self, overall, test_frac, detail, elapsed):
        self.overall.set(overall)
        self.overall_pct.configure(text=f"{overall*100:.0f}%")
        self.testbar.set(test_frac)
        if detail:
            self.detail.configure(text=detail)
        remaining = (elapsed * (1 - overall) / overall) if overall > 0.01 else None
        rem = fmt_time(remaining) if remaining is not None else "—:—"
        self.timers.configure(text=f"прошло {fmt_time(elapsed)} · осталось {rem}")

    def set_live_cores(self, values):
        if self.kind != "cpu" or not self.core_meters:
            return
        for i, v in enumerate(values[:len(self.core_meters)]):
            self.core_meters[i].set_value(v)
        if values:
            avg = sum(values) / len(values)
            self.cpu_total.configure(text=f"ЦП: {avg:.0f}%")

    def set_ram_live(self, mbps, moved_bytes, errors):
        if self.kind != "ram":
            return
        self.tile_speed.set(f"{mbps:,.0f} МБ/с".replace(",", " "))
        self.tile_moved.set(f"{moved_bytes/1024/1024:,.0f} МБ".replace(",", " "))
        acc = T.RED if errors else T.GREEN
        self.tile_err.set(f"{errors:,}".replace(",", " "), accent=acc)

    def add_result(self, rec):
        if self._empty is not None:
            self._empty.destroy()
            self._empty = None
        row = ctk.CTkFrame(self.results, fg_color=T.CARD_ALT, corner_radius=9,
                           border_width=1, border_color=T.BORDER)
        row.grid(row=self._result_rows, column=0, sticky="ew", padx=6, pady=3)
        row.grid_columnconfigure(1, weight=1)
        rnd = rec.get("round", 1)
        idx = ctk.CTkLabel(row, text=f"#{rnd}", font=self.fonts["mono_sm"],
                           text_color=T.INK_FAINT, width=32)
        idx.grid(row=0, column=0, padx=(10, 4), pady=8)
        name = ctk.CTkLabel(row, text=rec["name"], font=self.fonts["body_bold"],
                            text_color=T.INK, anchor="w")
        name.grid(row=0, column=1, sticky="w", pady=(8, 0))
        metric = rec.get("metric", "")
        if rec.get("kind") == "ram" and rec.get("mbps"):
            metric = f"{metric} · {rec['mbps']:,.0f} МБ/с".replace(",", " ")
        sub = ctk.CTkLabel(row, text=metric, font=self.fonts["mono_sm"],
                           text_color=T.INK_MUTED, anchor="w")
        sub.grid(row=1, column=1, sticky="w", pady=(0, 8))
        pill = StatusPill(row, self.fonts, rec["status"])
        pill.grid(row=0, column=2, rowspan=2, padx=8)
        dur = ctk.CTkLabel(row, text=fmt_time(rec.get("duration", 0)),
                           font=self.fonts["mono_sm"], text_color=T.INK_FAINT, width=56)
        dur.grid(row=0, column=3, rowspan=2, padx=(4, 10))
        self._result_rows += 1

    def reset(self):
        for w in self.results.winfo_children():
            w.destroy()
        self._result_rows = 0
        self._empty = ctk.CTkLabel(self.results, text="Пока нет результатов.",
                                   font=self.fonts["small"], text_color=T.INK_FAINT)
        self._empty.grid(row=0, column=0, pady=16)
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self.overall.set(0)
        self.testbar.set(0)
        self.overall_pct.configure(text="0%")
        self.round_lbl.configure(text="")
        self.timers.configure(text="прошло 00:00 · осталось —:—")
        self.set_current("Готов к запуску", "WAITING")
        self.set_detail("Выберите тесты и нажмите «Начать тест».")
        if self.kind == "ram":
            self.tile_err.set("0", accent=T.GREEN)
            self.tile_moved.set("0 МБ")
            self.tile_speed.set("0 МБ/с")
