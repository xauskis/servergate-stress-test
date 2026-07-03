"""AIDA-style system configuration collector (best effort, cross-platform).

collect() returns an ordered list of sections:
    [(section_title, [(key, value), ...]), ...]
Every probe is wrapped defensively — a missing tool or permission simply
drops the row, never crashes the GUI.
"""
from __future__ import annotations

import datetime
import json
import os
import platform
import re
import socket
import subprocess

try:
    import psutil
except Exception:  # pragma: no cover
    psutil = None

import sysinfo

CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# SMBIOS memory type codes -> human name
_MEM_TYPES = {20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4", 30: "LPDDR4",
              34: "DDR5", 35: "LPDDR5"}


def _run(cmd, timeout=15):
    kw = dict(capture_output=True, timeout=timeout)
    if os.name == "nt":
        kw["creationflags"] = CREATE_NO_WINDOW
    try:
        return subprocess.run(cmd, **kw)
    except Exception:
        return None


def _fmt_bytes(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "—"
    if n <= 0:
        return "—"
    for u in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if n < 1024:
            return (f"{n:.0f} {u}" if n >= 10 or u == "Б" else f"{n:.1f} {u}")
        n /= 1024
    return f"{n:.1f} ПБ"


def _clean(v: str) -> str:
    v = (v or "").strip()
    if v.lower() in ("", "to be filled by o.e.m.", "default string", "none",
                     "system product name", "system manufacturer", "0123456789"):
        return ""
    return re.sub(r"\s{2,}", " ", v)


# ---------------------------------------------------------------------------
# Windows: one combined CIM query
# ---------------------------------------------------------------------------
def _win_query() -> dict:
    ps = ("[Console]::OutputEncoding=[System.Text.Encoding]::UTF8;"
          "$o=[pscustomobject]@{"
          "cs=(Get-CimInstance Win32_ComputerSystem|"
          "Select-Object Manufacturer,Model,SystemFamily);"
          "bb=(Get-CimInstance Win32_BaseBoard|"
          "Select-Object Manufacturer,Product,Version);"
          "bios=(Get-CimInstance Win32_BIOS|"
          "Select-Object Manufacturer,SMBIOSBIOSVersion,ReleaseDate);"
          "os=(Get-CimInstance Win32_OperatingSystem|"
          "Select-Object Caption,Version,BuildNumber,OSArchitecture);"
          "mem=@(Get-CimInstance Win32_PhysicalMemory|"
          "Select-Object DeviceLocator,Capacity,Speed,ConfiguredClockSpeed,"
          "Manufacturer,PartNumber,SMBIOSMemoryType);"
          "gpu=@(Get-CimInstance Win32_VideoController|Select-Object Name);"
          "disk=@(Get-CimInstance Win32_DiskDrive|"
          "Select-Object Model,Size,InterfaceType)"
          "};$o|ConvertTo-Json -Compress -Depth 4")
    r = _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
             timeout=20)
    if r is None or r.returncode != 0:
        return {}
    try:
        return json.loads(r.stdout.decode("utf-8", "replace") or "{}") or {}
    except Exception:
        return {}


def _aslist(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _cim_date(v: str) -> str:
    m = re.search(r"/Date\((\d+)\)/", str(v or ""))
    if m:
        try:
            return datetime.datetime.fromtimestamp(
                int(m.group(1)) / 1000).strftime("%d.%m.%Y")
        except Exception:
            pass
    m = re.match(r"(\d{4})(\d{2})(\d{2})", str(v or ""))
    if m:
        return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    return _clean(str(v or ""))


# ---------------------------------------------------------------------------
# Linux probes (DMI sysfs, dmidecode, lsblk, lspci)
# ---------------------------------------------------------------------------
def _dmi(key: str) -> str:
    try:
        with open(f"/sys/class/dmi/id/{key}", encoding="utf-8",
                  errors="replace") as f:
            return _clean(f.read())
    except Exception:
        return ""


def _linux_mem_modules():
    """Parse `dmidecode -t 17` (root or passwordless sudo, e.g. Debian live)."""
    out = None
    for cmd in (["dmidecode", "-t", "17"], ["sudo", "-n", "dmidecode", "-t", "17"]):
        r = _run(cmd, timeout=10)
        if r is not None and r.returncode == 0 and r.stdout:
            out = r.stdout.decode("utf-8", "replace")
            break
    if not out:
        return []
    mods = []
    for block in out.split("Memory Device"):
        fields = {}
        for line in block.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                fields[k.strip()] = v.strip()
        size = fields.get("Size", "")
        if not size or "No Module" in size or size == "Unknown":
            continue
        parts = [size.replace("MB", "МБ").replace("GB", "ГБ")]
        t = fields.get("Type", "")
        if t and t != "Unknown":
            parts.append(t)
        spd = fields.get("Configured Memory Speed") or fields.get("Speed") or ""
        if spd and "Unknown" not in spd:
            parts.append(spd.replace("MT/s", "МТ/с"))
        man = _clean(fields.get("Manufacturer", ""))
        if man and man.lower() not in ("unknown", "not specified"):
            parts.append(man)
        pn = _clean(fields.get("Part Number", ""))
        if pn and pn.lower() not in ("unknown", "not specified"):
            parts.append(pn)
        loc = fields.get("Locator", "DIMM")
        mods.append((loc, " · ".join(parts)))
    return mods


def _linux_disks():
    r = _run(["lsblk", "-d", "-b", "-P", "-o", "NAME,MODEL,SIZE,TRAN,ROTA"])
    disks = []
    if r is not None and r.returncode == 0:
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            f = dict(re.findall(r'(\w+)="([^"]*)"', line))
            name = f.get("NAME", "")
            if re.match(r"^(loop|sr|ram|zram|fd)", name):
                continue
            model = _clean(f.get("MODEL", "")) or name
            size = _fmt_bytes(f.get("SIZE"))
            tran = (f.get("TRAN") or "").upper()
            kind = "SSD/NVMe" if f.get("ROTA") == "0" else "HDD"
            extra = " · ".join(x for x in (tran, kind) if x)
            disks.append((name, f"{model} · {size}" + (f" · {extra}" if extra else "")))
    return disks


def _linux_gpus():
    r = _run(["lspci", "-mm"])
    gpus = []
    if r is not None and r.returncode == 0:
        for line in r.stdout.decode("utf-8", "replace").splitlines():
            if re.search(r'"(VGA compatible controller|3D controller|Display controller)"',
                         line):
                m = re.findall(r'"([^"]*)"', line)
                if len(m) >= 3:
                    gpus.append(f"{m[1]} {m[2]}")
    return gpus


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------
def collect() -> list:
    sysd = sysinfo.gather()
    sections = []
    win = _win_query() if os.name == "nt" else {}

    # --- Система ---
    rows = [("Имя компьютера", socket.gethostname())]
    if os.name == "nt":
        osd = win.get("os") or {}
        cap = _clean(osd.get("Caption", "")) or sysd["os"]
        rows.append(("Операционная система", cap))
        rows.append(("Версия / сборка",
                     f'{osd.get("Version", platform.version())} '
                     f'(build {osd.get("BuildNumber", "")})'.strip()))
    else:
        pretty = ""
        try:
            with open("/etc/os-release", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        pretty = line.split("=", 1)[1].strip().strip('"')
        except Exception:
            pass
        rows.append(("Операционная система", pretty or sysd["os"]))
        rows.append(("Ядро", platform.release()))
    rows.append(("Архитектура", sysd["arch"]))
    rows.append(("Дата и время", datetime.datetime.now().strftime("%d.%m.%Y %H:%M")))
    sections.append(("Система", rows))

    # --- Платформа ---
    rows = []
    if os.name == "nt":
        cs = win.get("cs") or {}
        rows += [("Производитель", _clean(cs.get("Manufacturer", ""))),
                 ("Модель", _clean(cs.get("Model", ""))),
                 ("Семейство", _clean(cs.get("SystemFamily", "")))]
    else:
        rows += [("Производитель", _dmi("sys_vendor")),
                 ("Модель", _dmi("product_name")),
                 ("Версия", _dmi("product_version"))]
    rows = [(k, v) for k, v in rows if v]
    if rows:
        sections.append(("Платформа", rows))

    # --- Системная плата ---
    rows = []
    if os.name == "nt":
        bb = win.get("bb") or {}
        rows += [("Производитель", _clean(bb.get("Manufacturer", ""))),
                 ("Модель", _clean(bb.get("Product", ""))),
                 ("Версия", _clean(bb.get("Version", "")))]
    else:
        rows += [("Производитель", _dmi("board_vendor")),
                 ("Модель", _dmi("board_name")),
                 ("Версия", _dmi("board_version"))]
    rows = [(k, v) for k, v in rows if v]
    if rows:
        sections.append(("Системная плата", rows))

    # --- BIOS / UEFI ---
    rows = []
    if os.name == "nt":
        b = win.get("bios") or {}
        rows += [("Производитель", _clean(b.get("Manufacturer", ""))),
                 ("Версия", _clean(b.get("SMBIOSBIOSVersion", ""))),
                 ("Дата", _cim_date(b.get("ReleaseDate")))]
    else:
        rows += [("Производитель", _dmi("bios_vendor")),
                 ("Версия", _dmi("bios_version")),
                 ("Дата", _dmi("bios_date")),
                 ("Режим загрузки",
                  "UEFI" if os.path.isdir("/sys/firmware/efi") else "Legacy (BIOS)")]
    rows = [(k, v) for k, v in rows if v]
    if rows:
        sections.append(("BIOS / UEFI", rows))

    # --- Процессор(ы) ---
    rows = []
    pkgs = sysd["packages"]
    if sysd["sockets"] > 1:
        rows.append(("Конфигурация", sysd["cpu_short"]))
        rows.append(("Физических процессоров", str(sysd["sockets"])))
    for i, p in enumerate(pkgs, 1):
        label = f"Процессор {i}" if len(pkgs) > 1 else "Процессор"
        rows.append((label, p["name"]))
        rows.append((f"  Ядра / потоки{'' if len(pkgs) == 1 else f' (CPU {i})'}",
                     f'{p["cores"]} / {p["threads"]}'))
        if p["freq_mhz"]:
            rows.append((f"  Частота{'' if len(pkgs) == 1 else f' (CPU {i})'}",
                         f'{p["freq_mhz"]/1000:.2f} ГГц'))
    if not pkgs:
        rows.append(("Процессор", sysd["cpu_name"]))
    if sysd["sockets"] > 1:
        rows.append(("Всего ядер / потоков",
                     f'{sysd["physical"]} / {sysd["logical"]}'))
    sections.append(("Процессор", rows))

    # --- Память ---
    rows = [("Всего", f'{sysd["ram_total_gb"]:g} ГБ'),
            ("Доступно", f'{sysd["ram_avail_gb"]:g} ГБ')]
    if os.name == "nt":
        for m in _aslist(win.get("mem")):
            cap = _fmt_bytes(m.get("Capacity"))
            t = _MEM_TYPES.get(int(m.get("SMBIOSMemoryType") or 0), "")
            spd = m.get("ConfiguredClockSpeed") or m.get("Speed") or ""
            man = _clean(str(m.get("Manufacturer", "")))
            pn = _clean(str(m.get("PartNumber", "")))
            val = " · ".join(x for x in (
                cap, t, f"{spd} МТ/с" if spd else "", man, pn) if x)
            rows.append((_clean(str(m.get("DeviceLocator", ""))) or "Модуль", val))
    else:
        rows += _linux_mem_modules()
    sections.append(("Память", rows))

    # --- Накопители ---
    rows = []
    if os.name == "nt":
        for d in _aslist(win.get("disk")):
            model = _clean(str(d.get("Model", ""))) or "Диск"
            val = " · ".join(x for x in (
                _fmt_bytes(d.get("Size")),
                _clean(str(d.get("InterfaceType", "")))) if x and x != "—")
            rows.append((model, val or "—"))
    else:
        rows += _linux_disks()
    if rows:
        sections.append(("Накопители", rows))

    # --- Видеоадаптер ---
    gpus = []
    if os.name == "nt":
        gpus = [_clean(str(g.get("Name", ""))) for g in _aslist(win.get("gpu"))]
    else:
        gpus = _linux_gpus()
    gpus = [g for g in gpus if g]
    if gpus:
        sections.append(("Видеоадаптер",
                         [(f"GPU {i}" if len(gpus) > 1 else "GPU", g)
                          for i, g in enumerate(gpus, 1)]))

    # --- Сеть ---
    rows = []
    if psutil is not None:
        try:
            stats = psutil.net_if_stats()
            for name, addrs in psutil.net_if_addrs().items():
                low = name.lower()
                if low.startswith(("lo", "loopback")) or "loopback" in low:
                    continue
                st = stats.get(name)
                if st is not None and not st.isup:
                    continue
                ip4 = [a.address for a in addrs
                       if getattr(a.family, "name", str(a.family)) in
                       ("AF_INET",) or a.family == 2]
                mac = [a.address for a in addrs
                       if getattr(a.family, "name", str(a.family)) in
                       ("AF_LINK", "AF_PACKET") or a.family == 17]
                val = " · ".join(x for x in (
                    ", ".join(ip4) if ip4 else "",
                    mac[0].replace("-", ":") if mac else "") if x)
                if val:
                    rows.append((name, val))
        except Exception:
            pass
    if rows:
        sections.append(("Сеть", rows[:8]))

    return sections
