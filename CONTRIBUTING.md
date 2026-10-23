# Contributing & Hardware Telemetry Guide

Thank you for helping improve the **Nouveau Fermi Reclocking & 120Hz Driver**! 

Because NVIDIA Fermi GPUs (GF100, GF104, GF106, GF108, GF110, GF114, GF116, GF119) were manufactured by various OEMs with different VBIOS power tables, voltage regulators, and display connectors (eDP, LVDS, HDMI, DisplayPort), real-world user reports help us expand device compatibility and fine-tune hardware profiles.

---

## 🔍 How to Run the Hardware Diagnostic Tool

We have provided an automated telemetry tool in this repository:

1. Clone the repository (if you haven't already):
   ```bash
   git clone https://github.com/Twilight0/nouveau-dkms.git
   cd nouveau-dkms
   ```

2. Run the diagnostic tool with root privileges (required to read debugfs and VBIOS nodes):
   ```bash
   sudo python3 tools/nouveau-fermi-diag.py
   ```

3. The script will output your GPU information and automatically save a report to:
   ```text
   nouveau_fermi_diag_report.md
   ```

---

## 📝 Submitting Your Hardware Report

1. Open a new issue using the **[Hardware Telemetry Report](https://github.com/Twilight0/nouveau-dkms/issues/new?template=hardware-telemetry.md)** template.
2. Paste the contents of `nouveau_fermi_diag_report.md` into the issue description.
3. Include any notes on:
   - Laptop / Desktop model (e.g. *ASUS G73SW, Alienware M17x, MSI GT683R, Desktop GTX 560 Ti*).
   - Display panel refresh rate (60Hz, 120Hz, 144Hz).
   - Whether dynamic reclocking (`0f` state) and monitor sync operate stably on your card.

---

## 🛠️ Code Contributions & PRs

We welcome pull requests for:
- Device quirk table definitions for specific OEM subsystem IDs.
- Dynamic clock governor (`nouveau-dynclockd`) optimizations.
- Bug fixes for VBlank pacing, display hub clock gating, and voltage regulator handling.
- Packaging updates (AUR, Arch, Debian, Fedora, openSUSE).

### Guidelines:
- Keep pull requests focused on a single feature or bugfix.
- Ensure any modifications to driver patches apply cleanly against kernel DRM trees.
