# 🎬 Video Encoding & Hardware Acceleration on NVIDIA Fermi (GF106 / GT 555M)

This document details hardware video encoding and decoding capabilities, silicon limitations, platform topology, and GPU-accelerated encoding strategies for NVIDIA Fermi GPUs (specifically the GeForce GT 555M on the Dell XPS L702X) running the **Nouveau** open-source driver.

---

## 1. Silicon Architecture & The NVENC Gap

### Historical Context & Hardware Generations
- **NVENC (Hardware Video Encoder ASIC)**:
  - NVIDIA introduced dedicated fixed-function hardware encoding silicon with the **Kepler** architecture (March 2012, starting with GK104 / NVENC Generation 1).
  - **Fermi (GF100/GF104/GF106/GF108/GF110/GF114/GF116)** silicon **completely lacks a fixed-function hardware encoder**. No SIP core for encoding exists on the die.
- **NVDEC / PureVideo HD (Hardware Video Decoder)**:
  - Fermi *does* integrate dedicated hardware decoding silicon via the **PureVideo HD (VP4 / VP5)** engine.
  - Supported decode codecs: MPEG-1, MPEG-2, VC-1 / WMV9, and H.264 (AVC) up to 1080p @ 60 FPS.
  - On Linux / Nouveau, VP4/VP5 is exposed through the **VDPAU** (`vdpau`) and **VA-API** (`nouveau_drv_video.so`) user-space interfaces.

---

## 2. Platform Architecture: Dell XPS L702X Hardware Quirks

On standard mobile Optimus configurations, a laptop paired with an Intel Sandy Bridge CPU can utilize **Intel Quick Sync Video (QSV)** via the integrated Intel HD Graphics 3000 IGP for hardware-accelerated H.264 encoding.

### The 120Hz 3D Hardware Mux Isolation
- On the **Dell XPS L702X with the 120Hz 3D eDP Display** (panel ID `LGD 0x02c5`):
  - The Intel Sandy Bridge display engine (Gen6) was architecturally incapable of driving the **396.36 MHz pixel clock** required for `1920x1080 @ 120Hz`.
  - To support 120Hz refresh and NVIDIA 3D Vision, Dell physically bypassed and disabled the Intel IGP at the motherboard / ACPI level.
  - As verified via `lspci`:
    ```
    01:00.0 VGA compatible controller: NVIDIA Corporation GF106M [GeForce GT 555M] (rev a1)
    ```
  - The Intel HD Graphics 3000 device (`0000:00:02.0`) does not exist on the PCI bus.
  - **Result**: Intel QuickSync is physically unavailable on this hardware configuration. All display, decode, and compute tasks must be handled by the discrete GeForce GT 555M.

---

## 3. Hardware-Accelerated Video Encoding via Shader Compute

While fixed-function ASIC encoding (NVENC) is absent, **GPU-accelerated encoding is fully possible** through compute offloading.

### The Motion Estimation Bottleneck
In H.264/AVC video compression, the encoding pipeline consists of:
1. **Motion Estimation (ME)** & Motion Vector Search (70%–80% of total CPU time).
2. Discrete Cosine Transform (DCT) & Quantization (~10% of CPU time).
3. Context-Adaptive Binary Arithmetic Coding (CABAC / CAVLC) (~10%–15% of CPU time, inherently serial).

Because Motion Estimation evaluates block matching across dozens of candidate macroblocks across multiple reference frames, it is an embarrassingly parallel algorithm ideally suited for the GPU's **144 CUDA / Compute cores**.

By offloading Motion Estimation lookahead to the GPU, the CPU is freed from the heaviest algorithmic phase, resulting in:
- **2× to 4× faster encoding throughput** compared to pure CPU encoding on a 2nd-gen mobile i7.
- Substantially reduced CPU core temperatures and fan noise.

---

## 4. Practical Implementation: `x264` OpenCL Acceleration

The industry-standard `x264` video encoder features a built-in OpenCL motion estimation sub-engine.

### How `x264 --opencl` Operates
- When enabled, `x264` compiles OpenCL kernels at runtime to perform:
  - Low-resolution motion search across frames.
  - Intra-prediction cost evaluation.
  - Macroblock mode decision lookahead.
- The computed motion vectors and mode decisions are streamed back to the host CPU via PCIe, which finishes DCT quantization and CABAC entropy coding.

### FFmpeg Command Line Examples

#### 1. Transcoding with OpenCL-Accelerated Motion Estimation
```bash
ffmpeg -i input.mkv \
  -c:v libx264 \
  -preset medium \
  -crf 20 \
  -x264opts opencl=1 \
  -c:a copy \
  output.mp4
```

#### 2. Standalone `x264` CLI
```bash
x264 --opencl --opencl-device 0 \
  --preset slow \
  --crf 19 \
  -o output.264 input.y4m
```

#### 3. Real-Time Screen Recording / Streaming (OBS Studio / FFmpeg)
For low-latency capture, combine ultrafast preset with OpenCL lookahead:
```bash
ffmpeg -f x11grab -r 60 -s 1920x1080 -i :0.0 \
  -c:v libx264 -preset veryfast -tune zerolatency \
  -x264opts opencl=1 \
  -pix_fmt yuv420p output.mp4
```

---

## 5. Software Prerequisites on Nouveau

To utilize OpenCL-accelerated video encoding on Nouveau:

1. **OpenCL Runtime**:
   Install Mesa's OpenCL runtime and ICD bindings:
   ```bash
   sudo pacman -S opencl-mesa ocl-icd opencl-headers
   ```
2. **Enable Rusticl Driver on Nouveau**:
   Mesa 26 uses Rusticl for OpenCL 3.0:
   ```bash
   export RUSTICL_ENABLE=nouveau
   ```
3. **Verify OpenCL Acceleration in `x264`**:
   ```bash
   x264 --fullhelp | grep -A 5 "opencl"
   ```

---

## 6. Summary Matrix

| Encoding Method | Supported on GF106M? | Implementation | Performance Level |
| :--- | :---: | :--- | :--- |
| **NVIDIA NVENC** | ❌ No | Requires Kepler (GK104+) | N/A (Silicon absent) |
| **Intel QuickSync** | ❌ No | Intel IGP disabled on 120Hz SKU | N/A (Hardware bypassed) |
| **OpenCL Compute (`x264`)** | ✅ **Yes** | GPU Motion Estimation offload | **2×–4× faster than pure CPU** |
| **PureVideo HD Decode** | ✅ **Yes** | VDPAU / VA-API (VP5) | 1080p @ 60 FPS hardware decode |
| **CPU Software (`x264`/`svt-av1`)** | ✅ **Yes** | Sandy Bridge AVX1 (4C/8T) | Baseline |
