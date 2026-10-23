# 📋 Roadmap & TODO (`TODO.md`)

This document tracks completed milestones, open engineering tasks, and the multi-architecture roadmap for **`nouveau-reclocking-dkms`** (currently packaged as `nouveau-dkms`).

### Documentation Map
- **[`RECLOCKING_NOTES.md`](RECLOCKING_NOTES.md)**: Hardware register tables, Falcon microcode architecture, and decompiled NVIDIA `390.157` (`nv-kernel.o_binary` & `nv-modeset-kernel.o_binary`) specifications.
- **[`VRAM_AI.md`](VRAM_AI.md)**: OpenCL 3.0 (`Mesa Rusticl`), Local LLM/SLM inference guide (`llama.cpp`), Unified `VRAM + GART` memory pooling, `/dev/nvram0` DMA block device, and GPU-compressed `nvzram`.
- **[`VULKAN.md`](VULKAN.md)**: Fermi (`NVC0_3D` / `NVC0_COMPUTE`) Vulkan 1.0/1.1 feasibility & bound-descriptor (`nvk-fermi`) design.
- **[`NVENC.md`](NVENC.md)**: Video encoding (`x264` OpenCL, Hybrid Compute-Shader `VA-API` H.264 encoder for OBS Studio, Kepler/Maxwell `MSENC`) & PureVideo HD (`VP4`) hardware decode.
- **[`CHANGELOG.md`](CHANGELOG.md) & [`PATCH_HISTORY.md`](PATCH_HISTORY.md)**: Release changelog and patch rollback catalog.

---

## Table of Contents
1. [Completed Milestones (`v1.0` – `v2.1.0`)](#-completed-milestones)
2. [Kernel & Hardware Subsystems Roadmap](#-kernel--hardware-subsystems-roadmap)
3. [Falcon Microcode & Memory Controller Expansion](#-falcon-microcode--memory-controller-expansion)
4. [Dynamic Governor Modernization (`nouveau-dynclockd` 2.0)](#-dynamic-governor-modernization-nouveau-dynclockd-20)
5. [Telemetry, Modern DRM/DRI APIs & Wayland Explicit Sync](#-telemetry-modern-drmdri-apis--wayland-explicit-sync)
6. [Compute, Video Encoding, Vulkan & `nvzram`](#-compute-video-encoding-vulkan--nvzram)
7. [Project Evolution: `nouveau-reclocking-dkms`, Multi-Kernel CI & Cross-Distro Packaging](#-project-evolution-nouveau-reclocking-dkms-multi-kernel-ci--cross-distro-packaging)

---

## ✅ Completed Milestones

- [x] **`v1.0` — Baseline Fermi Core & Shader Reclocking**:
  - Implemented core and 2× hot-clock shader scaling (`50/101 MHz`, `202/405 MHz`, `590/1180 MHz`).
  - Unlocked 120 Hz eDP display mode (`1920x1080 @ 120 Hz`, pixel clock `396.36 MHz`). *(Zero-flash VBlank transitions tracked in §1 below.)*
- [x] **`v1.1` — Factory Voltage Regulation & State `10` Overclock**:
  - Resolved `0f` VMAP undervolting bug (`870 mV` → factory `1030 mV` / `VID 0x01`).
  - Added and verified synthetic **`10` OC P-State** (`700 MHz` core / `1400 MHz` shader / `900 MHz` DDR3 @ `1.030 V`, **403.2 GFLOPS FP32**, +18.6% compute), gated by `config=NvFermiOC=true`.
- [x] **`v1.2` — Telemetry Suite (`nouveau-ctrl` / `nouveau-tui`) & Dynamic Governor (`nouveau-dynclockd`)**:
  - Built CLI utility [`nouveau-ctrl`](nouveau-ctrl), interactive curses dashboard [`nouveau-tui`](nouveau-tui), and background governor [`nouveau-dynclockd.py`](nouveau-dynclockd.py) with thermal hysteresis protection and Dell SMM fan RPM readout.
- [x] **`v2.0.0` — Full Bidirectional DDR3 Memory Reclocking (`324 MHz` ↔ `900 MHz`)**:
  - Built custom resident Falcon microcode executor (`memx_exec_custom.fuc`) running on `PDAEMON` (`0x10a000`) via MMIO mailboxes (`SCRATCH2`/`SCRATCH3`), bypassing broken Tesla `MEMX` queues.
  - Added hardware DDR3 PHY commit strobe latch (`0x001548 = 0x80000101`) and excluded PMU clock domain `0x0c` from PLL switching (`RECLOCKING_NOTES.md` §8.3), unlocking full **43.2 GB/s** bandwidth (2.78× over boot clock).
- [x] **`v2.0.1` — S3 Suspend/Resume Self-Healing & Dynamic PCIe Gen1 ↔ Gen2 Scaling**:
  - Implemented `SCRATCH0 == 0xE1EC0001` handshake verification in `ramgf100.c` to detect cleared Falcon IMEM after S3 sleep and automatically cold-bootstrap without timeout (`RECLOCKING_NOTES.md` §8.4).
  - Verified automatic PCIe link speed switching between **Gen1 (`2.5 GT/s x16`)** in `03`/`07` and **Gen2 (`5.0 GT/s x16`, `8.0 GB/s`)** in `0f`/`10` (`0x02241c` / `0x088460` / `0x088088`).
- [x] **`v2.1.0` — Kernel `6.18.55` DRM Rebase, Live TTM VRAM Telemetry, Battery Cap & Initial VBlank Wait**:
  - Added `LINUX_VERSION_CODE`-guarded compatibility for the 1-argument `drm_client_dev_suspend()` / `drm_client_dev_resume()` API introduced in Linux `6.18.55` (`nouveau_display.c`).
  - Added exact in-kernel TTM VRAM accounting (`VRAM: <used> MiB / <total> MiB used` on debugfs `pstate`) and unprivileged `/run/nouveau/vram` snapshot for `nouveau-ctrl` and `nouveau-tui`.
  - Added `BATTERY_CAP=true` AC/DC power-supply awareness to `nouveau-dynclockd` (capping to `07` on battery, allowing `0f`/`10` on AC).
  - Added initial host-side `gf100_ram_wait_vblank()` (`NvFermiVblankSync=1`).
- [x] **Decompilation of `NVIDIA-Linux-x86_64-390.157` (`nv-kernel.o_binary` & `nv-modeset-kernel.o_binary`)**:
  - Solved the Fermi `PDAEMON` context-switch handshake (`_nv029647rm`), `OBJSEQ` opcode `0x3a` + `0x13d7f4` partition write-buffer flush (`_nv031754rm`), zero-flash `ISOHUB` + in-Falcon `WAIT_VBLANK` (`_nv031916rm`), `0x132004 = 0x10012702` P3 `650 MHz` formula (`_nv010738rm`), and 120 Hz 3D Vision eDP `8 bpc → 6 bpc` step-down (`_nv002219kms`). Documented in [`RECLOCKING_NOTES.md` §10](RECLOCKING_NOTES.md#10-concrete-reverse-engineering-findings-from-nvidia-390157-nv-modeset-kernelo_binary--nv-kernelo_binary).

---

## 🎯 Kernel & Hardware Subsystems Roadmap

### 1. Eliminating Screen Flashes During Clock Changes (True Zero-Flash VBlank Memory Reclocking)
*(Full hardware specification in [`RECLOCKING_NOTES.md` §10.4](RECLOCKING_NOTES.md#104-nv-kernelo_binary-the-rm-sequencer-objseq--seqscript--memx-bytecode-emitter-api--zero-flash-vblank-pipeline))*
- [ ] **Move `WAIT_VBLANK` Inside `memx_exec_custom.fuc` (`< 50 ns` Reaction Latency)**:
  - Host-side `gf100_ram_wait_vblank()` still suffers from host scheduling/MMIO latency after VBlank onset, pushing the ~150–250 µs `STOP_FB` window past the ~370 µs VBlank budget.
  - Poll the active CRTC's VBlank / raster status (`0x6160f8` / `0x616340`) directly inside the resident Falcon microcode immediately before asserting `STOP_FB` (`0x10a50c = 1` / `0x100c80 = 1`), matching `_nv031916rm` (opcode `0x14`).
- [ ] **Pre-`STOP_FB` Display `ISOHUB` Critical Watermark Spool-Up (`_nv031916rm` / `_nv031860rm`)**:
  - Boost `ISOHUB` (`0x616300+` / `0x610050`) watermarks to critical force-fill mode before `WAIT_VBLANK` so the display line buffer FIFO is 100% full before DRAM enters Self-Refresh, and restore normal watermarks after `RESTART_FB`.
- [ ] **FB Partition Write-Buffer Flush (`0x13d7f4 + (part << 6)`, `_nv031754rm` Opcode `0x3a`)**:
  - Emit the per-partition write-buffer drain after programming PHY DLL registers (`0x10f824`) and before releasing `STOP_FB`.
- [ ] **Pre-Warm Falcon Executor at Boot/Resume & Decouple PCIe Retraining**:
  - Run cold Falcon bootstrap during init/resume while display is blanked so runtime P-state changes always take the fast path, and schedule PCIe Gen1 ↔ Gen2 link retraining on a separate VBlank edge from MCLK switches.

### 2. Synthetic Intermediate Performance State (P3 / State `0a`)
*(Full derivation in [`RECLOCKING_NOTES.md` §10.5–§10.7](RECLOCKING_NOTES.md#105-nv-kernelo_binary-fermi-mclk--mempll-0x132000--0x132004-reclocking-state-machines))*
- [ ] **Inject Synthetic P3 State `0a` (`405 MHz` Core / `810 MHz` Shader / `650 MHz` DDR3 @ `0.920 V`)**:
  - **DDR3 `650 MHz` (`31.2 GB/s`) in `ramgf100.c` & `memx_exec_custom.fuc`**: Because `650 MHz` exceeds both the `405 MHz` and `500 MHz` thresholds in `_nv014883rm`, reuse the `900 MHz` VBIOS strap sequence with **`0x132004 = 0x10012702`** ($M=2, N=39, P=1$).
  - **Voltage Mapping (`VID 0x03`)**: Map P-state `0a` (`config=NvFermiP3=true`) to hardware VID `0x03` (`0.920 V`, ~18–22 W) in `nvkm_pstate_new()`.

### 3. 120 Hz 3D Vision eDP Display Pipeline & Stereoscopic 3D Support
*(Full decompilation in [`RECLOCKING_NOTES.md` §10.2](RECLOCKING_NOTES.md#102-nv-modeset-kernelo_binary-120-hz-3d-vision-edp-validation--automatic-dp-bpc-step-down))*
- [ ] **Automatic DP/eDP BPC Step-Down (`8 bpc` → `6 bpc`) & EDID `+5.0 MHz` Grace Margin**:
  - In `dispnv50` / `nouveau_connector.c`, automatically step down `bpc` from `8` (`24 bpp` = `9.51 Gbps > 8.64 Gbps` HBR1 limit) to **`6 bpc` (`18 bpp` = `7.13 Gbps <= 8.64 Gbps`)** with spatial/temporal dithering when `mode->clock * 24 > dp_link_bw` (matching `_nv002219kms`).
  - Grant the `+5.0 MHz` pixel-clock tolerance and ignore self-contradicting EDID range descriptors on 3D Vision panels (`LGD 0x02c5`, matching `_nv000659kms`).
  - Enforce a kernel-side minimum P-state floor of `07` (`dispclk = 405 MHz`) whenever active `pixel_clock > 135,000 kHz` (matching `_nv002187kms` IMP check).
- [ ] **Stereoscopic 3D (`NVIDIA 3D Vision`) Support (`LGD 0x02c5` + Internal USB IR Emitter `0955:0007`)**:
  - Trace EVO stereo head registers (`0x61xxxx`) in `nv-modeset-kernel.o_binary` and build a lightweight `nv3dvision-ir` helper synchronizing the built-in USB IR emitter (`0955:0007`) with `DRM_IOCTL_WAIT_VBLANK` at 120 Hz (`60 Hz` per eye) for `bino`, `mpv`, and quad-buffered stereo.

### 4. Fermi Engine Clock-Gating (BLCG / SLCG) & Hardware Load Counters (`0x10a600`)
*(Documented in [`RECLOCKING_NOTES.md` §10.3 & §10.8](RECLOCKING_NOTES.md#108-how-390157-handles-dynamic-reclocking-powermizer-vs-nouveau-dynclockd))*
- [ ] **Extract & Program Fermi BLCG / SLCG Clock-Gating Tables**:
  - Extract the static per-chip Block-Level and Second-Level Clock Gating tables from `.rodata` in `nv-kernel.o_binary` for `GF100`–`GF119` and program them during `gr`, `fb`, `copy`, and `therm` init to cut idle power by `2–4 W`.
- [ ] **Hardware GPU Engine Utilization Counters (`0x10a600..0x10a610`, `_nv029625rm` / `_nv029628rm`)**:
  - Decompile `_nv029625rm` (`0x515a70`) and `_nv029628rm` (`0x515ad0`) to extract the exact signal masks for `GR %`, `FB %`, and `VDEC %` busy counters in `PDAEMON` and expose them via debugfs/sysfs.

### 5. Single-Fan Shared Thermal Protection (`PTHERM`) & L2 / Z-Cull Compression
- [ ] **Hardware `PTHERM` Auto-Slowdown (`0x00020xxx`) & Progressive Multi-Step Thermal Throttling**:
  - Because the non-Optimus Dell XPS L702X cools both the Intel CPU and NVIDIA GT 555M with a **single shared blower fan**, program hardware `PTHERM` clock-slowdown failsafes at `90–92 °C` and implement progressive governor step-down (`10` → `0f` at `78 °C` → `0a` at `82 °C` → `07` at `86 °C`).
- [ ] **L2 Cache (`PLTCG` `0x140000`) & `PGRAPH` Z-Cull / Tile Compression Audit**:
  - Audit `nv-kernel.o_binary`'s initialization of `PLTCG` and `PGRAPH` Z-Cull / ROP compression registers against upstream Nouveau.

### 6. Hardware Quirk & Device Profile Database (`quirks.h`)
- [ ] **Unified `quirks.h` Subsystem Table**:
  - Map OEM Subsystem IDs (e.g., Dell `1028:04b7` for XPS L702X) to automatically apply panel quirks, display hub clock floors, and board-specific timings from community `tools/nouveau-fermi-diag.py` reports.

---

## ⚡ Falcon Microcode & Memory Controller Expansion

- [ ] **Generalize Falcon Executor Across All Fermi Chips (`GF100`–`GF119`)**:
  - Decouple GF106-specific DDR3 offsets in `ramgf100.c` using the per-family RM emitters (`_nv015935rm` GF100, `_nv015936rm` GF104/GF106, `_nv015937rm` GF108, `_nv015938rm` GF119) and partition unicast/broadcast mapper `[pFb + 0xd20]` (`_nv016234rm`) supporting 64-bit to 384-bit buses.
- [ ] **Fermi GDDR5 Timing & Training Engine (`_nv010721rm` / `_nv010722rm`)**:
  - Extract the GDDR5 branches of `_nv010721rm` (`0xec6b0`) and `_nv010722rm` (`0x104470`) to support GDDR5 Fermi cards (GT 555M GDDR5, GTX 460/470/480, GTX 560 Ti/570/580).

---

## 🔋 Dynamic Governor Modernization (`nouveau-dynclockd` 2.0)

- [ ] **Replace `/proc` CPU-Tick Scanning with Hardware GPU Load Counters (`0x10a600..0x10a610`)**:
  - Replace `get_monitored_app_ticks()` `/proc` scanning with a single `< 0.05 ms` read of hardware `GR %`, `FB %`, and `VDEC %` utilization counters.
- [ ] **120 Hz Display-Aware Idle Floor (`>= 07`)**:
  - Automatically clamp `IDLE_STATE` to `07` (`405 MHz` `dispclk`, `324 MHz` DDR3) when a `> 135 MHz` pixel-clock mode (120 Hz) is active, dropping to `03` only at 60 Hz or DPMS off.
- [ ] **5-Tier Scaling Ladder (`03` ↔ `07` ↔ `0a` ↔ `0f` ↔ `10`) with Hold-Down Timers**:
  - Scale across all 5 states based on hardware `GR`/`FB`/`VDEC` load with `5–8 s` PowerMizer-style hold-down timers so brief loading screens never trigger mid-game memory reclocks.
- [ ] **Manual Override Coordination (`/run/nouveau/mode`)**:
  - Coordinate `nouveau-ctrl set <pstate>` and `nouveau-tui` with `nouveau-dynclockd` via `/run/nouveau/mode` (`locked:<pstate>` vs `auto`) so manual locks are not overwritten on the next daemon poll while retaining thermal runaway protection.
- [ ] **Event-Driven Wakeups & Per-Application Profiles (`/etc/nouveau-dynclockd.d/`)**:
  - Support netlink/udev power-supply events and per-app P-state rules (Steam/Proton → `0f`/`10`, MPV/VLC → `07`/`0a`, OBS → `0a`/`0f`).

---

## 📊 Telemetry, Modern DRM/DRI APIs & Wayland Explicit Sync

- [ ] **Standard Linux DRM `drm_show_fdinfo` (`nvtop` / `btop` / `MangoHud` Support)**:
  - Wire `drm_driver.show_fdinfo` in `nouveau_drm.c` to export per-client `drm-memory-vram`, `drm-memory-gtt`, `drm-engine-gfx`, `drm-engine-dec`, and `drm-engine-dma`.
- [ ] **Unprivileged `sysfs` Telemetry (`gpu_busy_percent`, `mem_info_vram_used`, `mem_info_vram_total`)**:
  - Expose standard DRM `sysfs` attributes under `/sys/class/drm/card*/device/` so monitoring tools and `nouveau-ctrl`/`nouveau-tui` work without root or debugfs workarounds.
- [ ] **Real-Time ASCII Sparklines & Power Estimation ($P_{est}$) in `nouveau-tui` / `nouveau-ctrl watch`**:
  - Render 60-second scrolling sparklines (` ▂▃▄▅▆▇█`) and estimated Watt dissipation (`03`: ~4.2 W, `07`: ~8.5 W, `0a`: ~19.5 W, `0f`: ~38.0 W, `10`: ~46.5 W).
- [ ] **Wayland Explicit Sync (`linux-drm-syncobj-v1` / `drm_syncobj`) & Atomic Async Page-Flip (`DRM_MODE_PAGE_FLIP_ASYNC`)**:
  - Validate `drm_syncobj` timeline fences and enable atomic async page-flips on `dispnv50` (`wndw.c` / `head.c`) for tear-free 120 Hz Wayland pacing and unthrottled benchmarking.

---

## 🧠 Compute, Video Encoding, Vulkan & `nvzram`

- [ ] **OpenCL 3.0 (`Mesa Rusticl`), Unified `VRAM + GART` AI Inference & GPU-Compressed `nvzram` ([`VRAM_AI.md`](VRAM_AI.md))**:
  1. Unlock `~2.75 GiB` (`90%` of VRAM) single-buffer allocations in `nvc0` / `Rusticl` for `llama.cpp` and `CLBlast`.
  2. Implement Mode A (`TTM_PL_VRAM | TTM_PL_TT` transparent oversubscription + `PCOPY` layer prefetching) for `> 3 GiB` LLMs.
  3. Implement Mode B (`/dev/nvram0` `PCOPY1` DMA-backed upper-VRAM block device with automatic 3D/AI balloon eviction).
  4. Implement **`nvzram`** (`PCOPY0` batch DMA + `NVC0_COMPUTE` `SM20` Warp-LZ4 compression inside VRAM storing `~6.0–7.5 GiB` of compressed RAM in `2.5 GiB` VRAM, with `< 0.6 µs` compressed-DMA single-page `swapin`).
- [ ] **GPU Video Encoding (`VA-API` Hybrid Compute H.264 / `x264` OpenCL / `MSENC`) & `VP4` Decode ([`NVENC.md`](NVENC.md))**:
  1. Validate `x264 --opencl` lookahead via `Rusticl` in OBS Studio and FFmpeg.
  2. Build the 4-stage **Compute-Shader-Backed `VA-API` (`VAEntrypointEncSlice`) H.264 Encoder** (`DMA-BUF` `RGB → NV12` + SM parallel SAD/SATD ME + integer DCT/Quant + host CAVLC/CABAC packer) for OBS Studio (`obs-vaapi`) and FFmpeg (`h264_vaapi`).
  3. Ship `nouveau-extract-fw` to extract PureVideo HD `VP4` decode firmware (`nv98_fuc084/085/086`) from `390.157`.
  4. Reverse-engineer Kepler (`GK104+`) & Maxwell (`GM107+`) fixed-function `MSENC` (`0x1c8000`) for VA-API H.264 encoding.
- [ ] **Fermi Vulkan 1.0 / 1.1 (`nvk-fermi` Bound Descriptor Lowering — [`VULKAN.md`](VULKAN.md))**:
  - Prototype a `hasvk`-style bound-descriptor lowering pass (`128 TIC` / `32 TSC` slots per stage) pairing `NVK`'s command buffer/sync runtime with Mesa's `NIR → nv50_ir` (`TargetNVC0`) compiler backend.

---

## 🚀 Project Evolution: `nouveau-reclocking-dkms`, Multi-Kernel CI & Cross-Distro Packaging

Because upstream Linux's new Rust driver (`Nova`) exclusively supports Turing (`NV160+`) and newer GSP-based GPUs while upstream `nouveau` is in maintenance freeze for pre-Turing silicon, this project is evolving into **`nouveau-reclocking-dkms`**—an actively maintained out-of-tree DKMS driver and compute stack covering all **pre-`Nova` NVIDIA architectures**:

| Generation | Chip Families | GeForce Series | Firmware Security | `nouveau-reclocking-dkms` Target Roadmap |
| :--- | :--- | :--- | :---: | :--- |
| **Fermi** (`NVC0`–`NVCF`) | `GF100`–`GF119` | GeForce 400 / 500 / 600M–800M | **Unsigned Falcon** | ✅ **Working on GF106 (`v2.1.0`)!** Expand DDR3/GDDR5 tables, BLCG/SLCG, P3 (`0a`), and zero-flash VBlank to all `GF100`–`GF119` chips. |
| **Kepler** (`NVE0`–`NV108`) | `GK104`–`GK208` | GeForce 600 / 700 / 800M | **Unsigned Falcon** | Add automatic governor support, GPU Boost 1.0/2.0 interpolation, mobile `GK107M`/`GK208M` RAM fixes, and `MSENC` (`0x1c8000`) VA-API encode. |
| **Maxwell 1** (`NV117`–`NV118`) | `GM107`–`GM108` | GTX 750 / 750 Ti, GTX 850M–960M, MX110/MX130 | **Unsigned Falcon!** | **High-Value Target**: First-gen Maxwell has **no signed PMU lockdown** and is fully supported in `390.157`! Port custom Falcon PMU + PLL/RAM reclocking to `GM107`/`GM108`. |
| **Tesla** (`NV50`–`NVA8`) | `G80`–`GT218` | GeForce 8000 / 9000 / 200 / 300 | **Unsigned** | Stabilize `GT215`–`GT218` PDAEMON/host reclocking and integrate `nouveau-dynclockd`. |
| **Maxwell 2 & Pascal** (`NV120`–`NV138`) | `GM200`–`GP108` | GeForce GTX 900 & GTX 10-series | **HS RSA-Signed ACR/PMU** | Investigate extracting signed PMU/ACR images from official redistributables + unified governor and `fdinfo` telemetry. |

### Out-of-Tree Maintenance, Multi-Kernel CI & Cross-Distro Packaging Tasks
- [ ] **Centralized Multi-Kernel Compatibility Header (`nouveau_compat.h`)**:
  - Consolidate `LINUX_VERSION_CODE` API wrappers (such as the `6.18.55` `drm_client_dev_suspend` shim landed in `v2.1.0` and upcoming `6.19+` DRM/TTM shifts) into a dedicated `nouveau_compat.h` header so a single codebase compiles cleanly across `6.12 LTS`, `6.18 LTS`, and mainline kernels.
- [ ] **GitHub Actions Multi-Kernel DKMS CI Test Pipeline (`.github/workflows/ci-kernel-matrix.yml`)**:
  - Automated CI workflow triggered on push, PR, and weekly schedule that verifies patch application, compiles `nouveau.ko` against `linux-cachyos-lts`, `linux-cachyos`, Arch `linux`, and `linux-lts` headers, and runs `shellcheck` / `py_compile` on userspace scripts.
- [ ] **Package Rename / Transition (done: `nouveau-dkms`, was `nouveau-fermi-reclock-dkms`)**:
  - `PKGBUILD` carries `provides=('nouveau-fermi-reclock-dkms')`, `conflicts=('nouveau-fermi-reclock-dkms' 'nouveau-fermi-reclock-cachyos-lts-v2')`, `replaces=('nouveau-fermi-reclock-dkms')` so the old AUR package and prebuilt upgrade cleanly.
- [ ] **Cross-Distribution Packaging Pipeline (`.github/workflows/release-packages.yml`)**:
  1. **Arch Linux / AliveOS / CachyOS / Manjaro (`.pkg.tar.zst`)**: `PKGBUILD` + `.SRCINFO` + `pacman` hooks.
  2. **Debian / Ubuntu / Linux Mint / Pop!_OS (`.deb`)**: `debian/` packaging with `dh-dkms`, `dpkg-buildpackage`, and `update-initramfs -u` hooks.
  3. **Fedora / RHEL / Alma / Rocky / openSUSE (`.rpm`)**: `nouveau-reclocking-dkms.spec` with COPR & Open Build Service (`OBS`) automation and `dracut --force` hooks.
  4. **Gentoo (`sys-kernel/nouveau-reclocking-dkms` ebuild)** & **NixOS (`flake.nix` kernelModulePackage + NixOS service module)**.
  5. **Universal Distro-Agnostic `Makefile` (`sudo make dkms-install`)**: Fallback source installer for any Linux distribution.
