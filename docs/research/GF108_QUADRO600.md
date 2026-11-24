# GF108 (NVC1) Quadro 600: DDR3 324 <-> 800 MHz from NVIDIA's own PMU scripts

Patches: `0013` (board gate, 0f clamp limited to GF106), `0014` (perf v0x40
memory discovery), `0015` (Quadro 600 script, GF108 MPLL readback).
Data: `testing/gf108_quadro600_pmu_memx_decoded.txt`. Generator:
`tools/gen-fexec-gf108.py`.

Test board: a Quadro 600 (HP OEM, PCI `10de:0df8`, subsystem `103c:0835`,
GF108GL, 1 GiB DDR3 128-bit, VBIOS 70.08.2a.00.01, RAMCFG strap 3, 2 FBPAs)
in a desktop with an ASUS P5Q board, kernel 7.0.

## 1. Why a board gate was needed

- Before 0013 the GF106M L702X executor script (`fexec_code.inc`) ran on
  every Fermi DDR3 board: `gf100_ram_calc_ddr3()` had no chip or board check.
  With `NvFermiMemReclock=true` (the shipped default) a Quadro 600 would run
  the GF106M "900 -> 324" script for its 800 MHz state, and also for the
  135/324 MHz pre-warm.
- Other boards got `-EINVAL` "unsupported memory clock" instead (issue #46,
  GT 730 with 405/500 MHz).
- 0013 restricts each script to the board it was captured on (PCI ID +
  subsystem + chipset). Every other DDR3 board logs once
  `DDR3: no executor script for this board` and keeps its boot memory clock;
  core, shader and voltage of the pstate still apply.
- With the gate in place, the shipped default `NvFermiMemReclock=true` is
  safe and is kept unchanged.
- 0013 also limits the "raise 0f to VID 0x67" clamp to GF106 (NVC3). The
  Quadro 600's 0f asks for VID 0x63, which the ungated clamp would have
  raised.

## 2. Perf table v0x40 (0014)

- GF108 boards use perf table v0x40. There the memory clock is not in the
  entry itself but in sub-entry (perfS) domain 0x05, the gf100 clk domain
  index of `nv_clk_src_mem`.
- Pstate-0xff entries are unused and are skipped.
- Quadro 600: pstates 03/07/0xff/0f with memory 135/324/0/800 MHz, giving the
  pair 324/800 (135 is the usual idle alias of 324).
- GT 730 (issue #46): 405/500 MHz. It now logs the pair and, being
  ungated, skips memory reclock instead of failing.

## 3. How the scripts were captured

- Kernel 7.0, booted with `module_blacklist=nouveau` in text mode.
- NVIDIA 390.157 built with the community kernel-6.2 .. 7.3 compatibility
  patch stack and loaded with `insmod` under mmiotrace (`maxcpus=1`).
- A CUDA context was opened and held open: closing it, or running
  nvidia-smi, oopses 390 on 7.0. Load bursts made the driver go to P0 and
  idle periods made it fall back.
- The scripts travel through PDAEMON DATA (`0x10a1c4`) and were decoded with
  `tools/decode-pmu-memx.py`.
- Register dumps taken at each phase confirm the states listed below.

Captured scripts (all DMEM `0x5800`):

| Block | Words | Transition |
|---|---|---|
| 20 | 131 | boot 324 MHz (mdiv bypass) -> 324 MHz on MPLL |
| 28 | 213 | 324 (MPLL) -> 800 (793) MHz |
| 54 | 206 | 800 -> 324 (MPLL) |
| 61 | 211 | second 324 -> 800: block 28 minus its first write |
| 69 | 206 | second 800 -> 324: identical to 54 |

Block 61 lacks block 28's `0x137310 = 0x81200608` because after block 54 that
register already holds `0x0608` (block 54 never restores `0x0808`).

## 4. Clock tree and register states

- The MPLL reference is the `0x137320`/`0x137330` divider: 1620 MHz * 2 /
  (6 + 2) = 405 MHz.
- `0x132004` = P[21:16] N[15:8] M[7:0]:
  - `0x00051806`: 405 * 24 / 6 / 5 = 324 MHz;
  - `0x00032f08`: 405 * 47 / 8 / 3 = 793.1 MHz (NVIDIA reports 793 MHz).
- The boot bypass is `0x137300`/`0x137310`, 1620 * 2 / (8 + 2) = 324 MHz.
- `0x137360` bit 0 selects the bypass.
- There is no FBPA refpll on GF108: `0x10fe20`/`0x10fe24` stay 0, and
  `0x132020`/`0x132024` do not exist (reads raise PRIVRING faults).

| State | 132000 | 132004 | 137310 | 137360 | 10f290 | 10f200 |
|---|---|---|---|---|---|---|
| boot 324 | 18010002 | 00000000 | 81200808 | 3 | 05182411 | 00028800 |
| MPLL 324 (after 20) | 18010001 | 00051806 | 81200808 | 2 | 05182411 | 00028800 |
| MPLL 324 (after 54) | 18030001 | 00051806 | 81200608 | 2 | 05182411 | 00028800 |
| 800 | 18030001 | 00032f08 | 81200608 | 2 | 0c3c5d2a | 00029800 |

Mode registers:
- MR2 is `0x00200080` (CWL 5) at 324 MHz and `0x00200098` (CWL 8) at 800 MHz.
- MR0 is `0x1520`/`0x1420` at 324 MHz and `0x1d70`/`0x1c70` at 800 MHz.

## 5. Implementation (0015)

The resident executor image `fexec_code_gf108.inc` is generated, not
hand-written. It reuses the GF106M image byte for byte, including the
command loop and the wr32/rd32/wait/delay/block/unblock helpers, and appends
straight-line script bodies. These use only instruction encodings already
present in that image. Commands:

- cmd 0: probe; reports DONE and writes nothing.
- cmd 1: block 28 (324 MPLL -> 800). From the post-54 form its first write
  is a no-op, which makes it exactly block 61.
- cmd 2: "to 324". A dispatcher reads `0x137360`: bit 0 set (boot bypass)
  runs block 20, clear (800) runs block 54.

The host writes NVIDIA made around each script (PHY set `0x10f4xx`,
`0x1548`, `0x10f050`, `0x132018`, `0x10f824`, `0x10f808`) run inside the
program in NVIDIA's order.

Differences from NVIDIA:
- `wr32 0x13d834 <= 0` + op `0x3a n` becomes a delay of about n * 10 us. The
  GF106M image translates its `0x13d8b4` pair the same way.
- Markers are dropped.
- The vblank waits become a fixed spin, because the host aligns the trigger
  to vblank.
- `nsec` delays get a margin of at least 1.48x.
- Waits are bounded at 0x20000 polls.
- NVIDIA writes `0x1548 = 0x101` while the PMU is in its pre-block vblank
  wait; here it is emitted just before the vblank op.

Error handling:
- The GF106M image leaves FB_PAUSE asserted when a wait or an FB_PAUSE
  acknowledge times out. The GF108 image instead releases the pause, restores
  the `0x1620`/`0x26f0` engine gating and reports `0xDEAD0108`.
- A PLL lock timeout before the FB block reports `0xDEAD0020`; DRAM is
  untouched in that case.

Host side:
- The host refuses any transition unless the exact start state, VBIOS
  version, strap, FBPA count and VBIOS pair match the capture.
- At boot 324 a request for 800 runs cmd 2 then cmd 1, verifying the state
  after each.
- The GF108 MPLL readback in `clk/gf100.c` uses mpllsrcref * N / M / P and
  never reads `0x132020`/`0x132024`.
- New options, both default false:
  - `NvFermiMemProbe=true`: cmd 0 at 324.
  - `NvFermiMemDryRun=true`: block 20 on a 324 request while still on the
    boot bypass (a 324 -> 324 retime).

## 6. Hardware results (kernel 7.0, text console)

- Probe: `cmd=0 DONE` in 4 us.
- Dry run (block 20): 290 us; ends at `132004 = 00051806`, `137360 = 2`.
- 324 -> 800 -> 324 -> 800 -> 324: every transition completed and the system
  stayed stable. The final state equals NVIDIA's post-block-54 state.
- PRIVRING read faults on `0x132020`/`0x132024` came from the post-switch
  telemetry and are fixed in 0015.
- One fault at `0x01050c` after block 20 is unexplained: no host code reads
  that address, and the NVIDIA traces never touch it.

## 7. Limits

- Only this board and VBIOS are tested. Any other GF108 board is gated off
  until its own scripts are captured.
- S3 suspend/resume is untested.
- Reloading the module while memory is at 800 MHz cannot restart the
  executor: the cold path refuses a PDAEMON reset above 400 MHz. Reboot
  first.
- The governor-driven idle/load cycle is still to be soak-tested.

## 8. Corrections to RECLOCKING_NOTES.md (static analysis of 390.157 / 340.108)

- 390.157 FB emitters:
  - `_nv015935rm` serves all big-Fermi chips, GF100/GF110/GF104/GF114/GF106/
    GF116 and GF108.
  - `_nv015936rm` serves GF117 + Kepler, `_nv015937rm` GF119 only,
    `_nv015938rm` Maxwell.
  - There is no separate GF108 emitter, and GF104/GF106 do not use
    `_nv015936rm` (section 10.6).
- The MCLK builder for GF100..GF116 and GF108 is `_nv010721rm`.
  `_nv010722rm`/`_nv010738rm` are GF117/Kepler. The `0x132004 = 0x1001xxxx`
  formula in section 10.5 comes from the Kepler helper. Fermi uses
  M[7:0] N[15:8] P[21:16] with no bit 28 (see section 4 above).
- In 340.108, `_nv006997rm` is the GF119 override emitter; the GF100-family
  emitter is `_nv006995rm`. The section 4.25 "14 missing registers"
  comparison is therefore GF119 evidence.
- FBPA unicast addressing is `((0x110 + part) << 12) | reg`, i.e. stride
  0x1000 from 0x110000, not `0x10e000 + part * 0x4000`.
- The only GF108-specific step in the MCLK switch is CLK HAL slot 0x238
  (`_nv010766rm`): it writes only the `0x137320` mux and `0x137330`. There
  is no `0x10fe20`/`0x10fe24` refpll programming and no `0x137390` bit 17
  wait. The captures confirm this.
