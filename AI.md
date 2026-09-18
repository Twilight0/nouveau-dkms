# 🧠 Local AI & LLM Inference on NVIDIA Fermi (GF106M / GT 555M 3GB)

This document provides a comprehensive guide, architectural analysis, and practical deployment manual for running **Large Language Models (LLMs) and Small Language Models (SLMs)** locally on NVIDIA Fermi GPUs (specifically the **GeForce GT 555M 3GB DDR3** on the Dell XPS L702X) under Linux with the **Nouveau** open-source driver.

---

## 1. Hardware Compute & Memory Architecture

### Compute & Silicon Profile
- **GPU Architecture**: Fermi (GF106M, stepping A1).
- **Compute Capability**: `sm_21` (Compute Capability 2.1).
- **Streaming Multiprocessors (SM)**: 3 SMs, each with 48 CUDA cores = **144 CUDA cores total**.
- **Shader Clock Domain (Hot Clock)**: **1180 MHz** (unlocked via our [`nouveau-fermi-reclock-dkms`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms) patch).
- **Theoretical Single-Precision (FP32) Compute**:
  $$\text{FP32 TFLOPS} = 144 \times 1.180\text{ GHz} \times 2\text{ FLOP/clock} \approx \mathbf{0.340\text{ TFLOPS (340 GFLOPS)}}$$
- **Precision Support**: Native FP32 and Int32/Int16. FP16 is emulated via FP32 arithmetic (Fermi lacks native FP16 packed instructions and Tensor Cores).

### Memory Subsystem & Bandwidth
- **VRAM Capacity**: **3072 MB (3 GB)** DDR3 SDRAM.
- **Bus Width**: **192-bit** (three 64-bit memory crossbar channels).
- **Reclocked Memory Clock**: **900 MHz** (1800 MT/s effective), unlocked via our resident Falcon microcode executor in **v2.0.0**.
- **Peak Memory Bandwidth**:
  $$\text{Bandwidth} = \frac{192\text{ bits} \times 1.800\text{ GT/s}}{8\text{ bits/byte}} = \mathbf{43.2\text{ GB/s}}$$
- **Display Scanout Overhead**:
  - Panel mode: `1920x1080 @ 120Hz` (32-bit color $\approx$ 8.29 MB per frame).
  - Continuous scanout bandwidth consumption $\approx$ **1.0–1.9 GB/s**.
  - **Net Available Memory Bandwidth for Compute**: $\approx$ **41.3 GB/s**.
  - **Net Usable VRAM (after X11/Wayland compositing)**: $\approx$ **2.4–2.6 GB**.

---

## 2. The LLM Memory-Bandwidth Equation

A widespread misconception is that running LLMs requires hundreds of Tensor TFLOPS. While **training** and **pre-fill (prompt processing)** are compute-bound (GEMM operations), **autoregressive token generation** is almost exclusively **memory-bandwidth bound** (GEMV operations).

### Mathematical Model of Token Generation
During single-user autoregressive generation, each generated token requires reading every single weight of the model from VRAM exactly once:

$$\text{Max Generation Speed (tokens/sec)} = \frac{\text{Memory Bandwidth (GB/s)}}{\text{Model Weight Size in VRAM (GB)}}$$

| Model Size in VRAM | Theoretical Max Speed (43.2 GB/s) | Realistic Throughput (25%–35% Bus Efficiency) |
| :---: | :---: | :---: |
| **400 MB** (0.5B Q4) | **108 tokens/sec** | **25–35 tokens/sec** |
| **800 MB** (1.0B Q4) | **54 tokens/sec** | **14–18 tokens/sec** |
| **1.1 GB** (1.5B Q4) | **39 tokens/sec** | **10–13 tokens/sec** |
| **1.5 GB** (2.0B Q4) | **28 tokens/sec** | **7–10 tokens/sec** |

*(Note: Human reading speed is approximately 4–5 tokens per second. A throughput of 8–15 tokens/sec is fast, responsive, and highly usable for real-time interactive chats).*

---

## 3. Recommended Small Language Models (SLMs)

The modern open-weights ecosystem features highly capable sub-2B parameter models that fit comfortably within the 3 GB VRAM ceiling:

| Model Name | Parameters | Quantization | Model File Size | Total VRAM (w/ 2K Context) | Strengths |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Qwen 2.5 0.5B Instruct** | 0.5 Billion | `Q4_K_M` | **~395 MB** | **~650 MB** | Blazing speed, excellent instruction following, multilingual. |
| **Qwen 2.5 0.5B Instruct** | 0.5 Billion | `Q8_0` | **~550 MB** | **~820 MB** | Higher precision, minimal quantization loss. |
| **Llama 3.2 1B Instruct** | 1.2 Billion | `Q4_K_M` | **~750 MB** | **~1.15 GB** | Meta's state-of-the-art 1B model; strong summarization and tool use. |
| **SmolLM2 1.7B Instruct** | 1.7 Billion | `Q4_K_M` | **~1.05 GB** | **~1.55 GB** | Trained on 11 trillion tokens; outstanding coding and math for its class. |
| **Qwen 2.5 1.5B Instruct** | 1.5 Billion | `Q4_K_M` | **~1.12 GB** | **~1.60 GB** | Top-tier 1.5B reasoning, logic, and multi-turn dialogue. |
| **Gemma 2 2B Instruct** | 2.6 Billion | `Q3_K_M` | **~1.45 GB** | **~2.10 GB** | Google DeepMind architecture; high accuracy if context is kept under 2K. |

---

## 4. Compute Stack Options on Nouveau

### Stack A: Mesa Rusticl (OpenCL 3.0 via NIR)
Mesa 26 includes **Rusticl**, an OpenCL 3.0 implementation written in Rust:
- **How it works**: Rusticl parses OpenCL C into SPIR-V, lowers it to NIR, and executes it via the Gallium `nvc0` driver.
- **Status on Fermi**: The NVC0 Gallium driver supports OpenGL 4.3 Core Profile and exposes `GL_ARB_compute_shader`. Enabling Rusticl gives standard OpenCL 1.2/3.0 ICD access.
- **Activation**:
  ```bash
  sudo pacman -S opencl-mesa ocl-icd opencl-headers clinfo
  RUSTICL_ENABLE=nouveau clinfo
  ```

### Stack B: `llama.cpp` with CLBlast (OpenCL Backend)
`llama.cpp` has a battle-tested OpenCL backend built on **CLBlast**:
- **Why CLBlast**: CLBlast provides tuned OpenCL matrix-multiplication kernels (GEMM / GEMV). It includes an autotuner (`clblast_tuner`) that optimizes tile dimensions ($M, N, K$) specifically for the GF106 cache hierarchy (128 KB L2 cache and 48 KB shared memory per SM).
- **Compilation**:
  ```bash
  git clone https://github.com/ggerganov/llama.cpp
  cd llama.cpp
  cmake -B build \
    -DGGML_OPENCL=ON \
    -DGGML_OPENCL_EMBED_KERNELS=ON \
    -DCMAKE_BUILD_TYPE=Release
  cmake --build build --config Release -j$(nproc)
  ```

### Stack C: OpenGL 4.3 Compute Shaders (`GL_ARB_compute_shader`)
If OpenCL encounters instruction-lowering regressions in `nv50_ir` for Fermi, OpenGL Compute Shaders offer a direct, hardware-supported alternative:
- Verified on this system via `glxinfo`:
  ```
  GL_ARB_compute_shader, GL_ARB_compute_variable_group_size
  ```
- Lightweight compute frameworks (like `wgpu` with OpenGL ES 3.1 / GL 4.3 backend or custom GLSL matrix-vector multiplication shaders) execute natively on Fermi without requiring OpenCL ICD drivers.

### Stack D: CPU (AVX) + GPU Hybrid Offloading
The host Intel Core i7-2630QM provides 4 cores / 8 threads with **AVX1**:
- `llama.cpp` supports layer splitting (`-ngl <layers_on_gpu>`):
  - For larger models (e.g. 3B parameters), place 12 layers on the GPU (consuming ~1.8 GB VRAM) and 16 layers on the CPU.
  - This avoids out-of-memory errors while accelerating overall generation.

---

## 5. Step-by-Step Deployment Guide (`llama.cpp`)

### 1. Install Dependencies
```bash
sudo pacman -S base-devel git cmake opencl-mesa ocl-icd opencl-headers curl
```

### 2. Download a Small Language Model (GGUF Format)
Create a models directory and fetch `Qwen2.5-0.5B-Instruct` or `Llama-3.2-1B-Instruct`:
```bash
mkdir -p ~/models && cd ~/models

# Option 1: Qwen2.5-0.5B-Instruct (398 MB - Fast & Lightweight)
curl -L -o qwen2.5-0.5b-instruct-q4_k_m.gguf \
  "https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/qwen2.5-0.5b-instruct-q4_k_m.gguf"

# Option 2: Llama-3.2-1B-Instruct (750 MB - Strong 1B Baseline)
curl -L -o llama-3.2-1b-instruct-q4_k_m.gguf \
  "https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF/resolve/main/Llama-3.2-1B-Instruct-Q4_K_M.gguf"
```

### 3. Run Inference via CLI
```bash
# Offload all layers to GPU (-ngl 99) with 2048 token context (-c 2048)
RUSTICL_ENABLE=nouveau ./llama.cpp/build/bin/llama-cli \
  -m ~/models/qwen2.5-0.5b-instruct-q4_k_m.gguf \
  -ngl 99 \
  -c 2048 \
  --temp 0.7 \
  -p "<|im_start|>user\nExplain how memory bandwidth affects LLM generation in 3 bullet points.<|im_end|>\n<|im_start|>assistant\n"
```

### 4. Run an Interactive Chat Session
```bash
RUSTICL_ENABLE=nouveau ./llama.cpp/build/bin/llama-cli \
  -m ~/models/llama-3.2-1b-instruct-q4_k_m.gguf \
  -ngl 99 \
  -c 2048 \
  -co \
  --color
```

---

## 6. Performance & Thermal Management

When running continuous LLM inference on the Dell XPS L702X:
1. **P-State Lock**:
   Before initiating long batch generations, ensure the GPU is locked to P0 (`0f` / `590 MHz` core / `900 MHz` RAM) to prevent governor clock bouncing:
   ```bash
   nouveau-ctrl set 0f
   ```
2. **Thermal Monitoring**:
   Monitor temperatures using [`nouveau-ctrl watch`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/nouveau-ctrl) or [`nouveau-tui`](file:///home/twilight/Projects/nouveau-fermi-reclock-dkms/nouveau-tui). If temperature reaches the configured throttle threshold (`78°C`), `nouveau-dynclockd` will automatically downclock or scale fan speed via ACPI/hwmon.
3. **Return to Auto**:
   ```bash
   nouveau-ctrl set auto
   ```
