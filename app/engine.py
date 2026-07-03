"""Test orchestration.

A `TestEngine` runs a job (CPU or RAM) on a background thread and streams
events to a thread-safe queue that the GUI drains on a timer.  Supports
multiple rounds (loops), CPU sequential/concurrent modes, and per-test
result collection for the final SERVER GATE report.
"""
from __future__ import annotations

import multiprocessing
import queue
import threading
import time
import traceback

import cpu_tests
import ram_tests


# ---------------------------------------------------------------------------
# Child-process entry point for CPU "concurrent / extreme" mode.
# Module-level so it pickles under spawn.
# ---------------------------------------------------------------------------
def _proc_run_cpu_test(key, duration, num_workers, mp_stop, rq):
    def cb(frac, detail):
        try:
            rq.put(("progress", key, frac, detail))
        except Exception:
            pass
    try:
        res = cpu_tests.CPU_RUNNERS[key](duration, mp_stop, cb, num_workers)
    except Exception as e:  # noqa: BLE001
        res = {"status": "FAILED", "metric": "", "detail": "Ошибка процесса",
               "error": f"{type(e).__name__}: {e}"}
    try:
        rq.put(("result", key, res))
    except Exception:
        pass


def _fmt_bytes(n):
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.0f} ПБ"


class TestEngine:
    def __init__(self):
        self.queue: "queue.Queue[dict]" = queue.Queue()
        self._stop = threading.Event()
        self._thread = None
        self.running = False

    # ----- lifecycle -------------------------------------------------------
    def start(self, job: dict):
        if self.running:
            return
        self._stop.clear()
        self.running = True
        self._thread = threading.Thread(target=self._run, args=(job,), daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def is_running(self):
        return self.running

    # ----- helpers ---------------------------------------------------------
    def _emit(self, **kw):
        self.queue.put(kw)

    def _log(self, text, level="info"):
        self._emit(ev="log", level=level, text=text)

    # ----- main dispatch ---------------------------------------------------
    def _run(self, job):
        try:
            if job["kind"] == "cpu":
                self._run_cpu(job)
            else:
                self._run_ram(job)
        except Exception:  # noqa: BLE001
            self._log("Критическая ошибка движка:\n" + traceback.format_exc(), "error")
            self._emit(ev="done", results=[], all_passed=False, stopped=True,
                       elapsed=0, summary={})
        finally:
            self.running = False

    # ----- CPU -------------------------------------------------------------
    def _run_cpu(self, job):
        tests = job["tests"]
        rounds = max(1, int(job["rounds"]))
        duration = int(job["duration"])
        num_workers = int(job["num_workers"])
        mode = job.get("mode", "sequential")

        total_units = rounds * (1 if mode == "concurrent" else len(tests))
        self._emit(ev="start", kind="cpu", rounds=rounds, tests=tests,
                   mode=mode, duration=duration, total_units=total_units)
        self._log(f"Запуск CPU-теста · режим: "
                  f"{'ОДНОВРЕМЕННО (экстрим)' if mode == 'concurrent' else 'последовательно'} · "
                  f"кругов: {rounds} · {duration} c на тест", "head")

        results = []
        completed = 0
        run_start = time.time()

        for rnd in range(1, rounds + 1):
            if self._stop.is_set():
                break
            self._emit(ev="round", round=rnd, total=rounds)
            self._log(f"— Круг {rnd} из {rounds} —", "round")

            if mode == "concurrent":
                res_list = self._cpu_concurrent(tests, duration, num_workers, rnd, run_start,
                                                completed, total_units)
                results.extend(res_list)
                completed += 1
            else:
                for key in tests:
                    if self._stop.is_set():
                        break
                    r = self._cpu_single(key, duration, num_workers, rnd, run_start,
                                         completed, total_units)
                    results.append(r)
                    completed += 1

        self._finish_report("cpu", results, run_start, job)

    def _cpu_single(self, key, duration, num_workers, rnd, run_start, completed, total_units):
        name = cpu_tests.CPU_TESTS[key][0]
        self._emit(ev="test_start", key=key, name=name, round=rnd)
        self._log(f"▶ {name}", "test")
        t0 = time.time()

        def cb(frac, detail):
            overall = (completed + frac) / total_units
            self._emit(ev="progress", key=key, test_frac=frac, overall_frac=overall,
                       detail=detail, elapsed=time.time() - run_start)

        res = cpu_tests.CPU_RUNNERS[key](duration, self._stop, cb, num_workers)
        dur = time.time() - t0
        rec = {"kind": "cpu", "key": key, "name": name, "round": rnd,
               "duration": dur, **res}
        self._emit(ev="test_result", **rec)
        self._log(f"   {name}: {res['status']} · {res.get('metric','')}",
                  _lvl(res["status"]))
        return rec

    def _cpu_concurrent(self, tests, duration, num_workers, rnd, run_start, completed, total_units):
        # In extreme mode every test runs in its own process at once; the math
        # test uses a single worker since the other tests already occupy cores.
        mp_stop = multiprocessing.Event()
        rq = multiprocessing.Queue()
        procs = {}
        for key in tests:
            nw = 1 if key == "math" else 1
            p = multiprocessing.Process(target=_proc_run_cpu_test,
                                        args=(key, duration, nw, mp_stop, rq), daemon=False)
            p.start()
            procs[key] = p
            self._emit(ev="test_start", key=key, name=cpu_tests.CPU_TESTS[key][0], round=rnd)
            self._log(f"▶ параллельно: {cpu_tests.CPU_TESTS[key][0]}", "test")

        collected = {}
        details = {}
        t0 = time.time()
        stopped = False
        hard_timeout = duration + 60  # grace for tests to finish on their own
        while True:
            if self._stop.is_set():
                stopped = True
                mp_stop.set()
            # drain queue every tick so results are captured before join
            try:
                while True:
                    msg = rq.get_nowait()
                    if msg[0] == "progress":
                        details[msg[1]] = msg[3]
                    elif msg[0] == "result":
                        collected[msg[1]] = msg[2]
            except queue.Empty:
                pass
            alive = any(p.is_alive() for p in procs.values())
            elapsed = time.time() - t0
            frac = min(elapsed / duration, 1.0) if duration else 1.0
            active = sum(1 for p in procs.values() if p.is_alive())
            overall = (completed + frac) / total_units
            self._emit(ev="progress", key="__all__", test_frac=frac, overall_frac=overall,
                       detail=f"{active} активных тестов · {len(collected)} завершено",
                       elapsed=time.time() - run_start)
            # Each test runs for `duration` and returns on its own — do NOT set
            # mp_stop at the duration mark, or the runners would report STOPPED.
            if not alive:
                break
            if elapsed > hard_timeout:
                mp_stop.set()
                stopped = True
            time.sleep(0.1)

        mp_stop.set()
        for key, p in procs.items():
            p.join(timeout=5)
            if p.is_alive():
                try:
                    p.terminate()
                except Exception:
                    pass
        # final drain
        try:
            while True:
                msg = rq.get_nowait()
                if msg[0] == "result":
                    collected[msg[1]] = msg[2]
        except queue.Empty:
            pass

        recs = []
        for key in tests:
            name = cpu_tests.CPU_TESTS[key][0]
            res = collected.get(key, {"status": "STOPPED" if stopped else "FAILED",
                                      "metric": "", "detail": "Нет результата от процесса",
                                      "error": None})
            rec = {"kind": "cpu", "key": key, "name": name, "round": rnd,
                   "duration": time.time() - t0, **res}
            recs.append(rec)
            self._emit(ev="test_result", **rec)
            self._log(f"   {name}: {res['status']} · {res.get('metric','')}",
                      _lvl(res["status"]))
        return recs

    # ----- RAM -------------------------------------------------------------
    def _run_ram(self, job):
        tests = job["tests"]
        rounds = max(1, int(job["rounds"]))
        mb = int(job["mb"])
        opts = {"bit_fade_wait": job.get("bit_fade_wait", 5)}

        total_units = rounds * len(tests)
        self._emit(ev="start", kind="ram", rounds=rounds, tests=tests,
                   mb=mb, total_units=total_units)
        self._log(f"Запуск теста ОЗУ · объём: {mb} МБ · кругов (проходов): {rounds} · "
                  f"тестов: {len(tests)}", "head")

        self._log(f"Выделение буфера {mb} МБ…", "info")
        try:
            buf, v64 = ram_tests.allocate(mb)
        except MemoryError:
            self._log(f"Недостаточно памяти для выделения {mb} МБ. "
                      f"Уменьшите объём.", "error")
            self._emit(ev="done", results=[], all_passed=False, stopped=True,
                       elapsed=0, summary={})
            return
        self._log(f"Буфер выделен: {_fmt_bytes(buf.nbytes)} ({len(v64):,} слов)".replace(",", " "),
                  "info")

        results = []
        completed = 0
        run_start = time.time()

        for rnd in range(1, rounds + 1):
            if self._stop.is_set():
                break
            self._emit(ev="round", round=rnd, total=rounds)
            self._log(f"— Проход {rnd} из {rounds} —", "round")
            for key in tests:
                if self._stop.is_set():
                    break
                name = ram_tests.RAM_TESTS[key][0]
                self._emit(ev="test_start", key=key, name=name, round=rnd)
                self._log(f"▶ {name}", "test")
                t0 = time.time()

                def cb(frac, detail, _c=completed, _k=key):
                    overall = (_c + frac) / total_units
                    self._emit(ev="progress", key=_k, test_frac=frac, overall_frac=overall,
                               detail=detail, elapsed=time.time() - run_start)

                try:
                    res = ram_tests.RAM_RUNNERS[key](v64, self._stop, cb, opts)
                except Exception as e:  # noqa: BLE001
                    res = {"status": "FAILED", "errors": 0, "metric": "",
                           "detail": "Исключение", "error": f"{type(e).__name__}: {e}",
                           "bytes": 0, "first_bad": None}
                dur = time.time() - t0
                mbps = (res.get("bytes", 0) / (1024 * 1024) / dur) if dur > 0 else 0
                rec = {"kind": "ram", "key": key, "name": name, "round": rnd,
                       "duration": dur, "mbps": mbps, **res}
                results.append(rec)
                completed += 1
                self._emit(ev="test_result", **rec)
                extra = f" · ошибок: {res.get('errors', 0)}" if res.get("errors") else ""
                self._log(f"   {name}: {res['status']} · {res.get('metric','')}"
                          f" · {mbps:,.0f} МБ/с{extra}".replace(",", " "),
                          _lvl(res["status"]))

        del v64
        del buf
        self._finish_report("ram", results, run_start, job)

    # ----- report ----------------------------------------------------------
    def _finish_report(self, kind, results, run_start, job):
        elapsed = time.time() - run_start
        stopped = self._stop.is_set()
        statuses = [r["status"] for r in results]
        passed = sum(1 for s in statuses if s == "PASSED")
        failed = sum(1 for s in statuses if s in ("FAILED", "ERROR"))
        stopped_n = sum(1 for s in statuses if s == "STOPPED")
        total_errors = sum(int(r.get("errors", 0)) for r in results)
        all_passed = (failed == 0 and total_errors == 0 and len(results) > 0
                      and stopped_n == 0 and not stopped)
        rounds = int(job.get("rounds", 1))
        if kind == "cpu":
            mode = ("параллельный (экстрим)" if job.get("mode") == "concurrent"
                    else "последовательный")
            params = f"{rounds} круг. × {int(job.get('duration', 0))} c · {mode}"
        else:
            params = f"{rounds} проход. · буфер {int(job.get('mb', 0))} МБ"
        summary = {
            "kind": kind,
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "stopped": stopped_n,
            "errors": total_errors,
            "elapsed": elapsed,
            "rounds": rounds,
            "params": params,
            "verdict": "PASSED" if all_passed else ("STOPPED" if (stopped or stopped_n)
                                                    and failed == 0 and total_errors == 0
                                                    else "FAILED"),
        }
        self._log("Тестирование завершено." if not stopped else "Тестирование прервано.",
                  "head")
        self._emit(ev="done", results=results, all_passed=all_passed, stopped=stopped,
                   elapsed=elapsed, summary=summary)


def _lvl(status):
    return {"PASSED": "pass", "FAILED": "fail", "ERROR": "fail",
            "STOPPED": "warn"}.get(status, "info")
