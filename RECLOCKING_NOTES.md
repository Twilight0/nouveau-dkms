# Nouveau & NVIDIA Proprietary Driver Reclocking & Architecture Guide (`RECLOCKING_NOTES.md`)

This document is the unified hardware, kernel, and reverse-engineering reference for GPU reclocking, performance optimization, and display architecture on the **Dell XPS L702X** laptop equipped with an **NVIDIA GeForce GT 555M** (Fermi / **GF106M**, Device ID `10de:0dcd`, 3072 MiB DDR3, 1920×1080 @ 120 Hz 3D panel) and sibling pre-`Nova` NVIDIA GPUs.

---

## Table of Contents
1. [Hardware & System Specifications](#1-hardware--system-specifications)
2. [Executive Summary & Component Status (`v2.1.0`)](#2-executive-summary--component-status-v210)
3. [Nouveau Reclocking Architecture & Bug Fixes](#3-nouveau-reclocking-architecture--bug-fixes)
4. [DDR3 Memory Reclocking Reverse Engineering (`mmiotrace` & Falcon Chronicles)](#4-ddr3-memory-reclocking-reverse-engineering-proprietary-trace)
5. [Display Engine & 120 Hz Investigation](#5-display-engine--120-hz-investigation)
6. [Performance Benchmark Summary](#6-performance-benchmark-summary)
7. [Modified Driver Files Inventory](#7-modified-driver-files-inventory)
8. [Resident Falcon Microcode Executor, S3 Recovery & PCIe Scaling (`v2.0.0`–`v2.1.0`)](#8-alternative-approaches-for-future-work)
9. [Reverse Engineering Methodology & Multi-Architecture Scope (`390.157` via REA)](#9-reverse-engineering-the-nvidia-390157-proprietary-driver-via-rea-roadmap--research)
10. [Concrete Reverse-Engineering Findings from `NVIDIA-Linux-x86_64-390.157` (`nv-modeset-kernel.o_binary` & `nv-kernel.o_binary`)](#10-concrete-reverse-engineering-findings-from-nvidia-390157-nv-modeset-kernelo_binary--nv-kernelo_binary)

---

## 1. Hardware & System Specifications

| Parameter | Value |
|---|---|
| **GPU** | GeForce GT 555M (Fermi GF106M, stepping A1, 144 CUDA Cores) |
| **Chipset ID** | `0x0c3680a1` (GF106, TSMC 40nm) |
| **VRAM Type** | **DDR3** (192-bit bus width, `43.2 GB/s` @ 900 MHz) |
| **VRAM Size** | 3072 MiB |
| **RAMCFG Strap** | `0x6` |
| **Internal Panel** | 1920×1080 @ 120 Hz (eDP-1 / LGD `0x02c5`, 396.36 MHz pixel clock) |
| **Active Kernel** | Linux CachyOS LTS (`6.18.55+`) |

### VBIOS & Synthetic P-State Table

| State | Core / Shader Clock | Memory Clock | Bandwidth | Voltage | PCIe Link | Usage Profile |
|---|---|---|---|---|---|---|
| `03` (P12) | 50 / 101 MHz | 135 MHz | 6.5 GB/s | 820 mV | Gen1 (`2.5 GT/s`) | Low-Power Idle / Standby |
| `07` (P8) | 202 / 405 MHz | 324 MHz | 15.5 GB/s | 820 mV | Gen1 (`2.5 GT/s`) | Standard 2D Desktop Idle |
| `0a` (P3, *Planned*) | 405 / 810 MHz | 650 MHz | 31.2 GB/s | 920 mV (`VID 0x03`) | Gen1 / Gen2 | Balanced 3D / Multimedia (Derived in §10.5–10.7) |
| `0f` (P0) | 590 / 1180 MHz | 900 MHz | 43.2 GB/s | 1030 mV (`VID 0x01`) | Gen2 (`5.0 GT/s`) | Full 3D Performance (`339.8 GFLOPS`) |
| `10` (OC, `NvFermiOC=1`) | **700 / 1400 MHz** | **900 MHz** | **43.2 GB/s** | **1030 mV** | **Gen2 (`5.0 GT/s`)** | **Verified Overclock (`403.2 GFLOPS`, +18.6% ALU)** |

---

## 2. Executive Summary & Component Status (`v2.1.0`)

| Component | Status | Description / Solution |
|---|---|---|
| **Core / Shader / Voltage Reclocking** | ✅ **Working** | Transitions `03` ↔ `07` ↔ `0f` ↔ `10` cleanly via `nvkm_cstate_prog()` with factory `1.030 V` regulation. |
| **Bidirectional DDR3 Memory Reclocking (`324` ↔ `900 MHz`)** | ✅ **Working (`v2.0.0+`)** | Custom resident Falcon microcode executor (`memx_exec_custom.fuc`) + hardware PHY latch (`0x001548 = 0x80000101`) + PMU clock domain protection (`0x0c`). See §8.3. |
| **S3 Suspend/Resume Recovery** | ✅ **Working (`v2.0.1+`)** | Hardware signature check (`SCRATCH0 == 0xE1EC0001`) detects cleared Falcon IMEM on wake and self-heals via cold bootstrap without timeout. See §8.4. |
| **Dynamic PCIe Gen1 ↔ Gen2 Scaling** | ✅ **Working (`v2.0.1+`)** | Automatically scales between PCIe Gen1 (`2.5 GT/s x16`) in `03`/`07` and Gen2 (`5.0 GT/s x16`, `8.0 GB/s`) in `0f`/`10`. See §8.4. |
| **Live TTM VRAM Telemetry & Battery Cap** | ✅ **Working (`v2.1.0+`)** | Exact TTM `VRAM:` readout in debugfs + `/run/nouveau/vram` snapshot and `BATTERY_CAP` AC/DC profile awareness. |
| **Zero-Flash VBlank Memory Reclocking** | 📋 **Root Cause Solved (§10.4)** | Host-side `gf100_ram_wait_vblank()` landed in `v2.1.0`; full zero-flash requires moving `WAIT_VBLANK` inside `memx_exec_custom.fuc` + `ISOHUB` watermark boost (`_nv031916rm`). |
| **Dynamic Clock Daemon (`nouveau-dynclockd`)** | ✅ **Working** | Automatically scales P-states (`03`/`07` ↔ `0f`) with thermal protection (`80 °C`) and battery cap. |
| **Backlight & Fan RPM Telemetry** | ✅ **Working** | ACPI EC hotkey driver (`dell-xps-brightness-dkms`) and `dell_smm_hwmon` RPM monitoring in `nouveau-ctrl` / `nouveau-tui`. |

---

## 3. Nouveau Reclocking Architecture & Bug Fixes

### 3.1 The Reclocking Execution Pipeline

```
Userspace write to /sys/kernel/debug/dri/0/pstate
  └─► nvkm_clk_ustate()           [clk/base.c]
      └─► nvkm_pstate_prog()      [clk/base.c]
          ├─► Memory Reclock Block (if NvFermiMemReclock=1):
          │   ├─► gf100_ram_calc(ram, khz)    [fb/ramgf100.c]
          │   │   ├─ BIOS rammap/ramcfg/timing lookup
          │   │   ├─ gt215_pll_calc() for refpll & mempll
          │   │   └─ Generates MEMX bytecode via ram_wr32/ram_wait/ram_nsec
          │   │      └─► memx_cmd()            [pmu/memx.c]
          │   │          └─ Packages into PMU data segment via 0x10a1c4
          │   ├─► gf100_ram_prog()             [fb/ramgf100.c]
          │   │   └─► ram_exec() → nvkm_memx_fini(exec=true)
          │   │       └─► nvkm_pmu_send(MEMX_MSG_EXEC)  [pmu/gt215.c]
          │   │           └─ PMU Falcon microcontroller executes bytecode autonomously
          │   └─► gf100_ram_tidy()
          └─► nvkm_cstate_prog()   [clk/base.c] — programs core and shader clock domains
```

### 3.2 Resolved Kernel Bugs

1. **PRIVRING Fault Loop on Register `0x10a580` (Resolved)**:
   - *Problem*: Register `0x10a580` is a PMU data lock that exists only on Tesla (`card_type < NV_C0`). On Fermi (`NV_C0` / GF100+), writing to it generated ~33,000 PRIVRING faults every 5 seconds and hung in an infinite `do { wr32(0x10a580) } while (rd32 != 1)` loop.
   - *Fix*: Guarded all accesses with `if (device->card_type < NV_C0)`.

2. **PMU Reply Timeout D-State Hang (Resolved)**:
   - *Problem*: `gt215_pmu_send()` used unconditional `wait_event()`. If the PMU encountered a delay or missing VBlank interrupt, the calling thread entered uninterruptible sleep (D-state) forever.
   - *Fix*: Replaced `wait_event()` with active polling and a strict 100ms timeout window.

3. **Missing GDDR5 Training Guard on DDR3 (Resolved)**:
   - *Problem*: `gf100_ram_calc()` unconditionally called GDDR5 hardware training routines that do not exist on DDR3 cards, hanging the Falcon engine.
   - *Fix*: Added a check to skip GDDR5 training when `ram->base.type == NVKM_RAM_TYPE_DDR3`.

4. **Silent Error Swallowing (Resolved)**:
   - *Problem*: Return codes from memory reclocking failures were overwritten before exiting `nvkm_pstate_prog()`.
   - *Fix*: Correctly propagate PMU and MEMX error codes up the call stack.

5. **Display Hub Clock Locking & Black Screen Prevention (`gf100_clk_calc`)**:
   - *Problem*: In `nvkm/subdev/clk/gf100.c`, `gf100_clk_calc()` attempted to recalculate and reprogram display crossbar/hub clocks (`hubk07`, `hubk06`, `hubk01`) on every performance state change. On Fermi (particularly with high pixel-clock eDP 120Hz displays at 396.36 MHz), reprogramming the hub causes display FIFO underruns, display link loss, or black screens during clock transitions.
   - *Fix*: Omitted `hubk07`, `hubk06`, and `hubk01` from dynamic frequency transitions. The display hub remains locked to its stable boot frequency, enabling seamless core (`gpc`), shader, and `rop` scaling without display jitter.

6. **VBIOS VMAP Undervoltage Correction (`nvkm_pstate_new`)**:
   - *Problem*: `nvkm_volt_map` mapped the `0f` voltage ID to 862.5 mV (VID `0x04` = 870 mV) instead of factory 1.030 V (VID `0x01`), causing instability/freezes under 3D load.
   - *Fix*: Enforcing `cstate->voltage = 0x67` (1030000 µV fallback) for pstate `0x0f` guarantees factory 1.030 V delivery under full 3D load.

---

## 4. DDR3 Memory Reclocking Reverse Engineering (Proprietary Trace)

From the demmio-decoded mmiotrace of the NVIDIA 390.157 proprietary driver (`nvidia_full_reclock_trace.txt`), the complete register sequence for DDR3 reclocking on GF106 is documented below.

### 4.1 Host-Side PHY Configuration (Prior to MEMX Execution)

| Register | 324 MHz (P7/P8 Idle) | 900 MHz (P0 Load) | Description |
|---|---|---|---|
| `0x10f050` | `0xff000450` | `0xff001050` | PFB broadcast mode control |
| `0x10f440` | `0x22f84f10` | `0x22f84f10` | DDR3 impedance calibration |
| `0x10f444` | `0x04cc001f` | `0x04cc883f` | DDR3 termination tuning |
| `0x10f468` | `0x00001005` | `0x00020020` | DDR3 data strobe timing |
| `0x10f808` | `0x08020004` | `0x08020004` | PHY DLL configuration |
| `0x10f824` | `0x000279e7` | `0x00021e67` | PHY DLL feedback divider |

### 4.2 Critical DDR3 Timing Registers (Inside MEMX Script)

| Register | 324 MHz (Idle) | 900 MHz (Load) | Timing Parameter |
|---|---|---|---|
| `0x10f290` | `0x061a3813` | `0x0e44922e` | `tRAS` / `tRC` |
| `0x10f294` | Derived from JEDEC | `0x4ce3848c` | `tRCD` / `tRP` |
| `0x10f298` | `0x44060411` | `0x440e0711` | `tWR` / `tRFC` |
| `0x10f29c` | `0x00001e6a` | `0x000050b6` | `tFAW` |
| `0x10f2a0` | `0x42e28069` | `0x42e38069` | `tRRD` / `tWTR` |
| `0x10f224` | VBIOS default | `0x0e070c07` | Arbiter timing |

### 4.3 MEMPLL Frequency Dividers (`0x132004`)

- **324 MHz**: `0x00071806` ($M=6, N=24, P=7$)
- **900 MHz**: `0x0002230b` ($M=11, N=35, P=2$)

### 4.4 DDR3 Mode Register Sequence

1. `0x10f300` $\leftarrow$ `0x00001520` (MR0: DLL Reset + CAS Latency)
2. `0x10f300` $\leftarrow$ `0x00001420` (MR0: DLL Stable)
3. `0x10f320` $\leftarrow$ `0x002000a0` (EMR2: CAS Write Latency for 900 MHz)
4. `0x10f300` $\leftarrow$ `0x00001e04` (MR0: CAS=7, Burst Length=8)
5. `0x10f870` $\leftarrow$ `0xaaaaaaaa` (ZQ Calibration pattern)
6. `0x10f324` $\leftarrow$ Write leveling sequence (`0x03cb`, `0x06cb`, `0x01cb`, `0x03ca`, `0x06ca`, `0x01ca`)
7. `0x10f830` $\leftarrow$ `0x01000011` $\rightarrow$ `0x00000011` (PHY DLL reset pulse & release)

### 4.5 Direct-MMIO Replay of the Proprietary PMU Script (current approach)

**Why the PMU path can never work here.** `gt215_pmu_send()` (used unchanged by
GF100 *and* GK104) touches `FIFO_PUT`/`RFIFO_GET` at `0x10a4a0`/`0x10a4cc`.
On this GF106 these fault with `PRIVRING` and the 100 ms reply timeout fires,
so neither `MEMX_MSG_INFO` nor `MEMX_MSG_EXEC` ever reach the Falcon.

**Why the first direct-MMIO attempt corrupted VRAM (2026-09-06).** Executing
`gf100_ram_calc()` from the host worked mechanically, but that function is Ben
Skeggs' **GDDR5** sequence for the GF100 reference board. Its mode-register
writes (`0x10f300 = 0x0000011d / 0x0000084d`) are GDDR5 MRS encodings; splicing
DDR3 timing values into it does not make it a DDR3 sequence. A 324→324 "no-op"
transition ran the full script and killed the framebuffer (`PAGE_NOT_PRESENT`
faults on every channel, `PRIVRING` fault at `0x13b0d4`).

**What the blob really does.** `tools/decode-pmu-memx.py` decodes the script
the 390.157 driver streams through `PDAEMON.DATA` (`0x10a1c4`). The framing is
`(nwords << 16) | opcode`:

| opcode | meaning | nouveau equivalent |
|---|---|---|
| `0x21` | `wr32(addr, val)` pairs | `ram_wr32` |
| `0x2e` | delay (ns) | `ram_nsec` |
| `0x00` / `0x01` | set data / set addr for next wait | – |
| `0x15` | wait `(addr & mask) == data`, timeout | `ram_wait` |
| `0x14` | wait for vblank on head (45 ms timeout) | `ram_wait_vblank` |
| `0x20 1,0` / `0x20 0,0` | block / unblock host | `ram_block` / `ram_unblock` |
| `0x34 0x0a/0x0b` | unknown marker (also appears as comments in upstream `ramgf100.c`) | ignored |
| `0x3a n` | unknown, always after `0x13d8b4 <= 0` | treated as 10 µs delay |
| `0x16` | end | – |

Two scripts exist: **324 → 900** (72 writes, MEMPLL `0x132004 = 0x0002230b`)
and **900 → 324** (43 writes, `0x00071806`). After the script the host applies
the PHY tune (`0x10f824`, `0x10f468`, `0x10f444`, `0x10f050`, and `0x10f808`
for 324). The DDR3 mode-register dance is `MR0 0x1520 → 0x1420` (DLL reset),
`MR2 0x002000a0`, `MR0 0x1e04`, ZQ pattern `0xaaaaaaaa`, write-levelling on
`0x10f324`, then a `0x10f830` DLL reset pulse.

**Implementation.** `gf100_ram_calc()` now dispatches DDR3 boards to
`gf100_ram_calc_ddr3()`, which replays these two scripts verbatim through the
`ramfuc` layer in `direct_exec` mode:

- Reads the current memory clock and **returns without touching DRAM** if it
  already matches the target (this alone would have prevented the crash above).
- `ram_block`/`ram_unblock` are a host-side replica of the PMU firmware's
  `memx_func_enter`/`memx_func_leave` (GF100 variant, `pmu/fuc/memx.fuc`):
  gate engine→FB traffic (`0x001620` clear `0xaa2` then bit 0, `0x0026f0` clear
  bit 0), assert **FB_PAUSE** through the PDAEMON window (`0x10a7e0 = 4`) and
  wait for the ack in `0x10a7c0 & 4`, then disable local IRQs. Leave reverses
  the order. IRQs are held only inside this window, not for the whole calc.
- `ram_wait_vblank` polls the exact bit the Falcon polls, `NV_PPWR_INPUT
  HEAD0_VBLANK`, via `0x10a7c4 & 8`.

**Second test (2026-09-06, 15:59).** With the correct DDR3 script but `block`
implemented as *only* `local_irq_save()`, 324→324 was a clean no-op, and
324→900 executed — but PGRAPH immediately faulted (`PAGE_NOT_PRESENT` on
wezterm's channel), BAR flushes started timing out, and `nvkm_intr` read
`0xffffffff` from `PMC_BOOT_0`: the memory controller had hung. Display stayed
intact. Diagnosis: disabling host IRQs stops the *CPU*, but PGRAPH/PFIFO kept
issuing VRAM traffic while DRAM was in self-refresh. The PMU avoids this with
the FB_PAUSE handshake above, which the replay now performs too. The "system
became unresponsive over ~60 s" symptom was every `g84_bar_flush` spinning 2 s
under `spin_lock_irqsave` on a dead GPU — not a leak.

Only the two VBIOS memory clocks (324 / 900 MHz) exist for this board; the
P-state table has exactly three entries (`03`, `07`, `0f`).

**Third test (2026-09-06, 16:56).** With FB_PAUSE/vblank implemented via the
PDAEMON I/O window from the host, the log showed `MMIO read FAULT at 10a7c4
[PRIVRING]` (×9) → `ramfuc_wait_vblank timeout` → DRAM retimed with display
and engines live → display lost, VRAM corrupted, `PMC_BOOT_0 == 0xffffffff`.
The PDAEMON I/O block (`0x10a4xx` queues, `0x10a6xx` MEMIF, `0x10a7xx` GPIO)
is *entirely* host-inaccessible in the state nouveau leaves the Falcon in.

### 4.6 The actual root cause: PDAEMON I/O block is gated after Falcon reset

Re-reading the mmiotrace around the blob's PMU bring-up settles it. The
proprietary driver **does** use `FIFO_PUT`/`RFIFO_GET` (`0x10a4a4`,
`0x10a4b4`, `0x10a4c8`, `0x10a4cc`) — the exact registers that fault for us.
Right after resetting the Falcon (`PMC.ENABLE` toggle) and *before* uploading
firmware, it performs:

```
W 0x10a048 0x00000001   PDAEMON.ACCESS_EN.CHANNEL_SWITCH
W 0x10a090 0x00010040   PDAEMON.UNK090 bit16
W 0x10a47c 0x701074ef   PDAEMON.CHANNEL_SETUP (VALID | dummy channel)
W 0x10a058 0x00000002   PDAEMON.CHANNEL_TRIGGER.LOAD
R 0x10a128              UC_STATUS  0x000fd23d -> 0x000f023f (ctxsw done)
W 0x10a004 0x00000008   INTR_ACK
W 0x10a600..0x10a610    MEMIF.PORT[0..4] = 0,0,4,5,6
```

Only after this does the `0x10a4xx` block respond. `gt215_pmu_init()` (shared
by GF100 and GK104) does none of it; on Kepler the block is evidently open by
default, on this GF106 it is not — hence two months of PRIVRING faults on
`0x10a4a0`/`0x10a4cc`.

The patch now replicates this sequence in `gt215_pmu_init()` for `NV_C0`
after the scrub wait. With the queue usable, the DDR3 reclock goes through the
**normal MEMX path**: `gf100_ram_calc_ddr3()` builds the decoded script via
`ramfuc`, the PMU executes it and handles FB_PAUSE/vblank itself. The
host-side `direct_exec` mode is retained behind `NvFermiMemDirect=true` for
experiments only; it is documented as unsafe (no FB_PAUSE possible from host).

### 4.7 Live-fire results: firmware boots, then dies; stale trigger is poison (2026-09-06/07)

With the unlock patch installed, boot-time `gt215_pmu_init()` runs the unlock
and nouveau's PMU firmware demonstrably boots: `H2D`/`D2H` read back as
`0x00800270`/`0x008002f0`, which are exactly the `fifo_queue`/`rfifo_queue`
DMEM link addresses from `nvkm/subdev/pmu/fuc/host.fuc` (confirmed at
`gf100.fuc3.h:164` and `:197`). Only firmware that executed `host_init` could
program those values, so the firmware upload (DATA/CODE ports) and START work.

But the first real use (`nouveau-ctrl set 0f` -> MEMX INFO query) fails:
`pmu reply timeout`, with two `MEMX 584d454d`-filled "unexpected message"
warnings consumed from stale/unwritten RFIFO slots. Afterwards the Falcon is
found halted (`UC_CTRL = 0x10`, i.e. `STOPPED`), all queue regs read 0, and a
live `ENTRY=0` + `START_TRIGGER` is ignored (no firmware in memory anymore).

Key experiments (all via raw BAR from userspace, root):
- A manual PMC toggle (`0x000200` bit 13 off/on) is a *real* reset: `STATUS_BUSY`
  1->0, `UC_STATUS` -> `0x000f023f` (idle, no channel). Note the boot-time reset
  leaves `UC_STATUS = 0x000fd23d` instead -- residue of resetting a Falcon that
  still had the VBIOS channel loaded.
- Replaying the blob's `CHANNEL_SETUP = 0x701074ef` (`VALID | TARGET=3/SYSRAM_
  NO_SNOOP | 0x1074ef000`, a sysram DMA allocation from the *captured* boot)
  plus `CHANNEL_TRIGGER.LOAD` visibly engages the ctxsw engine (`UC_STATUS`
  `f023f -> fc33d`, CTXSW no longer idle) but never completes. It programs DMA
  from/to a garbage physical address on *this* boot.
- Manual firmware re-upload (parsed `gf100.fuc3.h`, 915+943 words via DATA/CODE
  ports, with scrub wait + unlock, with and without MUTEX/ACCESS_EN/TRIGGER
  variants) never lands: DMEM readback stays zero. The DATA/CODE ports appear
  gated in the freshly-reset state; at boot they were open (upload provably
  landed), so *something* in the boot path -- plausibly the trigger attempt
  itself -- opens them as a side effect.
- Repeated stale-trigger + toggle + upload + START pokes froze the desktop
  (garbage ctxsw DMA writing to random system RAM). Lesson: never replay the
  captured `CHANNEL_SETUP` again, in the driver or by hand.

Consequence: the `CHANNEL_SETUP`/`CHANNEL_TRIGGER` replay is removed from the
patch (kept: pause-before-reset, INTR routing/enable, `ACCESS_EN`, `UNK090`
bit16, `INTR_ACK`, MEMIF port mapping -- all plain writes that provably stick).
Next experiment is a clean boot without the trigger: if `H2D` still comes up as
`0x00800270` and the firmware *survives* to first use, the trigger was the
poison and MEMX reclocking should work end to end.

---


### 4.8 Selective PUT/RGET-read gating: the Falcon core side was never unlocked (2026-09-07)

The `set 0f` attempt with full dynamic-debug finally produced the decisive
fault pattern (no trigger involved anywhere on this boot):

```
fb: DDR3: reclocking memory 324000 -> 900000 kHz
bus: MMIO read FAULT at 10a4a0 [ PRIVRING ]      <- FIFO_PUT read (send)
bus: MMIO read FAULT at 10a4cc [ PRIVRING ] x9   <- RFIFO_GET reads (recv poll)
pmu reply timeout
```

while `PUT` *writes*, `GET`/`RPUT` reads and all `DATA`-window accesses go
through silently. The driver's message reached DMEM and the PUT bump landed;
only reads of exactly the two registers the **Falcon core itself** reads
(its `PUT` poll in `host_send`, its `RGET` poll for reply space) are gated.
Reinterpretation: the boot-time unlock (`ACCESS_EN`, `UNK090`, MEMIF) opened
only the *host* side. The *Falcon-core* side needs a valid loaded channel --
which is what the blob's `CHANNEL_TRIGGER.LOAD` was actually for. Without it
the firmware boots (writes only), idles healthy (asleep, never polls `PUT`;
5-minute idle watch is clean, `UC_CTRL = SLEEPING`), and halts on its first
`PUT` poll when the first host message wakes it. That single mechanism
explains idle-health, first-message-death, the silent post-mortem (halt, not
a host-visible violation), and why no host fault lines appear at INFO time.

The fix replays a channel descriptor that is valid *by construction*: the
live VBIOS channel (`CHANNEL_CUR`, `0x10a050`) is saved before reset (reads
may fault pre-reset and yield zero, disabling the reload gracefully) and,
falling back to the post-reset register if the reset retained it, written
back to `CHANNEL_SETUP` + `TRIGGER.LOAD` after the unlock, with completion
detected via `CHANNEL_CUR` match + `CTXSW_IDLE`. No captured/stale pointer is
replayed anywhere, so no garbage DMA is possible. Stale queue pointers (a
reset does not clear them; VBIOS-era `RPUT` caused the phantom-slot warnings)
are explicitly zeroed after START. All milestones are `nvkm_info`-visible at
boot (saved/pre/post/effective channel, reload result) for forensics.

Two adjacent findings from the same session, kept separate:
- `set 07` (core-only) re-gates/power-downs the whole PDAEMON block:
  post-`07` every access faults (`13b0d4` PWR write during the volt step,
  `10a100` read after). The boot unlock does not survive a reclock; a
  re-unlock in the reclock path (after the volt step) will be needed next.
- `nvapeek` prints `...` for zero-valued reads; cross-checked with raw BAR
  reads, so `...` == `0x00000000`, not an error.


### 4.9 Diagnostic build: pristine-INFO self-test, window check, send audit (2026-09-07)

To stop theorizing and measure, a diagnostic-only module adds four
forensics (all Fermi-gated, all info-visible, to be removed afterwards):
- **D1 window check**: magic pattern via seg1 to unused send slot 7, read
  back via seg2 (blob-style raw DMEM reads), slot restored after. Settles
  whether seg1 offsets are byte-aligned with firmware DMEM addressing.
- **D2 pristine INFO self-test**: one `MEMX_INFO` query at the end of
  `gt215_pmu_init`, before any clock is ever touched -- the first
  host->PMU message against a just-booted firmware, with ret/reply logged.
  Success proves message handling works (killer = later reclock step);
  failure proves the message path itself is broken.
- **D3 re-unlock in the DDR3 path**: host-side unlock writes (no channel
  games) re-applied right before MEMX, with PUT/GET logged before/after
  (their reads fault visibly if the volt step re-gated the block).
- **D4 send audit**: every `pmu_send` (proc/msg/data) and every consumed
  packet (with slot) info-logged; replies logged on success (timeout warn
  already exists). Idle-proven silent, verbose only around reclock.


### 4.10 Firmware fix: skip the RFIFO space-wait (core-side RGET gated) (2026-09-07)

Disassembly of the checked-in `gf100` PMU image (`envydis -m falcon -V
fuc3`, plus reference-assembled instruction encodings) located the
`host_recv_wait` loop at code offset `0x559` (`RGET` poll triple,
`RPUT` poll, `xor 8`, `cmp`, `bra e -26`). Combined with the
selective-fault pattern (§4.8: host reads of `PUT`/`RGET` fault while
`GET`/`RPUT`/writes/`DATA` pass), the mechanism is now precise: the
I/O gating also blocks the **Falcon core's** read of `RGET`, so the
firmware consumes the first message (`GET` advances — core `PUT` reads
work), then halts inside `host_recv_wait` before writing any reply
(`RPUT` never advances). Idle health (asleep, never polls) and
first-message death follow directly.

Fix (Fermi `gf100` image only; Tesla/Kepler+ untouched): the 29-byte
wait is skipped with `bra +29` patched over its first instruction
(code offset `0x559`: `f1 17 cc 04` -> `f4 0e 1d`, target `0x576` = the
old fall-through into slot computation). Same length, no address
shifts, all header labels stay valid; verified by re-disassembly.
Skipping is safe: the host serializes all sends (`pmu->send.mutex`)
and drains replies synchronously (5-minute idle watch proved zero
unprompted firmware traffic), so at most one of eight RFIFO slots is
ever outstanding. `host.fuc` documents the change for future
regenerations (full-regen is currently blocked by envyas/CPP dialect
drift: `#define` handling and multi-statement lines no longer parse).
Worst case if wrong: identical halt as today (fresh firmware upload
every boot makes it fully reversible).


### 4.11 Reply without RPUT: NOP the bump+trigger, poll slots (2026-09-07)

Elimination complete on the reply path: the firmware demonstrably
consumes (`GET` advances — core `PUT` reads and the whole
dispatch (`find`/`send_proc`/MEMX queue) work), but no reply is ever
visible and the post-mortem is `STOPPED` with pointers cleared. The
remaining unproven core-side steps were the `RPUT` bump and the
`INTR_TRIGGER` MMIO writes in `host_recv` — both fault candidates
under the same direction-gating (§4.8), and the trigger is redundant
anyway (the driver polls; 5-minute silence proved zero async traffic).

Fix (Fermi `gf100` image only): the 10-byte `RPUT` bump
(`mov/shl/iowr` at code offset `0x592`) and the 12-byte trigger block
(`0x59e`) are NOP-filled with `clear b32 $r0` (`bd 04`, keeps the ZERO
register zero, lengths preserved, verified by re-disassembly).
Driver side (`gt215_pmu_send`, Fermi only): the reply wait additionally
polls all 8 reply slots directly for the awaited `(process, message)`
and consumes via an `RGET` write (host writes work); the `RPUT` path is
kept as a belt-and-suspenders fallback. Stale slots cannot false-match
(their message word is never a valid reply id) and the driver's own
packet lives in the disjoint send area. Single-flight usage
(`pmu->send.mutex` + synchronous drain) keeps slot accounting safe.
If replies now arrive, the RPUT-bump fault is confirmed and memory
reclocking should proceed end to end; if slots stay unchanged, the
fault lies earlier (reply stores / `memx_info`).


### 4.12 Verify-and-retry upload, true-slot logging (2026-09-07)

Since fault logging itself is flaky on this block (same access logs one
boot, silent the next), silent drops can't be excluded by absence of
logs. The init now verifies every DATA word with explicit per-word
indexing (robust against any auto-increment step) and rewrites gaps,
bounded to 3 passes with per-round mismatch counts, then logs the true
queue slots via seg2 raw reads -- so the boot log proves landed-vs-
missed with no userspace probing. The pointer clear also reads back
(and retries once), logging final values. Windows sniffing was
considered and rejected: same driver architecture (nothing new to
learn), trap overhead risks the timing-sensitive training, the gap was
never MMIO content (the trace is complete) but sysram descriptor bytes
(sniffers can't see RAM) -- better covered by disassembling the blob's
embedded PMU ucode / VBIOS firmware with the installed `envydis`.


### 4.13 Bump verify-and-retry: PUT delivery is racy (2026-09-07)

The counters settled it: `DSCRATCH` reads zero while the same boot's
firmware was alive earlier, i.e. the `PUT` bump never reached the
Falcon (no interrupt ever fired, firmware kept sleeping). Across boots
the identical write lands, vanishes silently, or faults loudly --
marginal BAR-to-PDAEMON posting, not a protocol bug. The send path now
(Fermi only): requires two consecutive agreeing `PUT` reads before
trusting the slot; verifies the bump landed via readback and retries
(packet rewrite + re-unlock, bounded x3), rewriting only when the
pointer demonstrably did not advance (never tearing a slot the Falcon
may already be reading; ambiguous reads proceed with a warning). The
`RGET` consume bump gets a readback log (no retry in IRQ context).
Either the bump sticks and INFO proceeds deterministically, or it never
sticks and the gating itself -- not messaging -- is proven the wall
(next: proper allocated-descriptor channel).


### 4.14 RPUT restored, parasite-rejecting INFO matching (2026-09-07)

Without an `RPUT` advance replies are undetectable (no other
trustworthy signal exists), so the bump is back in the Fermi image and
only the `INTR_TRIGGER` stays NOP-filled (the driver polls). Matching
is now sanity-gated for `INFO`: base must be nonzero and both words
under `0x1000` (true reply is `base ~= 0xCC`, small size). VBIOS junk
(`0x584d454d` payloads) and latch echoes of our own packet (`base 0`)
fail the check and are drained as parasites without completing the
wait -- so a success is provably real and a timeout provably means no
valid reply exists. The slot-polling fallback is removed (it could
false-positive on echoes).


### 4.15 Unconditional queue-area zeroing (2026-09-07)

Host-side zero of DMEM `0x270-0x36f` (both FIFO areas) after upload,
before START: idempotent if the upload landed, clearing if VBIOS
staleness survived it. Proc structs untouched. Firmware not running,
so no race. Prediction matrix for the next boot's self-test: clean
timeout with zero consumes (dispatch-drop confirmed, VBIOS message
content), vs `ret 0` (stale slots were the whole story).


### 4.16 Pre-upload I/O-open probe (2026-09-07)

`RPUT` reads 2 with `RGET` at 2 and zero fault lines, minutes after a
*verified* zeroing, means early-init writes are silently lost while the
block still reports open later (D1 MATCH minutes after). The upload now
waits for a `PUT` write/readback round-trip (bounded 5s, polled
1-2ms), logging open vs never-opened, before a single image word goes
out. If D2 then succeeds, the race was the whole wall; if it fails
identically with an open-proven I/O, the wall is logic, not timing.


### 4.17 Watchdog-gated interrupt accounting around INFO (2026-09-07)

`DSCRATCH(0)` counts every Falcon interrupt (including our `PUT`-bump),
`DSCRATCH(1)` every idle loop — but the firmware's own watchdog timer
fires several times per second, burying the single-bump signal in noise.
The self-test now freezes the watchdog (`WATCHDOG_ENABLE = 0`, restored
after), verifies frozen-ness with two reads 100ms apart, then sends INFO
up to 3 times and reports `intr`/`loops` deltas. `intr +>= 1` with a
frozen counter proves bump arrival; `loops` delta proves idle-loop
processing; both zero with frozen counters proves the bump lost in I/O
gating (fix = proper channel, not messaging). Adds ~0.4s to boot,
diagnostic only.


### 4.17 Full-range true sweep + blind image rewrite (2026-09-07)

The 8-word TRUE-log only samples slot 0 of each area. Widened to the
full `0x270-0x36f` range (64 words, still the first seg2 use in the
boot, so still pristine-genuine — seg2 is never written through,
unlike seg1): `N/64 nonzero` plus the first four nonzero address=value
pairs. Zeros-then-M across the range is the partial-upload smoking gun
(first words land, later ones silently dropped); all-zeros points
firmware-side. Immediately after, a blind second pass rewrites the full
data image (idempotent if landed, repairing if missed — no readback
theater). Both run pre-START with the Falcon halted, so no race either
way.


### 4.18 Host-side zeroing of MEMX/HOST queue structs (2026-09-07)

RPUT/RGET both advance with the firmware alive+sleeping, yet no valid
reply ever appears: consistent with `send_proc` silently dropping into
a VBIOS-full foreign queue (by design: full means skip, no fault, no
halt) while `GET` still bumps unconditionally. The idle loop should
drain such queues, but belt-and-suspenders wins here: init now zeroes
`qput`/`qget` + private queue data for the HOST (`@0x60`) and MEMX
(`@0xb8`) structs (layout from `gf100.fuc3.h` ID-word scan, stride
`0x58`; `id`/`init`/`recv` words deliberately preserved), in addition
to the FIFO slot areas. Idempotent if landed, repairing if VBIOS-
retained; pre-START so no race. If D2 still consumes phantoms
afterwards, the queue-full theory is dead and only dispatch-drop
(VBIOS message content) or reply-store faults remain.


### 4.19 TEST ping: looper-dead vs INFO-specific (2026-09-07)

`test_recv` is a near-no-op that bumps `DSCRATCH(2)` (observable via
the trustworthy control path; side effect is arming a timer, accepted
for diagnostics). The self-test now fire-and-forgets `(PROC_TEST,0,0,0)`
(no reply wait), sleeps 200ms, and compares `DSCRATCH(2)`: advanced
means the looper dequeued, dispatched and ran handler code (so INFO's
failure is INFO-specific — reply generation); static means nothing
message-driven can ever work (custom executor, which needs no looper,
becomes mandatory). `PROC_IDLE` was rejected for this (its recv is a
bare `ret` with no observable).


### 4.20 Keepalive pings to keep the looper hot (2026-09-07)

`intr +N / loops +0` proved the handler runs while the idle loop never
resumes: every host message queues behind a sleeping looper (with
boot-to-boot variance from an early timing race — sometimes it drains,
sometimes it sleeps through). Five fire-and-forget `TEST` pings
(~20ms apart, no reply wait) now precede the INFO loop, each another
wake chance plus a longer awake window via `p2`. Cheap, driver-side
only, no firmware change; if D2 still shows `loops +0`, the looper is
unwakeable and only ENTRY+START-driven code (custom executor, §8.1)
can ever run here.


### 4.21 Custom executor built (2026-09-07)

`tmp/memx_exec_custom.fuc` (559 bytes, pure envyas dialect, every
encoding reference-assembled first): main loop over a custom TLV script
(op + fixed args, opcodes 1 ENTER / 2 LEAVE / 3 WR32 / 4 WAIT / 6 VBLANK,
op 5 DELAY takes host-precomputed iters), ENTER/LEAVE via `FB_PAUSE` +
`0x1620`/`0x26f0` gating copied from `memx_func`, engine MMIO through
inlined `rd32`/`wr32` portal subroutines, all waits bounded with
`ERROR = 0xDEADxxxx` fallbacks, `DONE = 0xE1EC0001` in `DSCRATCH(2)`,
verified by re-disassembly. Driver (`ramgf100.c`): script emitter
(`WR`/`NSEC`/`WAIT`/`block`/`unblock`/`vblank` redefined to emit;
DELAY iters `(nsec*203)/3000` formally >= requested time; WAIT bound
generous with host 2s backstop; VBLANK fixed spin, safe under pause),
program upload to IMEM 0 via CODE ports, script to DMEM `0x1004` with
count at `0x1000`, `ENTRY=0`+`START`, poll DONE, verify clocks. PMU
firmware sacrificed for the window (proven safe halted); `direct_exec`
removed (unsafe path deleted, not deprecated); `prog()` early-returns
for DDR3 (calc runs synchronously, `fb==NULL` guard verified).


### 4.22 Pipeline probe before the full program (2026-09-07)

`STOPPED` + zero `DSCRATCH` can't separate "never started" from
"died instantly". An 8-instruction probe (`DSCRATCH(2)=0xBEAC0001`,
spin; no DMEM reads, no engine regs) now runs first in the glue, with
a 200ms window: marker present proves `ENTRY`/`START`/IMEM-upload and
core MMIO all work (fault is then op-specific — bisect engine regs);
absent means the loading layer itself failed (fix upload/`ENTRY`,
not opcodes). Live-overwrite of the spinning probe by the full program
is bounded (worst case a faulted halt; `START` reboots cleanly).


### 4.23 Reset-before-ENTRY in the glue (2026-09-07)

First live run: probe uploaded cleanly, `START` issued with zero fault
lines, `DSCRATCH` never moved. Post-mortem `STOPPED` + dark block: the
volt step fault-halts the Falcon, and `START` on a fault-latched core
is ignored (it only boots from fresh-reset or sleep). Fix, glue-only:
PMC bit-13 toggle + full re-unlock (MEMIF included, reset clears it)
before the probe phase. No asm change; worst case unchanged (timeout).

Follow-up: the toggle alone is insufficient — the scrubber (`0x10a10c`
bits) runs after reset and can wipe the image mid-upload or fault an
early `START`. Init waits for it; the glue didn't. Added the same
bounded scrub wait post-toggle. If the marker still stays absent with
zero faults, the remaining suspects are CODE-port upload misses
(write-only, unverifiable) vs `START` ignored on halted cores.


### 4.24 Build hygiene: always nuke src/ before makepkg (2026-09-07)

Incremental `src/` reuse across patch versions produces mixed old/new
objects that link into a `.ko` which then dies at the BTF/objcopy stage
(`file format not recognized`) — misleading, looks like a code bug.
`rm -rf src pkg` before every `makepkg -f`, and verify the built `.ko`
(strings + firmware byte patterns), never just the patch file. Two
separate incidents (stale tree diffed into the patch; stale objects
linked into the module) both traced to reusing build directories.

### 4.25 `nv-kernel.o` (340.108): `_nv006997rm` host-side DDR training sequence (2026-10-26)

Linear `objdump` extraction (`testing/nv340_nv006997rm_disasm.txt`,
reproducible via `tools/extract-nv6997-writes.py`) of the DDR
link-training routine at `.text+0x2976b0` (~3.7 KB, 54 register
writes), located via string-xref to the `Failed ... sddr3 link
training` logs. Register-address convention: `ESI` = addr,
`EDX` = value (struct field), `RDI` = adapter cookie, near `call` =
write helper (values computed at runtime from VBIOS tables, so only
the address order transfers — never the values).

Write order (values are per-board, addresses are the finding):

```
0x10f60c → 0x10f304 → 0x10f328 → 0x10f320 → 0x10f30c → 0x10f304
→ 0x10f300(MR0) → 0x10f224 → 0x10f290/94/98/2a0/2a4/2a8 (timings)
→ 0x10f200 → 0x10f604/610/614 → 0x10f808 → 0x1373ec/f8
→ 0x10f30c/304 (MR loop) → 0x10f328/320 → 0x10f340/344/348 (arbiter)
→ 0x100750/100710/100c00 (host DMA fences) → 0x61c140 (display arbiter)
→ 0x10f618 → 0x10f870(ZQ cal) → 0x10f29c
→ 0x10f30c/308/300 (final MR0/MR1/MR2/MR3 + DLL reset pulse)
```

Gap vs our 390-derived `fexec` script (block 29, 900-up): **14 registers
the script never programs** — `0x10f2a4/2a8` (extended timings),
`0x10f304/308/30c` (full MR1/MR2/MR3 bank; script writes MR0/`0x10f300`
only), `0x10f328`, `0x10f340/344/348`, `0x10f604/60c/618`,
`0x61c140`, `0x100710/100750`. The **MR-bank gap is the prime suspect**
for non-GF106 DDR3 boards (issues #2 GF119M 410M, #5 GF108M):
Hynix/Samsung binnings needing different ODT/RTT_NOM get no MR1–MR3
programming from our script. Fix direction: extend `fexec_code.inc`
with the MR1/MR2/MR3 writes (values from the board's own VBIOS strap,
never copied), plus the `0x10f2a4/2a8` timing pair — one new Falcon
`cmd`, fail-safe refuse on unknown boards (Class B board registry).

### 4.26 Chip-support order: Fermi → Kepler → Maxwell/Pascal GSP (2026-10-26)

Goal is full support for chips whose blobs no longer build on current
kernels — each generation on its own terms, not Fermi code ported over:
1. **Fermi** (`GF100`–`GF119`, 390.157): proving ground. 340's fuller
   host-side training sequence (§4.25) ports here; GF119/GF108 DDR3 via
   Class B per-board scripts.
2. **Kepler** (`GK104`–`GK208`, 470.256.02 pre-GSP paths): same
   direct-MMIO family, reporters already filing GF119/GF108 reports.
3. **Maxwell 1** (`GM107`/`GM108`, unsigned Falcon, in 390.157):
   highest-value GSP-era target — port custom Falcon PMU + PLL/RAM
   reclocking directly.
4. **Maxwell 2 & Pascal** (`GM200`–`GP108`, signed PMU): GSP message
   interface (`nvkm/subdev/gsp/`), not register replay. 470's
   `_nv015478rm` (`.text+0xfa540`, 655 insns) confirms the split: it is
   a firmware-RPC sequencer (~20 checked call steps, status-word
   accumulation, zero direct `0x10fxxx` touches) — the MC programming
   moved into `gsp.bin`. Reclock policy behind GSP RPC, unimplemented
   in Nouveau; needs message-protocol RE, not MMIO traces.

## 5. Display Engine & 120 Hz Investigation

### 5.1 Bandwidth Limits on Fermi eDP
- The 1920×1080 @ 120 Hz panel operates at a **396.36 MHz pixel clock**.
- Standard DisplayPort 1.1a (supported on Fermi GF106) provides 4 lanes at 2.7 Gbps (HBR), yielding a max usable data bandwidth of **8.64 Gbps**.
- At 24 bpp (8 bpc), 120 Hz requires **9.51 Gbps** (exceeds link bandwidth).
- Both drivers resolve this by clamping color depth to **6 bpc** (18 bpp, ~7.13 Gbps) with spatial dithering (`asyh->or.bpc = 6`).

### 5.2 Why Nouveau Compositor Locks to 60 FPS
1. **Aggressive VBlank Power Saving (`dev->vblank_disable_immediate = true`)**:
   In `dispnv50/disp.c` (line 3014), Nouveau disables VBlank interrupts immediately when unrequested. When desktop compositors (Muffin/Mutter/Clutter) query VBlank timestamps via DRI2/DRI3, waking up the IRQ creates micro-delays that degrade frame pacing, locking `glxgears` to ~53–57 FPS under VSync.
2. **Compositor Unredirection**:
   With VSync disabled (`vblank_mode=0`), the GPU renders at **556+ FPS** on Nouveau.
3. **Proprietary NVIDIA Driver Advantage**:
   The NVIDIA 390.157 driver utilizes its proprietary closed-source `NV-CONTROL` display pipeline, custom hardware microcode, and dedicated hardware timestamping registers that bypass generic Xorg KMS VBlank interrupt scheduling, achieving full native 120 FPS rendering.

---

## 6. Performance Benchmark Summary

| Configuration | Driver | Core Clock | Memory Clock | `glxgears` (Unthrottled) | `glxgears` (VSync) |
|---|---|---|---|---|---|
| **Boot State (Default)** | Nouveau | 202 MHz | 324 MHz | ~320 FPS | ~52 FPS |
| **Reclocked (`0f`)** | Nouveau | 590 MHz | 324 MHz | **~2,700 FPS** | ~57 FPS |
| **Proprietary (Xorg)** | NVIDIA 390.157 | 590 MHz | 900 MHz | **~11,850 FPS** | 120 FPS |
| **Proprietary (XLibre-Beta)** | NVIDIA 390.157 | 590 MHz | 900 MHz | **~12,750+ FPS** | 120 FPS |

---

## 7. Modified Driver Files Inventory

- **`nouveau_backlight.c`**: Force `nv_backlight` registration and bypass ACPI checks.
- **`nvkm/subdev/clk/base.c`**: Add `NvFermiMemReclock` safety gate and error propagation.
- **`nvkm/subdev/clk/gf100.c`**: Fix clock domain table and add `NVKM_CLK_DOM_FLAG_CORE`.
- **`nvkm/subdev/fb/ramgf100.c`**: Add DDR3 register tables, skip GDDR5 training on DDR3.
- **`nvkm/subdev/pmu/gt215.c`**: Guard `0x10a580` PRIVRING lock and add 100ms timeout polling.
- **`nvkm/subdev/pmu/memx.c`**: Guard `0x10a580` lock in `memx_init` and `memx_fini`.

---

## 8. Alternative Approaches for Future Work

Status as of 2026-09-07: the PMU-firmware message path is a dead end for
small patches (see §4.7–4.16 for the full elimination log). The firmware
boots, idles healthily, consumes the first message (`GET` advances), then
never produces a valid reply; every observation channel into *why* is
compromised (DMEM reads-after-writes are latch-suspect, fault logging is
flaky, volt steps halt+darken the block post-mortem). Do not continue
patching the queue path. The two approaches below start from mechanisms
that are individually proven and avoid every undecidable.

### 8.1 Custom Falcon MEMX-executor (recommended, ~40-50% first-try)

**Idea.** Stop talking to any PMU firmware through message queues. Upload
our *own* tiny Falcon program into PDAEMON IMEM, point `ENTRY` at it,
`START` it, and let it execute the decoded DDR3 script directly — with
host↔Falcon communication restricted to mechanisms proven working.

**Bypassed entirely (all the §4 undecidables):** `PUT`/`GET`/`RPUT`/`RFIFO`
pointers, DATA-window *reads*, `memx_recv` dispatch, `send_proc`/HOST
queues, `RPUT` bump, `INTR_TRIGGER`, the nouveau PMU firmware image, VBIOS
DMEM remnants, Falcon channels. None of these exist in the design.

**Relied upon (each proven this session):**
- Falcon reset (`PMC.ENABLE` bit 13 toggle) and the I/O unlock
  (`ACCESS_EN`/`UNK090`/MEMIF) — both work every boot.
- IMEM upload via CODE ports (`0x10a180/184/188`) — the firmware boots
  from it every time (`H2D = 0x00800270` proves code runs).
- DMEM writes via seg1 (`0x10a1c0/1c4`) — self-consistent (D1 MATCH);
  program and driver use the *same* window, so any addressing quirk
  affects both sides identically.
- `ENTRY` + `START` (`0x10a104`/`0x10a100 = 2`) — proven.
- Falcon-core MMIO writes *and* reads (`H2D` programmed, `GET` advanced
  by firmware action — core-side MMIO works in both directions).
- `FB_PAUSE` (`0x10a7e0`) + engine gating (`0x001620`/`0x0026f0`) from
  Falcon context — the proprietary driver's own reclock does exactly
  this (mmiotrace proves firmware-side engine access works).
- Completion via `DSCRATCH` (`0x10a5d0+`, control block — the trustworthy
  read class, consistent across `nvapeek`/raw-BAR/kernel reads).

**Design sketch.**
- Falcon program (~60-100 insns): on `START`, walk the already-decoded
  DDR3 script from a DMEM scratch area (host-written, e.g. DMEM `0x1000`,
  beyond the `0xE00`-byte firmware image, inside 24KB DMEM per `CAPS`).
  Implement the same 7 MEMX opcodes (`os.h`: `ENTER`/`LEAVE`/`WR32`/
  `WAIT`/`DELAY`/`VBLANK`/`TRAIN`) so existing scripts run unmodified:
  `WR32`/`WAIT` are plain MMIO write/poll loops, `ENTER`/`LEAVE` assert
  and release `FB_PAUSE` + engine gating, `TRAIN` replays the decoded
  DDR3 training sequence verbatim. On completion write a DONE magic to
  `DSCRATCH(2)` and halt (`STOPPED` is then *expected*, read as success).
- Host driver (in `ramgf100.c` DDR3 path, replacing the MEMX call):
  re-apply the I/O unlock, upload program to high IMEM (24KB IMEM per
  `CAPS`, image ends ~`0xEBC`, load at `0x1000`), write script via seg1,
  `ENTRY` + `START`, poll `DSCRATCH(2)` for DONE with a 2s timeout, then
  verify clocks by MMIO readback. Timeout path: abort and reboot (watchdog
  pattern already established: `sleep 90; echo b > /proc/sysrq-trigger`).
- Assembler: installed `envyas` (`envyas -m falcon -V fuc3`, reads stdin,
  `-o` for output; `envydis -m falcon -V fuc3 -w` disassembles 32-bit-word
  streams for verification). Stick to observed-good instructions only
  (`mov`/`shl`/`add`/`and`/`cmp`/`bra`/`ld`/`st`/`iord`/`iowr`/`call`/
  `ret`/`push`/`pop`/`clear` — all with reference-assembled encodings, see
  §4.10 notes). Write pure envyas dialect (numeric operands, bare labels,
  `.equ #name` constants); avoid `#define` (installed envyas rejects it —
  preprocess with `cpp -P` first if C macros are wanted, then verify the
  few lines around the failure point). Embed the resulting bytes as a
  static C array (like `gf100.fuc3.h` format); no kernel build dependency.
- Script source: `tools/decode-pmu-memx.py` output (blocks 20/29 in
  `testing/`) or the existing `ramgf100.c` script builder, which already
  emits the 7 opcodes — reuse it, retargeted at the DMEM scratch area.

**Honest risks.**
1. Falcon-side engine MMIO (clocks/MC/display regs from Falcon context):
   high confidence (blob does it), not proof. Failure = halted Falcon
   mid-script → watchdog reboot, system safe, reboot restores.
2. Training values must match the board — see pre-flight (b) below.
   Verifiable *before* building; do not skip it.
3. `VBLANK` from Falcon: if the head-raster poll (`0x616340`, host-proven)
   misbehaves, substitute a fixed 200ms delay. Engines are paused under
   `FB_PAUSE`, so worst case is slower, never unsafe.

**Effort**: 1–2 focused days. Odds ~40–50% first try — an order of
magnitude better than another queue patch, because exactly one link is
unproven (Falcon-side engine MMIO) instead of six.

### 8.2 Hypervisor channel-descriptor capture (highest certainty, most setup)

The one datum no MMIO sniffer can ever yield (mmiotrace sees BAR traffic,
never RAM contents) is the *channel descriptor bytes* the proprietary
driver builds in sysram before `CHANNEL_TRIGGER.LOAD`. Capture it live:
Linux/KVM host, Windows *or* Linux guest with GPU passthrough, EPT trap
on the PDAEMON BAR pages (same principle as `mmiotrace`: mark pages
not-present, log every `MMIO32` access on VMEXIT), plus a guest-RAM
snapshot at the `CHANNEL_SETUP` write. The descriptor (TARGET/address,
ctxsw program, save areas) then lets us construct a *valid* channel of
our own — unlocking the Falcon-core side properly (§4.8) with zero
garbage DMA. Expected certainty for a valid channel ~70%; cost is days
of infrastructure (IOMMU/passthrough/VFIO on this laptop, EPT tooling)
before the first datum. Windows specifically adds nothing (same driver
architecture, harder tooling); do it with the Linux blob.

### Pre-flight checks (do these before either build)

**(a) Trace provenance — was the trace captured on *this* machine?**
`testing/README.md` attributes all artifacts to the reference hardware
(Dell XPS L702X, GF106M stepping A1, `10de:0dcd`, 3072 MiB DDR3,
RAMCFG strap `0x6`, VBIOS `70.06.32.00.03`). To confirm exact-machine
match (not just same model):
- `sudo dmesg | grep -E "bios: version|NVIDIA GF106"` must report
  `70.06.32.00.03` and the same PCI/subsystem IDs.
- `nvbios -p version testing/gpu_vbios.rom` must report the identical
  version string; `nvbios -p ram testing/gpu_vbios.rom` must list strap
  `0x6` tables.
- Capture provenance: `testing/run_mmiotrace.sh`,
  `testing/sniff_memory_reclock.py`, `testing/trace_driver_reload.sh`
  (Aug 2026) document how the traces were taken; `testing/README.md`
  lists every file. If any identifier mismatches, treat the decoded
  values as *same-model* (very likely transferable, GDDR3 timings are
  strap-selected) rather than *same-board* and lean harder on (b).

**(b) Decoded-values vs VBIOS `ramcfg` comparison.**
The DDR3 training values (MR0/MR1/MR2 mode registers, timing registers,
MEMPLL dividers at `0x132004`, PHY tune writes) must agree with this
board's VBIOS tables, otherwise replaying them trains for the wrong
RAM configuration:
- Dump the tables: `nvbios -p perf testing/gpu_vbios.rom` (P-state
  table — confirm the 3 states 03/07/0f and the 135/324/900 MHz memory
  clocks — plus MEMORY TIMINGS MAPPING/TABLE at `0xced3`/`0xd0db` and
  the VOLTAGE table; this mask parses cleanly). NOTE: `nvbios -p ram`
  (RAMCFG strap tables) outputs nothing on this ROM with current
  envytools (parse errors on several BIT tables); fall back to
  `testing/gpu_vbios_perf.txt` (pre-decoded Jun 2026, same content),
  to the kernel driver's own `nvbios_ramcfg` parsing (strap `0x6`,
  visible in a `dyndbg`-enabled boot log around `ram_exec`), or to
  `nvamemtiming` (needs the GPU idle and root).
- Compare, entry by entry, against the decoded scripts (§4.2–§4.4 and
  `tools/decode-pmu-memx.py` output for blocks 20/29): every MR value,
  every timing register, every divider.
- Match on all entries → replay verbatim with confidence.
- Systematic offset/scale on some entries → the trace is same-model but
  different strap/binning: scale per the local strap table (or re-derive
  with `nvamemtiming`, which needs the GPU idle and root).
- Wholesale mismatch → do NOT replay; the trace is from different
  hardware and training values must come from the local VBIOS only.

### 8.3 Resident Falcon Microcode Executor (Bidirectional Memory Reclocking)

The single-shot executor previously halted via `exit` instruction after
completing a reclock script (e.g. 324 -> 900 MHz). On Fermi GF100/GF106,
transitioning PDAEMON Falcon from `RUNNING` to `STOPPED` activates the hardware
power-management block, clock-gating PDAEMON and placing the PRIVRING into
lockdown. Any subsequent MMIO access (`0x10a...`) or PMC reset triggers fatal
PRIVRING faults (`0x10a10c`, `0x10a048`, `0x10a080`), rendering memory
downclocking impossible.

#### Resident Command-Wait Architecture
1. **Microcode Resident Loop (`memx_exec_custom.fuc`)**:
   - Replaced `exit` with a resident wait loop (`cmd_wait`).
   - On completing script execution, the microcode writes `0xE1EC0001` to
     `SCRATCH2` (`0x10a080`) and spins polling `SCRATCH3` (`0x10a084`).
   - When the host signals a new transition by writing `1` to `SCRATCH3`, the
     Falcon clears `SCRATCH3` (ack) and `SCRATCH2`, then branches directly to
     `#main` to parse and execute the newly uploaded DMEM script.
   - Because the Falcon microcode remains permanently in the `RUNNING` state,
     hardware power-gating and clock-gating never engage.

2. **Fast-Path Host Handshake (`ramgf100.c`)**:
   - `gf100_ram_exec_custom()` checks if the resident executor is already active
     (`fexec_loaded` and `SCRATCH2 == 0xE1EC0001`).
   - If active, it skips PMC reset, Falcon memory scrubbing, and IMEM upload.
   - It writes and verifies the target DDR3 script into DMEM (0x1000), clears
     `SCRATCH2`, triggers `SCRATCH3 = 1`, and polls `SCRATCH2 == 0xE1EC0001`.
   - Transition latency drops to ~5 ms with zero reset overhead.

3. **Voltage Step-Down Re-Unlock (`clk/base.c`)**:
   - Following voltage drops in `nvkm_cstate_prog()` via `nvkm_volt_set_id(..., -1)`,
     the driver re-applies the PDAEMON unlock registers (`0x10a014`, `0x10a01c`,
     `0x10a010`, `0x10a048`, `0x10a090`, `0x10a004`) to preserve MMIO routing
     stability.
   - In `nvkm_pstate_prog()`, error propagation ensures the clock state machine
     aborts cleanly if memory reclocking encounters an unexpected error.

### 8.4 S3 Suspend/Resume Falcon Auto-Recovery, Cold-Boot Clock Sync & PCIe Link Scaling (v2.0.1)

1. **S3 Suspend/Resume Falcon Executor Auto-Recovery**:
   - Across ACPI S3 suspend/resume cycles, GPU power removal wipes PDAEMON IMEM/DMEM and resets `SCRATCH2` (`0x10a080`) to `0x00000000`, invalidating the host's `fexec_loaded` flag.
   - `gf100_ram_exec_custom()` now validates hardware state on every transition: if `SCRATCH2 != 0xE1EC0001` (or if a fast-path trigger times out), it clears `fexec_loaded` and transparently falls back to a full cold bootstrap (PMC bit-13 reset, scrub wait, PDAEMON I/O unlock, IMEM/DMEM upload, and `START`), restoring full bidirectional DDR3 reclocking after resume.
2. **Cold-Boot Clock Desync Fix**:
   - Synchronized hardware clock readout on initial module load so the kernel's cached P-state and clock domains accurately reflect VBIOS boot state before the first manual or daemon-driven transition.
3. **Dynamic PCIe Gen1 / Gen2 Link Speed Synchronization (`0x02241c` / `0x088460` / `0x088088`)**:
   - Integrated PCIe link speed switching (`2.5 GT/s` Gen1 in low-power states `03`/`07` ↔ `5.0 GT/s` Gen2 in performance states `0f`/`10`) into the P-state transition path:
     - **PUNIT Capability Register (`0x02241c`)**: Bit 0 (`0x01` = Gen2 2.0 spec version via `gf100_pcie_set_version()`), Bit 7 (`0x80` = advertise `5.0 GT/s` via `gf100_pcie_set_cap_speed()`).
     - **NVIDIA Extended Config `0x460` (MMIO `0x088460`)**: Bits `[5:4]` target link speed (`0x10` = `2.5 GT/s`, `0x20` = `5.0 GT/s`), Bit 0 (`0x01`) `LINK_RETRAIN` trigger (`g84_pcie_set_link_speed()`).
     - **PCIe Link Status `0x88` (MMIO `0x088088`, `PCI_EXP_LNKSTA`)**: Bits `[19:16]` negotiated speed (`0x10000` = `2.5 GT/s`, `0x20000` = `5.0 GT/s`), Bit 11 (`0x0800`) retraining in flight.

### 8.5 Synthetic Intermediate Performance State (P3 / State `0a`)
- **Target Operating Point**: `0a` (`405 MHz` Core / `810 MHz` Shader / `650 MHz` DDR3 @ `0.920 V`, `VID 0x03`, `~31.2 GB/s`).
- **Solved in §10.5–§10.7**: Decompilation of `_nv010738rm` (`0x132004 = 0x10012702`) and `_nv014883rm` (`405 MHz` / `500 MHz` strap thresholds) proved that `650 MHz` uses the exact `900 MHz` VBIOS strap timing/PHY table with only `0x132004` changed from `0x10013602` to `0x10012702`.

---

## 9. Reverse Engineering the NVIDIA 390.157 Proprietary Driver via REA (Methodology & Scope)

The NVIDIA `390.157` legacy driver is the final official proprietary release supporting Fermi (`GF10x`/`GF11x`) alongside Kepler (`GK10x`/`GK11x`/`GK208`), Maxwell (`GM10x`/`GM20x`), and early Pascal (`GP10x`). Using the **REA (Reverse Engineer Anything)** MCP server together with **Ghidra** and `envytools` (`envydis`), we systematically extract hardware programming sequences from `390.157` to improve Nouveau across all pre-signed-firmware architectures.

### 9.1 Clean-Room Methodology & Boundaries

| Principle | Rule |
|---|---|
| **Clean-Room Specification Split** | Static analysis via REA produces *hardware specifications* (register addresses, bitfields, state-machine ordering, timing formulas, and lookup tables) documented in `RECLOCKING_NOTES.md` with REA Evidence IDs. All kernel code in `nouveau.patch` is written from scratch against those specifications—never copied from decompiled Resource Manager (RM) C pseudocode. |
| **No Firmware Redistribution** | Proprietary Falcon microcode blobs embedded in `nv-kernel.o_binary` must never be committed to git or packaged in AUR/AliveOS. Where hardware behavior can be implemented in our own clean `envyas` microcode (`memx_exec_custom.fuc`), we write original assembly; if an official image is ever required, it must be extracted locally from the user's `.run` archive at install time. |
| **Static vs. Runtime Verification** | Static decompilation findings are treated as hypotheses until corroborated against `mmiotrace` captures (`demmio`) or live hardware telemetry on the target GPU. |
| **Signed Firmware Wall (GM20x+)** | Maxwell 2 (`GM20x`) and Pascal (`GP10x`) enforce High-Security (HS) RSA-signed PMU/ACR firmware in hardware. Reverse engineering can document their P-state and thermal tables, but cannot unlock custom PMU reclocking without NVIDIA's signed images. |

### 9.2 Target Artifacts Inside `NVIDIA-Linux-x86_64-390.157.run`

| Artifact | Internal Role | Value for Nouveau |
|---|---|---|
| `kernel/nvidia/nv-kernel.o_binary` | Core **Resource Manager (RM)**: per-chip HAL (`_nv0xxxxxrm`), VBIOS BIT/P/M/T parsers, PLL calculators, DDR3/GDDR5 training generators, `OBJSEQ` sequencer, PMU task managers, BLCG/SLCG tables, and voltage/thermal controllers. | ⭐⭐⭐ Primary RE target |
| Embedded Falcon Ucode Arrays (inside `nv-kernel.o_binary`) | Compiled Falcon `fuc3`/`fuc4`/`fuc5` bytecode images for PMU (`0x10a000`), FECS (`0x409000`), GPCCS (`0x41a000`), and `MSENC` (`0x1c8000`). | ⭐⭐⭐ Reveals PMU command protocols & video firmware |
| `kernel/nvidia-modeset/nv-modeset-kernel.o_binary` | Proprietary modesetting core (EVO / NVDisplay): head timing validation, DisplayPort/eDP link training, BPC step-down, and IMP bandwidth checks. | ⭐⭐ Solved 120 Hz eDP 6 bpc step-down & stereo quirks (§10.2) |
| `kernel/nvidia/*.c` (open glue layer) | Unobfuscated GPL kernel interface layer (`nv.c`, `nv-modeset-interface.c`, `os-interface.c`). | ⭐⭐ Human-readable entry points & struct layouts |

### 9.3 Phase 1–5 Research Matrix & Cross-Reference to Solved Findings

| Phase / Topic | Status | Where Documented / Next Action |
|---|---|---|
| **120 Hz 3D Vision eDP, `+5 MHz` Grace & `8 bpc → 6 bpc` Step-Down** | ✅ **Solved** | See **§10.2** (`_nv000659kms`, `_nv002219kms`, `_nv002187kms`) |
| **Fermi PDAEMON Context-Switch State Machine (`0x10a128` ↔ `0x10a058`)** | ✅ **Solved** | See **§10.3** (`_nv029783rm`, `_nv029647rm`) |
| **`OBJSEQ` Bytecode VM, Opcode `0x3a` & Zero-Flash `ISOHUB` + `WAIT_VBLANK`** | ✅ **Solved** | See **§10.4** (`_nv031916rm`, `_nv031754rm`, `_nv031860rm`) |
| **`0x132004` (`MEMPLL_COEFF`) & Synthetic P3 (`0a` @ `650 MHz` = `0x10012702`)** | ✅ **Solved** | See **§10.5–§10.7** (`_nv010738rm`, `_nv014883rm`, `_nv014880rm`) |
| **PDAEMON Hardware Load Counters (`0x10a600..0x10a610`) & PowerMizer** | ✅ **Identified** | See **§10.3 & §10.8** (`_nv029625rm` / `_nv029628rm`); mask extraction tracked in `TODO.md` §6 |
| **Fermi BLCG / SLCG Clock-Gating `.rodata` Tables** | 📋 **Pending Extraction** | Tracked in `TODO.md` §6 |
| **Kepler (`GK104`–`GK208`) & Maxwell 1 (`GM107`–`GM108`) Reclocking** | 📋 **Planned (`Phase 2–3`)** | Tracked in `TODO.md` (Pre-`Nova` Evolution) |

---

## 10. Concrete Reverse-Engineering Findings from NVIDIA 390.157 (`nv-modeset-kernel.o_binary` & `nv-kernel.o_binary`)

This section records the concrete hardware specifications, RM/NVKMS function mappings, register formulas, and state machines extracted from `NVIDIA-Linux-x86_64-390.157.run` using **REA (Reverse Engineer Anything)** + **Ghidra 12.1.2** and `objdump`.

### 10.1 Binary Inventory & REA Evidence Ledger

| Binary Artifact | Size | SHA-256 | Architecture / Format | Key Subsystems Analyzed |
|---|---|---|---|---|
| `kernel/nvidia-modeset/nv-modeset-kernel.o_binary` | 1,288,832 B | `db0e6be60c43fac82ed4c6e26a41516b2f47ba8e6d0833df7a3ce395284ee74c` | ELF64 relocatable `x86-64` (832 procedures) | NVKMS mode validation, 3D Vision stereo EDID quirks, DisplayPort BPC step-down, IMP bandwidth & DMI blanking checks |
| `kernel/nvidia/nv-kernel.o_binary` | 15,728,392 B | `66021e3e6ea75a31cf565a187ee3cd8aa1df03457d7265f5dbca493fb366c963` | ELF64 relocatable `x86-64` (27,763 procedures) | Fermi PDAEMON context-switch handshake, `OBJSEQ` (`seqScript`) MEMX bytecode API, MCLK/MEMPLL state machines, FBPA DDR3 VBIOS-to-register calculators |

#### REA Evidence IDs (`nv-modeset-kernel.o_binary`)
- `ev_12040d53f04f21f651926ce78901fa00e200875de653d990f00d87d6c4794622` — `binary_overview` (`nv-modeset-kernel.o_binary`, 832 functions)
- `ev_fa95a0b6b9316092e01b195fdb81ebc901df199540c4b38f7e140c5fb4c0e97a` — `analyze_function` on `_nv000653kms` (`0x2196a0`, master mode-validation entry point)
- `ev_9c21b9f6c9867be11bbf0365b2f5ae395963eb182f980883a9e280f54cf23025` — `analyze_function` on `_nv000659kms` (`0x217f20`, EDID range & 3D Vision stereo quirk validator)
- `ev_7d59fbf88033c2b34d1c8900aa284a8afd3c8557a6f279dd6ad1e15107905b5b` — `analyze_function` on `_nv002185kms` (`0x2095f0`, EVO hardware timing & DP link validator)
- `ev_eb27496a338fe2fa3106418bc6cc3947b05ba8c22961586061a3d672c825eedb` — `analyze_function` on `_nv002219kms` (`0x226b20`, DisplayPort BPC step-down loop)
- `ev_8df11ded1afea100086ad27157d16175fa4cda73360572096d64bf4cebb594bf` — `analyze_function` on `_nv002218kms` (`0x226b00`, DP link config wrapper)
- `ev_7de61b926008cb5aab7a2913029ab29d4916621af9010cfa6fb7293845a48470` — `analyze_function` on `_nv002220kms` (`0x226a90`, single-head DP bandwidth test)
- `ev_48d782d2a325f44ced93c6f75fcdfb8bd03758739d168a95445f59c5e3e570f3` — `analyze_function` on `_nv000673kms` (`0x2269e0`, BPC-to-BPP converter & `dpLib` bandwidth query)
- `ev_fc5e532558b955f45a7c56ecba58bff5dd53ac918bdb4dc3179122dde6b1c46d` — `analyze_function` on `_nv002187kms` (`0x209440`, RM Isochronous Memory Pool / IMP check)
- `ev_c61984d15728812ec61030925d30a031e6ce0d353d35ad47b6b64e550ea0fe1c` — `analyze_function` on `_nv002183kms` (`0x2093b0`, EVO `calcDmiBlankingInterval` dispatch)

---

### 10.2 `nv-modeset-kernel.o_binary`: 120 Hz 3D Vision eDP Validation & Automatic DP BPC Step-Down

Decompiling the NVKMS mode validation pipeline (`_nv000653kms` @ `0x2196a0`) revealed three critical mechanisms that allow the proprietary 390.157 driver to drive the Dell XPS L702X's `1920x1080 @ 120 Hz` 3D Vision eDP panel (`LGD 0x02c5`, pixel clock `396.36 MHz`) without link-training failure or display FIFO underflow:

#### 1. 3D Vision Stereo Panel EDID Quirks (`_nv000659kms` @ `0x217f20`)
- Many early 120 Hz 3D Vision laptop eDP panels (including `LGD 0x02c5`) ship with an EDID whose Range Limits descriptor reports a lower `Max PixelClock` or `VertRefresh` than the 120 Hz Detailed Timing Descriptor (`396.36 MHz`).
- In `_nv000659kms`, NVKMS checks `(*(byte *)(pConnector + 0x3bdc) & 0x2) != 0` (3D Vision Stereo panel flag):
  - When set, NVKMS grants an automatic **+5.0 MHz (`+5000 kHz`) pixel-clock grace margin** (`uVar22 = max_pclk_khz + 5000`) above both the Display Device maximum and the EDID maximum pixel clock:
    > *"PixelClock (%d.%d MHz) is slightly higher than Display Device maximum (%d.%d MHz), but within 5.0 MHz margin allowed for 3DVision Stereo panel."*
  - Furthermore, if the mode comes from an EDID Detailed Timing Descriptor (`*param_3 == 1`) on a 3D Vision panel, NVKMS explicitly bypasses contradicting EDID Range Limits (`HorizSync`, `VertRefresh`, `Max PixelClock`) rather than pruning the 120 Hz mode.

#### 2. Automatic DisplayPort Color Depth (BPC) Step-Down Loop (`_nv002185kms` $\to$ `_nv002219kms` $\to$ `_nv000673kms`)
- On a 4-lane HBR1 (`2.7 Gbps/lane`) eDP link, the maximum 8b/10b data payload bandwidth is:
  $$\text{Max Payload Bandwidth} = 4 \times 2.16\text{ Gbps} = 8.64\text{ Gbps} \ (1080\text{ MB/s})$$
- At `1920x1080 @ 120 Hz` (`396.36 MHz` pixel clock):
  - **10 bpc (`30 bpp`, code `2`)**: $396.36\text{ MHz} \times 30 = 11.89\text{ Gbps} > 8.64\text{ Gbps}$ (**Fails**)
  - **8 bpc (`24 bpp`, code `1`)**: $396.36\text{ MHz} \times 24 = 9.51\text{ Gbps} > 8.64\text{ Gbps}$ (**Fails**)
  - **6 bpc (`18 bpp`, code `0`)**: $396.36\text{ MHz} \times 18 = 7.13\text{ Gbps} \le 8.64\text{ Gbps}$ (**Succeeds!**)
- Decompiling `_nv002185kms` (`0x2095f0`), `_nv002219kms` (`0x226b20`), and `_nv000673kms` (`0x2269e0`) shows how NVKMS handles this transparently:
  1. `_nv002185kms` initializes the target color depth code at `*(uint *)(pEvoTimings + 0x20)` (`2` = 10 bpc, `1` = 8 bpc, `0` = 6 bpc).
  2. For DisplayPort/eDP connectors, `_nv002185kms` calls `_nv002219kms(pDisp, pConnector, pDpGroup, pEvoTimings, b2Heads1Or)`.
  3. `_nv002219kms` executes a `while` loop calling `_nv002218kms` $\to$ `_nv002220kms` $\to$ `_nv000673kms`:
     - `_nv000673kms` converts the color depth enum into bits-per-pixel (`2 -> 0x1e (30 bpp)`, `1 -> 0x18 (24 bpp)`, `0 -> 0x12 (18 bpp)`), converts `pixelClock_kHz * 1000` to Hz, and calls the DisplayPort Library (`dpLib`) link bandwidth validator (`vtable + 0x60`).
     - If the bandwidth check fails, `_nv002219kms` steps down the color depth (`2 -> 1`, and then `1 -> 0`) in-place at `*(uint *)(pEvoTimings + 0x20)` and retries until `18 bpp` (6 bpc with spatial/temporal dithering) succeeds.

#### 3. Isochronous Memory Bandwidth (IMP) & DMI Blanking Interval (`_nv002187kms` & `_nv002183kms`)
- After link validation, `_nv002185kms` calls:
  - `_nv002183kms` (`0x2093b0`): Invokes the EVO display HAL method `calcDmiBlankingInterval` (`offset +0xe8` in the display HAL vtable at `*(long *)(*pDev + 8) + 0x380`), computing the Display Memory Interface (DMI) blanking window during which MCLK P-state switches or spool-up can occur without scanout corruption.
  - `_nv002187kms` (`0x209440`): Builds an RM Isochronous Memory Pool (IMP) query structure containing the active raster timings, viewport dimensions, pixel depth, and head usage bounds, and invokes `_nv002603kms` (RM `NV0073_CTRL_CMD_SYSTEM_CHECK_IMP` / internal IMP validator).
  - **Implication for Nouveau 120 Hz & Reclocking**: At `1920x1080 @ 120 Hz` (`396.36 MHz` pixel clock, ~`1.58 GB/s` scanout bandwidth at 32-bit XRGB framebuffer fetch), P-state `03` (`135 MHz` DDR3 = `3.24 GB/s` raw, where `dispclk`/`hubk07` drops to `135 MHz`) cannot sustain a `396.36 MHz` pixel clock (`pixel_clock > dispclk`!). When the 120 Hz mode is active, the minimum P-state floor must keep `dispclk` (`hubk07`) $\ge 405\text{ MHz}$ (i.e., P-state `07` / `0a` / `0f`).

---

### 10.3 `nv-kernel.o_binary`: Solved the Fermi PDAEMON Falcon Context-Switch Handshake (§4.6–§4.8)

In Section 4.6, we observed from the `390.157` `mmiotrace` that the proprietary driver wrote `0x701074ef` to `0x10a054` (`NXTCTX`) and `0x10a47c`, and wrote `0x2` to `0x10a058` (`CTXACK`), after which the Fermi PDAEMON Falcon unlocked and accepted commands without `PRIVRING` faults. However, when we replayed those raw register writes statically in Nouveau (§4.8), `0x10a054` echoed into `0x10a050` (`CURCTX`) without completing the context load because the dynamic state-machine handshake was unknown.

Disassembling the Fermi PMU HAL in `nv-kernel.o_binary` (`0x5158d0–0x5168c0`) solved this completely:

| RM Function | Address | Role |
|---|---|---|
| `_nv029733rm` | `0x5158d0` | Initializes Fermi PMU (`0x10a000`) register pointers: `CMD_QUEUE_HEAD[0..3]` at `0x10a4a0`, `CMD_QUEUE_TAIL[0..3]` at `0x10a4b0`, `MSG_QUEUE_HEAD` at `0x10a4c8`, `MSG_QUEUE_TAIL` at `0x10a4cc`, `MUTEX` at `0x10a580`. |
| `_nv029625rm` / `_nv029628rm` | `0x515a70` / `0x515ad0` | Configures PDAEMON idle/busy counter signal filters at `0x10a600 + idx*4` (`idx = 0..4` $\to$ `0x10a600..0x10a610`). |
| `_nv029783rm` | `0x5163a0` | **Master Fermi PMU Context Bind**: constructs the 32-bit context descriptor and binds it to `0x10a054` (`NXTCTX`) and `0x10a47c`. |
| `_nv029786rm` | `0x5165f0` | Enables context switching (`0x10a048 |= 0x1`) and invokes `_nv029650rm`. |
| `_nv029650rm` | `0x516750` | Triggers the context switch, runs the `_nv029647rm` state-machine loop, and clears interrupt bit `0x8` via `0x10a004 = 0x8`. |
| `_nv029647rm` | `0x516850` | **The Software Context-Switch State Machine (`0x10a128` $\leftrightarrow$ `0x10a058`)**. |

#### Exact Hardware Sequence in `_nv029783rm` $\to$ `_nv029650rm` $\to$ `_nv029647rm`:
1. **Instance Block Descriptor Format (`_nv029783rm` @ `0x5163a0`)**:
   - Reads the PMU instance block memory descriptor at `[pPmu + 0x7b50]` and extracts its physical page frame (`(phys_addr >> 12) & 0x0fffffff`) and aperture type (`[memDesc + 0x2c]`):
     - Aperture `1` (VRAM) $\to$ `0x60000000 | (phys_addr >> 12)`
     - Aperture `2` + Coherent (`[memDesc + 0x50] == 1`) $\to$ `0x40000000 | (phys_addr >> 12)`
     - Aperture `2` + Non-coherent System RAM $\to$ `0x70000000 | (phys_addr >> 12)` *(matches `0x701074ef` in the `mmiotrace`!)*
2. **Pre-Bind Register Setup (`_nv029783rm` & `_nv029786rm`)**:
   - `nvkm_mask(device, 0x10a048, 0x00000001, 0x00000001)` — set bit 0 (`CTXEN`).
   - `nvkm_mask(device, 0x10a090, 0x00010000, 0x00010000)` — set bit 16 (`0x10000`) to enable host-assisted context-switch state transitions.
   - `nvkm_wr32(device, 0x10a054, ctx_desc)` (`NXTCTX`).
   - `nvkm_wr32(device, 0x10a47c, ctx_desc)` (PDAEMON host aperture/channel bind).
3. **The Interactive State-Machine Loop (`_nv029647rm` @ `0x516850`)**:
   - When `NXTCTX` (`0x10a054`) is written on a Fermi Falcon that has `0x10a090` bit 16 set, the hardware context-switch controller enters an interactive state machine reported in **`0x10a128` (`FALCON_CTXSW_STATUS`)**:
     ```c
     for (;;) {
         u32 stat = nvkm_rd32(device, 0x10a128);
         u32 state = (stat >> 12) & 0x7;
         if (state == 2) {
             /* State 2: Save current context requested -> acknowledge save */
             nvkm_wr32(device, 0x10a058, 0x00000001);
         } else if (state == 5) {
             /* State 5: Load next context requested -> acknowledge load */
             nvkm_wr32(device, 0x10a058, 0x00000002);
         }
         /* Re-read status; bit 1 (0x2) indicates context switch is idle/complete */
         stat = nvkm_rd32(device, 0x10a128);
         if (stat & 0x00000002)
             break;
     }
     /* Clear CTXSW interrupt pending bit */
     nvkm_wr32(device, 0x10a004, 0x00000008);
     ```
   - **Why our earlier static replay in §4.8 failed**: Without polling `0x10a128` bits `[14:12]` for state `5` before writing `0x2` to `0x10a058` (`CTXACK`), and waiting for `0x10a128 & 0x2` before clearing `0x10a004 = 0x8`, the context switch was acknowledged at the wrong cycle!

---

### 10.4 `nv-kernel.o_binary`: The RM Sequencer (`OBJSEQ` / `seqScript` / MEMX) Bytecode Emitter API & Zero-Flash VBlank Pipeline

Every memory reclocking function in RM (`_nv010721rm`, `_nv015935rm`, `_nv015936rm`, etc.) does not write to PFB/MEMPLL registers directly from the CPU; instead, it emits instructions into a Sequencer Script (`pSeqScript`) via the `OBJSEQ` (`_nv0318xxrm`) API (`0x52f8a0–0x532960`), which is then dispatched to the PMU (or host interpreter) during VBlank:

| RM Function | Address | Sequencer Opcode | Equivalent in Nouveau `ramfuc.h` | Behavior & Disassembled Details |
|---|---|---|---|---|
| `_nv031894rm(pSeqScript, flags)` | `0x52f8a0` | *(init)* | `nvkm_memx_init()` | Opens a new sequencer script buffer (`flags = 0x5` for MCLK switch). |
| `_nv031916rm(pGpu, pSeq, pSeqScript, flags, timeoutUs)` | `0x5316a0` | `0x14` + `0x22` + `0x24` + `0x20` | `nvkm_memx_block()` | **Master `STOP_FB` sequence**: boosts `ISOHUB` watermarks (`0x12`), emits `WAIT_VBLANK` (`0x14`), captures start PTIMER (`0x24` $\to$ `[+0xa0]`), and emits `FB_STOP(1)` (`0x20`). |
| `_nv031831rm(pSeq, pSeqScript, headMask, flag)` | `0x532470` | `0x14` | `ram_wait_vblank()` | Emits `NV_SEQ_OPC_WAIT_VBLANK` (timeout `0x1dcd6500` = `500 ms` inside Falcon script). |
| `_nv031872rm(pSeqScript, headMask)` | `0x52ff50` | `0x43` | `ram_wait_vblank()` | Emits `NV_SEQ_OPC_WAIT_VBLANK_DIRECT` (`0x43`) for active display heads. |
| `_nv031828rm(pSeq, pSeqScript, stopBool)` | `0x5323e0` | `0x20` | `STOP_FB` / `UNSTOP_FB` | Emits `NV_SEQ_OPC_FB_STOP` (`1` = freeze FB, `0` = unfreeze FB). |
| `_nv031893rm(pSeqScript, reg, val)` | `0x52fb10` | `0x01` + burst | `ram_wr32(fuc, reg, val)` | Calls `_nv031837rm` (`0x5320b0`) $\to$ `_nv007083rm` (`0x532160`) to append a 32-bit register write (and calls `[pSeq + 0x358]` = `_nv031754rm` hook first!). |
| `_nv031754rm(pSeq, pSeqScript, reg)` | `0x531560` | **`0x3a`** | *(missing in Nouveau)* | **Solved Mystery Opcode `0x3a` (§4.7)!** Counts writes to PHY training ranges `0x10f590..0x10f8ff` and `0x10fb00..0x10fdff` in `[pSeqScript + 0x90]`. As soon as a write targets a register outside `0x10f000..0x10ffff`, it writes `0x0` to `0x13d7f4 + (part << 6)` (partition write-buffer flush) and emits **opcode `0x3a`** with the burst count! |
| `_nv031890rm(pSeqScript, delayUs)` | `0x52fa20` | `0x2c` | `ram_nsec(fuc, delayUs * 1000)` | Multiplies `delayUs * 1000` (`imul $0x3e8`) and calls `_nv031832rm` (`0x531f80`) $\to$ `_nv031821rm` (`0x532710`) to emit a nanosecond delay (`0x2c`). |
| `_nv031889rm(pSeqScript, delayUs)` | `0x52fa00` | `0x2d` | `ram_nsec(fuc, ...)` | Multiplies `delayUs * 1000` and calls `_nv031833rm` (`0x531f40`) $\to$ `_nv031834rm` (`0x532450`, opcode `0x2d`). |
| `_nv031884rm(pSeqScript, reg, mask, val, timeout)` | `0x52fd60` | `0x0d` + `0x15` | `ram_wait(fuc, reg, mask, val, timeout)` | Calls `_nv031823rm` (`0x5322f0`) to emit register read (`0x0d`) + poll (`0x15`, timeout $\mu\text{s} \times 1000$). |
| `_nv031860rm(pGpu, pSeq, pSeqScript)` | `0x531b60` | `0x20` + `0x25` + `0x23` | `nvkm_memx_unblock()` + ISOHUB restore | **Master `RESTART_FB` sequence**: emits `FB_STOP(0)` (`0x20`), captures end PTIMER (`0x25` $\to$ `[+0xa4]`), and restores normal `ISOHUB` display watermarks (`pIsohub->vtable[0xd8]`). |
| `_nv031861rm(pGpu, pSeq, pSeqScript)` | `0x531dd0` | *(post-check)* | *(missing in Nouveau)* | Computes `elapsed_us = (end_ns - start_ns + 500) / 1000` (`[+0xa4] - [+0xa0]`) and verifies `elapsed_us <= max_vblank_us` (`[+0xa8]`). |
| `_nv031886rm(pSeqScript)` | `0x52fa80` | `0x16` | *(end of script)* | Calls `_nv031829rm` (`0x532550`) to emit `NV_SEQ_OPC_EXIT` (`0x16`). |
| `_nv031868rm(pGpu, pSeq, pSeqScript)` | `0x52f910` | *(run)* | `nvkm_memx_fini()` | Executes the closed script (`seqScriptRun`), followed by `_nv031895rm` (`0x52f920`) waiting for completion. |

#### Why Screen Flashes Still Occur on Clock Changes in Our Driver & How `_nv031916rm` / `_nv031860rm` Fix Them
1. **In-Falcon `WAIT_VBLANK` vs. Host-CPU Polling**:
   - In our current `ramgf100.c`, `gf100_ram_wait_vblank()` polls `0x6160f8` on the **host CPU** before triggering the Falcon. Any host scheduling jitter or MMIO setup occurs *after* VBlank has already started, pushing `STOP_FB` past the ~370 $\mu\text{s}$ VBlank window into active scanout.
   - In `390.157` (`_nv031916rm` @ `0x531943` / `0x531b33`), `WAIT_VBLANK` (opcode `0x14`) is executed **inside the PMU Falcon script itself** right before `FB_STOP(1)` (opcode `0x20`), giving `< 50 ns` hardware reaction time from VBlank entry to `STOP_FB`.
2. **Pre-`STOP_FB` Display `ISOHUB` Critical Watermark Spool-Up (`_nv031916rm` @ `0x5317d4`)**:
   - Before entering VBlank, `_nv031916rm` calls `pIsohub->vtable[0xd8]` with `0x12` to force the display `ISOHUB` (`0x616300+`) to pre-fill the scanout FIFO to 100%, and `_nv031860rm` (`0x531c63`) restores normal `ISOHUB` watermarks after `FB_STOP(0)`.

---

### 10.5 `nv-kernel.o_binary`: Fermi MCLK & MEMPLL (`0x132000` / `0x132004`) Reclocking State Machines

Scanning the per-chip RM HAL dispatch tables in `.rodata` (`0xdb60` for GF100, `0x1a0a0` for GF104/GF106, `0x16760` for GF108, `0x21f40` for GF119) mapped the complete family of Fermi MCLK switch builders:

| Chip Family | Primary MCLK Script Builder | Companion / Alt-Path Handler | Dedicated MEMPLL (`0x132004`) Helper |
|---|---|---|---|
| **GF100 / GF104 / GF106** (`NV_C0`, `NV_C4`, `NV_C3`) | `_nv010721rm` (`0xec6b0`, 11,936 B) | `_nv010718rm` (`0xef550`, 12,384 B) | Inline in `_nv010721rm` (`0xee450–0xee650`) |
| **GF108 / GF110 / GF117 / GF119** (`NV_C1`, `NV_C8`, `NV_D7`, `NV_D9`) | `_nv010722rm` (`0x104470`, 7,496 B) | `_nv010719rm` (`0x107570`, 14,910 B) | `_nv010738rm` (`0x10afb0`, 928 B) |

#### 1. Exact Formula for `0x132004` (`MEMPLL_COEFF`) & Origin of the `0x1001xxxx` Upper Halfword
In Section 2.5, we noted from the `mmiotrace` that `0x132004` (`MEMPLL_COEFF`) held `0x10013602` at `900 MHz` (`N=0x36 (54), M=2`) and `0x10011b02` at `405 MHz` (`N=0x1b (27), M=2`), with an unexplained upper halfword `0x1001`.

Disassembling `_nv010738rm` (`0x10afb0`) and `_nv010721rm` (`0xee490`) reveals the exact bitfield construction of `0x132004`:
```asm
10b1fa: 8b 5c 24 70          mov    0x70(%rsp),%ebx        ;M divider
10b201: 0f b6 44 24 70       movzbl 0x70(%rsp),%eax        ;M [7:0]
10b206: 0f b6 54 24 74       movzbl 0x74(%rsp),%edx        ;N [7:0]
10b216: c1 e2 08             shl    $0x8,%edx              ;N << 8
10b219: 09 d0                or     %edx,%eax              ;(N << 8) | M
10b21b: 8b 54 24 78          mov    0x78(%rsp),%edx        ;P [5:0]
10b21f: 83 e2 3f             and    $0x3f,%edx
10b222: c1 e2 10             shl    $0x10,%edx             ;(P & 0x3f) << 16
10b225: 09 d0                or     %edx,%eax
10b261: 25 ff ff c0 ff       and    $0xffc0ffff,%eax       ;clear [21:16] when P=1
10b26c: 0d 00 00 01 10       or     $0x10010000,%eax       ;set P=1 (bit 16) + bit 28 (0x10000000)!
10b271: ba 04 20 13 00       mov    $0x132004,%edx
10b276: 89 c1                mov    %eax,%ecx
10b278: e8 93 48 42 00       call   52fb10 <_nv031893rm>   ;ram_wr32(0x132004, val)
```
- **Bitfield Layout of `0x132004` (`MEMPLL_COEFF`)**:
  - **Bits `[7:0]` (`M`)**: Reference divider ($M = 2$ on GF106).
  - **Bits `[15:8]` (`N`)**: Feedback multiplier ($N = 54 \ (0x36)$ at $900\text{ MHz}$; $N = 27 \ (0x1b)$ at $450/405\text{ MHz}$).
  - **Bits `[21:16]` (`P`)**: Post-divider ($P = 1 \ (0x01)$ in PLL mode).
  - **Bit `[28]` (`0x10000000`)**: PLL lock-detector / SDM enable bit, explicitly ORed via `or $0x10010000, %eax`!
- **Exact `0x132004` Value for Synthetic P-State `0a` (`648 MHz` DDR3)**:
  - Since $900\text{ MHz}$ uses $M = 2, N = 54 \ (0x36), P = 1$ (effective step $= 900 / 54 = 16.667\text{ MHz}$ per $N$ increment):
    - For **$650.0\text{ MHz}$** ($N = 39 = \text{0x27}$): **`0x10012702`**
    - For **$633.3\text{ MHz}$** ($N = 38 = \text{0x26}$): **`0x10012602`**
    - Alternatively, with $M = 3, N = 58 \ (\text{0x3a}), P = 1$: $900 \times \frac{2}{3} \times \frac{58}{54} = \mathbf{644.4\text{ MHz}}$ (**`0x10013a03`**), or $M = 5, N = 97 \ (\text{0x61}), P = 1$: $900 \times \frac{2}{5} \times \frac{97}{54} = \mathbf{646.7\text{ MHz}}$ (**`0x10016105`**).
  - Using $M = 2, N = 39$ (**`0x10012702`**, $650\text{ MHz}$) keeps the phase detector frequency identical to $900\text{ MHz}$ ($M = 2$), guaranteeing identical loop filter stability!

#### 2. DDR3 DLL-On Threshold & Self-Refresh Sequence Inside `_nv010721rm` (`0xee660–0xef4d4`)
- At `0xee660`, `_nv010721rm` checks if the target MCLK falls inside `[270,000 kHz .. 405,000 kHz]` (`sub $0x41eb0, %eax; cmp $0x20f58, %eax`) or above `405,000 kHz` to decide between the bypass path (`0x137360 = 0x0`) and the full `MEMPLL` path (`0x137360 = 0x00020200`).
- Between `0xeeb59` and `0xef4d4`, `_nv010721rm` emits the exact `0x10f200` (Self-Refresh entry/exit) and `0x10f32c` / `0x10f324` (`EMRS` / `MRS` shadow triggers: `0x80` $\to$ `0x880` $\to$ `0x80` $\to$ `0x84` $\to$ `0x81` $\to$ `0x88` $\to$ `0x1080`) sequence that we captured in our `mmiotrace` (§2.2 Steps 25–28) and implemented in `ramgf100.c`!

---

### 10.6 `nv-kernel.o_binary`: VBIOS-to-Register DDR3 Timing, MR0/MR1/MR2 & PHY Calculators

Disassembling the FBPA (`0x10fxxx`) subsystem in `nv-kernel.o_binary` (`0x2ec530–0x2fe200`) revealed how RM computes every single PFB timing, mode, and PHY register during an MCLK transition:

#### 1. Master VBIOS RAM Timing Calculator: `_nv014883rm` (`0x2ec720`, 3,293 B)
`_nv014883rm` looks up the VBIOS Memory Clock Table entry (`%r14`) covering the target frequency via `_nv015366rm` (`0x2ec530`) and populates the FB timing state struct (`%r13`), which is then emitted to hardware by `_nv015935rm` (`0x2ee270`, GF100) or `_nv015936rm` (`0x2f66b0`, GF104/GF106):

- **Critical Discovery**: RM does **not** use an arbitrary polynomial to invent JEDEC timings out of thin air; instead, `_nv015366rm` selects the VBIOS Memory Clock Table entry whose `[MinFreq, MaxFreq]` range covers the requested frequency (or the next higher strap entry when `[pFb + 0x1033] != 0`), and then applies two frequency-dependent adjustments:
  1. **Branch A — VBIOS Pre-Packed Strap Mode (`[pFb + 0x1033] != 0` @ `0x2ed1d8`)**:
     - Copies the pre-packed 32-bit timing registers directly from the VBIOS strap entry (`[%r14 + 0x80..0x98]`):
       - `0x10f290` (`TIMING_0`) $\leftarrow$ `[entry + 0x80]`
       - `0x10f294` (`TIMING_1`) $\leftarrow$ `[entry + 0x84]`
       - `0x10f298` (`TIMING_2`) $\leftarrow$ `[entry + 0x88]`
       - `0x10f29c` (`TIMING_3`) $\leftarrow$ `[entry + 0x8c]`
       - `0x10f2a0` (`TIMING_4`) $\leftarrow$ `[entry + 0x90]`
       - `0x10f2a4` (`TIMING_5`) $\leftarrow$ `[entry + 0x94]`
       - `0x10f2a8` (`TIMING_6`) $\leftarrow$ `[entry + 0x98]`
     - Validates that `((TIMING_1 >> 7) & 0x7f) == entry[0x2a]` (`tCWL`) and `((TIMING_0 >> 17) & 0x7f) == entry[0x1d]` (`tCL`).
  2. **Branch B — Field-by-Field Formula Mode (`[pFb + 0x1033] == 0` @ `0x2ecada–0x2ece20`)**:
     - Constructs `0x10f290–0x10f2a0` from individual VBIOS timing byte fields (`entry[0x18..0x2c]`):
       - `0x10f290`: `(orig & 0x80000000) | ((entry[0x1e] & 0x7f) << 24) | ((entry[0x1d] & 0x7f) << 17) | (entry[0x1c] << 8) | entry[0x1b]`
         - Confirms: bits `[7:0]` = `tRC`, bits `[15:8]` = `tRFC`, bits `[23:17]` = `tCL` (`entry[0x1d]`), bits `[30:24]` = `tRCD` (`entry[0x1e]`).
       - `0x10f294`: `(orig & 0xfc000000) | ((entry[0x20] & 0x3f) << 20) | ((entry[0x1f] & 0x3f) << 14) | ((entry[0x2a] & 0x7f) << 7) | (entry[0x1a] & 0x7f)`
         - Confirms: bits `[6:0]` = `tRAS` (`entry[0x1a]`), bits `[13:7]` = `tCWL` (`entry[0x2a]`), bits `[19:14]` = `tWTR` (`entry[0x1f]`), bits `[25:20]` = `tWR` (`entry[0x20]`).
       - `0x10f298`: `0x11 | ((entry[0x19] & 0x7f) << 8) | ((entry[0x18] & 0x7f) << 16)`
         - Confirms: bits `[14:8]` = `tRP` (`entry[0x19]`), bits `[22:16]` = `tFAW` (`entry[0x18]`).
       - `0x10f29c`: `(orig & 0x00fe0000) | (entry[0x2b] << 9) | ((entry[0x2c] & 0xf) << 5) | (entry[0x22] & 0x1f)`
       - `0x10f2a0`: `(orig & 0xffe07fff) | ((entry[0x21] & 0x3f) << 15)`
  3. **High-Frequency `500 MHz` (`0x7a120 kHz`) Threshold in `_nv014883rm` (`0x2eccdc`)**:
     - At `0x2eccdc`, `_nv014883rm` checks `cmp $0x7a120, %ebx` (`targetFreq_kHz > 500,000 kHz`): when MCLK is above `500 MHz`, it applies the high-frequency turnaround/ODT adjustment (`[pFb + 0x448]`) to `0x10f29c` (`TIMING_3`)!

#### 2. DDR3 Mode Register (`MR0` / `MR1` / `MR2`) Calculator: `_nv014880rm` (`0x2ed5b0`, 2,929 B)
- Computes the JEDEC DDR3 Mode Registers written to `0x10f300` (`MR0`), `0x10f304` (`MR1`), and `0x10f308` (`MR2`):
  - **`MR0` (`0x10f300`)**: Encodes `CL = tCL - 4` into bits `[6:4]` and bit `[2]`, encodes `WR` (`tWR`) into bits `[11:9]`, and sets bit `[8]` (`0x100`, DLL Reset) during PLL/DLL transitions.
  - **`MR1` (`0x10f304`)**: Encodes DLL Disable bit `[0]` (`0` when DLL is enabled above `300 MHz`, `1` when DLL is disabled at `135 MHz`), output driver impedance (`Rtt_Nom`), and additive latency (`AL`).
  - **`MR2` (`0x10f308`)**: Encodes `CWL = (tCWL - 5) & 0x7` into bits `[5:3]` (`0x2ed781: lea -0x5(%rax), %esi; and $0x7, %esi; shl $0x3, %esi`) and dynamic ODT (`Rtt_WR`).

#### 3. Impedance / Drive Strength (`0x10f440` / `0x10f444` / `0x10f468`): `_nv015894rm` (`0x2efd60`)
- `_nv015894rm` (`0x2efd60`, GF100/GF104/GF106) and `_nv015895rm` (`0x2fc330`, GF108+) program `0x10f468`, `0x10f440`, and `0x10f444` directly from the selected VBIOS Memory Clock Table entry offsets `+0xd2` (16-bit word for `0x10f468`) and `+0xd5..+0xdc` (4-bit drive/termination nibbles packed into `0x10f440` and `0x10f444`).

#### 4. Per-Chip FBPA Script Emitters: `_nv015935rm` (`0x2ee270`) & `_nv015936rm` (`0x2f66b0`)
- `_nv015935rm` (GF100) and `_nv015936rm` (GF104/GF106) emit the FBPA register block (`0x10f30c`, `0x10f304`, `0x10f300`, `0x10f308`, `0x10f334`, `0x10f330`, `0x10f224`, `0x10f248`, `0x10f290..0x10f2ac`, `0x10f2cc`, `0x10f2e8`, `0x10f604`, `0x10f614`, `0x10f610`, `0x10f808`, `0x10f870`, `0x10f618`, `0x10f340..0x10f348`) into the sequencer script via `_nv031893rm` (`ram_wr32`).
- Every register offset is passed through `[pFb + 0xd20]` (`_nv016234rm` @ `0x2f3aa0` on GF100/GF106), which maps the offset to either broadcast (`0x10f000 + reg`) or per-partition unicast (`0x10e000 + part * 0x4000 + reg`), while reads use `_nv015759rm` (`0x2f3610`, unicast partition read from `0x10e000`) because `0x10f000` is write-only broadcast on Fermi!

---

### 10.7 Direct Engineering Implications for `nouveau`

1. **Synthetic P-State `0a` (P3: `405 MHz` Core / `810 MHz` Shader / `648 MHz` DDR3 @ `0.920 V`) is Immediately Actionable**:
   - Because `648 MHz` (`648,000 kHz`) lies above both the `405 MHz` (`0x62e08 kHz`)MEMPLL threshold and the `500 MHz` (`0x7a120 kHz`) high-frequency turnaround threshold in `_nv014883rm`, RM selects the **900 MHz VBIOS strap entry (`325–1000 MHz` range)** for all `0x10f290–0x10f2a0` JEDEC timings, `MR0/MR1/MR2` (`CL=13, CWL=9` — which is strictly conservative and rock-stable at `648 MHz` since fewer clock cycles elapse per nanosecond than at `900 MHz`!), and `0x10f440–0x10f468` drive strengths.
   - The **only** register that needs to change between the `900 MHz` (`0f`) table and the `648 MHz` (`0a`) table is **`0x132004` (`MEMPLL_COEFF`)**:
     - `900 MHz` (`0f`): `0x132004 = 0x10013602` ($M=2, N=54, P=1$)
     - `650 MHz` (`0a`): **`0x132004 = 0x10012702`** ($M=2, N=39, P=1 \implies 650.0\text{ MHz}$)
2. **120 Hz 3D Vision eDP Support (`LGD 0x02c5`)**:
   - In Nouveau's connector/DisplayPort validation (`nouveau_connector.c` / `dispnv50`), we must:
     1. Grant the `+5.0 MHz` pixel-clock tolerance and ignore self-contradicting EDID range descriptors for Detailed Timing Descriptors on 3D Vision panels (matching `_nv000659kms`).
     2. Allow DisplayPort/eDP `bpc` to step down from `8 bpc` (`24 bpp`) to **`6 bpc` (`18 bpp`)** when `pixel_clock * 24 > link_bw` (`396.36 MHz` on 4-lane HBR1 eDP, matching `_nv002219kms` $\to$ `_nv000673kms`).
     3. Enforce a minimum P-state floor of `07` (`dispclk = 405 MHz`) whenever a mode with `pixel_clock > 135 MHz` (such as `396.36 MHz` 120 Hz) is active so `dispclk >= pixel_clock`.
3. **Optional Native PDAEMON Context Switch (`_nv029647rm`)**:
   - While our custom Falcon executor (`memx_exec_custom.fuc`) already provides 100% reliable, zero-blob DDR3 reclocking across cold boot and S3 suspend/resume, `_nv029647rm` (`0x516850`) documents the exact `0x10a128` $\leftrightarrow$ `0x10a058` handshake if we ever wish to bind a host-memory context block to PDAEMON.

---

### 10.8 How `390.157` Handles Dynamic Reclocking (`PowerMizer`) vs. `nouveau-dynclockd`

Comparing the proprietary driver's open glue (`kernel/nvidia/nv.c`) + Resource Manager (`nv-kernel.o_binary`) against our userspace daemon ([`nouveau-dynclockd.py`](file:///home/twilight/Projects/nouveau-dkms/nouveau-dynclockd.py)) reveals how each architecture decides *when* to switch P-states:

| Mechanism | Proprietary `390.157` (`PowerMizer` in `nv-kernel.o_binary`) | `nouveau` (`nouveau-dynclockd` + `nouveau.ko`) |
|---|---|---|
| **Where the Governor Lives** | **In-kernel inside RM (`OBJPERF`)**, ticked once per second by the kernel timer `nvidia_rc_timer_callback()` $\to$ `rm_run_rc_callback()` (`1 Hz` periodic timer in `nv.c`) plus immediate event hooks on channel creation/pushbuffer kickoff. | **Userspace daemon (`nouveau-dynclockd.py`)** polling `/sys/kernel/debug/dri/*/clients`, `/proc/interrupts`, and `pstate` every `0.5–1.0 s` and writing target P-state IDs to debugfs `pstate`. |
| **How GPU Load is Measured** | **Hardware PDAEMON Idle/Busy Counters (`0x10a600..0x10a610`)**: `_nv029625rm` (`0x515a70`) and `_nv029628rm` (`0x515ad0`) program 4 hardware signal filters in PDAEMON: <br>1. `GR` (3D/Compute engine busy cycles)<br>2. `FB` (Memory controller busy cycles)<br>3. `VDEC` (`MSPDEC`/`MSVLD`/`MSPPP` video decode busy cycles)<br>4. `PCIE` / Host FIFO activity.<br>Every `1 Hz` tick, RM reads elapsed busy cycles vs. reference clock cycles (`0x10a5xx`) to compute exact hardware `%` utilization. | **Software Activity Heuristics (Currently)**: Tracks active DRM render/X11/Wayland clients (`/sys/kernel/debug/dri/*/clients`) and Nouveau hardware interrupt deltas (`/proc/interrupts`). *(Planned upgrade in `TODO.md` §6: read the same `0x10a600..0x10a610` hardware counters!)* |
| **Proactive "Boost on Context/Swap" Triggers** | Userspace OpenGL (`libGLX_nvidia.so`) and VDPAU (`libvdpau_nvidia.so`) send an immediate `rm_ioctl` (`NV2080_CTRL_CMD_PERF_BOOST`) when a 3D context swaps buffers or creates a swapchain, jumping straight to `P0` (`0f`) *before* the 1 Hz timer even fires. | `nouveau-dynclockd` detects new DRM client contexts / IRQ bursts within `500 ms` (or immediately via `nouveau-ctrl` / per-app rules). |
| **Downclock Hysteresis (Hold Timers)** | Uses multi-step hold-down timers (`~3–5 s` in `P0` $\to$ `~5–10 s` in `P8` $\to$ `P12`) so brief pauses between game frames or shader compiles never cause a jarring mid-game DDR3 reclock. | Configurable cooldown hysteresis in `nouveau-dynclockd` + thermal runaway protection (auto-steps down from `10` $\to$ `0f` if GPU temp $\ge 85\text{ }^\circ\text{C}$). |
| **Hardware Constraints (`IMP` & Power Source)** | Automatically locks out `P12` (`03`) when `396.36 MHz` 120 Hz mode is active (`_nv002187kms`), and caps to `P8` (`07`) on battery power via ACPI `_PSR` notifications. | Supports `BATTERY_CAP` (`AC`/`BAT` sysfs awareness), `10` overclock state, and user-selectable manual override modes (`auto`, `p12`, `p8`, `p3`, `p0`, `oc`). |


