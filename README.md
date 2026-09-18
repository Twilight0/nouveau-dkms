# nouveau-fermi-reclock-dkms

Out-of-tree **Nouveau DKMS kernel module** with **Fermi (GF100–GF119)** core, shader, voltage, and **bidirectional DDR3 memory reclocking** support, bundled with an intelligent two-stage dynamic GPU governor and telemetry management suite.

> [!WARNING]
> **EXPERIMENTAL SOFTWARE DISCLAIMER**
> This driver and dynamic clock governor have been extensively tested and verified specifically on a **Dell XPS L702X (GeForce GT 555M / GF106M, 3072 MB DDR3, 120Hz display)** running Linux. 
> Behavior on different hardware models, memory configurations (e.g. GDDR5 vs DDR3), or GPU variants may vary. Use at your own risk.

---

## Features

- **Bidirectional DDR3 Memory Reclocking (324 MHz ↔ 900 MHz)**:
  - Custom resident Falcon microcode executor engine running sub-millisecond DRAM retiming via MMIO mailboxes.
  - Completely bypasses the Tesla-era PMU MEMX queue architecture, avoiding PRIVRING hardware faults and pipeline hangs.
  - Restores full 43.2 GB/s memory bandwidth under 3D workloads.
- **Fermi GPU Core & Shader Reclocking (GF100 / GF104 / GF106 / GF108 / GF110 / GF114 / GF116 / GF119)**:
  - Complete 3-tier clock scaling: `03` (50 MHz) ↔ `07` (202 MHz) ↔ `0f` (590 MHz core / 1180 MHz shader).
  - Synchronous factory voltage regulation (820 mV idle ↔ 1.030 V full 3D).
  - Optional synthetic overclock pstate `10` (`core 700 / shader 1400 / memory 900 @ 1.030 V`), gated behind `config=NvFermiOC=true`.
- **Flicker-Free Two-Stage Dynamic Frequency Governor (`nouveau-dynclockd`)**:
  - Automatically manages GPU power states without display flicker.
  - **Stage 1 (2D / Browser / Desktop)**: Smoothly toggles between `03` (50 MHz) and `07` (202 MHz) while keeping memory clamped at 324 MHz — **100% flicker-free at 120 Hz**.
  - **Stage 2 (Dedicated 3D Graphics)**: Instantly scales to `0f` (590/900 MHz @ 1.030 V) when games, emulators, or benchmarks run.
  - **Thermal Protection**: Automatically caps highest clocks to `07` when GPU temperature reaches the throttle limit (default: 80 °C with 5 °C hysteresis). Configurable via `/etc/nouveau-dynclockd.conf`.
- **Comprehensive Hardware Telemetry (`nouveau-ctrl` & `nouveau-tui`)**:
  - Interactive Curses TUI and scriptable CLI with colorized thermal zones (<65°C Green, 65-75°C Yellow, >75°C Red).
  - Real-time Fan RPM reading via Dell SMM platform monitor (`dell_smm`).
  - Real-time PCIe link speed & generation telemetry (`current_link_speed` / width).
- **DKMS Integration**:
  - Automatically rebuilds and installs across kernel upgrades.
---

## Hardware Configuration Tested

- **Laptop**: Dell XPS L702X
- **GPU**: NVIDIA GeForce GT 555M (Fermi / GF106M, Device ID `10de:0dcd`)
- **VRAM**: 3072 MB DDR3 (192-bit bus)
- **Display**: 1920x1080 @ 120Hz Internal Panel
- **Kernel Tested**: Linux 6.18 LTS (`linux-cachyos-lts` / Arch Linux)

---

## Installation

### Arch Linux / CachyOS / Manjaro (via AUR)

```bash
# Using yay
yay -S nouveau-fermi-reclock-dkms

# Or manual build
git clone https://aur.archlinux.org/nouveau-fermi-reclock-dkms.git
cd nouveau-fermi-reclock-dkms
makepkg -si
```

### Enable the Dynamic Clock Governor

```bash
sudo systemctl enable --now nouveau-dynclockd.service
```

---

## Recommended Kernel Parameters

Add the following options to your bootloader configuration (e.g. `/etc/default/grub`):

```text
nouveau.modeset=1 acpi_backlight=native video.allow_duplicates=1
```

After updating GRUB, rebuild the bootloader config:
```bash
sudo update-grub  # or sudo grub-mkconfig -o /boot/grub/grub.cfg
```

---

## Module Options

The driver supports tuning options via `/etc/modprobe.d/nouveau-fermi-reclock.conf`:

```text
# Default (no overclock)
options nouveau modeset=1 vblank_continuous=1

# Optional: enable the overclock pstate (700/1400 core/shader, memory 900)
# options nouveau modeset=1 vblank_continuous=1 config=NvFermiOC=true
```

### Module parameters

- **`vblank_continuous`** (default: `0`): Keeps hardware VBlank interrupts running continuously to support high-refresh (120Hz) frame pacing. Added by this project.
- **`modeset`** (default: `1`): Enable kernel modesetting.

### `config=` sub-options

- **`NvFermiOC`** (default: `false`): Creates the synthetic overclock pstate `10` — `core 700 MHz / shader 1400 MHz / memory 900 MHz @ 1.030 V`. Off by default; enable with `config=NvFermiOC=true`, then select it via `nouveau-ctrl set 10`. Added by this project.
- **`NvFermiMemReclock`** (default: `false`): Experimental DDR3 memory reclock on Fermi. Without it, memory stays at the boot clock (324 MHz) regardless of the requested pstate. Added by this project.
- **`NvClkMode` / `NvClkModeAC` / `NvClkModeDC`** (upstream): Force the clock state for both / AC / DC power sources respectively. E.g. `NvClkModeDC=07` caps the GPU at P8 (202 MHz) on battery.
- **`NvPmEnableGating`** (default: `false`, upstream): PMU clock gating for power saving. Unrelated to PMU firmware loading.
- **`NvFanPWM`** (upstream): Fan PWM control for manual cooling.

### Voltage fix

On the **Dell XPS L702X** (`GF106M`, `10de:0dcd`), the `0f` pstate was undervolted: `nvkm_volt_map` (the VMAP speedo formula) mapped the `0f` voltage ID to 862.5 mV, yielding 870 mV instead of the factory 1.030 V. This project patches `nvkm_pstate_new` to force `0f` to 1.030 V. Without this fix the overclock pstate is unstable under load.
---

## Repository Contents

- `PKGBUILD`: Arch Linux / AUR package specification.
- `.SRCINFO`: AUR metadata.
- `dkms.conf`: DKMS module build and installation rules.
- `nouveau-fermi-reclock.patch`: Unified reclocking, display clocking, and backlight patch against upstream Nouveau.
- `nouveau-ctrl`: CLI management utility for status, clock locking, and governor control.
- `nouveau-tui`: Interactive terminal user interface for GPU reclocking & telemetry.
- `nouveau-dynclockd.py`: Dynamic frequency scaling daemon with Wayland/EGL load awareness.
- `tools/nouveau-fermi-diag.py`: Standalone hardware diagnostic, MMIO register, and VBIOS BIT telemetry tool.
- `tools/sniff-memory-reclock.py`: Direct hardware BAR0 memory controller (PFB) and PLL timing sniffer.
- `tools/run-mmiotrace.sh`: Automated kernel MMIO tracing and `demmt` decoder script.
- `RECLOCKING_NOTES.md`: Comprehensive DDR3 memory reclocking, display architecture, and reverse engineering notes.
- `NVENC.md`: Hardware video encoding analysis, silicon limitations, and OpenCL-accelerated encoding guide.
- `AI.md`: Local AI / LLM inference manual, Small Language Models (SLMs), and OpenCL compute guide.
- `CONTRIBUTING.md`: Guide for running diagnostics and submitting hardware telemetry.
- `TODO.md`: Project roadmap and planned driver enhancements.

---

## 🔍 Hardware Diagnostics & Community Contributions

Have a different Fermi GPU or laptop model? Help us expand hardware compatibility!

Run our standalone diagnostic tool:
```bash
sudo python3 tools/nouveau-fermi-diag.py
```
And submit your generated `nouveau_fermi_diag_report.md` via our [**Hardware Telemetry Issue Template**](https://github.com/Twilight0/nouveau-fermi-reclock-dkms/issues/new?template=hardware-telemetry.md). See [`CONTRIBUTING.md`](CONTRIBUTING.md) for details.

---

## License

- Nouveau Kernel Module: `GPL-2.0-only`
- Daemon & Helper Scripts: `MIT`\n