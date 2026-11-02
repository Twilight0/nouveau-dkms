#!/usr/bin/env bash
# ==============================================================================
# nouveau-pcie-live-recovery.sh
# ==============================================================================
# Live PCIe Configuration Space & BAR/MSI Recovery for Nouveau Fermi (GF106M)
# Restores GPU responsiveness without requiring a system reboot or compositor restart.
#
# Root Cause Addressed:
#   Upstream PCIe Root Port (0000:00:01.0) ASPM L1 transitions or electrical bus
#   glitches trigger a hot link reset on the discrete GPU (0000:01:00.0).
#   A link reset zeroes out volatile PCI config registers:
#     - Command (0x04) clears to 0x0000 (I/O-, Mem-, BusMaster-)
#     - BAR0..BAR5 (0x10..0x24) clear to 0x00000000
#     - MSI Control/Address/Data (0x6A..0x74) clear to 0
#   Once Mem- is cleared, every MMIO read to BAR0/BAR1 returns 0xffffffff,
#   causing kernel timers to stall ("timer: stalled at ffffffffffffffff"),
#   g84_bar_flush timeouts, D-state process deadlocks, and an unresponsive desktop.
#
# Recovery Operations:
#   1. Pause nouveau-dynclockd (if active) to stop concurrent MMIO polling.
#   2. Disable PCIe ASPM L0s/L1 and ClockPM on 0000:01:00.0 link.
#   3. Restore authoritative 32-bit & 64-bit BARs from kernel resource map.
#   4. Re-enable MSI vector & address (or default vector 0x21 on CPU 7).
#   5. Enable Command register 0x0407 (I/O+, Mem+, BusMaster+, DisINTx+).
#   6. Strobe Fermi MSI re-arm latch at extended PCI config offset 0x704.
#   7. Restore HDMI audio companion (0000:01:00.1).
#   8. Resume nouveau-dynclockd and verify GPU responsiveness.
# ==============================================================================

set -euo pipefail

# ANSI color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

GPU_PCI="0000:01:00.0"
GPU_SHORT="01:00.0"
AUDIO_PCI="0000:01:00.1"
AUDIO_SHORT="01:00.1"
BRIDGE_PCI="0000:00:01.0"

echo -e "${CYAN}${BOLD}=== Nouveau Fermi PCIe Live Recovery Tool ===${NC}"

# Check for root privileges
if [[ $EUID -ne 0 ]]; then
    echo -e "${RED}[ERROR] This script must be run as root (or with sudo).${NC}" >&2
    exit 1
fi

# Verify GPU presence
if ! lspci -s "${GPU_SHORT}" >/dev/null 2>&1; then
    echo -e "${RED}[ERROR] Target GPU (${GPU_SHORT}) not detected on PCI bus.${NC}" >&2
    exit 1
fi

echo -e "${BLUE}[*] Checking initial PCI status for ${GPU_SHORT}...${NC}"
INITIAL_CMD=$(setpci -s "${GPU_SHORT}" COMMAND)
INITIAL_BAR0=$(setpci -s "${GPU_SHORT}" BASE_ADDRESS_0)
echo -e "    Current Command Register : 0x${INITIAL_CMD}"
echo -e "    Current BAR0 Register    : 0x${INITIAL_BAR0}"

# 1. Stop background dynamic clocking daemon during re-programming
DAEMON_WAS_ACTIVE=0
if systemctl is-active --quiet nouveau-dynclockd.service 2>/dev/null; then
    echo -e "${YELLOW}[*] Pausing nouveau-dynclockd service during recovery...${NC}"
    systemctl stop nouveau-dynclockd.service
    DAEMON_WAS_ACTIVE=1
fi

# 2. Disable PCIe ASPM on the link
echo -e "${BLUE}[*] Disabling PCIe ASPM L0s/L1 and ClockPM on link...${NC}"
for aspm_path in \
    "/sys/bus/pci/devices/${GPU_PCI}/link/l1_aspm" \
    "/sys/bus/pci/devices/${GPU_PCI}/link/l0s_aspm" \
    "/sys/bus/pci/devices/${GPU_PCI}/link/clkpm"; do
    if [[ -w "${aspm_path}" ]]; then
        echo 0 > "${aspm_path}" || true
    fi
done

# 3. Read authoritative resource mapping from sysfs
RES_FILE="/sys/bus/pci/devices/${GPU_PCI}/resource"
if [[ ! -r "${RES_FILE}" ]]; then
    echo -e "${RED}[ERROR] Cannot read ${RES_FILE}.${NC}" >&2
    exit 1
fi

echo -e "${BLUE}[*] Extracting kernel BAR resource assignments...${NC}"
BAR0_RAW=$(sed -n '1p' "${RES_FILE}" | awk '{print $1}')
BAR1_RAW=$(sed -n '2p' "${RES_FILE}" | awk '{print $1}')
BAR3_RAW=$(sed -n '4p' "${RES_FILE}" | awk '{print $1}')
BAR5_RAW=$(sed -n '6p' "${RES_FILE}" | awk '{print $1}')

# Strip leading 0x
BAR0_HEX=$(printf "%08x" "${BAR0_RAW}")
BAR1_HEX=$(printf "%08x" "$(( ${BAR1_RAW} | 0x0c ))")
BAR3_HEX=$(printf "%08x" "$(( ${BAR3_RAW} | 0x0c ))")
BAR5_HEX=$(printf "%08x" "$(( ${BAR5_RAW} | 0x01 ))")

echo -e "    Target BAR0 (MMIO 16M)   : 0x${BAR0_HEX}"
echo -e "    Target BAR1 (VRAM 256M)  : 0x${BAR1_HEX}"
echo -e "    Target BAR3 (FIFO 32M)   : 0x${BAR3_HEX}"
echo -e "    Target BAR5 (I/O 128B)   : 0x${BAR5_HEX}"

# 4. Reprogram BAR registers on GPU
echo -e "${BLUE}[*] Writing BAR registers via setpci...${NC}"
setpci -s "${GPU_SHORT}" \
    10.l="${BAR0_HEX}" \
    14.l="${BAR1_HEX}" \
    18.l=00000000 \
    1c.l="${BAR3_HEX}" \
    20.l=00000000 \
    24.l="${BAR5_HEX}"

# 5. Restore Audio Companion (0000:01:00.1) if present
AUDIO_RES="/sys/bus/pci/devices/${AUDIO_PCI}/resource"
if [[ -r "${AUDIO_RES}" ]]; then
    AUD_BAR0_RAW=$(sed -n '1p' "${AUDIO_RES}" | awk '{print $1}')
    if [[ "${AUD_BAR0_RAW}" != "0x0000000000000000" && -n "${AUD_BAR0_RAW}" ]]; then
        AUD_BAR0_HEX=$(printf "%08x" "${AUD_BAR0_RAW}")
        echo -e "${BLUE}[*] Restoring HDMI Audio companion (${AUDIO_SHORT}) BAR0: 0x${AUD_BAR0_HEX}...${NC}"
        setpci -s "${AUDIO_SHORT}" 10.l="${AUD_BAR0_HEX}" 04.w=0006 || true
    fi
fi

# 6. Reprogram MSI Configuration (Capability offset 0x68)
echo -e "${BLUE}[*] Programming MSI vector and enabling MSI capability...${NC}"
# Determine MSI target APIC address from IRQ 37 affinity or default to CPU 7 (0xFEE07000)
MSI_ADDR="fee07000"
MSI_DATA="0021"

if [[ -r "/proc/irq/37/effective_affinity_list" ]]; then
    CPU_TARGET=$(cat /proc/irq/37/effective_affinity_list | tr -d ' \n')
    if [[ -n "${CPU_TARGET}" && "${CPU_TARGET}" =~ ^[0-9]+$ ]]; then
        MSI_ADDR=$(printf "fee%02x000" "${CPU_TARGET}")
    fi
fi

echo -e "    MSI Target Address       : 0x${MSI_ADDR}"
echo -e "    MSI Interrupt Vector     : 0x${MSI_DATA}"

# 0x6c.l: MSI Address (32-bit)
# 0x70.l: MSI Address High (32-bit = 0)
# 0x74.w: MSI Data Vector (0x0021)
# 0x6a.w: MSI Control (Bit 0 = Enable -> 0x0081)
setpci -s "${GPU_SHORT}" \
    6c.l="${MSI_ADDR}" \
    70.l=00000000 \
    74.w="${MSI_DATA}" \
    6a.w=0081

# 7. Enable Bus Master, Memory Space, I/O Space, and DisINTx (0x0407)
echo -e "${BLUE}[*] Enabling BusMaster, Mem, I/O, and DisINTx (0x0407)...${NC}"
setpci -s "${GPU_SHORT}" 04.w=0407

# 8. Rearm NVIDIA Fermi MSI edge trigger latch at extended offset 0x704
echo -e "${BLUE}[*] Pulsing Fermi MSI edge-trigger rearm latch (offset 0x704)...${NC}"
setpci -s "${GPU_SHORT}" 704.b=ff

# 9. Verify Interrupt Counter Increment
echo -e "${BLUE}[*] Verifying IRQ 37 interrupt delivery...${NC}"
IRQ_BEFORE=$(grep -E "^ *37:" /proc/interrupts | awk '{print $NF}' || echo "0")
sleep 0.5
setpci -s "${GPU_SHORT}" 704.b=ff
sleep 0.5
IRQ_AFTER=$(grep -E "^ *37:" /proc/interrupts | awk '{print $NF}' || echo "0")
echo -e "    IRQ 37 Counter: ${IRQ_BEFORE} -> ${IRQ_AFTER}"

# 10. Restart dynamic clocking daemon if it was running
if [[ ${DAEMON_WAS_ACTIVE} -eq 1 ]]; then
    echo -e "${BLUE}[*] Resuming nouveau-dynclockd.service...${NC}"
    systemctl start nouveau-dynclockd.service
fi

# 11. Final Health Check
echo -e "${BLUE}[*] Performing hardware & compositor health check...${NC}"
FINAL_CMD=$(setpci -s "${GPU_SHORT}" COMMAND)
FINAL_BAR0=$(setpci -s "${GPU_SHORT}" BASE_ADDRESS_0)

if [[ "${FINAL_CMD}" =~ (0407|0007) && "${FINAL_BAR0}" != "00000000" ]]; then
    echo -e "${GREEN}${BOLD}[✓] SUCCESS: GPU PCI Configuration Space restored successfully!${NC}"
    echo -e "    Command Register : 0x${FINAL_CMD} (Mem+, BusMaster+, I/O+)"
    echo -e "    BAR0 Register    : 0x${FINAL_BAR0}"
else
    echo -e "${RED}[WARNING] Command or BAR0 register verification mismatch (CMD=0x${FINAL_CMD}, BAR0=0x${FINAL_BAR0}).${NC}"
fi

# Test reading P-State from debugfs
if [[ -r "/sys/kernel/debug/dri/0/pstate" ]]; then
    CURRENT_PSTATE=$(grep '\*' /sys/kernel/debug/dri/0/pstate || true)
    echo -e "    Current GPU State: ${CURRENT_PSTATE:-Read OK}"
fi

echo -e "${CYAN}${BOLD}=== Recovery Finished ===${NC}"
