#!/usr/bin/env bash
# trace_driver_reload.sh — NVIDIA GF106 DDR3 reclock MMIO tracer
#
# Captures: PMU firmware init + PMU queue unlock + DDR3 324→900→324 MHz reclock.
#
# USAGE
#   sudo bash trace_driver_reload.sh          # full run (init + 3D reclock)
#   sudo bash trace_driver_reload.sh --init   # init only, no 3D
#
# RUN FROM a VT (Ctrl+Alt+F2) as root, BEFORE starting any desktop.
# nouveau must not be loaded; proprietary nvidia-390xx packages must be installed.
#
# WHAT IT DOES
#   1. Stop display manager and unload all GPU drivers (nouveau or nvidia)
#   2. Size the mmiotrace ring buffer large enough to hold the entire session
#   3. Enable mmiotrace and open the pipe
#   4. Load nvidia → nvidia_modeset → nvidia_drm  (captures full PMU init)
#   5. Start a minimal X server with only glxgears on :1  (triggers P0 reclock)
#   6. Wait for P8→P0 transition, then let it idle back to P8
#   7. Stop X, stop tracer, stop nvidia
#   8. Decode with demmio and report key counters
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
RAW_TRACE="$SCRIPT_DIR/nvidia_trace_${TIMESTAMP}.raw"
DECODED_TRACE="$SCRIPT_DIR/nvidia_trace_${TIMESTAMP}.txt"
GPU_PCI="01:00.0"          # BDF of your GF106
USER="twilight"            # non-root user to run X/glxgears as
INIT_ONLY="${1:-}"         # pass --init to skip 3D load
GLXGEARS_RUNTIME=10        # seconds to run glxgears at P0 (needs ≥2 to reclock)

# Per-CPU ring buffer in KB.
# 32 MB × 8 CPUs = 256 MB.  Eliminates LOST events for a ~12-second session.
# Lower to 8192 if the kernel OOMs (check dmesg after setting).
BUFFER_KB=32768

TRACE_PID=0
X_PID=0
XORG_DISP=":1"

# ── Helpers ───────────────────────────────────────────────────────────────────
die()    { printf '\n[-] %s\n' "$*" >&2; exit 1; }
info()   { printf '[*] %s\n' "$*"; }
ok()     { printf '[+] %s\n' "$*"; }
banner() { printf '\n══════════════════════════════════════════════════\n %s\n══════════════════════════════════════════════════\n\n' "$*"; }

# ── Cleanup ───────────────────────────────────────────────────────────────────
cleanup() {
    local rc=$?
    info "Cleaning up..."

    # Kill glxgears / X if still running
    pkill -KILL -f glxgears 2>/dev/null || true
    [[ $X_PID -ne 0 ]] && { kill -KILL "$X_PID" 2>/dev/null || true; wait "$X_PID" 2>/dev/null || true; }

    # Stop the tracer — must happen BEFORE unloading nvidia so the
    # unmap events are captured cleanly
    echo nop > "$TRACE_DIR/current_tracer" 2>/dev/null || true
    sleep 0.5

    # Drain and close the pipe
    if [[ $TRACE_PID -ne 0 ]]; then
        kill "$TRACE_PID" 2>/dev/null || true
        wait "$TRACE_PID" 2>/dev/null || true
        TRACE_PID=0
    fi

    # Restore buffer size
    echo "$ORIG_BUF" > "$TRACE_DIR/buffer_size_kb" 2>/dev/null || true

    # Unload nvidia (best-effort; ignore if X is still holding it)
    for mod in nvidia_drm nvidia_modeset nvidia_uvm nvidia; do
        modprobe -r "$mod" 2>/dev/null || true
    done

    if [[ -s "$RAW_TRACE" ]]; then
        info "Raw trace saved: $RAW_TRACE ($(wc -l < "$RAW_TRACE") lines)"
    fi
    [[ $rc -ne 0 ]] && info "Exited with error code $rc"
}
trap cleanup EXIT INT TERM

# ── Sanity checks ─────────────────────────────────────────────────────────────
[[ $EUID -eq 0 ]]      || die "Must be run as root"
command -v xinit       >/dev/null || die "xinit not found (install xorg-xinit)"
command -v glxgears    >/dev/null || die "glxgears not found (install mesa-demos)"

# Locate tracefs
TRACE_DIR=""
for d in /sys/kernel/tracing /sys/kernel/debug/tracing; do
    [[ -d "$d" ]] && { TRACE_DIR="$d"; break; }
done
[[ -n "$TRACE_DIR" ]] || die "tracefs not mounted; try: mount -t tracefs nodev /sys/kernel/tracing"
grep -qw mmiotrace "$TRACE_DIR/available_tracers" \
    || die "CONFIG_MMIOTRACE not enabled in this kernel"

banner "NVIDIA GF106 DDR3 Reclock MMIO Tracer — $TIMESTAMP"

# ── Step 1: tear down any existing GPU session ────────────────────────────────
info "[1/5] Stopping display manager and GPU drivers..."

for dm in lightdm gdm sddm lxdm; do
    systemctl is-active --quiet "$dm" 2>/dev/null && { systemctl stop "$dm"; sleep 1; } || true
done

# Kill compositor/X if DM stop didn't do it
pkill -TERM Xorg 2>/dev/null || true
sleep 1
pkill -KILL Xorg 2>/dev/null || true
pkill -KILL xinit 2>/dev/null || true
fuser -k /dev/nvidia* /dev/dri/* 2>/dev/null || true
sleep 0.5

# Unload whichever GPU driver is currently active (nouveau OR nvidia)
for mod in nvidia_drm nvidia_modeset nvidia_uvm nvidia nouveau; do
    modprobe -r "$mod" 2>/dev/null || true
done
sleep 0.5

if lsmod | grep -qE "^(nvidia|nouveau)"; then
    lsmod | grep -E "^(nvidia|nouveau)"
    die "GPU driver still loaded — run from a VT with no desktop active"
fi
ok "GPU drivers unloaded."

# ── Step 2: configure mmiotrace ───────────────────────────────────────────────
info "[2/5] Configuring mmiotrace ring buffer..."

ORIG_BUF="$(cat "$TRACE_DIR/buffer_size_kb" 2>/dev/null || echo 7)"

# Reset any prior session
echo nop > "$TRACE_DIR/current_tracer"
echo > "$TRACE_DIR/trace" 2>/dev/null || true
echo "$BUFFER_KB" > "$TRACE_DIR/buffer_size_kb"

ACTUAL_BUF="$(cat "$TRACE_DIR/buffer_size_kb")"
TOTAL_MB=$(( ACTUAL_BUF * $(nproc) / 1024 ))
info "  ${ACTUAL_BUF} KB/CPU × $(nproc) CPUs = ${TOTAL_MB} MB total"

echo mmiotrace > "$TRACE_DIR/current_tracer"
[[ "$(cat "$TRACE_DIR/current_tracer")" == "mmiotrace" ]] \
    || die "mmiotrace failed to activate"
ok "mmiotrace active."

# ── Step 3: open the capture pipe ─────────────────────────────────────────────
info "[3/5] Opening trace_pipe → $RAW_TRACE"

# cat blocks correctly on trace_pipe — it waits for events as they arrive.
# dd with iflag=nonblock exits immediately with EAGAIN on this special file.
cat "$TRACE_DIR/trace_pipe" > "$RAW_TRACE" &
TRACE_PID=$!

# Confirm the reader is alive
sleep 0.3
kill -0 "$TRACE_PID" 2>/dev/null || die "trace_pipe reader died immediately"
ok "Pipe reader PID $TRACE_PID running."

# ── Step 4: load nvidia and start X ───────────────────────────────────────────
info "[4/5] Loading NVIDIA driver stack..."

# Load in dependency order; each modprobe is captured because the tracer
# is already watching BAR0 (the kernel maps it during probe).
modprobe nvidia
ok "  nvidia core loaded (PMU firmware upload captured)."
sleep 0.5

modprobe nvidia_modeset
modprobe nvidia_drm modeset=1
ok "  nvidia_modeset + nvidia_drm loaded."
sleep 0.5

if [[ "$INIT_ONLY" == "--init" ]]; then
    info "  --init mode: skipping X/glxgears."
    info "  Sleeping 3 s to capture post-init idle state..."
    sleep 3
else
    # ── Start minimal X + glxgears on a free display ──────────────────────────
    info "  Starting minimal X server on $XORG_DISP..."

    # Remove any stale lock
    rm -f "/tmp/.X${XORG_DISP#:}-lock" "/tmp/.X11-unix/X${XORG_DISP#:}" 2>/dev/null || true

    # Run X + glxgears as the user (not root) — glxgears drives the GPU to P0
    # __GL_SYNC_TO_VBLANK=0  → uncapped FPS → maximum GPU load → fastest reclock
    # DISPLAY is exported so glxgears connects to the right server
    su - "$USER" -c "
        xinit /usr/bin/env \
            DISPLAY=${XORG_DISP} \
            __GL_SYNC_TO_VBLANK=0 \
            /usr/bin/glxgears \
        -- ${XORG_DISP} -nolisten tcp \
        >/tmp/nvidia-trace-xorg.log 2>&1
    " &
    X_PID=$!

    info "  Waiting for X to start and GPU to reach P0..."
    sleep 4  # X startup ~1-2 s; P0 transition follows within next frame

    # Confirm X is up
    if ! su - "$USER" -c "DISPLAY=${XORG_DISP} xdpyinfo >/dev/null 2>&1"; then
        info "  X didn't start cleanly — check /tmp/nvidia-trace-xorg.log"
        info "  Continuing anyway (driver init trace is still valuable)."
    else
        ok "  X running. glxgears rendering. GPU should be at P0 (900 MHz DDR3)."
    fi

    info "  Holding P0 for ${GLXGEARS_RUNTIME} seconds..."
    sleep "$GLXGEARS_RUNTIME"

    info "  Stopping glxgears (P0 → P8 down-clock will follow)..."
    pkill -TERM glxgears 2>/dev/null || true
    sleep 3  # capture the down-clock transition

    ok "  3D session done."

    # Stop X cleanly so nvidia_drm is freed
    kill -TERM "$X_PID" 2>/dev/null || true
    wait "$X_PID" 2>/dev/null || true
    X_PID=0
    sleep 0.5
fi

# ── Step 5: stop tracer and decode ────────────────────────────────────────────
info "[5/5] Stopping tracer and decoding..."

echo nop > "$TRACE_DIR/current_tracer"
sleep 0.5
kill "$TRACE_PID" 2>/dev/null || true
wait "$TRACE_PID" 2>/dev/null || true
TRACE_PID=0

RAW_LINES="$(wc -l < "$RAW_TRACE")"
RAW_BYTES="$(wc -c < "$RAW_TRACE")"
info "  Raw: ${RAW_LINES} lines / $(( RAW_BYTES / 1024 )) KB"

LOST="$(grep -c "^LOST" "$RAW_TRACE" 2>/dev/null || echo 0)"
if [[ "$LOST" -gt 0 ]]; then
    printf '[!] WARNING: %s LOST markers — increase BUFFER_KB (now %s KB) and retry\n' \
        "$LOST" "$ACTUAL_BUF"
else
    ok "  No dropped events."
fi

# Decode
if command -v demmio >/dev/null 2>&1; then
    info "  Decoding with demmio..."
    # -a GF106 avoids autodetect; fall back without -a if it fails
    demmio -a GF106 -f "$RAW_TRACE" > "$DECODED_TRACE" 2>/dev/null \
        || demmio -f "$RAW_TRACE" > "$DECODED_TRACE" 2>/dev/null \
        || { info "  demmio failed — raw trace only."; }
    ok "  Decoded: $(wc -l < "$DECODED_TRACE") lines → $DECODED_TRACE"
else
    info "  demmio not found; install envytools for decoded output."
fi

# Compress raw in background (typically 20:1 ratio)
xz -T0 -3 --keep "$RAW_TRACE" &
info "  Compressing raw trace in background..."

# ── Summary ───────────────────────────────────────────────────────────────────
CODE_IDX=0; DATA_IDX=0; DATA_HIT=0
if [[ -f "$DECODED_TRACE" ]]; then
    CODE_IDX=$(grep -c "0x10a180" "$DECODED_TRACE" 2>/dev/null || echo 0)
    DATA_IDX=$(grep -c "0x10a1c0" "$DECODED_TRACE" 2>/dev/null || echo 0)
    DATA_HIT=$(grep -c "0x10a1c4" "$DECODED_TRACE" 2>/dev/null || echo 0)
fi

banner "Done"
printf '  Raw trace   : %s\n'     "$RAW_TRACE"
printf '  Decoded     : %s\n'     "$DECODED_TRACE"
printf '  Compressed  : %s.xz\n'  "$RAW_TRACE"
echo ""
printf '  PDAEMON CODE_INDEX (0x10a180) hits : %s\n' "$CODE_IDX"
printf '  PDAEMON DATA_INDEX (0x10a1c0) hits : %s\n' "$DATA_IDX"
printf '  PDAEMON DATA       (0x10a1c4) hits : %s\n' "$DATA_HIT"
printf '  LOST markers                       : %s\n' "$LOST"
echo ""
printf '  If CODE_INDEX = 0, firmware was uploaded via DMA (not MMIO port).\n'
printf '  If LOST > 0, increase BUFFER_KB in this script and retry.\n'
echo ""
printf '  Restart desktop: systemctl start lightdm\n'
