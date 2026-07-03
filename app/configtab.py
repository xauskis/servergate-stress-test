"""«Конфигурация системы» tab — AIDA-style hardware passport."""
from __future__ import annotations

import threading

import customtkinter as ctk

import hwinfo
import theme as T
from widgets import Card


class ConfigTab(ctk.CTkFrame):
    def __init__(self, master, fonts):
        super().__init__(master, fg_color="transparent")
        self.fonts = fonts
        self._thread = None
        self._result = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(self, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=4, pady=(2, 8))
        head.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(head, text="Конфигурация системы", font=self.fonts["h1"],
                     text_color=T.NAVY, anchor="w").grid(row=0, column=0, sticky="w")
        self.status = ctk.CTkLabel(head, text="", font=self.fonts["small"],
                                   text_color=T.INK_MUTED)
        self.status.grid(row=0, column=1, sticky="e", padx=(0, 10))
        self.btn = ctk.CTkButton(head, text="↺  Обновить", width=120, height=32,
                                 font=self.fonts["small_bold"], fg_color=T.BLUE,
                                 hover_color=T.BLUE_DK, text_color="#FFFFFF",
                                 corner_radius=9, command=self.refresh)
        self.btn.grid(row=0, column=2, sticky="e")

        self.body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.body.grid(row=1, column=0, sticky="nsew")
        for c in (0, 1):
            self.body.grid_columnconfigure(c, weight=1, uniform="cfg")

        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self):
        if self._thread is not None and self._thread.is_alive():
            return
        for w in self.body.winfo_children():
            w.destroy()
        self.btn.configure(state="disabled")
        self.status.configure(text="Сбор информации о системе…")
        ph = ctk.CTkLabel(self.body, text="Сбор информации о системе…",
                          font=self.fonts["body"], text_color=T.INK_FAINT)
        ph.grid(row=0, column=0, columnspan=2, pady=40)
        self._result = None
        self._thread = threading.Thread(target=self._collect, daemon=True)
        self._thread.start()
        self.after(150, self._poll)

    def _collect(self):
        try:
            self._result = hwinfo.collect()
        except Exception as e:  # noqa: BLE001
            self._result = [("Ошибка", [("Не удалось собрать данные",
                                         f"{type(e).__name__}: {e}")])]

    def _poll(self):
        if self._result is None:
            self.after(150, self._poll)
            return
        for w in self.body.winfo_children():
            w.destroy()
        self._populate(self._result)
        self.btn.configure(state="normal")
        self.status.configure(text="")

    # ------------------------------------------------------------------
    def _populate(self, sections):
        for i, (title, rows) in enumerate(sections):
            card = Card(self.body)
            card.grid(row=i // 2, column=i % 2, sticky="new",
                      padx=6, pady=6)
            card.grid_columnconfigure(0, weight=1)
            ctk.CTkLabel(card, text=title, font=self.fonts["h3"],
                         text_color=T.ORANGE_DK, anchor="w").grid(
                row=0, column=0, sticky="ew", padx=16, pady=(12, 4))
            for j, (k, v) in enumerate(rows, start=1):
                rowf = ctk.CTkFrame(card, fg_color="transparent")
                rowf.grid(row=j, column=0, sticky="ew", padx=16, pady=1)
                rowf.grid_columnconfigure(1, weight=1)
                ctk.CTkLabel(rowf, text=k, font=self.fonts["small"],
                             text_color=T.INK_MUTED, width=178, anchor="nw",
                             justify="left").grid(row=0, column=0, sticky="nw")
                ctk.CTkLabel(rowf, text=v, font=self.fonts["small_bold"],
                             text_color=T.INK, anchor="w", justify="left",
                             wraplength=290).grid(row=0, column=1, sticky="w",
                                                  padx=(8, 0))
            ctk.CTkLabel(card, text="", height=6).grid(
                row=len(rows) + 1, column=0)
