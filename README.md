# nouveau-dkms (`v2.4.0`)

Out-of-tree **Nouveau DKMS kernel module** providing core, shader, voltage, PCIe link, and bidirectional DDR3 memory reclocking (324 MHz ↔ 900 MHz), S3 suspend/resume recovery, live TTM VRAM telemetry, vertical blanking synchronization, and multi-kernel support across Linux 6.18 through 7.3.

> [!WARNING]
> **EXPERIMENTAL HARDWARE DRIVER**
> This driver and dynamic clock governor have been developed, reverse-engineered, and tested on hardware using a **Dell XPS 17 L702X (NVIDIA GeForce GT 555M / Fermi `GF106M`, `10de:0dcd`, 3072 MB DDR3, 1920×1080 @ 120 Hz 3D Vision eDP display)**. Behavior on other board variants, memory types (GDDR5 vs. DDR3), or chipsets may vary. Use at your own risk.

---

## Key Features

- **Multi-Kernel Support (Linux 6.18 through 7.3) & Modular Patch Queue**:
  - Centralized multi-kernel compatibility layer (`nouveau_compat.h`) providing version-gated shims for Linux DRM, TTM, MM, and DMA-fence API shifts across Linux 6.18 LTS through 7.3.
  - Numbered patch queue (`patches/series` and `patches/0001`..`0013`) isolating universal driver improvements from architecture-specific reclocking logic.
  - Automated GitHub Actions multi-kernel CI matrix with verified builds for Arch Linux (`.pkg.tar.zst`), Debian/Ubuntu (`.deb`), and Fedora/RHEL (`.rpm`).
  - Early module loading integration via `/usr/lib/modules-load.d/nouveau.conf` to guarantee initialization prior to display manager handoff.

- **Vertical Blanking Synchronization**:
  - Aligns memory frequency transitions in `ramgf100.c` with the vertical blanking approach window and blanking leading edge.
  - Ensures memory reclock cycles complete during blanking intervals on high-refresh displays before scanout begins.

- **Fermi 256-Byte Render Target Alignment**:
  - Enforces 256-byte (`0x100`) base alignment in `nouveau_bo.c` and `nouveau_gem.c` for Fermi+ color targets, eliminating PGRAPH `DATA_ERROR 00000004 [INVALID_VALUE]` on method `0x0804` (`NV9097_SET_COLOR_TARGET_B`) with Wayland/Mesa suballocated buffers.

- **Bidirectional DDR3 Memory Reclocking (324 MHz ↔ 900 MHz)**:
  - Custom resident Falcon microcode executor (`memx_exec_custom.fuc`) running on the Fermi `PDAEMON` microcontroller (`0x10a000`) via MMIO mailboxes (`SCRATCH2` / `SCRATCH3`).
  - Replaces the legacy PMU `MEMX` queue interface (`gt215_pmu_send`), preventing `PRIVRING` bus faults (`0x10a580`).
  - Hardware DDR3 PHY commit strobe latching (`0x001548 = 0x80000101`) and PMU clock domain handling, reaching 43.2 GB/s memory bandwidth on 192-bit interfaces (2.78x over the 324 MHz boot clock).

- **Core, Shader, Voltage and Overclock Scaling**:
  - P-state scaling across `03` (idle), `07` (desktop), `0f` (full 3D boost), and synthetic `10` overclock (700 MHz core / 1400 MHz shader / 900 MHz DDR3 @ 1.030 V = 403.2 GFLOPS FP32).
  - Corrects VBIOS `VMAP` undervolting tables on `GF106M` (870 mV adjusted to factory 1.030 V on performance states, stepping down to 0.820 V at idle).

- **S3 Suspend / Resume Recovery**:
  - Verifies the resident Falcon microcode signature (`SCRATCH0 == 0xE1EC0001`) before executing mailbox commands. Re-bootstraps the microcode image if IMEM was cleared during system sleep.

- **Dynamic PCIe Link Scaling**:
  - Scales the x16 PCIe link between Gen1 (2.5 GT/s in P-states `03`/`07`) for reduced idle power and Gen2 (5.0 GT/s in `0f`/`10`) for maximum transfer rates.

- **Two-Stage Dynamic Governor (`nouveau-dynclockd`)**:
  - Desktop state: scales core and shader clocks between `03` (50 MHz) and `07` (202 MHz) while maintaining memory at 324 MHz for flicker-free desktop operation.
  - Performance state: scales to `0f` (590/1180/900 MHz @ 1.030 V) when 3D or compute workloads are active.
  - Thermal and battery management: limits maximum clock state to `07` on battery power and applies thermal throttling at 80 deg C (configurable via `/etc/nouveau-dynclockd.conf`).

- **Live TTM VRAM Telemetry (`nouveau-ctrl` & `nouveau-tui`)**:
  - Kernel-level TTM memory accounting exposed via `/run/nouveau/vram`, paired with fan RPM telemetry (`dell_smm_hwmon`), link status, and temperature monitoring.

---

## Supported Hardware & P-State Table (GeForce GT 555M / `GF106M`)

| P-State | Core (`gpc2clk`) | Shader (`sys2clk`) | Memory (`mclk`) | Bandwidth (192-bit) | Voltage | PCIe Link | Compute (`FP32`) | Status |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **`03` (P12 Idle)** | 50 MHz | 101 MHz | 135 MHz | 6.5 GB/s | 0.820 V | Gen1 (2.5 GT/s) | 29.1 GFLOPS | Active |
| **`07` (P8 2D/Med)** | 202 MHz | 405 MHz | 324 MHz | 15.5 GB/s | 0.820 V | Gen1 (2.5 GT/s) | 116.6 GFLOPS | Active |
| **`0a` (P3 Balanced)** | 405 MHz | 810 MHz | 650 MHz | 31.2 GB/s | 0.920 V | Gen1 / Gen2 | 233.3 GFLOPS | Derived (`0x10012702`) |
| **`0f` (P0 Boost)** | 590 MHz | 1180 MHz | 900 MHz | 43.2 GB/s | 1.030 V | Gen2 (5.0 GT/s) | 339.8 GFLOPS | Active |
| **`10` (Overclock)** | **700 MHz** | **1400 MHz** | **900 MHz** | **43.2 GB/s** | **1.030 V** | **Gen2 (5.0 GT/s)** | **403.2 GFLOPS** | Verified (`NvFermiOC=1`) |

---

## Installation

### Arch Linux / Manjaro / CachyOS
```bash
# Install via AUR
yay -S nouveau-dkms

# Or build from source
git clone https://github.com/Twilight0/nouveau-dkms.git
cd nouveau-dkms
makepkg -si
```

### Debian / Ubuntu
```bash
# Install prebuilt deb package from GitHub Releases or build artifact
sudo dpkg -i nouveau-dkms_*.deb || sudo apt-get install -f
```

### Fedora / RHEL
```bash
# Install prebuilt RPM package from GitHub Releases or build artifact
sudo dnf install ./nouveau-dkms-*.noarch.rpm
```

### Generic DKMS Installation
```bash
git clone https://github.com/Twilight0/nouveau-dkms.git
cd nouveau-dkms
sudo make dkms-install
```

---

## Userspace Utilities (`nouveau-utils`)

The userspace governor daemon (`nouveau-dynclockd`), control CLI (`nouveau-ctrl`), and interactive dashboard (`nouveau-tui`) are maintained in the companion repository:
[github.com/Twilight0/nouveau-utils](https://github.com/Twilight0/nouveau-utils)

```bash
# Enable the clock management daemon
sudo systemctl enable --now nouveau-dynclockd.service

# Query clock telemetry via CLI
nouveau-ctrl status
nouveau-ctrl set auto

# Launch the terminal interface
nouveau-tui
```

---

## Configuration

### Recommended Kernel Parameters (`/etc/default/grub`)
```text
nouveau.modeset=1 acpi_backlight=native video.allow_duplicates=1
```

### Module Options (`/etc/modprobe.d/nouveau.conf`)
```text
# Default configuration (Memory reclocking and VBlank sync enabled)
options nouveau modeset=1 vblank_continuous=1 NvFermiVblankSync=1 config=NvFermiMemReclock=true

# Optional: Enable synthetic P-State 10 Overclock (700 MHz core / 1400 MHz shader / 900 MHz DDR3 @ 1.030 V)
# options nouveau modeset=1 vblank_continuous=1 NvFermiVblankSync=1 config=NvFermiMemReclock=true,NvFermiOC=true
```

| Parameter / Option | Default | Description |
| :--- | :---: | :--- |
| `vblank_continuous` | `0` (`1` in default conf) | Keeps hardware VBlank interrupts active for display pacing. |
| `NvFermiVblankSync` | `1` | Aligns memory transitions with CRTC vertical blanking onset (`0x616340`). |
| `config=NvFermiMemReclock=true` | `false` (`true` in conf) | Enables bidirectional DDR3 memory reclocking (324 MHz ↔ 900 MHz) via resident Falcon executor. |
| `config=NvFermiOC=true` | `false` | Enables synthetic overclock P-state `10` (700/1400/900 MHz @ 1.030 V). |
| `config=NvClkMode` / `NvClkModeAC` / `NvClkModeDC` | *(upstream)* | Boot-time P-state override for AC/DC power sources. |

---

## Documentation & References

| Document | Description |
| :--- | :--- |
| **[`DRIVER_COMPARISON.md`](docs/DRIVER_COMPARISON.md)** | Technical comparison: `nouveau-dkms` vs. legacy proprietary NVIDIA drivers (`390.157` / `470.xx`) vs. upstream kernel Nouveau. |
| **[`RECLOCKING_NOTES.md`](docs/RECLOCKING_NOTES.md)** | Hardware and reverse-engineering reference: `GF106` register sequences, Falcon microcode architecture, S3 recovery, and decompiled NVIDIA driver routines. |
| **[`TODO.md`](docs/TODO.md)** | Completed milestones, active engineering items, and driver subsystem roadmap. |
| **[`research/vram-pooling-and-compression.md`](docs/research/vram-pooling-and-compression.md)** | Architectural research paper on OpenCL compute, unified memory pooling, and compressed VRAM swap (`nvzram`). |
| **[`research/vulkan-on-fermi.md`](docs/research/vulkan-on-fermi.md)** | Architectural research paper on bound-descriptor Vulkan 1.0/1.1 on Fermi architectures (`nvk-fermi`). |
| **[`research/video-encoding-architecture.md`](docs/research/video-encoding-architecture.md)** | Video encoding and decoding reference: hybrid compute-shader VA-API encoding, VP4 firmware, and MSENC analysis. |
| **[`research/stereoscopic-3d-vision.md`](docs/research/stereoscopic-3d-vision.md)** | Hardware stereoscopic 3D configuration and active-shutter display notes. |
| **[`CHANGELOG.md`](docs/CHANGELOG.md)** | Release notes and version history. |
| **[`PATCH_HISTORY.md`](docs/PATCH_HISTORY.md)** | Index of modular driver patches in `patches/`. |
| **[`CONTRIBUTING.md`](docs/CONTRIBUTING.md)** | Instructions for submitting diagnostic dumps from additional hardware configurations. |

---

## Hardware Diagnostics

To generate a hardware diagnostic report for other Fermi, Kepler, or Maxwell GPUs:
```bash
sudo python3 tools/nouveau-fermi-diag.py
```
Reports can be submitted via the issue tracker for inclusion in hardware verification tables.

---

## License

- Nouveau Kernel Module Patches: `GPL-2.0-only`
- Daemon, CLI/TUI and Diagnostic Tools: `MIT`
