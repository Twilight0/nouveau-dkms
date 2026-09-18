# Nouveau & NVIDIA Proprietary Driver Reclocking & Architecture Guide

This document is the unified reference for GPU reclocking, performance optimization, and display architecture on the **Dell XPS L702X** laptop equipped with an **NVIDIA GeForce GT 555M** (Fermi / **GF106M**, Device ID `10de:0dcd`, 3072 MiB DDR3, 1920×1080 @ 120 Hz 3D panel).

---

## 1. Hardware & System Specifications

| Parameter | Value |
|---|---|
| **GPU** | GeForce GT 555M (Fermi GF106M, stepping A1) |
| **Chipset ID** | `0x0c3680a1` (GF106, TSMC foundry) |
| **VRAM Type** | **DDR3** (192-bit bus width, NOT GDDR5) |
| **VRAM Size** | 3072 MiB |
| **RAMCFG Strap** | `0x6` |
| **Internal Panel** | 1920×1080 @ 120 Hz (eDP-1 / LGD `0x02c5`, 396.36 MHz pixel clock) |
| **Active Kernel** | Linux CachyOS LTS (6.18+) |

### VBIOS P-State Table (from BIT 'P' Table)

| State | Core Clock | Memory Clock | Effective Bandwidth | Voltage | Usage Profile |
|---|---|---|---|---|---|
| `03` | 50 MHz | 135 MHz | 270 MT/s | 820 mV | Low-Power Idle / Standby |
| `07` (or `08`) | 202 MHz | 324 MHz | 648 MT/s | 820 mV | Standard 2D Desktop Idle |
| `0f` | 590 MHz | 900 MHz | 1800 MT/s | 1030 mV | Full 3D Performance |

---

## 2. Executive Summary & Component Status

| Component | Status | Description / Solution |
|---|---|---|
| **Core / Shader Reclocking** | ✅ **Working** | Transitions to `590 MHz` core / `1180 MHz` shader cleanly via `nvkm_cstate_prog()`. |
| **Memory Reclocking Loop Locks** | ✅ **Fixed** | Fixed PRIVRING bus faults (`0x10a580`) and PMU D-state timeout deadlocks. |
| **DDR3 Memory Reclocking Path** | 🧪 **Testing (`NvFermiMemReclock=0` by default)** | Root cause found: PDAEMON I/O block is gated after Falcon reset; unlock sequence added to `gt215_pmu_init()`. Decoded proprietary DDR3 script runs via MEMX. See §4.5–4.6. |
| **Dynamic Clock Daemon** | ✅ **Working** | `nouveau-dynclockd.py` scales pstates (`07` ↔ `0f`) automatically based on GPU load. |
| **Backlight Control** | ✅ **Working** | ACPI EC hotkey driver (`dell-xps-brightness-dkms`) and hardware backlight sync. |
| **Fan RPM Reading** | ✅ **Working** | `dell_smm_hwmon` configured with `fan_mult=1` in `/etc/modprobe.d/dell-smm-hwmon.conf`. |

---

## 3. Nouveau Fermi Reclocking Architecture & Bug Fixes

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

