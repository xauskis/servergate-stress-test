"""SERVER GATE — Stress Test — application entry point.

Reproduces every capability of the original SERVER GATE console tool (7 CPU
tests) inside a graphical interface, and adds a full memtest86-style RAM test
suite on a second tab.
"""
import multiprocessing
import sys


def _selftest(outfile):
    """Headless diagnostic: proves multiprocessing works in a frozen build.

    Runs the multi-core math test (spawns worker processes) and a concurrent
    engine job (spawns one process per test), then writes the outcome so a
    --windowed build with no console can still be verified.
    """
    import threading
    import queue
    import time
    import cpu_tests
    from engine import TestEngine

    lines = []
    # 1) direct multi-core math (spawns processes)
    res = cpu_tests.run_math(2, threading.Event(), lambda f, d: None, 2)
    lines.append(f"math_multicore: {res['status']} | {res['metric']}")

    # 2) concurrent engine job (one process per test)
    eng = TestEngine()
    eng.start({"kind": "cpu", "tests": ["prime", "hashing"], "rounds": 1,
               "duration": 2, "num_workers": 1, "mode": "concurrent"})
    done = None
    t_end = time.time() + 30
    while time.time() < t_end:
        try:
            ev = eng.queue.get(timeout=0.2)
            if ev.get("ev") == "done":
                done = ev
                break
        except queue.Empty:
            pass
    if done:
        s = done["summary"]
        lines.append(f"concurrent_job: verdict={s.get('verdict')} "
                     f"passed={s.get('passed')} failed={s.get('failed')}")
    else:
        lines.append("concurrent_job: TIMEOUT")
    lines.append("SELFTEST_OK")
    with open(outfile, "w", encoding="utf-8") as fp:
        fp.write("\n".join(lines))


def main():
    # MUST be first: under a frozen (PyInstaller) build with the Windows
    # `spawn` start method, worker processes re-launch the executable and this
    # call reroutes them to their target instead of re-opening the GUI.
    multiprocessing.freeze_support()

    if "--selftest" in sys.argv:
        idx = sys.argv.index("--selftest")
        outfile = sys.argv[idx + 1] if idx + 1 < len(sys.argv) else "selftest.txt"
        _selftest(outfile)
        return

    from gui import launch
    launch()


if __name__ == "__main__":
    main()
