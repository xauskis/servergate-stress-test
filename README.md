<p align="center">
  <img src="logo-header.svg" width="380" alt="SERVER GATE">
</p>

<h1 align="center">SERVER GATE — Stress Test</h1>

<p align="center">
  <b>Bootable CPU &amp; RAM stress-testing suite with a modern GUI</b><br>
  7 CPU torture tests · 12 memtest86-style memory tests · multi-socket CPU detection ·
  AIDA-like hardware info · one-screen client report
</p>

<p align="center">
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20Live%20ISO-0684BD">
  <img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-FF9000">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
</p>

---

## ✨ Features

- **7 CPU stress tests** — all-core transcendental math (multiprocess), ZIP archiving (CPU+I/O),
  deep Fibonacci recursion, SHA-512 hashing, BZip2 compression, Sieve of Eratosthenes,
  Mandelbrot FPU torture. Sequential or **all-at-once "extreme" mode**, configurable
  duration (30 s … 3 h) and number of rounds.
- **12 memtest86-style RAM tests** — own address, walking ones/zeros, moving inversions
  (1/0, 8-bit, random), checkerboard, solid bits, block move, modulo-20, pseudo-random
  compare, bit-fade retention. Configurable buffer size and pass count, live error
  counter and MB/s throughput. Default profile: all 12 tests, 1 pass.
- **Multi-socket CPU detection** — dual/quad-socket servers are shown as
  `Intel Xeon Gold 6254 ×2` with per-package cores, threads and frequency.
- **System configuration tab** (AIDA-style) — platform, motherboard, BIOS/UEFI & boot mode,
  per-socket CPUs, every RAM module (size · type · speed · vendor · part number),
  drives, GPUs, network.
- **One-screen client report** — verdict, summary tiles, every test with metrics and
  status, full system info. Fits a single screenshot; detailed per-round log saves to `.txt`.
- **Bootable Live ISO** — remaster script turns the official Debian Live image into a
  self-starting stress-test appliance: boot from **Ventoy** or a raw USB stick on any
  server (BIOS & UEFI, Secure Boot friendly), the GUI opens fullscreen automatically.
- **Portable Windows build** — single-file `.exe`, no installation required.

## 📸 Screenshots

| CPU stress testing | RAM testing (memtest86-style) |
|---|---|
| ![CPU tab](docs/screenshots/cpu-tab.png) | ![RAM tab](docs/screenshots/ram-tab.png) |

| System configuration (AIDA-like) | One-screen report |
|---|---|
| ![Config tab](docs/screenshots/config-tab.png) | ![Report](docs/screenshots/report.png) |

## 🚀 Quick start

### Windows (portable)
Download `ServerGate_StressTest_GUI.exe` from
[**Releases**](../../releases) and run it. Nothing to install.

### Run from source
```bash
pip install -r requirements.txt
cd app
python main.py
```
Works on Windows and Linux (Tk + X11).

### Bootable ISO (for servers, via Ventoy)
The ISO is ~3.3 GB, so it is not hosted in this repository — build it yourself
in ~20 minutes on any Debian/Ubuntu machine (WSL2 works too):

```bash
cd iso
sudo ./build_iso.sh          # downloads official Debian Live, injects the app
# → servergate.iso  (BIOS + UEFI, isohybrid)
```

Copy `servergate.iso` onto your Ventoy stick, boot the server (e.g. HPE ProLiant —
press **F11** for the boot menu), pick the ISO — the stress-test GUI starts
automatically in fullscreen. In live mode almost the entire physical RAM of the
server is available to the memory test.

## 🔧 Building the Windows exe

```bash
pip install -r requirements.txt pyinstaller
cd app
pyinstaller --noconfirm --onefile --windowed --name ServerGate_StressTest_GUI ^
  --icon servergate.ico --collect-all customtkinter ^
  --add-data "logo_header.png;." --add-data "logo_report.png;." ^
  --add-data "logo_icon.png;." --add-data "servergate.ico;." main.py
```

## 🇷🇺 Кратко по-русски

**SERVER GATE Stress Test** — стресс-тестирование процессоров и оперативной памяти
серверов и ПК: 7 CPU-тестов, 12 тестов ОЗУ в стиле memtest86, определение
многопроцессорных конфигураций (×2/×4), вкладка «Конфигурация» как в AIDA,
отчёт в одно окно для скриншота клиенту. Загрузочный Live-ISO для Ventoy
собирается скриптом `iso/build_iso.sh`; portable-exe для Windows — в разделе
[Releases](../../releases).

## 📄 License

Code is released under the [MIT License](LICENSE).
The SERVER GATE name and logo are the property of [servergate.ru](https://servergate.ru).
