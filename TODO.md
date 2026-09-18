# 📋 Roadmap & TODO

This document tracks completed milestones, planned features, architectural improvements, and pending tasks for the **Nouveau Fermi Reclocking & 120Hz Driver** project.

---

## ✅ Completed Milestones

- [x] **v1.0 Baseline Fermi Core & Shader Reclocking**:
  - Implemented stable core and shader clock scaling (`50 MHz` / `202 MHz` / `590 MHz` core; `101 MHz` / `405 MHz` / `1180 MHz` shader).
  - Unlocked 120 Hz eDP display mode (`1920x1080 @ 120Hz`, pixel clock `396.36 MHz`) without scanout underflows or timing corruption.
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

### 1. VBlank-Synchronized Memory Reclocking (Zero-Pause Switching)
- [ ] **Raster Beam / Vertical Blanking Synchronization**:
  - **Goal**: Eliminate the single-frame visual micro-pause (~8.3 ms at 120 Hz) when transitioning memory clocks between `324 MHz` and `900 MHz` upon 3D application launch or exit.
  - **Mechanism**:
    - Query CRTC scanout position register (`0x6100f8` / `0x6160f8` on GF100/GF106 display engine).
    - Hook the Falcon PMU memory transition trigger into the hardware VBlank interrupt window or poll for raster line within vertical front porch / blank interval.
    - Ensure DLL retraining and MEMPLL re-lock sequence completes before the first active scanout line of the subsequent frame.

### 2. Dynamic PCIe Link Speed Scaling (Gen1 $\leftrightarrow$ Gen2)
- [ ] **Automatic Gen1 (2.5 GT/s) $\leftrightarrow$ Gen2 (5.0 GT/s) Switching**:
  - **Goal**: Retrain PCIe link dynamically to maximize power savings at idle and maximize throughput under 3D workloads.
    - **P12 (`03` idle)**: `2.5 GT/s x16` (Gen1) + ASPM L0s/L1 enabled for deep system C-state package residency (~4.2W package power).
    - **P8 (`07` 2D desktop)**: `2.5 GT/s x16` (Gen1) (~8.5W).
    - **P0 (`0f` 3D) / OC (`10`)**: `5.0 GT/s x16` (Gen2) with low-latency ASPM for maximum DMA throughput (~38W–46W).
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

---

## ⚡ Falcon Microcode & Memory Controller Expansion

### 1. Generalizing Falcon Executor for the Fermi Family
- [ ] **GF100 / GF104 / GF108 / GF114 / GF116 Support**:
  - Decouple hardcoded GF106 DDR3 PHY offsets in [`ramgf100.c`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/nouveau-source/nvkm/subdev/fb/ramgf100.c).
  - Implement dynamic register block parsing to support 128-bit, 192-bit, 256-bit, and 384-bit memory bus configurations.
  - Auto-extract memory timing tables (CAS, tRCD, tRP, tRAS, tRFC) directly from VBIOS performance tables.

### 2. GDDR5 Memory Support
- [ ] **GDDR5 Timing & Calibration Engine**:
  - Implement PHY write/read training, DLL phase tracking, and command/address bus retraining for GDDR5-equipped Fermi desktop cards (e.g., GTX 460/470/480, GTX 560 Ti/570/580).
  - Replicate driver-level handshake for GDDR5 link reset and CRC error check registers.

---

## 🔋 Dynamic Governor & Power Management (`nouveau-dynclockd`)

### 1. Power Source (AC vs. Battery) Awareness
- [ ] **Automatic Battery Conservation Profile**:
  - Poll `/sys/class/power_supply/` (e.g., `AC/online`, `BAT0/status`).
  - When on DC (battery), cap maximum performance state to P8 (`07`: `202 MHz` core / `324 MHz` mem @ `0.820 V`), matching proprietary NVIDIA `390.157` driver behavior.
  - Immediately permit P0 (`0f`) / OC (`10`) when AC power adapter is connected.

### 2. Zero-Overhead eBPF / Perf Tracepoint GPU Load Detection
- [ ] **Event-Driven Workload Detection**:
  - Replace polling loop (`/sys/kernel/debug/dri/*/clients`) with eBPF kprobes or kernel tracepoints:
    - `nouveau:nouveau_bo_move`
    - `nouveau:nouveau_fence_wait`
    - DRM engine pushbuffer submission IOCTLs (`DRM_IOCTL_NOUVEAU_GEM_PUSHBUF`).
  - Zero CPU overhead when idle; near-instantaneous (<2 ms) reaction time to 3D rendering spikes.

### 3. Per-Application Profile Overrides
- [ ] **Application Rules Directory (`/etc/nouveau-dynclockd.d/`)**:
  - Allow users to define application-specific P-State policies:
    - Gaming / Steam apps: lock to P0 / OC on launch.
    - Media players (MPV, VLC, Firefox video playback): lock to P8 for smooth decoding without unnecessary thermal ramp.
    - Compilers / productivity: keep in P12 idle state.

---

## 📊 Telemetry & Monitoring (`nouveau-ctrl` / `nouveau-tui`)

### 1. Live VRAM Allocation Tracking
- [ ] **Accurate VRAM Usage Reporting**:
  - Extract active, pinned, and total allocated VRAM from DRM TTM manager (`/sys/kernel/debug/dri/*/ttm_vram` or sysfs memory stats).
  - Display used/total VRAM in megabytes and percentage across `nouveau-ctrl status` and `nouveau-tui`.

### 2. Real-Time ASCII Sparkline History
- [ ] **60-Second Scrolling Metrics in `nouveau-tui` & `nouveau-ctrl watch`**:
  - Render terminal ASCII sparklines (` ▂▃▄▅▆▇█`) tracking:
    - Core & Memory clock history.
    - GPU core temperature with thermal color coding (green < 60°C, yellow < 75°C, red ≥ 75°C).
    - Fan RPM curve.

### 3. Instantaneous Power Dissipation Estimation ($P_{est}$)
- [ ] **Real-Time Dynamic Power Calculation**:
  - Model instantaneous power dissipation in Watts:
    $$P_{est} = C_{eff} \cdot V^2 \cdot f + P_{leak}(T)$$
  - Calibrated against Dell XPS L702X platform telemetry:
    - P12 (`03`): ~4.2 W
    - P8 (`07`): ~8.5 W
    - P0 (`0f`): ~38.0 W
    - OC (`10`): ~46.5 W
  - Expose live wattage in `nouveau-ctrl status` and `nouveau-tui`.

---

## 🌐 Community & Ecosystem

- [ ] **Upstream nouveau Patchset Submission**:
  - Organize clean RFC patch series for the Linux `dri-devel` mailing list:
    1. eDP high-pixel-clock / 120Hz display timing calculation fix.
    2. VMAP / voltage table fallback correction for Fermi mobile GPUs.
    3. Resident Falcon microcode memory reclocking subsystem.
- [ ] **Automated Telemetry Aggregation**:
  - Build CI workflow to ingest and catalog user diagnostic submissions from `tools/nouveau-fermi-diag.py`.
- [ ] **Mesa NVC0 / Zink Vulkan Validation**:
  - Benchmark performance improvements in Mesa NVC0 Gallium driver and Zink (Vulkan-over-OpenGL) under full P0/OC clocks.
