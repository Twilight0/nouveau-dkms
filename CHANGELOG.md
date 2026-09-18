# Changelog

All notable changes to the **Nouveau Fermi Reclocking** project will be documented in this file.

---

## [2.0.0] - 2026-09-18

### 🚀 Major Milestone: Full Bidirectional DDR3 Memory Reclocking & Telemetry Suite

This major release achieves the long-sought milestone of fully working, bidirectional DDR3 memory reclocking (`324 MHz` ↔ `900 MHz`) on NVIDIA Fermi (GF100–GF119) GPUs under Linux, paired with a flicker-free two-stage dynamic governor and a comprehensive telemetry management suite.

#### 🧠 Kernel Module & Custom Falcon Executor Engine
- **Custom Resident Falcon Microcode Executor (`ramgf100.c` / `gf100.fuc3`)**:
  - Completely bypasses the legacy Tesla-era PMU MEMX queue interface (`gt215_pmu_send`) that previously failed on Fermi with PRIVRING hardware faults.
  - Implements a dedicated resident microcode loop (`resident_idle`) polling `SCRATCH1` (`0x10a084`), executing bidirectional memory reclocking in sub-millisecond fast-path via MMIO mailboxes.
  - Eliminates destructive PMC hardware resets (`0x000200`) and IMEM re-uploads during runtime state transitions.
  - **Hardware PHY Commit Latch (`0x001548 = 0x80000101`)**: Asserts bit-31 commit strobe immediately after DDR3 PHY register writes, eliminating data-eye phase jitter, page-table corruption, and storage-type faults under 3D load.
  - **Interrupt & Timer Masking**: Masks Falcon periodic timers, watchdogs, and interrupt lines, preventing unhandled double-trap exits into `STOPPED` (`UC=0x10`).
  - **PMU Falcon Clock Domain Protection**: Excludes domain `0x0c` (`nv_clk_src_pmu`) from clock calculation, preventing asynchronous PLL multiplexer switching from glitching the running PDAEMON microcontroller.
- **Synchronous Voltage Regulation (`nvkm_volt`)**:
  - Dynamically commands the Fermi PWM voltage controller (`0x1373f0`) to step core voltage up to factory **1.030 V** before entering P-State `0f`, and safely steps it down to **0.820 V** when downclocking to `07` or `03`.
- **Native 120 Hz eDP Display Support**:
  - Enables continuous VBlank pacing (`vblank_continuous=1`) and 6 bpc color clamp for full 119.97 Hz refresh on internal laptop panels.

#### ⚡ Dynamic Frequency Governor (`nouveau-dynclockd`)
- **Flicker-Free Two-Stage Scaling**:
  - **Stage 1 (Desktop / Browser / UI)**: Dynamically scales core/shader between `03` (50 MHz) and `07` (202 MHz) while clamping memory at `324 MHz`. Transitions occur without DRAM retiming or scanout delay, achieving **100% flicker-free operation at 120 Hz**.
  - **Stage 2 (Dedicated 3D Graphics)**: Automatically boosts to `0f` (`590 MHz` core / `1180 MHz` shader / `900 MHz` memory @ 1.030 V) when dedicated 3D games, emulators, or benchmarks are launched.
- **Thermal Throttle Protection**:
  - Automatically caps maximum GPU clock state to `07` when core temperature reaches throttle limit (default: `80 °C` with `5 °C` hysteresis).
- **Persistent Configuration**:
  - Reads settings from `/etc/nouveau-dynclockd.conf` with automatic 1-second file mtime change detection and `SIGHUP` support.
- **Low-Power Startup**:
  - Immediately forces low-power idle state `03` upon service startup and boot.

#### 🎮 Management & Telemetry Utilities (`nouveau-ctrl` & `nouveau-tui`)
- **Hardware Telemetry Integration**:
  - **Dell SMM Fan Speed**: Real-time RPM reading via platform hardware monitor (`dell_smm fan1_input`).
  - **PCIe Link Telemetry**: Real-time PCIe generation and lane width status (`2.5 GT/s Gen1 x16 [Max: 5.0 GT/s Gen2 x16]`).
  - **Colorized Thermal Indicators**: Three-tier status coloring (<65 °C Bold Green, 65–75 °C Bold Yellow, >75 °C Bold Red).
  - **Runtime Throttle Configuration**:
    - CLI: `nouveau-ctrl set_throttle_temp <temp>`
    - TUI: Press `t` to type a limit, or `[` / `]` to adjust interactively in Tab 1.
  - Clean display: Removed all legacy "(target: ...)" references.

#### 🛠️ Reproducible Workflow Tools (`tools/`)
- `tools/nouveau-fermi-diag.py`: Standalone diagnostic tool dumping PCI IDs, VBIOS BIT tables (`P`, `M`, `U`, `C`), MMIO registers, and DRM clients.
- `tools/sniff-memory-reclock.py`: Direct BAR0 memory controller (PFB) and PHY DLL register delta sniffer.
- `tools/run-mmiotrace.sh`: Automated kernel MMIO tracing script for proprietary 390.xx driver analysis.

---

## [1.2.0] - 2026-09-06
- Initial interactive Curses TUI manager (`nouveau-tui`).
- Core & shader reclocking (202/405 MHz <-> 590/1180 MHz).
- Initial dynamic governor daemon (`nouveau-dynclockd`).
- Dell XPS backlight synchronization integration.

## [1.1.0] - 2026-08-30
- Native 120 Hz eDP display patch for Dell XPS L702X.
- Initial CLI reclocking utility (`nouveau-ctrl`).
- DKMS automated packaging.

## [1.0.0] - 2026-08-20
- Baseline out-of-tree Nouveau kernel module repository.
