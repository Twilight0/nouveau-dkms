# Hardware Diagnostic & MMIO Traces

This directory contains diagnostic artifacts, VBIOS firmware dumps, and MMIO register traces captured on the reference test hardware.

---

## 🖥️ Reference Hardware Profile & Alias

| Property | Value |
|---|---|
| **Hardware Alias** | `Dell XPS L702X (Fermi GF106M 3D 120Hz)` |
| **System Model** | Dell System XPS L702X (Subsystem Vendor/Device: `1028:04b7`) |
| **GPU Chipset** | NVIDIA GeForce GT 555M (Fermi / **GF106M**, Stepping A1, PCI ID `10de:0dcd`) |
| **VRAM** | 3072 MiB DDR3 (192-bit bus width, RAMCFG strap `0x6`) |
| **Display Panel** | 1920×1080 @ 120 Hz 3D (eDP-1 / LG Display `0x02c5`, 396.36 MHz pixel clock) |
| **Audio Controller** | NVIDIA GF106 High Definition Audio Controller (`10de:0be9`) |

---

## 📁 Directory Contents & Trace Descriptions

| File | Size | Description |
|---|---|---|
| **`nvidia_full_reclock_trace.txt.xz`** | ~1.2 MiB | Complete decoded MMIO register trace of full dynamic reclocking transitions (`P8` ↔ `P0` @ 900MHz) under the NVIDIA proprietary driver. |
| **`nvidia_reclock_full.raw.xz`** | ~1.7 MiB | Raw kernel `mmiotrace` binary capture pipe of memory controller and PLL events. |
| **`gpu_vbios.rom`** | 56 KiB | Reference VBIOS ROM dump containing the BIT tables (`P`, `M`, `U`, `C`, `d`). |
| **`gpu_vbios_perf.txt`** | 69 KiB | Decoded BIT performance tables, frequency steps, and VID voltage curves. |
| **`nouveau_boot.log`** | 11 KiB | Kernel `dmesg` log showing Nouveau driver initialization and probe sequencing. |
| **`nvidia_reclock.decoded`** | 2.4 KiB | Focused snippet of MEMX bytecode execution and clock PLL register writes. |
| **`nvidia_reclock.trace`** | 1.9 KiB | Summary trace of memory controller clock transition calls. |
| **`gf108_quadro600_pmu_memx_decoded.txt`** | 12 KiB | NVIDIA 390.157 PMU memx scripts captured on a GF108 Quadro 600 (`10de:0df8`, subsystem `103c:0835`), decoded with `tools/decode-pmu-memx.py`: block 20 boot 324 -> MPLL 324, blocks 28/61 324 -> 800, blocks 54/69 800 -> 324. Input of `tools/gen-fexec-gf108.py`; see `docs/research/GF108_QUADRO600.md`. |
| **`sniff_memory_reclock.py`** | 6.3 KiB | Original memory controller register diffing prototype. |
| **`run_mmiotrace.sh`** | 2.1 KiB | Automated `mmiotrace` logger script. |
| **`trace_driver_reload.sh`** | 3.0 KiB | Cold driver unload/reload initialization tracer. |

---

## 🔍 How to Decompress and Inspect Traces

To decompress the full trace files:
```bash
unxz -k nvidia_full_reclock_trace.txt.xz
unxz -k nvidia_reclock_full.raw.xz
```

To decode raw traces with `demmt` (from `envytools`):
```bash
demmt -l nvidia_reclock_full.raw > decoded_output.txt
```
