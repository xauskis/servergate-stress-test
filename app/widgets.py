"""Reusable CustomTkinter widgets for SERVER GATE."""
from __future__ import annotations

import customtkinter as ctk

import theme as T


def fmt_time(sec: float) -> str:
    sec = int(max(0, sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


class StatusPill(ctk.CTkLabel):
    """Small rounded status chip that recolours by status keyword."""
    LABELS = {
        "PASSED": "ПРОЙДЕН", "FAILED": "НЕ ПРОЙДЕН", "STOPPED": "ОСТАНОВЛЕН",
        "RUNNING": "ВЫПОЛНЯЕТСЯ", "WAITING": "ОЖИДАНИЕ", "ERROR": "ОШИБКА",
    }

    def __init__(self, master, fonts, status="WAITING", **kw):
        fg, soft = T.STATUS_COLORS.get(status, (T.INK_FAINT, T.CARD_INSET))
        super().__init__(master, text=self.LABELS.get(status, status),
                         font=fonts["small_bold"], text_color=fg, fg_color=soft,
                         corner_radius=8, padx=12, pady=3, **kw)

    def set_status(self, status):
        fg, soft = T.STATUS_COLORS.get(status, (T.INK_FAINT, T.CARD_INSET))
        self.configure(text=self.LABELS.get(status, status), text_color=fg, fg_color=soft)


class IntStepper(ctk.CTkFrame):
    """[-] [ value ] [+] integer control."""
    def __init__(self, master, fonts, value=1, minimum=1, maximum=999, width=132):
        super().__init__(master, fg_color=T.CARD_INSET, corner_radius=9,
                         border_width=1, border_color=T.BORDER)
        self.min, self.max = minimum, maximum
        self.var = ctk.StringVar(value=str(value))
        btn = dict(width=34, height=30, corner_radius=7, font=fonts["h2"],
                   fg_color=T.BLUE_SOFT, hover_color="#D4E4FB", text_color=T.BLUE)
        self._minus = ctk.CTkButton(self, text="−", command=self._dec, **btn)
        self._minus.grid(row=0, column=0, padx=4, pady=4)
        self._entry = ctk.CTkEntry(self, textvariable=self.var, width=width - 88,
                                   height=30, justify="center", font=fonts["mono_bold"],
                                   fg_color=T.CARD, border_color=T.BORDER,
                                   text_color=T.INK)
        self._entry.grid(row=0, column=1, padx=0, pady=4)
        self._plus = ctk.CTkButton(self, text="+", command=self._inc, **btn)
        self._plus.grid(row=0, column=2, padx=4, pady=4)
        self._entry.bind("<FocusOut>", lambda e: self._clamp())

    def _clamp(self):
        try:
            v = int(float(self.var.get()))
        except ValueError:
            v = self.min
        v = max(self.min, min(self.max, v))
        self.var.set(str(v))
        return v

    def _inc(self):
        self.var.set(str(min(self.max, self._clamp() + 1)))

    def _dec(self):
        self.var.set(str(max(self.min, self._clamp() - 1)))

    def get(self):
        return self._clamp()

    def set(self, v):
        self.var.set(str(max(self.min, min(self.max, int(v)))))

    def set_enabled(self, on):
        state = "normal" if on else "disabled"
        for w in (self._minus, self._plus, self._entry):
            w.configure(state=state)


class CoreMeter(ctk.CTkFrame):
    """A tiny per-core usage bar."""
    def __init__(self, master, fonts, index):
        super().__init__(master, fg_color="transparent")
        self.grid_columnconfigure(1, weight=1)
        self.lbl = ctk.CTkLabel(self, text=f"{index:>2}", font=fonts["mono_sm"],
                                text_color=T.INK_MUTED, width=24)
        self.lbl.grid(row=0, column=0, padx=(0, 6))
        self.bar = ctk.CTkProgressBar(self, height=9, corner_radius=4,
                                      progress_color=T.BLUE, fg_color=T.CARD_INSET)
        self.bar.set(0)
        self.bar.grid(row=0, column=1, sticky="ew")
        self.pct = ctk.CTkLabel(self, text="0%", font=fonts["mono_sm"],
                                text_color=T.INK_MUTED, width=40)
        self.pct.grid(row=0, column=2, padx=(6, 0))

    def set_value(self, v):
        self.bar.set(v / 100.0)
        self.pct.configure(text=f"{v:.0f}%")
        if v >= 90:
            self.bar.configure(progress_color=T.ORANGE)
        elif v >= 60:
            self.bar.configure(progress_color=T.BLUE)
        else:
            self.bar.configure(progress_color=T.GREEN)


class Card(ctk.CTkFrame):
    def __init__(self, master, **kw):
        kw.setdefault("fg_color", T.CARD)
        kw.setdefault("corner_radius", 14)
        kw.setdefault("border_width", 1)
        kw.setdefault("border_color", T.BORDER)
        super().__init__(master, **kw)


def section_label(master, fonts, text):
    return ctk.CTkLabel(master, text=text, font=fonts["h3"], text_color=T.NAVY,
                        anchor="w")
