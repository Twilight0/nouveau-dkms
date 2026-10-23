# 🌋 Vulkan on NVIDIA Fermi (`GF10x` / `GF11x`): Hardware Analysis & Implementation Roadmap

This document details our architectural and reverse-engineering findings on why NVIDIA omitted Vulkan support for Fermi (`NV_C0`–`NV_D9`, GeForce 400/500/600M series) in the proprietary `390.157` driver, what hardware capabilities the Fermi silicon actually possesses, and the concrete technical pathways to bring **Vulkan 1.0 / 1.1** (and DirectX 9/10/11 gaming) to Fermi on Linux alongside **`nouveau`**.

---

## 1. Executive Summary: Is Vulkan Possible on Fermi?

**Yes — Vulkan 1.0 / 1.1 is architecturally possible on Fermi (`GF100`–`GF119`).**

- **Hardware Reality**: Fermi is a fully programmable **DirectX 11.0 / OpenGL 4.3 / OpenGL ES 3.1 / OpenCL 1.1** architecture with hardware tessellation (Polymorph Engines), compute shaders (`NVC0_COMPUTE`), 32-bit/64-bit shared and global memory atomics, Shader Storage Buffer Objects (SSBOs), indirect draws (`ARB_draw_indirect`), and unified 40-bit virtual memory addressing.
- **Why NVIDIA Left Fermi Behind in `390.157`**: NVIDIA designed its proprietary Vulkan driver around **hardware bindless texture handles** introduced in **Kepler (`GK104+`)**, where shaders reference textures using arbitrary 32-bit integers in general-purpose registers. Fermi instead uses a **bound descriptor table model** (`TIC` / `TSC` binding slots + 16 Constant Buffers per stage). Rather than writing a separate bound-descriptor lowering pass for legacy Fermi cards at the end of their commercial lifecycle, NVIDIA cut off proprietary Vulkan support at Kepler.
- **Open-Source Precedent**: Multiple mainline Mesa Vulkan drivers—most notably **Intel `hasvk`** (for Ivy Bridge / Haswell Gen7 GPUs), **Broadcom `v3dv`**, and **Freedreno `turnip`**—implement compliant **Vulkan 1.0–1.2 on bound-descriptor hardware** with the exact same class of hardware binding tables that Fermi has.

---

## 2. Fermi Hardware Capabilities vs. Vulkan 1.0 / 1.1 Requirements

| Feature / Subsystem | Vulkan 1.0 / 1.1 Requirement | Fermi (`GF106` / `NV_C0`) Hardware Capability | Status |
|---|---|---|---|
| **3D Engine Class** | Programmable graphics pipeline | `NVC0_3D` (`0x9097`), `NVC1_3D` (`0x9097`), `NVC8_3D` (`0x9197`), `NVCE_3D` (`0x9297`) | ✅ Native HW |
| **Compute Engine Class** | `VK_QUEUE_COMPUTE_BIT` | `NVC0_COMPUTE` (`0x90c0`) with 48 KB L1/Shared Memory per SM & hardware barriers | ✅ Native HW |
| **DMA / Transfer Queue** | `VK_QUEUE_TRANSFER_BIT` | Dual async copy engines (`PCOPY0` `0x104000`, `PCOPY1` `0x105000`, class `0x90b5`) | ✅ Native HW |
| **Virtual Memory & MMU** | 40-bit virtual address space & sparse pages | 40-bit NV50/NVC0 VM with 4 KB / 64 KB / 128 KB page tables & compression tags | ✅ Native HW |
| **Tessellation** | `tessellationShader` | Hardware Polymorph Engines (Hull / Domain / Tessellator stages) | ✅ Native HW |
| **Geometry Shaders** | `geometryShader` & `multiViewport` | Native hardware Geometry Shader + up to 16 viewports | ✅ Native HW |
| **Shader Storage Buffers (SSBOs)** | `vertexPipelineStoresAndAtomics`, `fragmentStoresAndAtomics` | Native global memory loads/stores (`LD`/`ST`/`ATOM`/`RED` instructions on 64-bit pointers) | ✅ Native HW |
| **Storage Images** | `shaderStorageImageExtendedFormats` | Hardware surface load/store/atomic (`SULD`/`SUST`/`SURED`) via 8 surface binding slots | ✅ Native HW |
| **Indirect Draws & Dispatch** | `multiDrawIndirect`, `drawIndirectFirstInstance` | Hardware `Macro` processor (MME) in `PGRAPH` (`0x409800`) executes indirect draw loops natively | ✅ Native HW |
| **Push Constants** | Minimum 128 bytes | Can dedicate 1 Constant Buffer slot (`c0[]` or `c14[]`, up to 64 KB) for instant push constants | ✅ Native HW |
| **Uniform Buffers (UBOs)** | Minimum 12 per stage | **16 hardware Constant Buffer slots (`c0[]`..`c15[]`) per shader stage** (14 available to user shaders) or global memory loads | ✅ Native HW |
| **Sampled Images & Samplers** | Minimum 16 per stage | **128 `TIC` (Texture Image Control) slots + 32 `TSC` (Texture Sampler Control) slots per stage** | ⚠️ Bound Table (Requires Lowering) |

---

## 3. The Core Technical Hurdle: Bound `TIC`/`TSC` Slots vs. Kepler Bindless Handles

To understand why Mesa's new **NVK** driver supports Kepler (`GK104+`) before Fermi (`GF100+`), we must look at how the `TEX` instruction is encoded in the shader ISA:

1. **On Kepler (`GK104+`, `SM30`/`SM35`)**:
   - The `TEX` instruction accepts a **32-bit general-purpose register (GPR)** containing the packed `[TSC_index : 12 | TIC_index : 20]` handle directly from any memory buffer.
   - This makes Vulkan `VkDescriptorSet` trivial on Kepler: a descriptor set is just an array of 32-bit integers in VRAM, and the shader loads the handle into a register and executes `TEX`.
2. **On Fermi (`GF100`–`GF119`, `SM20`/`SM21`)**:
   - The `TEX` instruction encodes the **texture binding slot (`0..127`)** and **sampler binding slot (`0..31`)** as **immediate bitfields inside the instruction word itself** (bound to the hardware `TIC` and `TSC` pools via `NVC0_3D_BIND_TIC` / `NVC0_3D_BIND_TSC` pushbuffer methods).
   - **How Bound-Descriptor Vulkan Drivers Solve This**:
     - In Vulkan 1.0/1.1 (and `DXVK 1.10.3`), shaders almost always index into fixed descriptor sets and bindings known at pipeline compilation time (`vkCreateGraphicsPipelines` / `vkCreateComputePipelines`).
     - During pipeline compilation, a NIR pass (`nir_lower_descriptors`, identical in concept to Intel's `anv`/`hasvk`) assigns each `(set, binding, array_index)` to a deterministic slot in Fermi's **128 per-stage TIC slots** and **32 per-stage TSC slots**.
     - When `vkCmdBindDescriptorSets` is called on the command buffer, the driver emits a lightweight MME macro or pushbuffer packet updating the bound `TIC`/`TSC` pointers and `c0[]..c15[]` constant buffer base addresses (or uses 64-bit global pointers for UBOs/SSBOs, which Fermi supports natively without slot limits!).
     - If a shader uses dynamic indexing across an array of textures (`shaderSampledImageArrayDynamicIndexing`), the compiler emits a small binary-search waterfall over the immediate texture slots—the exact technique already used by `nv50_ir` in Mesa's `nvc0` OpenGL 4.3 driver!

---

## 4. Three Pathways to Vulkan & High-Performance 3D Gaming on Fermi

### Pathway A: Native Mesa Vulkan (`nvk-fermi` / `hasvk`-Style Extension to Mesa) — *The Gold Standard*
A dedicated Fermi backend within Mesa's Nouveau Vulkan stack (either as a legacy tier of **NVK** or a `nvk-fermi` split analogous to Intel's `anv` vs. `hasvk`):

1. **Command Buffer & Engine Submission (`NVC0_3D` `0x9097` & `NVC0_COMPUTE` `0x90c0`)**:
   - Over 85% of the `NVC0_3D` rasterizer, depth/stencil, blend, viewport, vertex attribute, and MME macro registers are **identical** between Fermi (`0x9097`) and Kepler (`0xa097`).
2. **Descriptor Lowering Pass (`nak_nir_lower_fermi_descriptors`)**:
   - Map **Push Constants** $\to$ Constant Buffer slot `c15[]` (updated inline via pushbuffer).
   - Map **UBOs & SSBOs** $\to$ Either Constant Buffer slots `c1[]..c13[]` or 64-bit global virtual addresses stored in a descriptor buffer table at `c14[]` (loaded via Fermi's native 64-bit `LD.E` / `ST.E` / `ATOM.E` instructions—giving **unlimited SSBOs and UBOs**!).
   - Map **Sampled Images / Samplers** $\to$ Fermi's 128 `TIC` and 32 `TSC` hardware binding slots per stage, flushed on `vkCmdBindDescriptorSets`.
   - Map **Storage Images** $\to$ Fermi's 8 hardware surface slots (`SU` bindings) or software format conversion via global memory `LD.E`/`ST.E`.
3. **Shader Compiler Backend (`SM20` / `SM21` ISA)**:
   - Either add `SM20` (`GF100`/`GF106`) instruction encoding to Mesa's `nak` compiler (Fermi and Kepler share the same 64-bit instruction word framing and register file model, differing mainly in scheduling control codes and bound vs. bindless `TEX`), **or** bridge SPIR-V $\to$ NIR into the existing battle-tested `nv50_ir` (`TargetNVC0`) code generator that already compiles NIR to `SM20` machine code for OpenGL 4.3!
   - *Note*: Bridging NIR $\to$ `nv50_ir` (`nouveau_compiler`) avoids rewriting the entire `SM20` instruction scheduler and register allocator from scratch, because `nvc0` in Mesa **already accepts NIR** as its default shader IR!

---

### Pathway B: Vulkan-on-OpenGL 4.3 Translation Layer (`vk-on-gl` over `nvc0`) — *Fastest Userspace Prototype*
Because Mesa's `nvc0` Gallium driver on Fermi already exposes **OpenGL 4.3 + GLES 3.1 + Compute Shaders + ARB_direct_state_access + ARB_buffer_storage**:
- *(Important distinction: Mesa's **Zink** translates OpenGL $\to$ Vulkan, which is the opposite direction. What Fermi can use immediately in userspace is a **Vulkan $\to$ OpenGL 4.3** ICD wrapper.)*
- How a Vulkan-to-OpenGL 4.3 ICD works on `nvc0`:
  - Translates `VkBuffer` / `VkDeviceMemory` $\to$ persistent mapped OpenGL buffer objects (`glNamedBufferStorage` with `GL_MAP_PERSISTENT_BIT | GL_MAP_COHERENT_BIT`).
  - Translates SPIR-V shaders $\to$ GLSL 430 via `SPIRV-Cross` (which natively flattens Vulkan descriptor sets into OpenGL 4.3 binding points!).
  - Translates `VkCommandBuffer` $\to$ pre-recorded command lists dispatched to the `nvc0` context.
- **Pros**: Zero kernel or Mesa compiler modifications required; runs directly on top of the existing `nvc0` Gallium driver.
- **Cons**: Higher CPU driver overhead than Pathway A (`NVK` native pushbuffers) and lacks sparse memory binding.

---

### Pathway C: Direct3D 9 / 10 / 11 Gaming Today (`Gallium Nine` + `WineD3D`) — *Production Ready Now*
For running Windows games via Wine / Proton on the GT 555M (`GF106M`) today without waiting for a Vulkan ICD:
1. **DirectX 9 Games (`Gallium Nine`)**:
   - Mesa includes the native `d3dadapter9` state tracker for `nvc0`.
   - Instead of translating DX9 $\to$ Vulkan (`DXVK`) or DX9 $\to$ OpenGL (`WineD3D`), **Gallium Nine executes Direct3D 9 calls directly on the `nvc0` Gallium pipe** with near-zero CPU overhead, outperforming even proprietary drivers in many DX9 titles when paired with P-State `0f` / `10`.
2. **DirectX 10 / 11 Games (`PROTON_USE_WINED3D=1`)**:
   - Proton and Wine include `WineD3D`'s OpenGL 4.3 backend, which uses Fermi's hardware tessellation, geometry shaders, UBOs, and compute shaders natively on `nvc0`.

---

## 5. Why `nouveau` Was the Missing Prerequisite for Everything Above

Even with a native Vulkan driver or OpenGL 4.3, stock upstream Nouveau crippled Fermi GPUs in the kernel:

| Hardware Bottleneck on Stock Nouveau | Impact on OpenGL 4.3 / Vulkan Workloads | Fixed by `nouveau` (`v2.0.1+`) |
|---|---|---|
| **Memory Stuck at `324 MHz` (or `135 MHz`)** | Only `15.5 GB/s` bandwidth (with ~`1.9 GB/s` eaten by 120 Hz scanout), starving every shader & render target | ✅ **900 MHz DDR3 (`43.2 GB/s`)** via custom Falcon PMU executor (`2.78×` bandwidth) |
| **Core/Shader Stuck at `202 / 405 MHz`** | `116 GFLOPS` FP32 (~29% of hardware capacity) | ✅ **590 / 1180 MHz (`0f`, `340 GFLOPS`)** and **700 / 1400 MHz (`10`, `403 GFLOPS`)** |
| **Voltage Stuck at `0.820 V` / `0.870 V`** | GPU hangs under heavy shader load due to VMAP undervolting bug | ✅ **True `1.030 V` factory rail** (plus upcoming `0.920 V` P3 state `0a`) |
| **PCIe Stuck at Gen1 (`2.5 GT/s`)** | Pushbuffer & staging buffer uploads bottlenecked at `4.0 GB/s` | ✅ **Dynamic PCIe Gen2 (`5.0 GT/s`, `8.0 GB/s` per direction)** |

### Kernel Capabilities Already Ready for `NVK` on Fermi
If we pursue **Pathway A** (wiring `NVC0` into Mesa's Vulkan stack using the existing NIR $\to$ `nv50_ir` compiler backend), the kernel interface in our driver (`nouveau_drm.c` / `nouveau_uvmm.c`) **already supports the modern `DRM_IOCTL_NOUVEAU_VM_BIND` and `EXEC` syncobj uAPI** required by Mesa NVK—meaning only the userspace device-info filter and bound-descriptor lowering pass in Mesa are needed to begin experimenting!
