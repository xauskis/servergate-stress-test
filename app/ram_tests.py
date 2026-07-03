"""RAM stress tests — memtest86-style patterns over a large allocated buffer.

These operate on user-space memory that the OS grants to the process (not the
firmware-reserved physical map a bare-metal tester like memtest86 sees), but
the algorithms are the classic ones: own-address, walking ones/zeros, moving
inversions, checkerboard, solid bits, block move, modulo-20, random compare
and bit-fade retention.  numpy keeps them fast enough to move real bandwidth.

Each runner: (v, stop, progress_cb, opts) -> result dict with an error count.
`v` is a numpy uint64 view of the buffer.  A non-zero error count means a
word read back different from what was written — i.e. a memory fault.
"""
from __future__ import annotations

import time

import numpy as np

np.seterr(over="ignore")  # LCG pattern relies on uint64 wraparound

MASK64 = np.uint64(0xFFFFFFFFFFFFFFFF)
CHUNK_WORDS = 4 * 1024 * 1024          # 32 MB per chunk (uint64)
WORD_BYTES = 8

RAM_TESTS = {
    "own_address":  ("Собственный адрес",        "Каждое слово хранит свой адрес"),
    "walking_ones": ("Бегущая единица",          "Одна единица проходит по всем 64 битам"),
    "walking_zeros":("Бегущий ноль",             "Один ноль проходит по всем 64 битам"),
    "movinv_ones":  ("Движ. инверсии (1/0)",     "Заполнение единицами, инверсия вперёд/назад"),
    "movinv_8bit":  ("Движ. инверсии (8-бит)",   "8-битный шаблон с движущейся инверсией"),
    "movinv_rand":  ("Движ. инверсии (случайн.)","Случайный 64-битный шаблон, движ. инверсия"),
    "checkerboard": ("Шахматный порядок",        "Чередование 0x55/0xAA по всем ячейкам"),
    "solid_bits":   ("Сплошные биты",            "Все нули, затем все единицы"),
    "block_move":   ("Перемещение блоков",       "Копирование половин памяти и сверка"),
    "modulo20":     ("Модуль-20",                "Шаблон в каждой 20-й ячейке, адресация"),
    "random_cmp":   ("Случайные данные",         "LCG-псевдослучайные данные, сверка по адресу"),
    "bit_fade":     ("Затухание битов",          "Запись, ожидание, повторная проверка (retention)"),
}
RAM_TEST_ORDER = [
    "own_address", "walking_ones", "walking_zeros", "movinv_ones", "movinv_8bit",
    "movinv_rand", "checkerboard", "solid_bits", "block_move", "modulo20",
    "random_cmp", "bit_fade",
]
# The "default" memtest tab: all 12 patterns, 1 pass.
RAM_DEFAULT_SELECTION = list(RAM_TEST_ORDER)


def fmt_int(n) -> str:
    return f"{int(n):,}".replace(",", " ")


def _chunks(n):
    a = 0
    while a < n:
        yield a, min(a + CHUNK_WORDS, n)
        a += CHUNK_WORDS


class _Prog:
    """Fraction tracker across a fixed number of full-buffer passes."""
    def __init__(self, n_words, total_passes, cb, name):
        self.n = n_words
        self.total = max(1, total_passes)
        self.done_passes = 0
        self.cb = cb
        self.name = name
        self._last = 0.0

    def update(self, chunk_end):
        frac = (self.done_passes * self.n + chunk_end) / (self.total * self.n)
        now = time.time()
        if now - self._last >= 0.1 or frac >= 1.0:
            self._last = now
            try:
                self.cb(min(frac, 1.0), self.name)
            except Exception:
                pass

    def next_pass(self):
        self.done_passes += 1


def _verify(v, a, b, expected, state):
    """Count mismatches in v[a:b] vs expected; remember first bad word."""
    seg = v[a:b]
    if np.isscalar(expected) or getattr(expected, "ndim", 1) == 0:
        bad = seg != expected
    else:
        bad = seg != expected
    cnt = int(np.count_nonzero(bad))
    if cnt and state["first_bad"] is None:
        idx = int(np.argmax(bad))
        state["first_bad"] = (a + idx) * WORD_BYTES
    state["errors"] += cnt
    state["bytes"] += (b - a) * WORD_BYTES
    return cnt


def _result(status, errors, metric, detail, first_bad=None, error=None, nbytes=0):
    return {
        "status": status, "errors": errors, "metric": metric,
        "detail": detail, "first_bad": first_bad, "error": error, "bytes": nbytes,
    }


def _finish(state, stopped, metric, detail):
    nbytes = state.get("bytes", 0)
    if state.get("exc"):
        return _result("FAILED", state["errors"], metric, "Исключение при тесте",
                       state["first_bad"], error=state["exc"], nbytes=nbytes)
    if state["errors"]:
        fb = state["first_bad"]
        loc = f" @ 0x{fb:X}" if fb is not None else ""
        return _result("FAILED", state["errors"], metric,
                       f"Обнаружено ошибок: {fmt_int(state['errors'])}{loc}",
                       state["first_bad"], nbytes=nbytes)
    if stopped:
        return _result("STOPPED", 0, metric, "Остановлено пользователем", nbytes=nbytes)
    return _result("PASSED", 0, metric, detail, nbytes=nbytes)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def t_own_address(v, stop, cb, opts):
    n = len(v)
    st = {"errors": 0, "bytes": 0, "first_bad": None}
    p = _Prog(n, 2, cb, "Запись адресов")
    stopped = False
    for a, b in _chunks(n):
        if stop.is_set():
            stopped = True; break
        v[a:b] = np.arange(a, b, dtype=np.uint64)
        p.update(b)
    p.next_pass()
    p.name = "Проверка адресов"
    if not stopped:
        for a, b in _chunks(n):
            if stop.is_set():
                stopped = True; break
            _verify(v, a, b, np.arange(a, b, dtype=np.uint64), st)
            p.update(b)
    return _finish(st, stopped, f"{fmt_int(n)} слов", "Адресная целостность подтверждена")


def _walk(v, stop, cb, opts, invert):
    n = len(v)
    st = {"errors": 0, "bytes": 0, "first_bad": None}
    bits = 64
    p = _Prog(n, bits * 2, cb, "Бегущий бит")
    stopped = False
    for bit in range(bits):
        base = np.uint64(1) << np.uint64(bit)
        pat = (base ^ MASK64) if invert else base
        for a, b in _chunks(n):
            if stop.is_set():
                stopped = True; break
            v[a:b] = pat
            p.update(b)
        p.next_pass()
        if stopped:
            break
        for a, b in _chunks(n):
            if stop.is_set():
                stopped = True; break
            _verify(v, a, b, pat, st)
            p.update(b)
        p.next_pass()
        p.name = f"Бит {bit + 1}/64"
        if stopped:
            break
    return st, stopped, f"64 бита × {fmt_int(n)} слов"


def t_walking_ones(v, stop, cb, opts):
    st, stopped, metric = _walk(v, stop, cb, opts, invert=False)
    return _finish(st, stopped, metric, "Все 64 позиции бегущей единицы пройдены")


def t_walking_zeros(v, stop, cb, opts):
    st, stopped, metric = _walk(v, stop, cb, opts, invert=True)
    return _finish(st, stopped, metric, "Все 64 позиции бегущего нуля пройдены")


def _moving_inversions(v, stop, cb, opts, pattern):
    """3 phases: fill(pat) -> asc verify(pat)+write(~pat) -> desc verify(~pat)+write(pat)."""
    n = len(v)
    st = {"errors": 0, "bytes": 0, "first_bad": None}
    pat = np.uint64(pattern) & MASK64
    inv = pat ^ MASK64
    p = _Prog(n, 3, cb, "Заполнение шаблоном")
    stopped = False
    for a, b in _chunks(n):
        if stop.is_set():
            stopped = True; break
        v[a:b] = pat
        p.update(b)
    p.next_pass(); p.name = "Инверсия (вперёд)"
    if not stopped:
        for a, b in _chunks(n):
            if stop.is_set():
                stopped = True; break
            _verify(v, a, b, pat, st)
            v[a:b] = inv
            p.update(b)
    p.next_pass(); p.name = "Инверсия (назад)"
    if not stopped:
        chunks = list(_chunks(n))
        for a, b in reversed(chunks):
            if stop.is_set():
                stopped = True; break
            _verify(v, a, b, inv, st)
            v[a:b] = pat
            p.update(b)
    return st, stopped


def t_movinv_ones(v, stop, cb, opts):
    st, stopped = _moving_inversions(v, stop, cb, opts, 0xFFFFFFFFFFFFFFFF)
    return _finish(st, stopped, f"{fmt_int(len(v))} слов",
                   "Движущиеся инверсии 1↔0 завершены")


def t_movinv_8bit(v, stop, cb, opts):
    st, stopped = _moving_inversions(v, stop, cb, opts, 0x8080808080808080)
    return _finish(st, stopped, f"{fmt_int(len(v))} слов",
                   "8-битный шаблон с инверсиями завершён")


def t_movinv_rand(v, stop, cb, opts):
    pat = int(np.random.default_rng().integers(0, 1 << 63)) | (1 << 62)
    st, stopped = _moving_inversions(v, stop, cb, opts, pat)
    return _finish(st, stopped, f"шаблон 0x{pat & 0xFFFFFFFFFFFFFFFF:016X}",
                   "Случайный шаблон с инверсиями завершён")


def _pattern_pair(v, stop, cb, opts, pats, label):
    n = len(v)
    st = {"errors": 0, "bytes": 0, "first_bad": None}
    p = _Prog(n, len(pats) * 2, cb, label)
    stopped = False
    for pat in pats:
        pv = np.uint64(pat) & MASK64
        for a, b in _chunks(n):
            if stop.is_set():
                stopped = True; break
            v[a:b] = pv
            p.update(b)
        p.next_pass()
        if stopped:
            break
        for a, b in _chunks(n):
            if stop.is_set():
                stopped = True; break
            _verify(v, a, b, pv, st)
            p.update(b)
        p.next_pass()
        if stopped:
            break
    return st, stopped


def t_checkerboard(v, stop, cb, opts):
    st, stopped = _pattern_pair(v, stop, cb, opts,
                                [0x5555555555555555, 0xAAAAAAAAAAAAAAAA], "Шахматный порядок")
    return _finish(st, stopped, f"{fmt_int(len(v))} слов", "0x55/0xAA подтверждены")


def t_solid_bits(v, stop, cb, opts):
    st, stopped = _pattern_pair(v, stop, cb, opts,
                                [0x0000000000000000, 0xFFFFFFFFFFFFFFFF], "Сплошные биты")
    return _finish(st, stopped, f"{fmt_int(len(v))} слов", "Все нули и все единицы подтверждены")


def t_block_move(v, stop, cb, opts):
    """Fill first half with an address pattern, copy to second half, verify."""
    n = len(v)
    st = {"errors": 0, "bytes": 0, "first_bad": None}
    half = n // 2
    if half == 0:
        return _result("PASSED", 0, "буфер мал", "Недостаточно памяти для теста")
    p = _Prog(half, 3, cb, "Заполнение блока")
    stopped = False
    for a, b in _chunks(half):
        if stop.is_set():
            stopped = True; break
        v[a:b] = np.arange(a, b, dtype=np.uint64) * np.uint64(2654435761)
        p.update(b)
    p.next_pass(); p.name = "Копирование блока"
    if not stopped:
        v[half:half + half] = v[0:half]
        p.done_passes += 1
    p.name = "Сверка блока"
    if not stopped:
        for a, b in _chunks(half):
            if stop.is_set():
                stopped = True; break
            expected = np.arange(a, b, dtype=np.uint64) * np.uint64(2654435761)
            _verify(v[half:half + half], a, b, expected, st)
            p.update(b)
    return _finish(st, stopped, f"{fmt_int(half)} слов × 2", "Перемещение блоков без ошибок")


def t_modulo20(v, stop, cb, opts):
    """Modulo-X (X=20): write pat to every 20th word, ~pat elsewhere, verify."""
    n = len(v)
    st = {"errors": 0, "bytes": 0, "first_bad": None}
    m = 20
    pat = np.uint64(0xFFFFFFFFFFFFFFFF)
    inv = np.uint64(0)
    p = _Prog(n, 2, cb, "Запись модуль-20")
    stopped = False
    for a, b in _chunks(n):
        if stop.is_set():
            stopped = True; break
        idx = np.arange(a, b, dtype=np.uint64)
        seg = np.where((idx % m) == 0, pat, inv)
        v[a:b] = seg
        p.update(b)
    p.next_pass(); p.name = "Проверка модуль-20"
    if not stopped:
        for a, b in _chunks(n):
            if stop.is_set():
                stopped = True; break
            idx = np.arange(a, b, dtype=np.uint64)
            expected = np.where((idx % m) == 0, pat, inv)
            _verify(v, a, b, expected, st)
            p.update(b)
    return _finish(st, stopped, f"{fmt_int(n)} слов, шаг {m}", "Адресация модуль-20 подтверждена")


def _lcg(a, b):
    idx = np.arange(a, b, dtype=np.uint64)
    return idx * np.uint64(6364136223846793005) + np.uint64(1442695040888963407)


def t_random_cmp(v, stop, cb, opts):
    n = len(v)
    st = {"errors": 0, "bytes": 0, "first_bad": None}
    p = _Prog(n, 2, cb, "Запись случайных данных")
    stopped = False
    for a, b in _chunks(n):
        if stop.is_set():
            stopped = True; break
        v[a:b] = _lcg(a, b)
        p.update(b)
    p.next_pass(); p.name = "Сверка случайных данных"
    if not stopped:
        for a, b in _chunks(n):
            if stop.is_set():
                stopped = True; break
            _verify(v, a, b, _lcg(a, b), st)
            p.update(b)
    return _finish(st, stopped, f"{fmt_int(n)} слов", "Псевдослучайные данные сверены по адресу")


def t_bit_fade(v, stop, cb, opts):
    """Retention: write pattern, wait, verify it survived. Abbreviated wait."""
    n = len(v)
    st = {"errors": 0, "bytes": 0, "first_bad": None}
    wait_s = float(opts.get("bit_fade_wait", 5))
    stopped = False
    for phase, pat in enumerate((np.uint64(0xFFFFFFFFFFFFFFFF), np.uint64(0))):
        for a, b in _chunks(n):
            if stop.is_set():
                stopped = True; break
            v[a:b] = pat
        if stopped:
            break
        # wait, staying responsive to stop
        t_end = time.time() + wait_s
        while time.time() < t_end:
            if stop.is_set():
                stopped = True; break
            cb(0.5 * phase + 0.25, f"Ожидание {int(t_end - time.time())} c…")
            time.sleep(0.2)
        if stopped:
            break
        for a, b in _chunks(n):
            if stop.is_set():
                stopped = True; break
            _verify(v, a, b, pat, st)
            cb(0.5 * phase + 0.5, "Проверка сохранности")
    return _finish(st, stopped, f"выдержка {int(wait_s)} c × 2",
                   "Данные сохранились после выдержки")


RAM_RUNNERS = {
    "own_address": t_own_address,
    "walking_ones": t_walking_ones,
    "walking_zeros": t_walking_zeros,
    "movinv_ones": t_movinv_ones,
    "movinv_8bit": t_movinv_8bit,
    "movinv_rand": t_movinv_rand,
    "checkerboard": t_checkerboard,
    "solid_bits": t_solid_bits,
    "block_move": t_block_move,
    "modulo20": t_modulo20,
    "random_cmp": t_random_cmp,
    "bit_fade": t_bit_fade,
}


def allocate(mb: int):
    """Allocate an aligned uint8 buffer of `mb` megabytes; return (buf, v64)."""
    nbytes = (int(mb) * 1024 * 1024) // WORD_BYTES * WORD_BYTES
    buf = np.empty(nbytes, dtype=np.uint8)
    v64 = buf.view(np.uint64)
    return buf, v64
