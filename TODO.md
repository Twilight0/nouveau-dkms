# 📋 Roadmap & TODO

This document tracks completed milestones, planned features, architectural improvements, and pending tasks for the **Nouveau Fermi Reclocking & 120Hz Driver** project.

---

## ✅ Completed Milestones

- [x] **v1.0 Baseline Fermi Core & Shader Reclocking**:
  - Implemented stable core and shader clock scaling (`50 MHz` / `202 MHz` / `590 MHz` core; `101 MHz` / `405 MHz` / `1180 MHz` shader).
  - Unlocked 120 Hz eDP display mode (`1920x1080 @ 120Hz`, pixel clock `396.36 MHz`). *(Note: Visual screen flashes during P-state / MCLK transitions remain open and are tracked in §1 below.)*
- [x] **v1.1 Voltage Table & Overclocking Fixes**:
  - Resolved `0f` undervolting bug (`870 mV` vs factory `1030 mV`) by enforcing authoritative voltage table mapping.
  - Added synthetic `0x10` OC P-State (`700 MHz` core / `1400 MHz` shader @ `1030 mV`), gated by the `NvFermiOC` module parameter.
- [x] **v1.2 Telemetry & Dynamic Governor**:
  - Created standalone CLI management utility [`nouveau-ctrl`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/nouveau-ctrl) and curses dashboard [`nouveau-tui`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/nouveau-tui).
  - Built background daemon [`nouveau-dynclockd`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/nouveau-dynclockd.py) with two-stage load scaling and thermal hysteresis protection.
- [x] **v2.0.0 Major Milestone — Full Bidirectional DDR3 Memory Reclocking**:
  - Developed custom resident Falcon microcode executor running directly on GPU PMU (`0x10a000` / `0x10a1c0`).
  - Achieved rock-solid bidirectional memory transitions between `324 MHz` (648 MT/s) and `900 MHz` (1800 MT/s) with locked DLL phase and strobe timings.
  - Packaged for DKMS and pre-built distribution in AliveOS repository.
- [x] **v2.0.1 S3 Suspend/Resume Self-Healing Recovery**:
  - Resolved GPU clock freeze at P-State `07` (202 MHz core / 324 MHz mem) after exiting S3 system sleep.
  - Implemented hardware handshake signature check (`SCRATCH0 == 0xE1EC0001`) to detect cleared PMU IMEM on resume and fall back to cold path without timeout.
  - Added subdev state reset in `gf100_ram_init()` and automatic timeout recovery.
- [x] **Dynamic PCIe Link Speed Scaling (Gen1 2.5 GT/s $\leftrightarrow$ Gen2 5.0 GT/s) Verified**:
  - Confirmed active on hardware: PCIe link operates at `2.5 GT/s x16` (Gen1) in P12/P8 (`03`/`07`), and dynamically retrains to `5.0 GT/s x16` (Gen2) upon entering P0 (`0f`) or OC (`10`).
  - Delivers full 8.0 GB/s per direction (16.0 GB/s aggregate) DMA throughput without Sandy Bridge root complex timeouts.
- [x] **State `10` Overclock Verification (`700 MHz` Core / `1400 MHz` Shader / `900 MHz` DDR3 @ `1.030 V`)**:
  - Verified rock-solid stability of the synthetic P-State `10` enabled via `NvFermiOC=true`.
  - Delivers +18.6% raw ALU compute scaling (340 $\to$ 403 GFLOPS FP32) without exceeding factory voltage rail.

---

## 🔬 Architectural Findings & Hardware Deep-Dive

### 🏎️ Why the Proprietary NVIDIA Driver Achieved High Performance
Historically, the proprietary NVIDIA driver (`390.157`) ran circles around open-source Nouveau on Fermi hardware. Our reverse-engineering and hardware telemetry reveal that this performance gap stems from four core hardware orchestrations:

1. **PCIe Gen2 Throughput & Zero-Latency ASPM Switching**:
   - **Bandwidth Doubling**: Dynamically scaling from Gen1 (`2.5 GT/s x16` = 4.0 GB/s) to Gen2 (`5.0 GT/s x16` = 8.0 GB/s per direction) doubles DMA bandwidth for vertex streams, high-resolution textures, and pushbuffer ring submissions.
   - **Eliminating L1 Exit Stutter**: ASPM L1 saves ~2W at idle, but exiting L1 introduces **16–32 µs of latency**. The proprietary blob proactively de-asserts ASPM and forces Gen2 before dispatching rendering bursts, preventing frame drops.
2. **The Memory Bandwidth Equation (2.78× Jump)**:
   - On a 192-bit DDR3 bus, running at `324 MHz` yields only **~15.5 GB/s**. Scanning out 1080p @ 120Hz constantly consumes **~1.9 GB/s** just for panel refresh, starving the 3D pipeline.
   - Running at `900 MHz` unlocks **43.2 GB/s**—a **2.78× increase** that enables fluid 120 FPS rendering.
3. **The 2× Shader "Hot Clock"**:
   - Fermi Streaming Multiprocessors (SM) employ dual-issue superscalar ALUs running on a dedicated hot clock domain at **exact 2× core frequency** (`590 MHz` core $\to$ `1180 MHz` shader).
   - Stock Nouveau left the shader domain dormant or unexposed, halving compute and vertex throughput.
4. **Hardware Tiling & Lossless Z-Cull Compression**:
   - The proprietary blob programs the memory controller (PFB) and rasterizer (PGRAPH) with optimized tiling patterns and Z-Cull compression, effectively multiplying effective DDR3 memory bandwidth during depth and stencil tests.

---

## 🎯 Kernel & Hardware Subsystems Roadmap

### 1. Eliminating Screen Flashes During Clock Changes (True VBlank-Synchronized Memory Reclocking)
- [ ] **Zero-Flash VBlank & ISOHUB Synchronized Memory Reclocking** *(Unresolved — host-side `gf100_ram_wait_vblank()` still exhibits visible screen flashes during P-state transitions)*:
  - **Why Screen Flashes Still Occur in Our Current Implementation**:
    1. **Host-Side VBlank Polling Latency**: Currently, `gf100_ram_wait_vblank()` polls `0x6160f8` on the **host CPU** before invoking `gf100_ram_exec_custom()`. Any host scheduling delay, MMIO setup, or cold Falcon bootstrap happens *after* VBlank onset, causing the Falcon's `STOP_FB` (`0x100c80` / `0x10a50c`) and DDR3 Self-Refresh window (~150–250 µs) to spill out of the ~370 µs vertical blanking interval into active scanout!
    2. **Missing Display ISOHUB FIFO Pre-Fill / Spool-Up**: Without boosting the display `ISOHUB` (`0x616300+`) watermarks to critical force-fill mode right before `STOP_FB`, the display scanout FIFO drains during the memory freeze, causing a visible horizontal flash/glitch line.
    3. **Overlapping PCIe Gen1 $\leftrightarrow$ Gen2 Retraining**: Performing PCIe link retraining (`50–200 µs` bus stall) back-to-back with MCLK switching in `nvkm_pstate_prog()` stretches total bus unavailability beyond a single VBlank window.
  - **How `390.157` Eliminates Flashes (`_nv031916rm` @ `0x5316a0`, `_nv031860rm` @ `0x531b60`, `_nv031861rm` @ `0x531dd0`, `_nv031754rm` @ `0x531560`)**:
    1. **Pre-`STOP_FB` ISOHUB Critical Watermark Boost (`_nv031916rm` @ `0x5317d4`)**:
       - Calls `pIsohub->vtable[0xd8]` with state `0x12` before waiting for VBlank, forcing the display `ISOHUB` (`0x6163xx`) to top up the scanout line buffer FIFO to 100% capacity during the last active scanlines of the frame.
    2. **Falcon-Side In-Script VBlank Wait (`_nv031831rm` @ `0x532470`, Opcode `0x14` / `_nv031872rm` @ `0x52ff50`, Opcode `0x43`)**:
       - Rather than waiting on the host CPU, RM emits **`WAIT_VBLANK` (opcode `0x14`) directly inside the PMU Falcon script** immediately prior to **`STOP_FB` (opcode `0x20`, `_nv031828rm` @ `0x5323e0`)**.
       - The Falcon microcontroller itself polls the display head VBlank / DMI blanking signal in hardware and asserts `STOP_FB` on the **very next Falcon clock cycle (<50 ns latency)** after VBlank begins!
    3. **FB Partition Write-Buffer Flush (`_nv031754rm` @ `0x531560`, Opcode `0x3a`)**:
       - After programming the PHY DLL/training registers (`0x10f590..0x10f8ff`), RM writes `0x0` to `0x13d7f4 + (part << 6)` to flush the partition write buffers and executes opcode `0x3a` before unfreezing FB.
    4. **Post-`RESTART_FB` ISOHUB Restoration & PTIMER Verification (`_nv031860rm` @ `0x531b60` & `_nv031861rm` @ `0x531dd0`)**:
       - `_nv031860rm` unfreezes FB (`_nv031887rm(pSeqScript, 0)`), records the end PTIMER timestamp (`opcode 0x24/0x25` into `[pSeqScript + 0xa4]`), and restores normal ISOHUB watermarks (`pIsohub->vtable[0xd8]`).
       - `_nv031861rm` computes `elapsed_us = (end_ns - start_ns + 500) / 1000` (`mul $0x10624dd3; shr $0x6`) and verifies that the entire `STOP_FB` $\to$ `RESTART_FB` window completed strictly inside the head's DMI blanking budget (`[pSeqScript + 0xa8]`).
  - **Actionable Implementation Plan for `nouveau-fermi-reclock`**:
    1. **Move VBlank Polling Inside `memx_exec_custom.fuc`**: Have the resident Falcon microcode poll the active CRTC's VBlank / raster line register (`0x6160f8` via PDAEMON I/O or host-mapped aperture) *inside* the Falcon right before writing `0x10a50c = 0x1` / `0x100c80 = 0x1` (`STOP_FB`), eliminating all host-to-PMU latency.
    2. **Pre-Warm the Falcon Executor at Boot & Resume**: Ensure the cold bootstrap (`gf100_ram_exec_custom` cold path) runs during init/resume while the display is blanked or before switching, so runtime P-state transitions **always** take the zero-upload fast path (`SCRATCH` trigger).
    3. **Program ISOHUB (`0x6163xx`) Pre-Fill & Partition Flush (`0x13d7f4`)**: Emit the ISOHUB critical watermark boost before `STOP_FB`, the `0x13d7f4 + (part << 6)` flush after `0x10f824`, and ISOHUB watermark restoration after `RESTART_FB`.
    4. **Decouple PCIe Link Retraining from MCLK VBlank**: Wait for a separate VBlank edge before executing PCIe Gen1 $\leftrightarrow$ Gen2 link retraining so PCIe retraining never steals time from the MCLK `STOP_FB` VBlank budget.


### 2. Dynamic PCIe Link Speed Scaling (Gen1 $\leftrightarrow$ Gen2)
- [x] **Automatic Gen1 (2.5 GT/s) $\leftrightarrow$ Gen2 (5.0 GT/s) Switching (Verified & Operational)**:
  - **Status**: Verified active on hardware.
  - **Observed Behavior**:
    - **P12 (`03` idle)**: Retrains to `2.5 GT/s x16` (Gen1) + ASPM L0s/L1 enabled for deep system C-state package residency (~4.2W package power).
    - **P8 (`07` 2D desktop)**: Stays at `2.5 GT/s x16` (Gen1) (~8.5W).
    - **P0 (`0f` 3D) & OC (`10`)**: Automatically retrains to `5.0 GT/s x16` (Gen2) for maximum DMA throughput (8.0 GB/s per direction / 16.0 GB/s aggregate).
  - **Hardware Register Mechanics**:
    - **PUNIT Capability Register (`0x02241c`)**:
      - Bit 0 (`0x01`): PCIe Specification Version (`0` = Gen1 1.1, `1` = Gen2 2.0). Managed by [`gf100_pcie_set_version()`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/nouveau-source/nvkm/subdev/pci/gf100.c).
      - Bit 7 (`0x80`): Capability Speed Advertisement (`1` = advertise 5.0 GT/s, `0` = limit to 2.5 GT/s). Managed by [`gf100_pcie_set_cap_speed()`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/nouveau-source/nvkm/subdev/pci/gf100.c).
    - **NVIDIA Extended Config Register `0x460` (MMIO `0x088460`)**:
      - Bits `[5:4]` (`0x30`): Target Link Speed (`0x10` = Gen1 2.5 GT/s, `0x20` = Gen2 5.0 GT/s).
      - Bit 0 (`0x01`): `LINK_RETRAIN` hardware trigger. Initiates LTSSM retraining via TS1/TS2 ordered sets. Managed by [`g84_pcie_set_link_speed()`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/nouveau-source/nvkm/subdev/pci/g84.c).
    - **PCIe Link Status Register `0x88` (MMIO `0x088088` — `PCI_EXP_LNKSTA`)**:
      - Bits `[19:16]` (`0x30000`): Current Negotiated Speed (`0x10000` = 2.5 GT/s, `0x20000` = 5.0 GT/s).
      - Bit 11 (`0x0800`): Retraining In-Flight indicator.
  - **Implementation Steps**:
    1. **P-State Mapping**: In [`nvkm_pstate_new()`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/nouveau-source/nvkm/subdev/clk/base.c), map `03`/`07` $\to$ `NVKM_PCIE_SPEED_2_5` and `0f`/`10` $\to$ `NVKM_PCIE_SPEED_5_0` instead of relying on conservative VBIOS byte quirks.
    2. **ASPM Sequencing**: Temporarily de-assert ASPM L1 on the upstream Sandy Bridge Root Port (`0000:00:01.0`) prior to retraining to avoid link-state race conditions.
    3. **Link Speed Trigger**: Program PUNIT `0x02241c |= 0x81`, configure target speed in `0x460`, and fire `LINK_RETRAIN`. Poll `0x88` until retraining clears.
    4. **VBlank Alignment**: Schedule retraining during CRTC vertical front porch to protect 120Hz display FIFO from the 50–200 µs bus stall.
    5. **Idle Power Savings**: Re-enable ASPM L0s/L1 on dropping back to `03` (Gen1) to allow CPU/PCH package to enter C6/C7 sleep, saving ~1.5W–2.0W on battery.

### 3. Hardware Quirk & Device Profile Table
- [ ] **Unified `quirks.h` Database**:
  - Map Subsystem Vendor and Device IDs (e.g. Dell `1028:04b7` for XPS L702X).
  - Automatically configure high-refresh panel constraints (120Hz / 144Hz eDP), minimum display hub clocks (`nv_clk_src_dom6`), and chipset-specific memory timings.
  - Ingest community diagnostic dumps submitted via `tools/nouveau-fermi-diag.py`.

### 4. Synthetic Intermediate Performance State (P3 / State `0a`)
- [ ] **Synthetic P3 State Implementation (`405 MHz` Core / `810 MHz` Shader / `650 MHz` DDR3 @ `0.920 V`)**:
  - **Assigned P-State**: **`0a`** (PowerMizer **P3** — Balanced 3D / Multimedia / Video Playback).
    - Positioned naturally in hex and performance order: `03` (P12) $\to$ `07` (P8) $\to$ **`0a` (P3)** $\to$ `0f` (P0) $\to$ `10` (OC).
  - **Hardware Profile & Operating Specifications**:
    - **Core Frequency**: `405 MHz` (exact midpoint between 202 MHz 2D and 590 MHz 3D).
    - **Shader Hot Clock**: `810 MHz` (strict 2× Fermi core multiplier).
    - **Memory Clock**: `648–650 MHz` (`1300 MT/s` DDR3, yielding **~31.2 GB/s** bandwidth on the 192-bit bus).
    - **Voltage Rail**: `0.920 V` (activates the unmapped silicon hardware VID step `0x03` on the GPU voltage regulator).
    - **PCIe Link Speed**: Gen1 `2.5 GT/s x16` or Gen2 `5.0 GT/s x16`.
    - **Estimated Power Consumption**: ~18–22 W (bridging the gap between ~8.5 W 2D desktop and ~38 W full 3D).
  - **Reverse-Engineered Hardware Specifications (`nv-kernel.o_binary` §10.5–§10.7)**:
    1. **Exact `0x132004` (`MEMPLL_COEFF`) Derivation (`_nv010738rm` @ `0x10afb0` & `_nv010721rm` @ `0xec6b0`)**:
       - RM constructs `0x132004` as `0x10010000 | (N << 8) | M`, where bit 16 (`0x00010000`) is $P = 1$ and bit 28 (`0x10000000`) enables the PLL lock-detector/SDM block.
       - At `900 MHz` (`0f`): $M = 2, N = 54 \ (\text{0x36}), P = 1 \implies \mathbf{0x10013602}$.
       - At **`650 MHz` (`0a`)**: $M = 2, N = 39 \ (\text{0x27}), P = 1 \implies \mathbf{0x10012702}$ (retains the exact same $M = 2$ reference divider and loop-filter phase margin as `900 MHz`).
    2. **VBIOS DDR3 Timing & Mode Register Selection (`_nv014883rm` @ `0x2ec720` & `_nv014880rm` @ `0x2ed5b0`)**:
       - Disassembly of `_nv014883rm` proves RM does not synthesize arbitrary polynomial JEDEC timings; instead, `_nv015366rm` (`0x2ec530`) selects the VBIOS Memory Clock Table entry covering the requested frequency (`325–1000 MHz` strap entry) and checks two frequency thresholds:
         - `targetFreq > 405,000 kHz` (`0x62e08` in `_nv010721rm` @ `0xee660`): uses full `MEMPLL` path (`0x137360 = 0x00020200`) and DDR3 DLL-On (`MR1` bit 0 = `0`).
         - `targetFreq > 500,000 kHz` (`0x7a120` in `_nv014883rm` @ `0x2eccdc`): applies the high-frequency turnaround/ODT adjustment to `0x10f29c` (`TIMING_3`).
       - Because `650 MHz` (`650,000 kHz`) lies above both `405 MHz` and `500 MHz`, RM uses the **exact `900 MHz` VBIOS strap table** for `0x10f290–0x10f2a0` (JEDEC timings), `0x10f300–0x10f308` (`MR0/MR1/MR2` with `CL=13, CWL=9`), `0x10f440–0x10f468` (`_nv015894rm` impedance/drive strength), and `0x10f808–0x10f824` (PHY DLL), which is strictly conservative at `650 MHz`.
       - **Result**: The `650 MHz` DDR3 transition script is identical to the battle-tested `900 MHz` table with **only `0x132004` changed from `0x10013602` to `0x10012702`**!
  - **Required Engineering Tasks**:
    1. **DDR3 650 MHz Register Sequence in [`ramgf100.c`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/nouveau-source/nvkm/subdev/fb/ramgf100.c)**:
       - Add the `648000` / `650000 kHz` branch in `gf100_ram_calc()` using the 900 MHz strap register sequence with `0x132004 = 0x10012702`.
    2. **Falcon Microcode Executor (`memx_exec_custom.fuc`)**:
       - Add `cmd = 3` (`650 MHz` target) or pass the target `0x132004` `MEMPLL_COEFF` word via `SCRATCH` / DMEM parameter block so the resident Falcon image handles `324 MHz`, `650 MHz`, and `900 MHz` without needing additional IMEM code size.
    3. **Kernel P-State Injection (`nvkm_pstate_new()`) & VID `0x03` (`0.920 V`)**:
       - Inject synthetic P-State `0a` (`core = 405 MHz`, `shader = 810 MHz`, `memory = 650 MHz`, `hub07 = 405 MHz`, `hub06 = 270 MHz`, `hub01 = 405 MHz`, `rop = 405 MHz`, `vdec = 405 MHz`) between `07` and `0f`, gated via module parameter `config=NvFermiP3=true`.
       - Map the voltage rail to VID `0x03` (`0.920 V`) in the GF106 voltage table.
    4. **Governor Integration (`nouveau-dynclockd`) & Telemetry (`nouveau-ctrl` / `nouveau-tui`)**:
       - Extend the dynamic frequency governor to a 3-tier scaling ladder (`07` $\leftrightarrow$ `0a` $\leftrightarrow$ `0f`/`10`) with hysteresis deadbands, and register `"0a": "P3  Balanced 3D / Multimedia"` in `PSTATE_LABELS`.

### 5. 120 Hz 3D Vision eDP Display Pipeline & Stereoscopic 3D Support
- [ ] **120 Hz eDP Link Validation, Auto-BPC Step-Down & Display Clock Floor (`nv-modeset-kernel.o_binary` §10.2)**:
  - **Root Cause Uncovered via REA**:
    - On the Dell XPS L702X (`LGD 0x02c5`, `1920x1080 @ 120 Hz`, pixel clock `396.36 MHz`, 4-lane HBR1 `2.7 Gbps` eDP link with `8.64 Gbps` max payload bandwidth):
      - At **8 bpc (`24 bpp`)**, required bandwidth is $396.36\text{ MHz} \times 24 = \mathbf{9.51\text{ Gbps}} > 8.64\text{ Gbps}$ (**Exceeds HBR1 link capacity**).
      - At **6 bpc (`18 bpp`)**, required bandwidth is $396.36\text{ MHz} \times 18 = \mathbf{7.13\text{ Gbps}} \le 8.64\text{ Gbps}$ (**Fits within HBR1 link capacity**).
    - Decompilation of `_nv002185kms` (`0x2095f0`) $\to$ `_nv002219kms` (`0x226b20`) $\to$ `_nv000673kms` (`0x2269e0`) proves that `390.157` runs an automatic DisplayPort BPC step-down loop (`30 bpp` $\to$ `24 bpp` $\to$ `18 bpp`), stepping down to **6 bpc (`18 bpp`) with spatial/temporal dithering** for the 120 Hz mode.
    - Decompilation of `_nv000659kms` (`0x217f20`) proves that `390.157` also grants a **+5.0 MHz (`+5000 kHz`) pixel-clock grace margin** and ignores self-contradicting EDID Range Limits (`HorizSync`, `VertRefresh`, `Max PixelClock`) on 3D Vision Stereo panels (`*(byte *)(pConnector + 0x3bdc) & 2`).
    - Decompilation of `_nv002187kms` (`0x209440`, RM IMP check) shows that when `396.36 MHz` is active, P-State `03` (`dispclk`/`hubk07 = 135 MHz < 396.36 MHz`) is locked out so the display engine never starves.
  - **Implementation Tasks**:
    1. **Automatic DP/eDP BPC Step-Down (`8 bpc` $\to$ `6 bpc`)**: In Nouveau's DisplayPort atomic check / connector validation (`dispnv50` / `nouveau_connector.c`), automatically step down `bpc` from `8` to `6` (`18 bpp`) with hardware dithering enabled whenever `mode->clock * 24 > dp_link_bw`.
    2. **3D Vision EDID Range Quirk (`+5.0 MHz` Margin)**: Bypass conflicting EDID range descriptors for Detailed Timing Descriptors on `LGD 0x02c5` and sibling 3D Vision panels.
    3. **Active 120 Hz P-State Floor (`>= 07`)**: Prevent transitions to P-State `03` (`135 MHz` `hubk07`) whenever any active CRTC has `pixel_clock > 135,000 kHz`, keeping `dispclk >= 405 MHz`.
    4. **VBlank & Page-Flip Timestamp Verification**: Verify DRM VBlank counter and page-flip completion interrupts at full `119.98 Hz` (`8.33 ms` frame interval) so Wayland/X11 compositors and OpenGL apps run at true 120 FPS instead of half-rate (~57–60 FPS).

- [ ] **Stereoscopic 3D (`NVIDIA 3D Vision`) Support on Linux (`LGD 0x02c5` 120 Hz Panel + Built-in IR Emitter)**:
  - **Is Stereoscopic 3D Possible?** **Yes!** On the Dell XPS L702X, 3D Vision hardware consists of:
    1. The `1920x1080 @ 120 Hz` eDP panel (`LGD 0x02c5`) alternating Left and Right eye frames at `60 Hz` per eye (`8.33 ms` per frame).
    2. The built-in USB NVIDIA 3D Vision IR Emitter (`USB ID 0955:0007` / `0955:7002`, wired internally on the laptop USB bus), which synchronizes the active-shutter LCD glasses with VBlank.
    3. EVO display backlight/frame-sync registers in `nv-modeset-kernel.o_binary` + userspace USB emitter control.
  - **Implementation Tasks**:
    1. **Reverse-Engineer EVO Stereo Registers in `nv-modeset-kernel.o_binary` & `nv-kernel.o_binary`**:
       - Trace stereo mode flags (`*(byte *)(pConnector + 0x3bdc) & 2` and EVO head stereo pin/signaling registers in `0x61xxxx`) using REA to see if the internal eDP panel requires a panel GPIO/backlight phase toggle or pure VBlank timing.
    2. **USB 3D Vision IR Emitter Daemon / Helper (`nv3dvision-ir`)**:
       - Build a lightweight `libusb` userspace helper (or integrate with open-source `libnvstusb` / `3dvision` protocol) that uploads the 8051 microcontroller firmware/timing pulses to the internal `0955:xxxx` USB IR emitter and triggers left/right eye shutter flips synchronized to DRM `DRM_IOCTL_WAIT_VBLANK` events at 120 Hz.
    3. **Side-by-Side / Frame-Sequential Stereo Presentation**:
       - Support frame-sequential 120 Hz stereo output for stereo media players (`bino`, `mpv`), emulators, and OpenGL quad-buffered stereo (`GLX_STEREO`) or Vulkan/GL layer injection.

### 6. Fermi Engine Clock-Gating (BLCG / SLCG) & Hardware Load Counters (`0x10a600`)
- [ ] **Extract & Program Fermi BLCG / SLCG Clock-Gating Tables (`nv-kernel.o_binary` §9.4.4)**:
  - **Goal**: Reduce GPU idle and multimedia power consumption by `2–4 W` and lower baseline temperatures by `3–5 °C` across all Fermi (`GF100`–`GF119`) chips.
  - **Implementation Tasks**:
    1. Use REA to extract the static per-chip Block-Level Clock Gating (BLCG) and Second-Level Clock Gating (SLCG) register/value arrays from `.rodata` in `nv-kernel.o_binary` for `GF100`, `GF104`, `GF106`, `GF108`, `GF110`, `GF114`, `GF116`, `GF117`, and `GF119`.
    2. Program the extracted BLCG/SLCG tables during `gr` (`PGRAPH`), `fb` (`PFB`), `copy` (`PCOPY`), and `therm` subdevice initialization in Nouveau.
- [ ] **Hardware GPU Engine Utilization Counters (`0x10a600..0x10a610`, `_nv029625rm` / `_nv029628rm` §10.3)**:
  - **Goal**: Provide true hardware GPU core (`GR`), memory controller (`FB`), and video decoder (`VDEC`) utilization percentages (0–100%), replacing software heuristic polling in `nouveau-dynclockd`, `nouveau-ctrl`, and `nouveau-tui`.
  - **Implementation Tasks**:
    1. Decompile `_nv029625rm` (`0x515a70`), `_nv029628rm` (`0x515ad0`), and their callers in `nv-kernel.o_binary` to extract the exact signal filter masks written to PDAEMON counter slots `0x10a600 + idx*4` (`idx = 0..4`) and counter readout offsets (`0x10a5xx`).
    2. Configure the hardware idle/busy counters in `nvkm/subdev/pmu/gf100.c` (making sure they coexist cleanly with `memx_exec_custom.fuc`).
    3. Expose hardware GPU load `%` (`GR`), memory controller load `%` (`FB`), and video engine load `%` (`VDEC`) via `/sys/kernel/debug/dri/*/pstate` and wire them into `nouveau-dynclockd`, `nouveau-ctrl`, and `nouveau-tui`.

### 7. Single-Fan Shared Thermal Protection (`PTHERM` `0x00020xxx`) & L2 / Z-Cull Compression
- [ ] **Hardware `PTHERM` Auto-Slowdown & Single-Fan Chassis Thermal Coordination**:
  - **Platform Context (Dell XPS L702X 3D Vision Edition)**:
    - Because the 120 Hz 3D Vision eDP panel (`LGD 0x02c5`) is wired directly to the discrete GT 555M (`01:00.0`) with the Sandy Bridge iGPU permanently disabled in BIOS (non-Optimus), the NVIDIA GPU drives the display 100% of the time.
    - The laptop uses a **single shared chassis blower fan** controlled by the Dell Embedded Controller (`dell-smm-hwmon` / `i8k`) to cool both the Intel CPU and the NVIDIA GT 555M heatpipes simultaneously.
  - **Implementation Tasks**:
    1. **Hardware `PTHERM` Clock-Slowdown Failsafe (`0x00020xxx`)**: Reverse-engineer the Fermi thermal slowdown registers in `nv-kernel.o_binary` so the GPU hardware itself automatically divides the core/shader clock if die temperature reaches `90–92 °C`, even if userspace is unresponsive.
    2. **Progressive Multi-Step Thermal Throttling for Single-Fan Cooling**: Instead of an abrupt `0f` $\to$ `07` drop at `80 °C`, step down smoothly across P-states (`10` OC $\to$ `0f` P0 at `78 °C` $\to$ `0a` P3 at `82 °C` $\to$ `07` P8 at `86 °C`) so the single blower fan can stabilize heatpipe temperatures during combined CPU+GPU workloads (such as gaming + OBS streaming) without tanking framerate.
- [ ] **L2 Cache (`PLTCG` `0x140000`) & `PGRAPH` Z-Cull / Tile Compression Optimization**:
  - Compare `nv-kernel.o_binary`'s initialization of `PLTCG` (`0x140xxx`) and `PGRAPH` Z-Cull / ROP compression registers against upstream Nouveau to ensure lossless depth/color bandwidth compression is fully active on Fermi.

### 8. GPU Video Encoding (OBS Studio / `VA-API`) & Hardware Decoding (`VP4` / `MSENC`)
- [ ] **Standard `VA-API` (`VAEntrypointEncSlice`) Hybrid Shader/Compute H.264 Encoder for Fermi (`NVCUVENC` Open-Source Equivalent)**:
  - **Hardware Context**:
    - On the non-Optimus Dell XPS L702X 3D Vision laptop (Intel iGPU disabled in BIOS) and on all Fermi (`GF100`–`GF119`) GPUs, there is no fixed-function `NVENC` ASIC (which debuted in Kepler `GK104`).
    - In the proprietary driver era, NVIDIA provided GPU-accelerated H.264 encoding on Fermi via **`NVCUVENC` (`libnvidia-encode.so`)**, which executed the heavy parallel stages of H.264 encoding on **Fermi's Shader/Compute cores (`1180–1400 MHz` hot clock) + `MSPPP` + `PCOPY` DMA**.
  - **How to Expose It to OBS Studio, FFmpeg & Standard Linux Apps**:
    - Standard Linux streaming and recording apps (OBS Studio, FFmpeg `-c:v h264_vaapi`, PipeWire, GStreamer) discover hardware encoders by querying **VA-API (`libva`, `/usr/lib/dri/nouveau_drv_video.so`)** for `VAProfileH264ConstrainedBaseline` / `VAProfileH264Main` with **`VAEntrypointEncSlice`**.
    - By implementing a **Compute-Shader-Backed `pipe_video_codec` H.264 Encoder** inside Mesa's Gallium VA frontend (`nvc0`), every VA-API application automatically sees a native hardware H.264 encoder:
      1. **Stage 1 — Zero-Copy DMA-BUF Input & GPU `RGB` $\to$ `NV12` Conversion (`< 0.3 ms`)**:
         - OBS Studio passes the rendered desktop/game texture directly as a GPU `DMA-BUF` into VA-API. A lightweight `nvc0` compute/fragment shader converts `BGRX/RGBA` $\to$ `NV12` (and scales if needed) entirely in VRAM, eliminating raw 1080p frame readbacks over PCIe.
      2. **Stage 2 — Parallel Hierarchical Motion Estimation on Fermi SMs (`NVC0_COMPUTE` `0x90c0`)**:
         - Offloads ~70% of H.264 encoding cost onto the GT 555M's 144 shader cores (`3 SMs × 48 cores @ 1300–1400 MHz`) using 48 KB on-chip Shared Memory per SM to perform 16×16 / 8×8 SAD/SATD diamond/hexagon motion search across macroblocks in parallel.
      3. **Stage 3 — GPU 4×4 / 8×8 Integer DCT, Quantization & Intra Prediction**:
         - Compute shaders transform and quantize macroblock residuals and write compact `[motion_vectors + quantized_coeffs]` into a host-visible ring buffer via Fermi's async `PCOPY` DMA engine.
      4. **Stage 4 — Lightweight Host CAVLC / CABAC Bitstream Packer**:
         - A single fast CPU thread packs the GPU-computed quantized coefficients and motion vectors into compliant H.264 `NAL` slices (~5% CPU usage) and returns the `VACodedBufferSegment` to OBS / FFmpeg.
- [ ] **Immediate OBS Studio / `x264` OpenCL Lookahead Acceleration via Mesa `Rusticl`**:
  - Configure and validate **Mesa `Rusticl`** (`RUSTICL_ENABLE=nouveau` OpenCL 3.0 on `nvc0`) so OBS Studio's `x264` encoder (`opencl=true`) can immediately offload frame downscaling, intra-cost analysis, and motion lookahead onto the GT 555M shader cores.
- [ ] **PureVideo HD `VP4` Hardware Video Decode (`MSVLD` / `MSPDEC` / `MSPPP`) Firmware Extractor**:
  - Ship a helper utility (`nouveau-extract-fw`) that extracts the `VP4` (`nv98_fuc084`, `nv98_fuc085`, `nv98_fuc086`) Falcon video decode firmware from `NVIDIA-Linux-x86_64-390.157.run` into `/lib/firmware/nouveau/`, enabling zero-CPU 1080p60 H.264 / VC-1 / MPEG-2 hardware decoding in Firefox, Chromium, MPV, and VLC via VA-API and VDPAU.
- [ ] **Fixed-Function `MSENC` / `NVENC` (`0x1c8000`) Support for Kepler (`GK104+`) & Maxwell 1 (`GM107+`)**:
  - Reverse-engineer the `MSENC` (`0x1c8000`) Falcon microcode loader and H.264 bitstream command queue from `390.157` (`nv-kernel.o_binary` & `libnvidia-encode.so.390.157`) to unlock fixed-function `NVENC` via VA-API on Kepler and Maxwell GPUs as the project expands.

---

## ⚡ Falcon Microcode & Memory Controller Expansion

### 1. Generalizing Falcon Executor for the Fermi Family
- [ ] **GF100 / GF104 / GF108 / GF114 / GF116 / GF117 / GF119 Support**:
  - Decouple hardcoded GF106 DDR3 PHY offsets in [`ramgf100.c`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/nouveau-source/nvkm/subdev/fb/ramgf100.c) using the per-family RM emitters (`_nv015935rm` GF100, `_nv015936rm` GF104/GF106, `_nv015937rm` GF108, `_nv015938rm` GF119) and calculators (`_nv014883rm`, `_nv014880rm`, `_nv015894rm`, `_nv015895rm`).
  - Support 64-bit, 128-bit, 192-bit, 256-bit, 320-bit, and 384-bit partition topologies via `[pFb + 0xd20]` (`_nv016234rm` / `_nv016235rm`).

### 2. GDDR5 Memory Support
- [ ] **GDDR5 Timing & Calibration Engine**:
  - Extract the GDDR5 branches of `_nv010721rm` (`0xec6b0`) and `_nv010722rm` (`0x104470`) to support GDDR5-equipped Fermi desktop and mobile cards (e.g., GT 555M GDDR5 variant, GTX 460/470/480, GTX 560 Ti/570/580).

---

## 🔋 Dynamic Governor & Power Management (`nouveau-dynclockd` 2.0 Modernization)

### 1. Power Source (AC vs. Battery) Awareness
- [x] **Automatic Battery Conservation Profile** (shipped in `v2.1.0` via `BATTERY_CAP`, field verification pending):
  - Poll `/sys/class/power_supply/` (e.g., `AC/online`, `BAT0/status`).
  - When on DC (battery), cap maximum performance state to P8 (`07`: `202 MHz` core / `324 MHz` mem @ `0.820 V`), matching proprietary NVIDIA `390.157` driver behavior.
  - Immediately permit P0 (`0f`) / OC (`10`) when AC power adapter is connected.

### 2. Replace `/proc` CPU-Tick Scanning with True Hardware GPU Load Counters (`0x10a600..0x10a610`)
- [ ] **Hardware-Counter-Driven Scaling in `nouveau-dynclockd`**:
  - **Problem**: [`get_monitored_app_ticks()`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/nouveau-dynclockd.py#L221-L240) currently scans every `/proc/[0-9]*/comm` and `/proc/[0-9]*/stat` on the system once per second to measure **CPU ticks** of browsers/compositors—boosting the GPU on CPU-only JavaScript loads while missing GPU-bound WebGL shaders that use <5% CPU.
  - **Solution**: Read the kernel-exposed PDAEMON hardware utilization counters (`GR %`, `FB %`, `VDEC %` from `0x10a600..0x10a610`) directly from `/sys/kernel/debug/dri/*/pstate` in a single `< 0.05 ms` file read with zero `/proc` scanning overhead.

### 3. 120 Hz Display-Aware Idle Floor (Preventing `03` Underflow & Desktop Flashes)
- [ ] **Automatic P8 (`07`) Floor When High-Pixel-Clock (120 Hz) Mode is Active**:
  - **Problem**: `IDLE_STATE` currently defaults to `03` (`50 MHz` core / `135 MHz` `dispclk`), which violates the `396.36 MHz` pixel-clock requirement of the `1920x1080 @ 120 Hz` panel (`135 MHz < 396.36 MHz`, as enforced by `_nv002187kms` in `390.157`) and causes unnecessary `03` $\leftrightarrow$ `07` transitions on the desktop.
  - **Solution**: Automatically detect when any active CRTC mode has `pixel_clock > 135,000 kHz` (or `refresh >= 100 Hz`) and clamp the idle floor to **`07` (`405 MHz` `dispclk`, `324 MHz` DDR3)**, dropping to `03` only when the display is running at 60 Hz or blanked (DPMS off).

### 4. Multi-Tier Scaling Ladder (`03` $\leftrightarrow$ `07` $\leftrightarrow$ `0a` $\leftrightarrow$ `0f` $\leftrightarrow$ `10`) & Staged Hold-Down Timers
- [ ] **5-Tier Governor State Machine with Anti-Flash Hold Timers**:
  - **Problem**: Currently `idle_cycles >= 2` drops straight from `0f` (`900 MHz`) to `03` after just 2 seconds, and `nouveau-dynclockd` never utilizes P3 (`0a`) or OC (`10`).
  - **Solution**:
    - Scale across all 5 states based on hardware `GR`/`FB`/`VDEC` utilization:
      - `03` (P12): Display off / 60 Hz deep idle (`GR < 5%`).
      - `07` (P8): 120 Hz desktop idle / light 2D (`GR < 25%`).
      - `0a` (P3): Video playback (`VDEC` active), WebGL, light 3D, or OBS compositing (`GR 25–60%`).
      - `0f` (P0): Heavy 3D rendering / gaming (`GR > 60%`).
      - `10` (OC): Sustained heavy 3D load (`GR > 85%` when `NvFermiOC=true` and `temp < 78 °C`).
    - Implement staged hold-down timers (`5–8 s` hold in `10`/`0f` before stepping down to `0a`/`07`) matching `390.157` PowerMizer so brief game loading screens never trigger a mid-game memory reclock.

### 5. Manual Override Coordination with `nouveau-ctrl` & `nouveau-tui`
- [ ] **Shared Governor Mode State (`/run/nouveau-fermi-reclock/mode`)**:
  - **Problem**: Running `nouveau-ctrl set 10` (or selecting a manual state in `nouveau-tui`) is currently overwritten by `nouveau-dynclockd` on the very next 1-second poll!
  - **Solution**: Have `nouveau-ctrl` and `nouveau-tui` write `mode=locked:<pstate>` (or `mode=auto`) to `/run/nouveau-fermi-reclock/mode` and signal `nouveau-dynclockd`, so manual locks persist cleanly (while keeping thermal runaway protection active!) until the user switches back to `auto`.

### 6. Event-Driven Workload & Power-Supply Detection
- [ ] **Zero-Overhead eBPF / DRM & Udev Event Wakeups**:
  - Replace polling loops with netlink/udev power-supply notifications and DRM client/pushbuffer tracepoints.

### 7. Per-Application Profile Overrides
- [ ] **Application Rules Directory (`/etc/nouveau-dynclockd.d/`)**:
  - Allow users to define application-specific P-State policies (e.g., Steam/Proton games $\to$ `0f`/`10`, MPV/VLC $\to$ `07`/`0a`, OBS Studio $\to$ `0a`/`0f`).

---

## 📊 Telemetry & Monitoring (`nouveau-ctrl` / `nouveau-tui`)

### 1. Live VRAM Allocation Tracking
- [x] **Accurate VRAM Usage Reporting** (shipped in `v2.1.0`, live-verified as root and user):
  - Extract active, pinned, and total allocated VRAM from DRM TTM manager (`/sys/kernel/debug/dri/*/ttm_vram` or sysfs memory stats).
  - Display used/total VRAM in megabytes and percentage across `nouveau-ctrl status` and `nouveau-tui`.

### 2. Real-Time ASCII Sparkline History
- [ ] **60-Second Scrolling Metrics in `nouveau-tui` & `nouveau-ctrl watch`**:
  - Render terminal ASCII sparklines (` ▂▃▄▅▆▇█`) tracking Core/Memory clocks, hardware `GR`/`FB` load `%`, GPU temperature, and single-fan RPM (`dell-smm-hwmon`).

### 3. Instantaneous Power Dissipation Estimation ($P_{est}$)
- [ ] **Real-Time Dynamic Power Calculation**:
  - Model instantaneous power dissipation in Watts ($P_{est} = C_{eff} \cdot V^2 \cdot f + P_{leak}(T)$), calibrated against platform telemetry (`03`: ~4.2 W, `07`: ~8.5 W, `0a`: ~19.5 W, `0f`: ~38.0 W, `10`: ~46.5 W).

---

## 🚀 Project Evolution: `nouveau-reclocking-dkms` (Covering All Pre-`Nova` NVIDIA GPUs)

Upstream Linux is developing the new Rust-based **`Nova`** kernel driver to replace `nouveau`—but **`Nova` exclusively supports Turing (`TU10x` / `NV160`, GeForce GTX 16xx / RTX 20xx) and newer GPUs** that contain a RISC-V **GSP (GPU System Processor)**.

Every single pre-Turing NVIDIA architecture (**Tesla, Fermi, Kepler, Maxwell 1, Maxwell 2, Pascal, and Volta**) is permanently excluded from `Nova` and will rely on `nouveau` forever. As we expand beyond `GF106`, this project will evolve into **`nouveau-reclocking-dkms`** to provide complete dynamic reclocking, power management, and display fixes for the entire pre-`Nova` hardware ecosystem:

| Generation | Chip Families | GeForce Series | Firmware Security | Current Upstream Nouveau Status | `nouveau-reclocking-dkms` Target Roadmap |
|---|---|---|---|---|---|
| **Fermi** (`NVC0`–`NVCE`) | `GF100`–`GF119` | GeForce 400 / 500 / 600M–800M | **Unsigned Falcon** | Memory reclocking broken; no P3/OC; no governor | ✅ **Working on GF106!** Expand DDR3/GDDR5 tables, BLCG/SLCG, P3 (`0a`), and zero-flash VBlank to all `GF100`–`GF119` chips via `390.157` RE. |
| **Kepler** (`NVE0`–`NV108`) | `GK104`–`GK208` | GeForce 600 / 700 / 800M | **Unsigned Falcon** | Manual debugfs only; mobile DDR3/GDDR5 bugs; no Boost; no governor | Add automatic governor support, GPU Boost 1.0/2.0 interpolation, mobile `GK107M`/`GK208M` RAM fixes, and `MSENC` (`NVENC`) via `390.157` / `470.xx` RE. |
| **Maxwell 1** (`NV117`–`NV118`) | `GM107`–`GM108` | GTX 750 / 750 Ti, GTX 850M / 860M, 940M / MX110 / MX130 | **Unsigned Falcon!** | **No reclocking at all in upstream Nouveau!** | **High-Value Target**: First-gen Maxwell does **not** enforce signed PMU firmware and is fully supported in `390.157`! Port custom Falcon PMU + PLL/RAM reclocking to `GM107`/`GM108`. |
| **Tesla** (`NV50`–`NVA8`) | `G80`–`GT218` | GeForce 8000 / 9000 / 200 / 300 | **Unsigned** | Partial/unstable `ramgt215` / `ramnv50`; no governor | Integrate `GT215`–`GT218` PDAEMON/host reclocking and dynamic governor support. |
| **Maxwell 2 & Pascal** (`NV120`–`NV138`) | `GM200`–`GM206`, `GP100`–`GP108` | GeForce GTX 900 & GTX 10-series | **HS RSA-Signed ACR/PMU** | Locked to boot clocks (~135–405 MHz) due to missing signed PMU/ACR blobs | Investigate extracting/loading official signed PMU/ACR images from `390.157`/`470.xx`/ NVIDIA redistributables (or host-side PLL paths not blocked by `PRIV_LEVEL_MASK`) + unified governor. |

### Packaging & Ecosystem Transition Tasks
- [ ] **Rename / Provide Unified Package `nouveau-reclocking-dkms`**:
  - Transition `nouveau-fermi-reclock-dkms` $\to$ `nouveau-reclocking-dkms` (and pre-built kernel packages `nouveau-reclocking-*`) with `provides=('nouveau-fermi-reclock-dkms')` and `replaces=('nouveau-fermi-reclock-dkms')` once multi-architecture support lands.
- [ ] **Mesa `NVC0` Vulkan ([`VULKAN.md`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/VULKAN.md)) & VA-API Compute Encoder Validation**:
  - Prototype bound-descriptor Vulkan ([`VULKAN.md`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/VULKAN.md)) and VA-API H.264 compute encoding on `NVC0` under full P0/OC clocks.
- [ ] **OpenCL 3.0 (`Rusticl`), Unified Memory AI Inference & `PCOPY` VRAM-as-RAM Block Device ([`VRAM_AI.md`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/VRAM_AI.md))**:
  - Unlock full `~2.75 GiB` OpenCL tensor allocations on `nvc0`, transparent `VRAM | GART` oversubscription for `> 3 GiB` LLMs, and `/dev/nvram0` `PCOPY` DMA-backed upper-VRAM system memory/swap pooling as detailed in [`VRAM_AI.md`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/VRAM_AI.md).


