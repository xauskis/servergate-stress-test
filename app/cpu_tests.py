"""CPU stress tests — faithful re-implementation of the original SERVER GATE
console tool, adapted to report progress/results to the GUI engine.

All seven original tests are preserved:
    math_multicore  - saturate every logical core with FPU/transcendental work
    archive_zip     - CPU + I/O: generate random files and DEFLATE them
    fibonacci       - deep naive recursion
    hashing         - repeated SHA-512 over a 0.5 MB block
    compression     - repeated BZip2 over a 2 MB block
    prime_sieve     - Sieve of Eratosthenes up to 500,000
    mandelbrot      - FPU torture: 100x70 Mandelbrot frames

Worker targets are module-level so they pickle cleanly under the Windows
`spawn` start method (required for a frozen PyInstaller build).
"""
from __future__ import annotations

import bz2
import hashlib
import math
import multiprocessing
import os
import random
import tempfile
import time
import zipfile

# ---------------------------------------------------------------------------
# Test catalogue.  key -> (display name, short description)
# ---------------------------------------------------------------------------
CPU_TESTS = {
    "math":       ("Математика (все ядра)",  "Насыщение всех логических ядер (log/exp/sin/cos)"),
    "archive":    ("Архивация (ZIP, CPU+I/O)", "Генерация случайных файлов и сжатие DEFLATE"),
    "fibonacci":  ("Фибоначчи (рекурсия)",    "Глубокая наивная рекурсия fib(30)"),
    "hashing":    ("Хэширование (SHA-512)",   "Повторное хэширование блока 0.5 МБ"),
    "compress":   ("Компрессия (BZip2)",      "Повторное сжатие блока 2 МБ алгоритмом BZip2"),
    "prime":      ("Простые числа (Решето)",  "Решето Эратосфена до 500 000"),
    "mandelbrot": ("FPU (Мандельброт)",       "Множество Мандельброта 100x70, торможение FPU"),
}
CPU_TEST_ORDER = ["math", "archive", "fibonacci", "hashing", "compress", "prime", "mandelbrot"]


def fmt_int(n: int) -> str:
    return f"{n:,}".replace(",", " ")


# ---------------------------------------------------------------------------
# Multiprocessing worker for the all-cores math test.
# ---------------------------------------------------------------------------
def _math_worker(mp_stop):
    """Busy loop of transcendental + modular arithmetic until stopped."""
    x = 0.1
    while not mp_stop.is_set():
        for _ in range(5000):
            x = random.uniform(0.1, 10.0)
            math.log(x)
            math.sqrt(x)
            try:
                math.exp(min(x, 700.0))
            except OverflowError:
                pass
            math.sin(x)
            math.cos(x)
        k = 12345
        for i in range(1000):
            k = (k * i + 5000) % 999983


def _fib(n: int) -> int:
    if n < 2:
        return n
    return _fib(n - 1) + _fib(n - 2)


def _sieve(limit: int, stop) -> int:
    is_prime = bytearray([1]) * (limit + 1)
    is_prime[0] = is_prime[1] = 0
    p = 2
    root = int(math.sqrt(limit))
    while p <= root:
        if is_prime[p]:
            if stop.is_set():
                break
            is_prime[p * p::p] = bytearray(len(is_prime[p * p::p]))
        p += 1
    return sum(is_prime)


def _mandelbrot_frame(w: int, h: int, max_it: int) -> int:
    r_min, r_max, i_min, i_max = -2.0, 1.0, -1.0, 1.0
    points = 0
    for y in range(h):
        c_i = i_min + (i_max - i_min) * y / h
        for x in range(w):
            c_r = r_min + (r_max - r_min) * x / w
            z_r = z_i = 0.0
            for _ in range(max_it):
                zrs = z_r * z_r
                zis = z_i * z_i
                if zrs + zis > 4.0:
                    break
                z_i = 2 * z_r * z_i + c_i
                z_r = zrs - zis + c_r
            points += 1
    return points


# ---------------------------------------------------------------------------
# Result helper
# ---------------------------------------------------------------------------
def _result(status, metric="", detail="", error=None):
    return {"status": status, "metric": metric, "detail": detail, "error": error}


def _throttled(cb, last, frac, detail, force=False):
    now = time.time()
    if force or now - last[0] >= 0.12:
        last[0] = now
        try:
            cb(min(frac, 1.0), detail)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Individual test runners.  Signature: (duration, stop, progress_cb, num_workers)
# ---------------------------------------------------------------------------
def run_math(duration, stop, progress_cb, num_workers):
    mp_stop = multiprocessing.Event()
    procs = [multiprocessing.Process(target=_math_worker, args=(mp_stop,), daemon=True)
             for _ in range(max(1, num_workers))]
    for p in procs:
        p.start()
    start = time.time()
    last = [0.0]
    stopped = died = False
    try:
        while time.time() - start < duration:
            if stop.is_set():
                stopped = True
                break
            if not any(p.is_alive() for p in procs):
                died = True
                break
            frac = (time.time() - start) / duration
            _throttled(progress_cb, last, frac,
                       f"{len(procs)} потоков нагрузки — все ядра")
            time.sleep(0.08)
    finally:
        mp_stop.set()
        for p in procs:
            p.join(timeout=3)
            if p.is_alive():
                try:
                    p.terminate()
                except Exception:
                    pass
    metric = f"{len(procs)} лог. ядер × {int(duration)} c"
    if died:
        return _result("FAILED", metric, "Дочерние процессы завершились преждевременно",
                       error="child processes exited early")
    if stopped:
        return _result("STOPPED", metric, "Остановлено пользователем")
    return _result("PASSED", metric, f"Все {len(procs)} ядер под нагрузкой {int(duration)} c")


def run_archive(duration, stop, progress_cb, num_workers=None):
    temp_dir = tempfile.mkdtemp(prefix="servergate_zip_")
    start = time.time()
    last = [0.0]
    ops = 0
    total_mb = 0
    stopped = False
    err = None
    try:
        while time.time() - start < duration:
            if stop.is_set():
                stopped = True
                break
            size_mb = random.randint(2, 8)
            src = os.path.join(temp_dir, f"data_{random.randint(1000, 9999)}.dat")
            zpath = os.path.join(temp_dir, f"arc_{ops}.zip")
            with open(src, "wb") as f:
                for _ in range(size_mb):
                    f.write(os.urandom(1024 * 1024))
            with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(src, os.path.basename(src))
            ops += 1
            total_mb += size_mb
            for pth in (src, zpath):
                try:
                    os.remove(pth)
                except OSError:
                    pass
            frac = (time.time() - start) / duration
            _throttled(progress_cb, last, frac, f"~{total_mb} МБ сжато / {ops} операций")
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    finally:
        try:
            for item in os.listdir(temp_dir):
                try:
                    os.remove(os.path.join(temp_dir, item))
                except OSError:
                    pass
            os.rmdir(temp_dir)
        except OSError:
            pass
    metric = f"{fmt_int(ops)} операций · ~{fmt_int(total_mb)} МБ"
    if err:
        return _result("FAILED", metric, "Ошибка ввода-вывода", error=err)
    if stopped:
        return _result("STOPPED", metric, "Остановлено пользователем")
    return _result("PASSED", metric, f"Заархивировано ~{fmt_int(total_mb)} МБ данных")


def run_fibonacci(duration, stop, progress_cb, num_workers=None):
    fib_n = 30
    start = time.time()
    last = [0.0]
    iters = 0
    stopped = False
    err = None
    try:
        while time.time() - start < duration:
            if stop.is_set():
                stopped = True
                break
            _fib(fib_n)
            iters += 1
            frac = (time.time() - start) / duration
            _throttled(progress_cb, last, frac, f"fib({fib_n}) × {fmt_int(iters)}")
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    metric = f"{fmt_int(iters)} × fib({fib_n})"
    if err:
        return _result("FAILED", metric, "Ошибка вычисления", error=err)
    if stopped:
        return _result("STOPPED", metric, "Остановлено пользователем")
    return _result("PASSED", metric, f"Выполнено {fmt_int(iters)} расчётов fib({fib_n})")


def run_hashing(duration, stop, progress_cb, num_workers=None):
    block = os.urandom(524288)  # 0.5 MB
    start = time.time()
    last = [0.0]
    iters = 0
    stopped = False
    err = None
    try:
        while time.time() - start < duration:
            if stop.is_set():
                stopped = True
                break
            hashlib.sha512(block).hexdigest()
            iters += 1
            if iters % 64 == 0:
                frac = (time.time() - start) / duration
                _throttled(progress_cb, last, frac, f"SHA-512 × {fmt_int(iters)}")
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    mb = iters * 0.5
    metric = f"{fmt_int(iters)} хэшей · {fmt_int(int(mb))} МБ"
    if err:
        return _result("FAILED", metric, "Ошибка хэширования", error=err)
    if stopped:
        return _result("STOPPED", metric, "Остановлено пользователем")
    return _result("PASSED", metric, f"Вычислено {fmt_int(iters)} хэшей SHA-512")


def run_compress(duration, stop, progress_cb, num_workers=None):
    data = os.urandom(2 * 1024 * 1024)  # 2 MB
    start = time.time()
    last = [0.0]
    iters = 0
    total_out = 0
    stopped = False
    err = None
    try:
        while time.time() - start < duration:
            if stop.is_set():
                stopped = True
                break
            out = bz2.compress(data)
            total_out += len(out)
            iters += 1
            frac = (time.time() - start) / duration
            _throttled(progress_cb, last, frac, f"BZip2 × {fmt_int(iters)}")
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    metric = f"{fmt_int(iters)} блоков · {fmt_int(iters * 2)} МБ вход"
    if err:
        return _result("FAILED", metric, "Ошибка компрессии", error=err)
    if stopped:
        return _result("STOPPED", metric, "Остановлено пользователем")
    return _result("PASSED", metric, f"Сжато {fmt_int(iters)} блоков по 2 МБ")


def run_prime(duration, stop, progress_cb, num_workers=None):
    limit = 500000
    start = time.time()
    last = [0.0]
    iters = 0
    primes = 0
    stopped = False
    err = None
    try:
        while time.time() - start < duration:
            if stop.is_set():
                stopped = True
                break
            primes = _sieve(limit, stop)
            iters += 1
            frac = (time.time() - start) / duration
            _throttled(progress_cb, last, frac, f"Решето до {fmt_int(limit)} × {fmt_int(iters)}")
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    metric = f"{fmt_int(iters)} проходов · {fmt_int(primes)} простых"
    if err:
        return _result("FAILED", metric, "Ошибка вычисления", error=err)
    if stopped:
        return _result("STOPPED", metric, "Остановлено пользователем")
    return _result("PASSED", metric, f"{fmt_int(iters)} проходов решета до {fmt_int(limit)}")


def run_mandelbrot(duration, stop, progress_cb, num_workers=None):
    w, h, max_it = 100, 70, 50
    start = time.time()
    last = [0.0]
    frames = 0
    points = 0
    stopped = False
    err = None
    try:
        while time.time() - start < duration:
            if stop.is_set():
                stopped = True
                break
            points += _mandelbrot_frame(w, h, max_it)
            frames += 1
            frac = (time.time() - start) / duration
            _throttled(progress_cb, last, frac, f"{fmt_int(frames)} кадров · {w}x{h}")
    except Exception as e:  # noqa: BLE001
        err = f"{type(e).__name__}: {e}"
    metric = f"{fmt_int(frames)} кадров · {fmt_int(points)} точек"
    if err:
        return _result("FAILED", metric, "Ошибка вычисления", error=err)
    if stopped:
        return _result("STOPPED", metric, "Остановлено пользователем")
    return _result("PASSED", metric, f"Отрисовано {fmt_int(frames)} кадров Мандельброта")


CPU_RUNNERS = {
    "math": run_math,
    "archive": run_archive,
    "fibonacci": run_fibonacci,
    "hashing": run_hashing,
    "compress": run_compress,
    "prime": run_prime,
    "mandelbrot": run_mandelbrot,
}
