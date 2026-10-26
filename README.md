# nouveau-dkms (`v2.2.0`)

Out-of-tree **Nouveau DKMS kernel module** and dynamic GPU frequency/power governor unlocking full **Core, Shader, Voltage, PCIe Gen1/Gen2, and bidirectional DDR3 Memory Reclocking (`324 MHz` ↔ `900 MHz`)**, S3 suspend/resume self-healing, live TTM VRAM telemetry, zero-stutter VBlank synchronization, and 120 Hz eDP display support on Linux `6.18+`—evolving into **`nouveau-reclocking-dkms`** for pre-`Nova` NVIDIA GPUs.

> [!WARNING]
> **EXPERIMENTAL HARDWARE DRIVER**
> This driver and dynamic clock governor have been developed, reverse-engineered, and production-verified on a **Dell XPS 17 L702X (NVIDIA GeForce GT 555M / Fermi `GF106M`, `10de:0dcd`, 3072 MB DDR3, 1920×1080 @ 120 Hz 3D Vision eDP display)**. Behavior on other board variants, memory types (GDDR5 vs. DDR3), or chipsets may vary. Use at your own risk.

---

## Key Features (`v2.2.0`)

- **Full Bidirectional DDR3 Memory Reclocking (`324 MHz` ↔ `900 MHz`)**:
  - Custom resident Falcon microcode executor (`memx_exec_custom.fuc`) running on the Fermi `PDAEMON` microcontroller (`0x10a000`) via sub-millisecond MMIO mailboxes (`SCRATCH2` / `SCRATCH3`).
  - Completely bypasses the broken Tesla-era PMU `MEMX` queue interface (`gt215_pmu_send`), eliminating `PRIVRING` bus faults (`0x10a580`) and pipeline hangs.
  - Hardware DDR3 PHY commit strobe latching (`0x001548 = 0x80000101`) + PMU clock domain freeze (`0x0c`), unlocking the full **43.2 GB/s** memory bandwidth (**2.78×** over the `324 MHz` boot clock).
- **Core, 2× Hot-Clock Shader, Voltage & Overclock Scaling**:
  - Full P-state scaling across `03` (Idle), `07` (2D Desktop), `0f` (Full 3D Boost), and verified synthetic **`10` Overclock (`700 MHz` core / `1400 MHz` shader / `900 MHz` DDR3 @ `1.030 V` = `403.2 GFLOPS FP32`)**.
  - Fixes the VBIOS `VMAP` undervolting bug on `GF106M` (`870 mV` → factory `1.030 V` on `0f`/`10`, stepping down to `0.820 V` on `03`/`07`).
- **S3 Suspend / Resume Self-Healing Recovery (`v2.0.1+`)**:
  - Verifies the resident Falcon microcode signature (`SCRATCH0 == 0xE1EC0001`) before fast-path mailbox commands; automatically detects cleared IMEM after system sleep and transparently cold-bootstraps the Falcon executor without timeouts or P-state `07` clock freezes.
- **Dynamic PCIe Gen1 (`2.5 GT/s`) ↔ Gen2 (`5.0 GT/s`) Link Scaling**:
  - Automatically scales the x16 PCIe link between Gen1 (`2.5 GT/s` in `03`/`07`) for low idle power and Gen2 (`5.0 GT/s`, `8.0 GB/s` per direction in `0f`/`10`) for maximum DMA throughput.
- **Flicker-Free Two-Stage Dynamic Governor (`nouveau-dynclockd`)**:
  - **Stage 1 (2D / Desktop / Browser)**: Scales core/shader between `03` (`50 MHz`) and `07` (`202 MHz`) while keeping memory at `324 MHz` for flicker-free 120 Hz desktop use.
  - **Stage 2 (3D Games / Compute)**: Automatically boosts to `0f` (`590/1180/900 MHz @ 1.030 V`) when 3D or compute workloads launch.
  - **Battery & Thermal Protection**: Caps maximum P-state to `07` on DC battery power (`BATTERY_CAP=true` in `v2.1.0`) and throttles automatically if GPU temperature reaches `80 °C` (`5 °C` hysteresis), configurable via `/etc/nouveau-dynclockd.conf`.
- **Live TTM VRAM Telemetry & Management Suite (`nouveau-ctrl` & `nouveau-tui`)**:
  - In-kernel TTM VRAM accounting (`v2.1.0`) exposed to unprivileged users via `/run/nouveau/vram`, paired with Dell SMM fan RPM (`dell_smm_hwmon`), PCIe link telemetry, and colorized thermal zones in both the CLI (`nouveau-ctrl`) and interactive curses dashboard (`nouveau-tui`).

---

## Performance State Ladder (GeForce GT 555M / `GF106M`)

| P-State | Core (`gpc2clk`) | Shader (`sys2clk`) | Memory (`mclk`) | Bandwidth (192-bit) | Voltage | PCIe Link | Compute (`FP32`) | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`03` (P12 Idle)** | `50 MHz` | `101 MHz` | `135 MHz` | `6.5 GB/s` | `0.820 V` | Gen1 (`2.5 GT/s`) | `29.1 GFLOPS` | ✅ Active |
| **`07` (P8 2D/Med)** | `202 MHz` | `405 MHz` | `324 MHz` | `15.5 GB/s` | `0.820 V` | Gen1 (`2.5 GT/s`) | `116.6 GFLOPS` | ✅ Active |
| **`0a` (P3 Balanced)** | `405 MHz` | `810 MHz` | `650 MHz` | `31.2 GB/s` | `0.920 V` | Gen1 / Gen2 | `233.3 GFLOPS` | 📋 Derived (`0x10012702`) |
| **`0f` (P0 Boost)** | `590 MHz` | `1180 MHz` | `900 MHz` | `43.2 GB/s` | `1.030 V` | Gen2 (`5.0 GT/s`) | `339.8 GFLOPS` | ✅ Active |
| **`10` (Overclock)** | **`700 MHz`** | **`1400 MHz`** | **`900 MHz`** | **`43.2 GB/s`** | **`1.030 V`** | **Gen2 (`5.0 GT/s`)** | **`403.2 GFLOPS`** | ✅ Verified (`NvFermiOC=1`) |

---

## Installation & Quickstart

### Arch Linux / AliveOS / CachyOS / Manjaro
```bash
# Install via AUR helper
yay -S nouveau-dkms

# Or build directly from source
git clone https://github.com/Twilight0/nouveau-dkms.git
cd nouveau-dkms
makepkg -si
```

### Companion Userspace Utilities (`nouveau-utils`)
The userspace governor (`nouveau-dynclockd`), control CLI (`nouveau-ctrl`), and interactive dashboard (`nouveau-tui`) are maintained in the companion repository:
👉 **[github.com/Twilight0/nouveau-utils](https://github.com/Twilight0/nouveau-utils)**

```bash
# Enable the dynamic frequency governor daemon
sudo systemctl enable --now nouveau-dynclockd.service

# Query telemetry & manage clocks via CLI
nouveau-ctrl status
nouveau-ctrl set auto

# Launch the interactive terminal dashboard
nouveau-tui
```

---

## Kernel & Module Configuration

### Recommended Kernel Boot Parameters (`/etc/default/grub`)
```text
nouveau.modeset=1 acpi_backlight=native video.allow_duplicates=1
```

### Module Options (`/etc/modprobe.d/nouveau.conf`)
```text
# Default configuration (Memory reclocking + VBlank sync enabled)
options nouveau modeset=1 vblank_continuous=1 NvFermiVblankSync=1 config=NvFermiMemReclock=true

# Enable synthetic P-State 10 Overclock (700 MHz core / 1400 MHz shader / 900 MHz DDR3 @ 1.030 V)
# options nouveau modeset=1 vblank_continuous=1 NvFermiVblankSync=1 config=NvFermiMemReclock=true,NvFermiOC=true
```

| Parameter / `config=` Option | Default | Description |
| :--- | :---: | :--- |
| `vblank_continuous` | `0` (`1` in conf) | Keeps hardware VBlank interrupts active for 120 Hz eDP frame pacing. |
| `NvFermiVblankSync` | `1` | Aligns memory reclock execution with CRTC vertical blanking onset (`rgpos 0x616340`). |
| `config=NvFermiMemReclock=true` | `false` (`true` in conf) | Enables bidirectional DDR3 memory reclocking (`324 MHz` ↔ `900 MHz`) via the resident Falcon executor. |
| `config=NvFermiOC=true` | `false` | Injects synthetic overclock P-state `10` (`700/1400/900 MHz @ 1.030 V`). |
| `config=NvClkMode` / `NvClkModeAC` / `NvClkModeDC` | *(upstream)* | Optional boot-time P-state pin for AC/DC power sources. |

---

## Documentation & Architecture Guides

All reverse-engineering findings (including Ghidra + REA decompilation of NVIDIA `390.157`), register sequences, and subsystem specifications are documented in dedicated guides:

| Document | Contents |
| :--- | :--- |
| **[`DRIVER_COMPARISON.md`](docs/DRIVER_COMPARISON.md)** | Detailed comparison matrix & user benefits: `nouveau-dkms` vs. legacy official NVIDIA drivers (`390.157` / `470.xx`) vs. stock upstream Nouveau. |
| **[`RECLOCKING_NOTES.md`](docs/RECLOCKING_NOTES.md)** | Master hardware & reverse-engineering reference: `GF106` DDR3 register sequences, Falcon `memx_exec_custom.fuc` design, S3 recovery, and concrete decompilation of `NVIDIA-Linux-x86_64-390.157` (`nv-kernel.o_binary` & `nv-modeset-kernel.o_binary`). |
| **[`TODO.md`](docs/TODO.md)** | Completed milestones (`v1.0`–`v2.2.0`), active engineering tasks (synthetic P3 `0a`, 120 Hz 6 bpc eDP, BLCG/SLCG, `0x10a600` load counters), and the **`nouveau-reclocking-dkms`** roadmap for all pre-`Nova` GPUs (Tesla, Fermi, Kepler, Maxwell 1 `GM107`/`GM108`, Maxwell 2/Pascal). |
| **[`VRAM_AI.md`](docs/VRAM_AI.md)** | OpenCL 3.0 (`Mesa Rusticl`), Local LLM/SLM inference guide (`llama.cpp` + `CLBlast`), Mode A (`VRAM + GART` unified memory for `> 3 GiB` models), Mode B (`/dev/nvram0` `PCOPY` DMA block device), and **`nvzram`** (GPU-accelerated `SM20` Warp-LZ4 compressed swap in VRAM). |
| **[`VULKAN.md`](docs/VULKAN.md)** | Architectural analysis and implementation blueprint for Vulkan 1.0/1.1 on Fermi (`nvk-fermi` bound `TIC`/`TSC` descriptor lowering paired with Mesa's `NIR → nv50_ir` backend). |
| **[`NVENC.md`](docs/NVENC.md)** | Video encoding & decoding architecture: `x264 --opencl` lookahead, the planned 4-stage **Hybrid Compute-Shader `VA-API` H.264 Encoder** for OBS Studio (`NVCUVENC` equivalent), `VP4` PureVideo HD firmware extraction, and Kepler/Maxwell `MSENC` (`0x1c8000`). |
| **[`CHANGELOG.md`](docs/CHANGELOG.md)** | Versioned release history (`v1.0.0` through `v2.2.0`). |
| **[`PATCH_HISTORY.md`](docs/PATCH_HISTORY.md)** | Detailed catalog of incremental patches in `patches/` and 1-command rollback instructions. |
| **[`3D_VISION.md`](docs/3D_VISION.md)** | Stereoscopic 3D guide: active-shutter glasses on Linux, `libnvstusb` USB IR emitter protocol, and 3D movie playback via Kodi, `bino`, and `mpv`. |
| **[`FEATURES_BREAKDOWN_CHECKLIST.md`](docs/FEATURES_BREAKDOWN_CHECKLIST.md)** | Architectural classification: kernel driver (`nouveau.ko`) vs. companion user-space tools (`nouveau-tools`) vs. upstream Mesa components, plus downstream packaging strategies. |
| **[`CONTRIBUTING.md`](docs/CONTRIBUTING.md)** | Instructions for running `tools/nouveau-fermi-diag.py` and submitting hardware telemetry for additional Fermi/Kepler/Maxwell GPUs. |

---

## Hardware Diagnostics & Community Contributions

Have a different Fermi, Kepler, or Maxwell GPU or laptop model? Run the standalone diagnostic script:
```bash
sudo python3 tools/nouveau-fermi-diag.py
```
And submit your generated `nouveau_fermi_diag_report.md` via the [**Hardware Telemetry Issue Template**](https://github.com/Twilight0/nouveau-dkms/issues/new?template=hardware-telemetry.md). See [`CONTRIBUTING.md`](docs/CONTRIBUTING.md) for details.

---

## License

- Nouveau Kernel Module Patch: `GPL-2.0-only`
- Daemon, CLI/TUI & Diagnostic Tools: `MIT`