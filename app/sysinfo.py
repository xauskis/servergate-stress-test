"""Hardware / OS discovery for SERVER GATE.

Detects every physical CPU package (servers ship 1/2/4 sockets) with the
exact model name, core/thread counts and frequency, and aggregates them for
display: "Intel Xeon Gold 6254 ×2".
"""
from __future__ import annotations

import json
import multiprocessing
import os
import platform
import re
import subprocess

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _run(cmd, timeout=12):
    kw = dict(capture_output=True, timeout=timeout)
    if os.name == "nt":
        kw["creationflags"] = CREATE_NO_WINDOW
    try:
        return subprocess.run(cmd, **kw)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CPU name helpers
# ---------------------------------------------------------------------------
def short_cpu_name(name: str) -> str:
    """'Intel(R) Xeon(R) Gold 6254 CPU @ 3.10GHz' -> 'Intel Xeon Gold 6254'."""
    s = re.sub(r"\((?:R|TM|r|tm)\)", "", name or "")
    s = re.sub(r"\b(?:CPU|Processor)\b", "", s)
    s = re.sub(r"@\s*[\d.,]+\s*[GM]Hz", "", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" -@,")
    return s or (name or "").strip()


def _freq_from_name(name: str) -> float:
    m = re.search(r"@\s*([\d.,]+)\s*GHz", name or "")
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except ValueError:
            pass
    return 0.0


# ---------------------------------------------------------------------------
# Per-socket package detection
# ---------------------------------------------------------------------------
def _packages_windows():
    """One PS/CIM call: CPU packages + platform vendor/model."""
    ps = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
          "$o=[pscustomobject]@{"
          "cpu=@(Get-CimInstance Win32_Processor|"
          "Select-Object Name,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed);"
          "cs=(Get-CimInstance Win32_ComputerSystem|Select-Object Manufacturer,Model)"
          "};$o|ConvertTo-Json -Compress -Depth 3")
    r = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps])
    if r is None or r.returncode != 0:
        return [], ""
    try:
        data = json.loads(r.stdout.decode("utf-8", "replace") or "null") or {}
    except Exception:
        return [], ""
    cpus = data.get("cpu")
    if isinstance(cpus, dict):
        cpus = [cpus]
    pkgs = []
    for d in cpus or []:
        name = (d.get("Name") or "").strip()
        if not name:
            continue
        pkgs.append({
            "name": re.sub(r"\s{2,}", " ", name),
            "cores": int(d.get("NumberOfCores") or 0),
            "threads": int(d.get("NumberOfLogicalProcessors") or 0),
            "freq_mhz": float(d.get("MaxClockSpeed") or 0),
        })
    cs = data.get("cs") or {}
    plat = " ".join(x for x in [(cs.get("Manufacturer") or "").strip(),
                                (cs.get("Model") or "").strip()] if x)
    return pkgs, plat


def _packages_linux():
    """Group /proc/cpuinfo by `physical id` — one entry per socket."""
    try:
        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            txt = f.read()
    except Exception:
        return [], ""
    pkgs, order = {}, []
    for block in txt.split("\n\n"):
        if not block.strip():
            continue
        fields = {}
        for line in block.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fields[k.strip()] = v.strip()
        if "processor" not in fields:
            continue
        pid = fields.get("physical id", "0")
        if pid not in pkgs:
            pkgs[pid] = {
                "name": re.sub(r"\s{2,}", " ",
                               fields.get("model name") or fields.get("Hardware")
                               or platform.processor() or "CPU"),
                "cores": int(fields.get("cpu cores") or 0),
                "threads": int(fields.get("siblings") or 0),
                "freq_mhz": 0.0,
                "_seen": 0,
            }
            order.append(pid)
        p = pkgs[pid]
        p["_seen"] += 1
        try:
            p["freq_mhz"] = max(p["freq_mhz"], float(fields.get("cpu MHz") or 0))
        except ValueError:
            pass
    # prefer the rated max frequency when the kernel exposes it
    try:
        with open("/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_max_freq") as f:
            mx = int(f.read().strip()) / 1000.0
        for p in pkgs.values():
            p["freq_mhz"] = mx
    except Exception:
        pass
    out = []
    for pid in order:
        p = pkgs[pid]
        seen = p.pop("_seen")
        if not p["threads"]:
            p["threads"] = seen
        if not p["cores"]:
            p["cores"] = p["threads"]
        out.append(p)

    vendor = _dmi("sys_vendor")
    product = _dmi("product_name")
    plat = " ".join(x for x in (vendor, product) if x)
    return out, plat


def _dmi(key: str) -> str:
    try:
        with open(f"/sys/class/dmi/id/{key}", encoding="utf-8",
                  errors="replace") as f:
            v = f.read().strip()
        if v.lower() in ("", "to be filled by o.e.m.", "default string", "none"):
            return ""
        return v
    except Exception:
        return ""


def _registry_cpu_name() -> str:
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0")
        name, _ = winreg.QueryValueEx(key, "ProcessorNameString")
        winreg.CloseKey(key)
        return re.sub(r"\s{2,}", " ", (name or "").strip())
    except Exception:
        return ""


def aggregate_packages(pkgs, fallback_name=""):
    """-> (base_name, display_name_with_xN, short_display, sockets)."""
    if not pkgs:
        base = fallback_name or "Unknown CPU"
        return base, base, short_cpu_name(base), 1
    names = []
    for p in pkgs:
        if p["name"] not in names:
            names.append(p["name"])
    base = names[0] if len(names) == 1 else " / ".join(names)
    n = len(pkgs)
    suffix = f" ×{n}" if n > 1 else ""
    return base, base + suffix, short_cpu_name(base) + suffix, n


def _bytes_to_gb(n: int) -> float:
    return round(n / (1024 ** 3), 1)


def gather() -> dict:
    """Return a dict describing the machine under test."""
    logical = multiprocessing.cpu_count()
    physical = logical
    total_ram = avail_ram = 0
    if psutil is not None:
        try:
            physical = psutil.cpu_count(logical=False) or logical
        except Exception:
            physical = logical
        try:
            vm = psutil.virtual_memory()
            total_ram, avail_ram = vm.total, vm.available
        except Exception:
            pass

    if os.name == "nt":
        pkgs, plat = _packages_windows()
        fallback = _registry_cpu_name() or platform.processor() or "Unknown CPU"
    else:
        pkgs, plat = _packages_linux()
        fallback = platform.processor() or platform.machine() or "Unknown CPU"

    base, disp, short, sockets = aggregate_packages(pkgs, fallback)

    # totals: trust per-package sums when they exceed what psutil sees
    sum_cores = sum(p["cores"] for p in pkgs) if pkgs else 0
    sum_threads = sum(p["threads"] for p in pkgs) if pkgs else 0
    physical = max(physical, sum_cores)
    logical = max(logical, sum_threads)

    freq = 0.0
    if pkgs:
        freq = round(max(p["freq_mhz"] for p in pkgs) / 1000.0, 2)
    if not freq:
        freq = _freq_from_name(base)
    if not freq and psutil is not None:
        try:
            f = psutil.cpu_freq()
            if f:
                freq = round((f.max or f.current) / 1000.0, 2)
        except Exception:
            pass

    return {
        "cpu_name": disp,            # full, with ×N
        "cpu_base": base,            # full, single package
        "cpu_short": short,          # compact, with ×N
        "packages": pkgs,
        "sockets": sockets,
        "platform": plat,
        "logical": logical,
        "physical": physical,
        "freq_ghz": freq,
        "ram_total": total_ram,
        "ram_avail": avail_ram,
        "ram_total_gb": _bytes_to_gb(total_ram) if total_ram else 0,
        "ram_avail_gb": _bytes_to_gb(avail_ram) if avail_ram else 0,
        "os": f"{platform.system()} {platform.release()}",
        "os_build": platform.version(),
        "arch": platform.machine(),
        "python": platform.python_version(),
    }


def live_cpu_percent_percore():
    if psutil is None:
        return []
    try:
        return psutil.cpu_percent(percpu=True)
    except Exception:
        return []


def live_ram_percent() -> float:
    if psutil is None:
        return 0.0
    try:
        return psutil.virtual_memory().percent
    except Exception:
        return 0.0


def live_ram_available() -> int:
    if psutil is None:
        return 0
    try:
        return psutil.virtual_memory().available
    except Exception:
        return 0
