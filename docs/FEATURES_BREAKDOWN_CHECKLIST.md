# 🧭 Features Architectural Breakdown & Project Separation Checklist (`FEATURES_BREAKDOWN_CHECKLIST.md`)

This document outlines the architectural boundaries of all planned and in-flight features across the project. It classifies which components belong directly inside the **kernel driver (`nouveau.ko`)**, which must be maintained in **upstream user-space projects (e.g. Mesa)**, and which belong in a **companion user-space utilities suite**.

It also documents the distribution and maintenance strategy for upstream components when upstream acceptance is uncertain.

---

## Table of Contents
1. [Architectural Overview & Separation Blueprint](#1-architectural-overview--separation-blueprint)
2. [Category 1: Inside the Kernel Driver (`nouveau.ko` / `nouveau-reclocking-dkms`)](#2-category-1-inside-the-kernel-driver-nouveauko--nouveau-reclocking-dkms)
3. [Category 2: Upstream User-Space Projects (Mesa, Compilers, Runtimes)](#3-category-2-upstream-user-space-projects-mesa-compilers-runtimes)
4. [Category 3: Companion User-Space Utilities Suite (`nouveau-tools`)](#4-category-3-companion-user-space-utilities-suite-nouveau-tools)
5. [Upstream Strategy: Benefiting from Changes Without Upstream Approval](#5-upstream-strategy-benefiting-from-changes-without-upstream-approval)
6. [Master Implementation Checklist](#6-master-implementation-checklist)

---

## 1. Architectural Overview & Separation Blueprint

```mermaid
graph TD
    subgraph KERNEL["1. Kernel Driver Repository (nouveau-reclocking-dkms)"]
        K1["nouveau.ko (Out-of-Tree DKMS Driver)"]
        K2["Resident Falcon Microcode (memx_exec_custom.fuc)"]
        K3["Kernel Compatibility Shims (nouveau_compat.h)"]
        K4["VRAM Block Device /dev/nvram0 (Mode B Engine)"]
    end

    subgraph TOOLS["2. Companion Utilities Suite (nouveau-tools / bundled)"]
        T1["Dynamic Governor 2.0 (nouveau-dynclockd.py)"]
        T2["Management CLI & TUI (nouveau-ctrl & nouveau-tui)"]
        T3["3D Vision USB IR Emitter Daemon (nv3dvision-ir)"]
        T4["Firmware Extractor (nouveau-extract-fw)"]
    end

    subgraph MESA["3. User-Space Graphics & Compute (Mesa & Runtimes)"]
        M1["Mesa Rusticl: Raise CL_DEVICE_MAX_MEM_ALLOC_SIZE"]
        M2["Mesa Gallium VA-API: Hybrid Compute-Shader H.264 Encoder"]
        M3["Mesa NVK: Bound-Descriptor Vulkan for Fermi (nvk-fermi)"]
        M4["llama.cpp / CLBlast: Local SLM / LLM Inference"]
    end

    KERNEL <--> TOOLS
    KERNEL <--> MESA
```

---

## 2. Category 1: Inside the Kernel Driver (`nouveau.ko` / `nouveau-reclocking-dkms`)

These items require direct MMIO register access, hardware interrupt servicing, physical DRAM controller management, or kernel DRM subsystem hooks.

### 1. Reclocking & Clock State Management
- [x] **Bidirectional DDR3 Memory Reclocking (`324 MHz` ↔ `900 MHz`)**: Resident Falcon microcode executor (`memx_exec_custom.fuc`) via `SCRATCH2`/`SCRATCH3` mailboxes.
- [x] **S3 Suspend / Resume Self-Healing**: Hardware signature check (`SCRATCH0 == 0xE1EC0001`) and cold fallback path.
- [x] **Dynamic PCIe Gen1 (`2.5 GT/s`) ↔ Gen2 (`5.0 GT/s`) Link Retraining**: Automatic retraining via `0x02241c`, `0x088460`, and `0x088088`.
- [x] **P-State 10 Overclock (`700/1400/900 MHz @ 1.030 V`)**: Gated behind `config=NvFermiOC=true`.
- [ ] **True Zero-Flash VBlank Memory Reclocking**:
  - In-Falcon `WAIT_VBLANK` polling (opcode `0x14` / `_nv031916rm`).
  - Pre-`STOP_FB` display `ISOHUB` watermark spool-up (`0x610050+` / `_nv031860rm`).
  - Per-partition write-buffer flush (`0x13d7f4` / opcode `0x3a` / `_nv031754rm`).
- [ ] **Synthetic P3 State `0a` (`405/810/650 MHz @ 0.920 V`)**:
  - `0x132004 = 0x10012702` MEMPLL formula + VBIOS strap selection + VID `0x03` voltage mapping.
- [ ] **Pre-`Nova` Architecture Expansion**:
  - Tesla (`GT215`), Fermi (`GF100–GF119`), Kepler (`GK104–GK208`), and First-Gen Maxwell (`GM107`/`GM108` unsigned Falcon).

### 2. Display Engine & Modesetting (`dispnv50`)
- [ ] **120 Hz eDP DP Link Validation & Auto BPC Step-Down**:
  - Connector atomic check stepping down `8 bpc` (`24 bpp` = 9.51 Gbps) → **`6 bpc` (`18 bpp` = 7.13 Gbps)** with hardware dithering to fit 4-lane HBR1 (8.64 Gbps max).
- [ ] **EDID `+5.0 MHz` Grace Margin & Stereo Quirk**:
  - Bypass conflicting EDID range caps on 3D Vision panels (`LGD 0x02c5`).
- [ ] **Active 120 Hz P-State Floor**:
  - Kernel-side clamp locking `dispclk >= 405 MHz` when `pixel_clock > 135 MHz`.
- [ ] **Atomic KMS Async Page-Flip (`DRM_MODE_PAGE_FLIP_ASYNC`)**:
  - Allow low-latency presentation in games above 120 FPS.

### 3. Hardware Telemetry & Thermal Protection
- [x] **In-Kernel TTM VRAM Accounting**: Exact `VRAM: <used> MiB / <total> MiB used` in debugfs `pstate`.
- [ ] **PDAEMON Hardware Engine Utilization Counters**:
  - Configure signal filters in `0x10a600..0x10a610` to measure true hardware `GR %`, `FB %`, and `VDEC %` load.
- [ ] **Standard DRM `fdinfo` (`drm_show_fdinfo`)**:
  - Expose per-process engine and VRAM usage for `nvtop`, `btop`, and `MangoHud`.
- [ ] **Unprivileged sysfs Telemetry**:
  - Expose `gpu_busy_percent` and `mem_info_vram_*` under `/sys/class/drm/card*/device/`.
- [ ] **Hardware `PTHERM` Auto-Slowdown**:
  - Configure hardware thermal clock dividers at `90–92 °C` as an unkillable safety floor.

### 4. Memory Subsystem Extensions
- [ ] **Mode A (Kernel Layer)**:
  - Transparent `TTM_PL_VRAM | TTM_PL_TT` oversubscription fallback in `nouveau_bo.c` and 40-bit UVMM address mapping for `> 3 GiB` models.
- [ ] **Mode B (`/dev/nvram0`)**:
  - `PCOPY` DMA-backed `blk-mq` block device driver exposing upper VRAM with dynamic balloon eviction.

### 5. Out-of-Tree Maintenance Infrastructure
- [x] **Kernel 6.18.55 Rebase Compatibility**: Version-guarded `drm_client_dev_suspend/resume`.
- [ ] **Multi-Kernel Compatibility Header (`nouveau_compat.h`)**: Centralize kernel API compatibility wrappers.
- [ ] **Multi-Kernel GitHub Actions CI Matrix**: Automated compile checks across CachyOS, Arch, and LTS kernels.

---

## 3. Category 2: Upstream User-Space Projects (Mesa, Compilers, Runtimes)

These components live above the kernel interface. They compile against user-space graphics APIs and cannot be included directly in `nouveau.ko`.

### 1. Mesa Gallium (`nvc0` / Rusticl / VA-API)
- [ ] **Mesa Rusticl: Raise `CL_DEVICE_MAX_MEM_ALLOC_SIZE`**:
  - **Location**: `src/gallium/drivers/nouveau/nvc0/` in Mesa.
  - **Action**: Raise single buffer allocation cap from 25% of VRAM (`768 MiB`) to **90% of VRAM (`~2.75 GiB`)** so `llama.cpp` and `CLBlast` can load weights into contiguous buffers.
- [ ] **Mesa Gallium VA-API: Hybrid Compute-Shader H.264 Encoder**:
  - **Location**: `src/gallium/frontends/va/` and `src/gallium/drivers/nouveau/nvc0/`.
  - **Action**: Implement `pipe_video_codec` with `VAEntrypointEncSlice` running color conversion, parallel SAD/SATD motion estimation, and integer DCT on Fermi SMs (`NVC0_COMPUTE`), outputting to standard OBS Studio (`obs-vaapi`) and FFmpeg.
- [ ] **Mesa Gallium VA-API: Kepler/Maxwell Fixed-Function `MSENC` (`0x1c8000`)**:
  - **Location**: `src/gallium/drivers/nouveau/nve4/` and `nv50/`.
  - **Action**: Expose hardware `NVENC` via VA-API on Kepler (`GK104+`) and Maxwell (`GM107+`).

### 2. Mesa Vulkan (`NVK` / `nvk-fermi`)
- [ ] **Vulkan 1.0/1.1 Bound-Descriptor Lowering (`nvk-fermi`)**:
  - **Location**: `src/nouveau/vulkan/` in Mesa.
  - **Action**: Implement `hasvk`-style bound-descriptor lowering (mapping Vulkan descriptor sets into Fermi's 128 `TIC` / 32 `TSC` binding tables) over Mesa's `NIR → nv50_ir` compiler backend.

### 3. Application Runtimes & Inference Engines
- [ ] **`llama.cpp` / `CLBlast` OpenCL Acceleration**:
  - Build and tune `llama.cpp` with `-DGGML_OPENCL=ON` for Small Language Models (SLMs) on Fermi.

---

## 4. Category 3: Companion User-Space Utilities Suite (`nouveau-tools`)

These tools reside in user space. They can be distributed alongside the DKMS package initially, but architecturally form a standalone management suite:

### 1. Daemon & Power Management
- [x] **`nouveau-dynclockd.py` (Dynamic Governor)**:
  - Two-stage scaling (`03` ↔ `07` for 2D, `0f`/`10` for 3D), thermal protection (`80 °C`), and battery profile cap (`BATTERY_CAP=true`).
- [ ] **`nouveau-dynclockd` 2.0 Modernization**:
  - Hardware counter sampling (`0x10a600`), 120 Hz idle floor (`>= 07`), 5-tier scaling ladder (`03` ↔ `07` ↔ `0a` ↔ `0f` ↔ `10`), and hold-down timers.
  - Coordination with manual mode overrides via `/run/nouveau/mode`.

### 2. Management & Diagnostics
- [x] **`nouveau-ctrl`**: Scriptable CLI for P-state locking, telemetry queries, and governor control.
- [x] **`nouveau-tui`**: Interactive curses terminal interface with thermal indicators and real-time monitoring.
- [x] **`tools/nouveau-fermi-diag.py`**: Standalone hardware diagnostic and VBIOS register dumper.
- [ ] **Real-Time ASCII Sparkline History**: 60-second activity sparklines in `nouveau-tui` and `nouveau-ctrl watch`.

### 3. Standalone Daemons & Firmware Helpers
- [ ] **`nv3dvision-ir` (3D Vision USB IR Emitter Daemon)**:
  - Lightweight `libusb` daemon communicating with the internal USB IR emitter (`0955:0007`) to synchronize active-shutter glasses with DRM VBlank.
- [ ] **`nouveau-extract-fw` (Firmware Extractor)**:
  - Standalone script extracting `VP4` video decode and `MSENC` firmware from `NVIDIA-Linux-x86_64-390.157.run` into `/lib/firmware/nouveau/`.

---

## 5. Upstream Strategy: Benefiting from Changes Without Upstream Approval

Because upstream projects (like Mesa) may reject or deprioritize legacy hardware patches, use the following distribution strategy:

### Strategy A: AliveOS / Downstream Custom Mesa Package (Recommended)
Maintain a downstream package in your repository (`aliveos-repo`):
1. **Package Name**: `mesa-nouveau-enhanced` or custom patch hook in your standard `mesa` package.
2. **Implementation**: Keep a `patches/` folder in your packaging repo with your targeted patches:
   - `0001-nvc0-rusticl-max-alloc-increase.patch`
   - `0002-nvc0-vaapi-hybrid-compute-h264.patch`
3. **Build**: The PKGBUILD pulls the official Mesa release tag, applies the patchset, and compiles. Your system and AliveOS users automatically receive the capabilities via standard package updates.

### Strategy B: Overlay Library Path (Isolated Testing Without Replacing System Mesa)
Compile custom Mesa components into an isolated prefix (e.g. `/opt/nouveau-enhanced/`):
- **For VA-API**: `LIBVA_DRIVERS_PATH=/opt/nouveau-enhanced/lib/dri vainfo`
- **For Vulkan**: `VK_ICD_FILENAMES=/opt/nouveau-enhanced/share/vulkan/icd.d/nouveau_icd.x86_64.json vkcube`
- **For OpenCL**: Place custom ICD JSON in `/etc/OpenCL/vendors/`.

### Strategy C: Submit Upstream Draft / RFC Merge Request Anyway
Always open a draft Merge Request on Mesa GitLab (`gitlab.freedesktop.org/mesa/mesa`):
- Gives public visibility and triggers automated CI regression tests.
- Connects you with upstream developers who maintain `nv50_ir` and Gallium video frontends.
- If rejected or stalled, the branch remains public and easy for anyone to cherry-pick.

---

## 6. Master Implementation Checklist

### Repository 1: `nouveau-reclocking-dkms` (Kernel Module)
- [x] Core / Shader / Voltage reclocking + factory 1.030 V fix
- [x] Bidirectional DDR3 memory reclocking (`324 MHz` ↔ `900 MHz`) via resident Falcon executor
- [x] S3 suspend/resume self-healing recovery (`0xE1EC0001`)
- [x] Dynamic PCIe Gen1 ↔ Gen2 link speed retraining
- [x] Verified State 10 Overclock (`700/1400/900 MHz`, `403.2 GFLOPS`)
- [x] Linux 6.18.55 DRM client API rebase
- [x] In-kernel TTM VRAM usage accounting
- [ ] In-Falcon `WAIT_VBLANK` + `ISOHUB` watermark spooling (True Zero-Flash VBlank)
- [ ] Synthetic P3 state `0a` (`405/810/650 MHz @ 0.920 V`, `0x132004 = 0x10012702`)
- [ ] 120 Hz eDP `8 bpc → 6 bpc` step-down & `+5.0 MHz` EDID grace margin
- [ ] PDAEMON hardware load counters (`0x10a600..0x10a610`)
- [ ] DRM `drm_show_fdinfo` support (`nvtop`/`btop`)
- [ ] Unprivileged sysfs load and VRAM attributes
- [ ] Multi-kernel compatibility header (`nouveau_compat.h`) & GitHub Actions CI matrix
- [ ] Pre-`Nova` architecture expansion (Tesla, Kepler, Maxwell 1 `GM107`/`GM108`)
- [ ] Mode A (Unified `VRAM + GART` oversubscription)
- [ ] Mode B (`/dev/nvram0` `PCOPY` DMA block device)

### Repository 2: `nouveau-tools` (User-Space Management Suite)
- [x] `nouveau-ctrl` CLI status, clock locking, and watcher
- [x] `nouveau-tui` curses interface with thermal coloring and fan RPM
- [x] `nouveau-dynclockd` basic governor (2D/3D load scaling, thermal throttle, battery cap)
- [ ] `nouveau-dynclockd` 2.0 (hardware counters, 120 Hz idle floor, 5-tier ladder, hold timers)
- [ ] Governor mode lock coordination via `/run/nouveau/mode`
- [ ] `nv3dvision-ir` USB emitter synchronization daemon (`0955:0007`)
- [ ] `nouveau-extract-fw` PureVideo HD / MSENC firmware extraction script
- [ ] Cross-distribution release packaging (`.deb`, `.rpm`, Gentoo, NixOS, Makefile)

### External Project: Mesa Enhancements (Downstream `aliveos-repo` Package / RFC MR)
- [ ] Mesa `Rusticl`: Raise `CL_DEVICE_MAX_MEM_ALLOC_SIZE` to 90% VRAM (`~2.75 GiB`) on `nvc0`
- [ ] Mesa Gallium VA-API: 4-stage Hybrid Compute-Shader H.264 Encoder for OBS Studio / FFmpeg
- [ ] Mesa Gallium VA-API: Kepler/Maxwell fixed-function `MSENC` (`0x1c8000`)
- [ ] Mesa Vulkan: Fermi bound-descriptor lowering (`nvk-fermi`)
