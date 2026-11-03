# Contributing & Issue Reporting Guide

Thank you for helping improve the **nouveau-dkms** driver and compute stack!

This guide outlines our issue triage workflow, bug reporting requirements, and code contribution standards.

---

## 1. Issue Triage: Bug Reports vs. Discussions

To keep project tracking focused and actionable, we maintain two separate channels:

| Topic | Channel | What Belongs Here |
| :--- | :--- | :--- |
| **Bug Reports & Regressions** | **GitHub Issues** | System lockups, kernel panics, screen blackouts, visual corruption, resume failures, or compiler build errors. |
| **Hardware Compatibility & Telemetry** | **GitHub Discussions** | Diagnostic dumps from `nouveau-fermi-diag.py`, reports of successful boots/reclocking, general questions, and architecture discussions. |

> Please do not open an Issue solely to share working diagnostic logs. Post those under [GitHub Discussions](https://github.com/Twilight0/nouveau-dkms/discussions) instead.

---

## 2. Submitting an Actionable Bug Report

When reporting a driver malfunction or regression in GitHub Issues, provide sufficient detail for reproduction and root-cause analysis:

### Required Information
1. **Hardware Identity**:
   - GPU model and PCI Subsystem IDs:
     ```bash
     lspci -nnk -d 10de:
     ```
   - System / Motherboard model (e.g. Dell XPS L702X, ASUS K53SJ, ThinkPad T520, Custom Desktop).
   - Display connection (eDP, LVDS, HDMI, DisplayPort, DVI) and refresh rate (60 Hz, 120 Hz, etc.).
   - Graphics topology (muxless Optimus, muxed, or standalone dGPU).

2. **Software Environment**:
   - Distribution and release (e.g. Arch Linux, CachyOS, Debian Sid, Ubuntu 24.04).
   - Kernel version (`uname -a`).
   - Driver package version (`nouveau-dkms`).

3. **Problem Description**:
   - Clear explanation of the observed behavior versus expected behavior.
   - Exact steps to reproduce the issue (e.g., "running glxgears triggers a lockup", "switching from P-state 07 to 0f causes display corruption", "system freezes upon S3 resume").

4. **Kernel Logs**:
   - Complete `dmesg` output from the boot session leading up to the issue:
     ```bash
     sudo dmesg -T > dmesg.log
     ```
   - For system lockups or hard freezes, capture persistent journal logs:
     ```bash
     journalctl -b -1 -k > journal_prev.log
     ```

---

## 3. Sharing Hardware Diagnostic Dumps (Discussions)

If you wish to contribute hardware telemetry or confirm compatibility for a card:
1. Run the diagnostic tool with root privileges:
   ```bash
   sudo python3 tools/nouveau-fermi-diag.py
   ```
2. The script will save a comprehensive report to `nouveau_fermi_diag_report.md`.
3. Share the report as a comment in the community hardware compatibility thread on [GitHub Discussions](https://github.com/Twilight0/nouveau-dkms/discussions).
4. Subsystem IDs and board topologies from these discussions are triaged and ingested into `include/nvkm/core/quirks.h`.

---

## 4. Code Contributions & Pull Requests

We welcome pull requests for:
- Hardware quirk entries in `include/nvkm/core/quirks.h` for specific OEM subsystem IDs.
- Core and memory reclocking enhancements across supported silicon generations.
- Multi-kernel compatibility shims in `nouveau_compat.h`.
- Out-of-tree build and cross-distribution packaging improvements.

### Development Guidelines:
- **Patch Queue Integrity**:
  - Driver modifications must be integrated through the modular patch series (`patches/0001` through `patches/0049`) managed by `tools/nouveau-matrix-builder.py`.
  - All patches must apply cleanly with strict `--fuzz=0`.
- **Architectural Isolation**:
  - Keep generational subdev logic strictly decoupled (`clk/gf100.c` vs `clk/gk104.c` vs `clk/gm107.c`).
  - Verify isolation prior to submitting PRs:
    ```bash
    python3 tools/nouveau-matrix-builder.py check-isolation
    ```
- **Code Standards**:
  - Adhere to the Linux kernel coding style (`Documentation/process/coding-style.rst`).
  - Zero emojis in commit messages, code comments, and documentation.
  - Plain UTF-8 text throughout without invisible characters or watermarks.
