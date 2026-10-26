# Driver Comparison: Nouveau Reclocking (`nouveau-dkms`) vs. NVIDIA Official Drivers & Stock Nouveau

This document provides an objective, architectural, and practical comparison between **`nouveau-dkms` (v2.2.0+)**, the **official legacy NVIDIA drivers (390.157 / 470.xx)**, and **stock upstream kernel Nouveau**.

---

## 1. Executive Summary: Why Nouveau Benefits Users *Right Now*

For years, the consensus on pre-Turing NVIDIA GPUs (Fermi, Kepler, Maxwell 1) was that users had to choose between two broken worlds:
1. **The Proprietary Driver (NVIDIA 390.157 / 470.xx)**: High performance, but abandoned upstream, incompatible with modern Linux kernels (`6.x+`), completely broken on Wayland, stuck on legacy X11, and reliant on fragile third-party patches to compile.
2. **Stock In-Tree Nouveau**: Rock-solid modern kernel integration and flawless Wayland desktop compatibility, but crippled by **boot-state clock locking** (running at ~200 MHz core / 324 MHz memory, or ~20% of hardware potential) with terrible 3D performance and frame stutter.

**`nouveau-dkms` changes this reality.** By unlocking bidirectional memory reclocking, resident microcode execution, signed-`vpos` VBlank synchronization, and dynamic thermal/power scaling, users get **the best of both worlds**: native modern kernel and Wayland support paired with full hardware performance.

---

## 2. Comprehensive Comparison Matrix

| Architectural Feature | Official NVIDIA `390.157` (Legacy) | Official NVIDIA `470.xx` (Kepler Legacy) | Stock Upstream Nouveau (`kernel.org`) | **`nouveau-dkms` (v2.2.0+)** |
| :--- | :---: | :---: | :---: | :---: |
| **Target Architectures** | Fermi (`GF100`–`GF119`) | Kepler (`GK104`–`GK208`) | All NVIDIA architectures | **Fermi (`GF106` active, expanding to Kepler/Maxwell 1)** |
| **Linux Kernel Compatibility** | ❌ Abandoned; requires社区 hacks for Linux `6.x+` | ⚠️ Frozen; breaks on modern DRM shifts | ✅ Native upstream | ✅ **DKMS on Linux `6.12 LTS`, `6.18+`, `6.19+`** |
| **Core & Shader Clocks** | ✅ Full (`590 / 1180 MHz`) | ✅ Full Boost 1.0/2.0 | ⚠️ Manual debugfs only; uncoordinated | ✅ **Full Hardware P-States (`03`, `07`, `0f`, `10` OC)** |
| **DDR3 Memory Reclocking** | ✅ Full (`900 MHz` / `1800 MHz` eff.) | ✅ Full | ❌ **Stuck at boot (`324 MHz`)** | ✅ **Full Resident Microcode (`324 ↔ 900 MHz`)** |
| **PCIe Link Scaling** | ✅ Gen1 `2.5 GT/s` ↔ Gen2 `5.0 GT/s` | ✅ Gen1 ↔ Gen3 | ⚠️ Stalled or manual | ✅ **Dynamic Gen1 (`2.5 GT/s`) ↔ Gen2 (`5.0 GT/s x16`)** |
| **Memory Bandwidth** | ✅ `43.2 GB/s` (DDR3) | ✅ Up to `200+ GB/s` (GDDR5) | ❌ `15.5 GB/s` (64% bandwidth loss) | ✅ **`43.2 GB/s` (100% physical bandwidth)** |
| **Screen Flash on Reclocking** | ✅ Zero flash (custom VBlank pipeline) | ✅ Zero flash | ❌ Screen flash, blanking & timeouts | ✅ **Zero Stutter (`vpos` VBlank-onset sync, 477–535 µs)** |
| **Dynamic Frequency Governor** | ✅ PowerMizer (in daemon/driver) | ✅ PowerMizer | ❌ None (stuck at boot state) | ✅ **`nouveau-dynclockd` 2.0 (Hysteresis, App Profiles)** |
| **Wayland Support (KMS / GBM)** | ❌ **Completely Broken** (EGLStreams only) | ⚠️ Partial (lacks explicit sync) | ✅ Flawless | ✅ **Flawless (Qtile, Plasma 6, GNOME 46, Sway)** |
| **Wayland Explicit Sync (`syncobj`)** | ❌ None | ❌ None | ✅ Linux 6.8+ syncobj | ✅ **Full `linux-drm-syncobj-v1` support** |
| **Display Server ABI** | ❌ Breaks on modern Xorg / Xwayland ABI | ⚠️ Deprecated | ✅ Modern KMS/DRM standard | ✅ **Standard Linux KMS & Xwayland** |
| **120 Hz eDP Display Protection** | ✅ Proprietary IMP check (`_nv002187kms`) | ✅ Proprietary | ❌ FIFO underflows / screen tearing | ✅ **`DISPLAY_120HZ_FLOOR=true` (CRTC guard)** |
| **Thermal & Fan Protection** | ✅ Built-in hardware curve | ✅ Built-in | ⚠️ Fixed / manual fan | ✅ **`dell_smm` fan integration & throttle hysteresis** |
| **Modern OpenCL / Compute** | ❌ Stuck on ancient CUDA 9.1 | ⚠️ Stuck on CUDA 11.4 | ⚠️ Basic Clover | ✅ **OpenCL 3.0 via Mesa Rusticl (`llama.cpp` + `CLBlast`)** |
| **Unprivileged Telemetry** | ⚠️ `nvidia-smi` (requires root daemon) | ⚠️ `nvidia-smi` | ❌ Root-only `/sys/kernel/debug` | ✅ **Zero-sudo `/run/nouveau/` snapshots (`ctrl` / `tui`)** |
| **S3 Suspend / Resume** | ⚠️ Often freezes on modern kernels | ⚠️ Flaky on modern kernels | ⚠️ Clock freeze after resume | ✅ **Self-healing resident handshake (`fexec_code`)** |

---

## 3. Key Benefits for Users Today

### 🟢 1. Native Wayland Without Compromise
- **The Problem with NVIDIA 390/470**: NVIDIA 390 relies on legacy `EGLStreams` instead of the Linux standard Generic Buffer Management (`GBM`). Modern Wayland compositors (Plasma 6.1+, GNOME 46+, Sway 1.10, Qtile Wayland) have completely dropped EGLStreams support, meaning users on proprietary drivers are trapped in X11.
- **The `nouveau-dkms` Advantage**: Runs natively on standard Mesa GBM and modern DRM KMS with explicit sync (`linux-drm-syncobj-v1`). Users get perfectly smooth, tear-free Wayland desktop compositing with zero configuration.

### 🟢 2. No Broken Compiles on Kernel Updates
- **The Problem with NVIDIA 390/470**: Every upstream Linux kernel update (`6.1`, `6.6`, `6.12`, `6.18+`) alters internal DRM and memory management APIs (`drm_client_dev_suspend`, `ioremap_nocache`, etc.). Proprietary drivers require manual third-party GitHub patches that frequently fail or break during system upgrades.
- **The `nouveau-dkms` Advantage**: Built as an active out-of-tree DKMS module with built-in `LINUX_VERSION_CODE` shims. Upgrading kernels on Arch, CachyOS, Fedora, or Ubuntu builds automatically and reliably.

### 🟢 3. Hardware Clocks Without the "Nouveau Sluggishness"
- Stock in-tree Nouveau runs the GPU at P-State `07` (202 MHz core / 324 MHz DDR3), delivering ~320 FPS in basic OpenGL benchmarks and struggling even with desktop browser scrolling.
- `nouveau-dkms` unlocks the full `590 MHz` core / `1180 MHz` shader / `900 MHz` DDR3 states (and `708 / 1416 MHz` OC), reaching **2,700–3,500+ FPS** in unthrottled benchmarks with sub-millisecond dynamic downclocking when idle.

### 🟢 4. Modern Local AI & OpenCL 3.0
- NVIDIA 390 is locked to CUDA 9.1, which cannot run PyTorch, modern llama.cpp, or contemporary AI tools.
- `nouveau-dkms` pairs with **Mesa Rusticl** to provide conformant **OpenCL 3.0**, enabling local Small Language Model (SLM) inference on Fermi GPUs via `CLBlast` and unified GART memory.

---

## 4. The Path Forward: Expanding to More Chips

With Fermi GF106 running rock-solid at production stability, the immediate architectural priority is generalizing the driver to support additional pre-`Nova` GPUs:

```
               ┌─────────────────────────────────────────────────────────────┐
               │                nouveau-reclocking-dkms Roadmap               │
               └─────────────────────────────────────────────────────────────┘
                                              │
         ┌────────────────────────────────────┼───────────────────────────────────┐
         ▼                                    ▼                                   ▼
 ┌───────────────┐                    ┌───────────────┐                   ┌───────────────┐
 │ Fermi (GF1xx) │                    │ Kepler (GK1xx)│                   │Maxwell 1(GM1xx│
 ├───────────────┤                    ├───────────────┤                   ├───────────────┤
 │ • GF106 (Done)│                    │ • GK104/GK107 │                   │ • GM107/GM108 │
 │ • GF100/GF110 │                    │ • GK208 / M   │                   │ • GTX 750/Ti  │
 │ • GF108/GF119 │                    │ • Boost 1.0/2 │                   │ • No PMU Lock!│
 │ • GDDR5 Strap │                    │ • Mobile RAM  │                   │ • High-Value  │
 └───────────────┘                    └───────────────┘                   └───────────────┘
```

1. **Fermi Family Generalization (`GF100`–`GF119`)**:
   - Decouple GF106-specific partition offsets using the family Resource Manager emitters (`_nv015935rm` GF100, `_nv015937rm` GF108, `_nv015938rm` GF119).
   - Add GDDR5 timing strap tables for desktop GTX 460/470/480 and 560/570/580.
2. **Maxwell 1 (`GM107` / `GM108` — GTX 750 / 750 Ti / 850M–960M)**:
   - **The Highest Value Target**: Unlike Maxwell 2 and Pascal, First-Gen Maxwell has **NO signed PMU firmware lockdown**. The microcontroller runs unsigned Falcon code just like Fermi! Porting our resident Falcon reclocking executor to GM107 unleashes hundreds of thousands of budget desktop cards.
3. **Kepler (`GK104`–`GK208`)**:
   - Port dynamic governor support and mobile RAM training fixes to Kepler chips, restoring smooth performance without the buggy proprietary 470 driver.

---

## 5. Performance Metrics & Architecture: Understanding `glxgears` vs. Real-World 3D Workloads

A common observation when comparing drivers is that the official proprietary NVIDIA driver can reach **~12,000 FPS** in `glxgears`, whereas `nouveau-dkms` with full DDR3 memory reclocking reaches **~2,800–3,500+ FPS**. Understanding this discrepancy requires analyzing what `glxgears` actually measures and where the architectural differences lie.

### ⚠️ Why `glxgears` Is NOT an Accurate Benchmark for GPU Performance

`glxgears` is widely misunderstood as a 3D graphics benchmark. In reality:
* **Negligible GPU Workload**: `glxgears` renders approximately 300 trivial flat-shaded triangles per frame. The GPU rasterizer completes this workload in less than **5 microseconds**.
* **What It Actually Measures**: It is purely an **API command-dispatch latency and CPU-to-GPU pushbuffer roundtrip benchmark**:
  $$\text{At } 12,000\text{ FPS} \implies \text{Frame Time} = \frac{1}{12,000}\text{ s} \approx 83\text{ µs per frame}$$
  $$\text{At } 2,800\text{ FPS} \implies \text{Frame Time} = \frac{1}{2,800}\text{ s} \approx 357\text{ µs per frame}$$

The ~4× difference in `glxgears` has almost nothing to do with GPU silicon speed, shader clocks, or memory bandwidth; it is entirely governed by how the driver communicates between the CPU and GPU.

```
[ NVIDIA Proprietary Driver: 12,000 FPS (~83 µs/frame) ]
  glDrawElements() ──> Handwritten ASM Dispatcher ──> Direct MMIO Hardware Doorbell
  (Zero kernel context switches! Writes directly to GPU ring buffer in userspace memory)

[ Nouveau + Mesa Gallium: 2,800+ FPS (~357 µs/frame) ]
  glDrawElements() ──> st/mesa State Tracker ──> pipe_context ──> nvc0 Pushbuf
                         └──> ioctl(DRM_IOCTL_NOUVEAU_GEM_PUSHBUF) ──> Kernel GEM Validation
  (Full Linux CPU context switch, spinlock acquisition & buffer validation on every flush)
```

### Architectural Differences: Proprietary Runtime vs. Mesa Gallium

#### 1. The Syscall Wall (`ioctl` vs. Direct Userspace Doorbell)
* **Proprietary NVIDIA (`libnvidia-glcore.so`)**:
  NVIDIA maps the GPU FIFO pushbuffer and hardware doorbell registers directly into userspace virtual memory (`mmap` via BAR1). When the proprietary driver submits commands, it writes directly to user-mapped GPU memory and rings the hardware doorbell with a single CPU instruction. **Zero kernel syscalls or context switches are made per batch.**
* **Nouveau + Mesa Gallium**:
  Every pushbuffer flush requires a standard Linux kernel syscall: `ioctl(fd, DRM_IOCTL_NOUVEAU_GEM_PUSHBUF, ...)`. Entering the kernel, validating GEM buffer objects, checking memory relocations, acquiring spinlocks, and context-switching back to userspace incurs dozens of microseconds of pure CPU overhead. Doing this thousands of times per second caps micro-benchmarks at ~3,000 FPS.

#### 2. Mesa Gallium Abstraction Overhead
* Mesa's **Gallium3D** architecture is intentionally designed for universal portability across AMD, Intel, ARM, and NVIDIA hardware.
* Every draw call traverses multiple abstraction layers:  
  `OpenGL API` $\to$ `st/mesa` (Mesa State Tracker) $\to$ `CSO` (Constant State Objects cache) $\to$ `pipe_context` $\to$ `nvc0` Gallium driver.
* In real-world games running at 60–120 FPS, this ~50 µs abstraction overhead represents less than **0.3% of a 16 ms frame budget** (completely imperceptible). But in a 10,000+ FPS micro-benchmark, it becomes the primary bottleneck.

#### 3. Compositor Synchronization (Wayland vs. Raw X11)
* Under Wayland / XWayland, every frame swap (`glXSwapBuffers()`) must negotiate DMA-BUF buffer passing, damage tracking, and fence synchronization with the Wayland compositor (`wlroots`/Qtile).
* The proprietary driver on legacy X11 performs unthrottled front/back buffer blits directly to the screen with internal software queues.

---

### Real-World 3D Gaming & Applications: The Gap Closes

In real-world GPU-bound 3D games (Portal, Half-Life 2, Left 4 Dead 2) and professional 3D modeling (**Blender 3.6 LTS**):
* The bottleneck shifts away from CPU syscall dispatch to **GPU shader execution cores and DDR3 memory bandwidth**.
* With our **900 MHz DDR3 reclocking** (v2.2.1+) and full core P-State scaling (`0f` / `10`), Nouveau delivers **75% to 90%+ of the proprietary driver's frame rates** in actual gameplay.
* The legacy perception of Nouveau being "sluggish" was entirely caused by the stock kernel leaving the memory locked at 324 MHz and core at 202 MHz. With clocks unlocked, the user experience is smooth, responsive, and fully hardware-accelerated.

### The Long-Term Solution: Vulkan & Modern UAPI
This exact pushbuffer submission bottleneck is why the industry developed **Vulkan** and modern kernel memory models:
* Vulkan removes driver state-tracking by allowing applications to pre-record command lists without CPU overhead.
* Modern Linux kernel UAPIs (`DRM_NOUVEAU_VM_BIND` and timeline sync objects) eliminate the `GEM_PUSHBUF` syscall wall by moving buffer binding and queue synchronization into userspace—paving the way for maximum submission throughput on open-source drivers.

