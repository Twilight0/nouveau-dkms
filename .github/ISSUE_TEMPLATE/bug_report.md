---
name: Bug Report
about: Report a driver crash, kernel panic, display freeze, or regression
title: '[Bug] Brief summary of the issue'
labels: 'bug'
assignees: ''
---

### 1. Hardware & System Configuration
- **GPU Model:** (e.g. GeForce GT 555M / GTX 460M / GTX 580)
- **PCI Device & Subsystem IDs:** (Output of `lspci -nnk -d 10de:`)
- **Computer / Motherboard:** (e.g. Dell XPS L702X / ASUS K53SJ / Lenovo ThinkPad T520)
- **Display Connection & Refresh Rate:** (e.g. internal eDP 120Hz, LVDS 60Hz, external HDMI)
- **Graphics Topology:** (Muxless Optimus / Muxed / Standalone dGPU)
- **Linux Distribution:** (e.g. Arch Linux, CachyOS, Debian Sid, Ubuntu 24.04)
- **Kernel Version:** (Output of `uname -a`)
- **Driver Package:** (e.g. `nouveau-dkms 2.3.0-1`)

---

### 2. Problem Description
<!-- Clear and concise description of the bug -->

---

### 3. Steps to Reproduce
1. Boot kernel with parameters `...`
2. Launch application or trigger P-state change `...`
3. Observe crash, freeze, or display corruption `...`

---

### 4. Expected vs. Actual Behavior
- **Expected:** 
- **Actual:** 

---

### 5. Kernel Logs (`dmesg` / `journalctl`)
<!-- Please paste relevant lines from dmesg -T or journalctl -b -k below -->
```text

```

---

### 6. Additional Context
<!-- Any additional logs, module parameters, or observations -->
