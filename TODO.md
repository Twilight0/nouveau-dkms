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

## 🎯 Kernel & Hardware Subsystems

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
    - P12 (`03` idle): `2.5 GT/s x16` (Gen1) + ASPM L0s/L1 enabled for deep system C-state package residency.
    - P8 (`07` 2D desktop): `2.5 GT/s x16` (Gen1).
    - P0 (`0f` 3D) / OC (`10`): `5.0 GT/s x16` (Gen2) for high-bandwidth texture streaming and vertex buffer DMA.
  - **Implementation**:
    - Hook `nvkm_pcie_set_link()` into [`nvkm/subdev/clk/base.c`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/nouveau-source/nvkm/subdev/clk/base.c) during P-State transitions.
    - Assert PCIe Gen2 capability via PUNIT strap register `0x02241c` (bits 0 and 7).
    - Initiate physical link retraining via internal extended config register `0x460` (bits `[5:4]` = `0x20`, bit 0 = `0x1`) and negotiate with upstream Root Complex (`0000:00:01.0`).
    - Coordinate with display scanout to prevent LTSSM retraining bus stalls from impacting active refresh.

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
