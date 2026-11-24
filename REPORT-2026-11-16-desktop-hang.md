# Desktop Hang Report — 2026-11-16 (17:56–18:03 EET)

Investigative only. No changes were made to the running system during this
investigation, and no recovery action was needed — the desktop recovered on its
own.

## TL;DR

**This was not a Qtile bug.** Qtile never crashed, never restarted, and was
responsive again afterwards (uptime at time of writing: 1 day 7 hours, PID 840,
started 2026-11-15 10:49). What froze was the **display path**: the GPU stopped
accepting work, so Qtile could not commit frames and the desktop appeared hung.

The trigger was a **`PBDMA0` `[EMPTY_SUBC]` error followed immediately by a PGRAPH fault in a Vivaldi GPU channel** (`vivaldi-bin`, channel 7), which killed that channel and then wedged the Fermi runlist (`nvkm_runl_rc` / `nv50_runl_wait` / `SCHED_ERROR 0d`). Every subsequent display commit blocked for ~7 minutes until channel teardown completed.

While the custom DDR3 reclocking (`custom Falcon executor`) was initially suspected (89 reclock events on the day, the last one **4m47s** earlier), the `17:51:37` transition completed cleanly in `491 us (vpos 1078 -> -13)`, and the `PBDMA0 [EMPTY_SUBC]` submission from `vivaldi-bin` points more strongly to a userspace/Mesa `nvc0` pushbuffer or BO-lifetime fault amplified by upstream `nouveau` runlist recovery timeouts.

There is a working recovery path already in this repo —
`tools/nouveau-pcie-live-recovery.sh` — and it did not need to be used this
time (nor was a PCIe link reset involved here). Recommended next steps are
updated in the last sections.

## Hardware / OS context

| Item | Value |
| :--- | :--- |
| Machine | Dell XPS L702X (2011 laptop) |
| CPU | Intel i7-2670QM, Sandy Bridge — currently 88 °C, high=86 °C |
| GPU | NVIDIA GeForce GT 555M, Fermi GF106M, `nouveau` |
| Driver | `nouveau-xanmod-lts-x64v2` 2.3.3-3 (out-of-tree, `updates/nouveau.ko`) |
| Kernel | 6.18.63-x64v2-xanmod1 |
| Session | Qtile (Wayland), Xwayland, Vivaldi, swaync |
| Clocking | `nouveau-dynclockd` active 1d7h, 34 min CPU |
| Reclocking | 89 events on 2026-11-16 (324000 ↔ 900000 kHz) |

Note the driver is **not** in-tree: `/lib/modules/.../updates/nouveau.ko.zst`
from `nouveau-xanmod-lts-x64v2`, described as *"Prebuilt Nouveau kernel module
with Fermi core, shader, and DDR3 memory reclocking"*, installed 2026-11-13.

## Timeline (2026-11-16)

| Time | Event |
| :--- | :--- |
| 17:46:43 → 17:51:37 | 6 reclock events (324↔900 MHz) in 5 minutes (`17:51:37` completed cleanly in `491 us`, `vpos 1078 -> -13`) |
| **17:56:24** | **`PBDMA0` error**, Vivaldi channel 7: `00800000 [EMPTY_SUBC]`, `subc 7 mthd 0000 data 001f906e` |
| **17:56:24** | **PGRAPH fault**, Vivaldi channel 7: `READ at 0000000000000000`, `client 05 [HUB/CTXCTL]`, `reason 02 [PAGE_NOT_PRESENT]` |
| 17:56:24 | Channel 7 errored, **disabled** — `vivaldi-bin[2040425]: channel 7 killed!` |
| 17:56:34 | First `nouveau timeout`, `nvkm_runl_wait` WARNING |
| 17:57:04 → 18:03:25 | 14 × `fifo: SCHED_ERROR 0d`, repeated runlist stalls |
| **17:59:46** | **kworker blocked 120 s** — `nv50_disp_atomic_commit_work` waiting on `dma_fence` |
| 18:01:47 | Second kworker blocked — `ttm_bo_delayed_delete` |
| 18:03:15 | `nouveau_drm_postclose` → `nvkm_runl_preempt_wait` timeout |
| after 18:03 | Recovers; no further errors logged |

**Total unresponsive window: ~7 minutes.**

## Findings

### 1. The GPU runlist wedged; the compositor was starved

The blocking chain is unambiguous:

```
kworker/u32:14  state:D
  Workqueue: events_unbound nv50_disp_atomic_commit_work [nouveau]
  dma_fence_default_wait
  dma_fence_wait_timeout
  drm_atomic_helper_wait_for_fences
  nv50_disp_atomic_commit_tail [nouveau]
```

`nv50_disp_atomic_commit_work` is how a frame reaches the display. It was
waiting on a GPU fence that never signalled, because the runlist had stalled
after the channel kill. No commit could complete → no new frames → the desktop
froze.

### 2. Qtile was a victim, not a cause

- Qtile's process start time is unchanged across the incident
  (`Sun Nov 15 10:49:02`, 1d7h uptime) — it did not crash or restart.
- There are **no** Qtile core dumps on 2026-11-16.
- Qtile's own log shows only routine Xwayland property errors and two
  `toggoup` keybinding errors — no exceptions, no tracebacks.
- Qtile IPC answers in 3 ms now.

Qtile was blocked in `wlr_scene_output_commit`, waiting for the DRM commit to
return. That is correct behaviour when the driver stalls.

### 3. Two distinct layers: Vivaldi/Mesa trigger vs. upstream runlist recovery

| Observation | Value |
| :--- | :--- |
| Reclock events on 2026-11-16 | **89** |
| Last reclock before the fault | 17:51:37 (900000 → 324000 kHz, `491 us`, `vpos 1078 -> -13`) |
| Gap between last reclock and fault | **4 m 47 s** |
| First fault line (`17:56:24`) | `fifo: PBDMA0: 00800000 [EMPTY_SUBC] ch 7 ... subc 7 mthd 0000 data 001f906e` |
| Custom `nouveau-dkms` patches | Do **not** touch `fifo`, `runl`, or `PGRAPH` recovery |

Two separate issues combined here:

1. **The trigger (`PBDMA0 [EMPTY_SUBC]` -> `HUB/CTXCTL PAGE_NOT_PRESENT`):**
   `PBDMA0` attempted to execute a method on unbound/uninitialized `subc 7` in
   `vivaldi-bin`'s channel (`ch 7`). Because the last reclock finished cleanly in
   vblank **4m47s** earlier, an in-flight DDR3 timing glitch is a weak fit; a
   userspace/Mesa (`nvc0`) pushbuffer or BO-lifetime bug in `vivaldi-bin` is
   the stronger primary suspect (though pinning `07` remains a cheap control
   test if hangs recur).
2. **The 7-minute freeze (upstream kernel `nouveau`):**
   Even when one client submits bad commands and is killed (`channel 7 killed!`),
   it should not starve the display compositor. In upstream `nouveau`
   (`nvkm_runl_rc` / `nv50_runl_wait` / `nvkm_runl_preempt_wait`), the `PGRAPH`
   fault led to repeated 10 s runlist preemption timeouts (`SCHED_ERROR 0d`)
   until `nouveau_drm_postclose` finished tearing down channel 7.

### 4. Why PCIe link reset is ruled out for this incident

`tools/nouveau-pcie-live-recovery.sh` documents a separate failure mode for
this exact hardware:

> Upstream PCIe Root Port (`0000:00:01.0`) ASPM L1 transitions or electrical
> bus glitches trigger a hot link reset on the discrete GPU (`0000:01:00.0`).
> A link reset zeroes out volatile PCI config registers — Command clears to
> 0x0000, BAR0..BAR5 clear to 0, MSI Control/Address/Data clear to 0. Once
> `Mem-` is cleared, every MMIO read to BAR0/BAR1 returns `0xffffffff`.

In this event, the GPU **remained reachable over MMIO**: the kernel read valid
`PBDMA0`, `PGRAPH HUB/CTXCTL`, and `SCHED_ERROR 0d` fault/interrupt registers
and recovered on its own after ~7 minutes without `setpci` restoring BARs or
`COMMAND`. A PCIe link reset therefore did not cause this hang.

If a future hang occurs without `PBDMA0`/`PGRAPH` fault descriptors, live
checks during the hang remain useful to distinguish the two paths:

```bash
setpci -s 01:00.0 COMMAND          # 0407/0007 = healthy, 0000 = link reset
setpci -s 01:00.0 BASE_ADDRESS_0   # 00000000 = BAR zeroed
lspci -vv -s 01:00.0 | grep -i aspm
```

### 5. Thermal is an aggravating factor, not the cause

Current readings put the CPU at **88 °C** against a `high` threshold of 86 °C
(critical 100 °C). The 2026-10-26 report found the same machine pinned at
100 °C during a freeze. High package temperature destabilises the PCIe link and
shortens the time before a reclock goes wrong, but it did not trigger this
event — there is no thermal critical event in the journal at 17:56.

## Suggested fixes

Ordered by ratio of risk-reduction to effort. **None applied** — these are
proposals.

### A. Add a pre-fault snapshot so future occurrences are immediately classifiable

If a hang recurs, capturing PCI + pstate status at the first `nouveau.*timeout`
makes it trivial to separate a PCIe link drop from a `PBDMA0`/`PGRAPH` runlist
stall:

```bash
# /usr/local/bin/nouveau-fault-snapshot
# Triggered on the first nouveau timeout in a boot; dumps the PCI state
# that distinguishes a link reset from a runlist stall.
out="/var/log/nouveau-fault-$(date +%s).txt"
setpci -s 01:00.0 COMMAND BASE_ADDRESS_0 BASE_ADDRESS_1 > "$out"
lspci -vv -s 01:00.0 >> "$out"
cat /sys/kernel/debug/dri/*/pstate >> "$out" 2>/dev/null
```

Wire it to a systemd unit or journal watcher on `nouveau.*timeout` (note the
`dri/*/pstate` glob so it works regardless of DRM card probe order).

### B. Do NOT add a separate `options nouveau config=noaspml1` file

- PCIe link reset was **not** the cause of this hang (§4).
- `/etc/modprobe.d/nouveau.conf` already sets:
  `options nouveau modeset=1 config=NvFermiMemReclock=true,NvFermiOC=true`
- Creating a second `/etc/modprobe.d/*.conf` with `options nouveau config=noaspml1`
  would **overwrite** `config=` and silently disable `NvFermiMemReclock` and
  `NvFermiOC`. Furthermore, `noaspml1` is not a standard Nouveau `config=` key
  (Nouveau uses `NvPCIE=0` or kernel `pcie_aspm.policy=performance` / `setpci`).
  Only touch ASPM if a future snapshot (A) actually shows `COMMAND=0000` /
  `BAR0=00000000`.

### C. Throttle the reclocking daemon (medium risk, addresses §3)

`nouveau-dynclockd` produced 89 clock changes in one day, including six in five
minutes. Each is a window where the memory controller is mid-change.

Concrete options, least invasive first:

1. **Raise the hysteresis** so it stops bouncing between 324 and 900 MHz.
   Six transitions in five minutes is oscillation, not adaptation.
2. **Pin to the low state** (`324000`) as a diagnostic: if the hangs stop, the
   reclock path is confirmed as the cause. Run for a week.
3. **Add an idle guard**: never reclock while any GPU channel has pending work.
   This is the correct fix but needs a change in the driver or the daemon's
   trigger logic.

Option 2 is the cheapest experiment and gives a definitive answer.

### D. Recover without a reboot (already implemented)

`tools/nouveau-pcie-live-recovery.sh` restores BARs, MSI and the Command
register, then resumes the clocking daemon. **It did not need to run this
time** — the system recovered on its own after ~7 minutes.

Two gaps worth closing in it:

1. **It only helps if the PCI registers were zeroed.** Run the §4 checks first;
   if `COMMAND` is healthy, this script will do nothing for a runlist stall.
2. **Nothing invokes it automatically.** Consider a `systemd` unit triggered by
   the same journal pattern as (A), gated on the `COMMAND`/`BAR0` check so it
   only acts when the link really was reset.

### E. Thermal headroom (independent of the above)

88 °C against an 86 °C high threshold is not a healthy operating point for a
14-year-old laptop. It is not the cause of this event, but it makes every other
failure mode more likely. Worth a separate investigation: fan curve, dust,
thermal paste, or simply capping the CPU governor.

## Recommended approach (wait & isolate before patching)

1. **Do not rush a kernel driver patch yet.** This was a single self-recovered
   event, and `nouveau-dkms`'s custom patches (`patches/`) do not modify
   `fifo`, `runl`, or `PGRAPH` recovery. Writing speculative kernel patches for
   a one-off userspace-triggered fault risks destabilizing a working build.
2. **Add (A) — the snapshot watcher** (with `dri/*/pstate`), so any future
   hang captures live PCI/pstate evidence immediately.
3. **Observe on recurrence:**
   - Check `journalctl` for `PBDMA0` / `[EMPTY_SUBC]` and whether `vivaldi-bin`
     (or another specific Mesa client) is consistently the faulting channel.
   - Optionally run **C.2** (pin `07` / `324 MHz` for a few days) as a clean,
     reversible control test to rule out reclocking involvement.
4. **Target the right layer only if it recurs:**
   - Stops with `07` pinned → add an idle/quiesce guard around reclocking in
     `nouveau-dkms`.
   - Recurs even with `07` pinned → treat as a **Mesa `nvc0` / Vivaldi**
     command-stream trigger (`PBDMA0 [EMPTY_SUBC]`) plus an **upstream kernel
     `nouveau`** `nvkm_runl_rc` / `PGRAPH` reset timeout issue.
5. **Skip (B)** unless (A) ever shows `COMMAND=0000` / `BAR0=00000000`, and
   address **(E) thermals** separately.

## Appendix — evidence commands

```bash
# the fault sequence
journalctl --since "2026-11-16 17:50" --until "2026-11-16 18:10" \
  | grep -E "fifo:|timeout|blocked for more than"

# reclocking history
journalctl -b | grep "reclocking memory"

# Qtile was not restarted
ps -o pid,lstart,etime -p $(pgrep -x qtile)

# no Qtile cores
coredumpctl list | grep -i qtile
```
