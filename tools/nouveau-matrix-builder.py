#!/usr/bin/env python3
"""
nouveau-matrix-builder: Multi-Generation Chip Matrix & Patch Queue Builder
========================================================================
Manages, validates, and builds nouveau-dkms driver flavors across NVIDIA
pre-Nova chip generations:
  - Universal (0001..0009): Common fixes, 256b alignment, TTM telemetry, compat shims
  - Tesla     (0040..0049): GT215..GT218 PDAEMON / host clk reclocking
  - Fermi     (0010..0019): GF100..GF119 core/shader/voltage, resident Falcon DDR3, vblank
  - Kepler    (0020..0029): GK104..GK208 pstates, boost curves, mobile RAM timings
  - Maxwell 1 (0030..0039): GM107..GM108 unsigned Falcon PMU & PLL reclocking
  - All / Unified: Consolidated multi-architecture production driver

Usage:
    python3 tools/nouveau-matrix-builder.py --list
    python3 tools/nouveau-matrix-builder.py --check-isolation
    python3 tools/nouveau-matrix-builder.py --build-tree fermi --out /tmp/tree-fermi
    python3 tools/nouveau-matrix-builder.py --build-patch fermi --out /tmp/nouveau-fermi.patch
    python3 tools/nouveau-matrix-builder.py --test-generation fermi
    python3 tools/nouveau-matrix-builder.py --test-matrix
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
from pathlib import Path

# Repository root directory
REPO_ROOT = Path(__file__).resolve().parent.parent
PATCHES_DIR = REPO_ROOT / "patches"
SOURCE_TAR = REPO_ROOT / "nouveau-source.tar.gz"

GENERATIONS = {
    "universal": {
        "name": "Universal Subsystems",
        "description": "Common core enhancements, 256b alignment, TTM VRAM telemetry, 120Hz display & compat shims",
        "chips": "All Pre-Nova Architectures (NV50..NV138)",
        "patch_range": (1, 9),
        "status": "production",
        "always_include": True,
        "subdev_targets": [
            "nouveau_bo.c",
            "nouveau_gem.c",
            "nouveau_debugfs.c",
            "dispnv50/disp.c",
            "nouveau_backlight.c",
            "nouveau_compat.h",
            "include/nvkm/core/quirks.h",
            "include/nvkm/core/device.h",
            "nvkm/engine/device/pci.c",
        ],
    },
    "fermi": {
        "name": "Fermi (NVC0 / NVCF)",
        "description": "Core/shader pstates, PDAEMON bootstrap, resident Falcon DDR3 & zero-stutter VBlank sync",
        "chips": "GeForce 400 / 500 / 600M..800M (GF100, GF104, GF106, GF108, GF114, GF116, GF119)",
        "patch_range": (10, 19),
        "status": "production",
        "always_include": False,
        "subdev_targets": [
            "nvkm/subdev/clk/base.c",
            "nvkm/subdev/clk/gf100.c",
            "nvkm/subdev/fb/ramfuc.h",
            "nvkm/subdev/fb/ramgf100.c",
            "nvkm/subdev/pmu/fuc/gf100.fuc3.h",
            "nvkm/subdev/pmu/gt215.c",
            "nvkm/subdev/pmu/memx.c",
        ],
    },
    "kepler": {
        "name": "Kepler (NVE0 / NV108)",
        "description": "Kepler pstate ladder, GPU Boost 1.0/2.0 scaling & mobile GK107M/GK208M memory timings",
        "chips": "GeForce 600 / 700 / 800M (GK104, GK106, GK107, GK110, GK208)",
        "patch_range": (20, 29),
        "status": "staged",
        "always_include": False,
        "subdev_targets": [
            "nvkm/subdev/clk/gk104.c",
            "nvkm/subdev/clk/gk20a.c",
            "nvkm/subdev/fb/ramgk104.c",
        ],
    },
    "maxwell1": {
        "name": "Maxwell 1 (NV117 / NV118)",
        "description": "First-gen Maxwell unsigned Falcon PMU, PLL reclocking & memory training",
        "chips": "GeForce GTX 750 / 750 Ti, GTX 850M..960M, MX110 / MX130 (GM107, GM108)",
        "patch_range": (30, 39),
        "status": "staged",
        "always_include": False,
        "subdev_targets": [
            "nvkm/subdev/pmu/gm107.c",
            "nvkm/subdev/clk/gm107.c",
            "nvkm/subdev/fb/ramgm107.c",
        ],
    },
    "tesla": {
        "name": "Tesla (NV50 / NVA8)",
        "description": "Tesla GT215..GT218 PDAEMON and host clock reclocking",
        "chips": "GeForce 8000 / 9000 / 200 / 300 series (GT215, GT216, GT218, etc.)",
        "patch_range": (40, 49),
        "status": "staged",
        "always_include": False,
        "subdev_targets": [
            "nvkm/subdev/clk/gt215.c",
            "nvkm/subdev/fb/ramgt215.c",
        ],
    },
}

def log(tag: str, msg: str):
    tags = {
        "INFO": "[INFO]",
        "PASS": "[PASS]",
        "FAIL": "[FAIL]",
        "WARN": "[WARN]",
    }
    prefix = tags.get(tag, f"[{tag}]")
    print(f"{prefix} {msg}")

def discover_available_patches():
    """Scans patches/ and groups patch files by generation range."""
    res = {gen: [] for gen in GENERATIONS}
    res["unassigned"] = []
    
    if not PATCHES_DIR.is_dir():
        return res

    for p in sorted(PATCHES_DIR.glob("*.patch")):
        m = re.match(r"^(\d{4})-(.*)\.patch$", p.name)
        if not m:
            continue
        num = int(m.group(1))
        matched = False
        for gen, info in GENERATIONS.items():
            low, high = info["patch_range"]
            if low <= num <= high:
                res[gen].append(p)
                matched = True
                break
        if not matched:
            res["unassigned"].append(p)
    return res

def get_patches_for_generation(gen_id: str):
    """Returns the ordered list of patches for a given generation target."""
    if gen_id not in GENERATIONS and gen_id != "all":
        raise ValueError(f"Unknown generation '{gen_id}'. Choices: {list(GENERATIONS.keys()) + ['all']}")
    
    discovered = discover_available_patches()
    
    if gen_id == "all":
        # All available patches in numeric order
        all_patches = []
        for g in ["universal", "fermi", "kepler", "maxwell1", "tesla"]:
            all_patches.extend(discovered.get(g, []))
        all_patches.extend(discovered.get("unassigned", []))
        return sorted(all_patches, key=lambda p: p.name)
    
    patches = list(discovered.get("universal", []))
    if gen_id != "universal":
        patches.extend(discovered.get(gen_id, []))
    
    return sorted(patches, key=lambda p: p.name)

def inspect_touched_files(patch_path: Path):
    """Extracts a list of relative file paths modified by a unified diff patch."""
    touched = set()
    try:
        with open(patch_path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("--- a/") or line.startswith("+++ b/"):
                    path = line[6:].strip()
                    if path != "/dev/null":
                        touched.add(path)
    except Exception as e:
        log("WARN", f"Failed reading patch {patch_path.name}: {e}")
    return sorted(touched)

def cmd_list(args):
    """Displays registry of supported chip generations and discovered patches."""
    discovered = discover_available_patches()
    
    print("\nSupported Chip Generations & Modular Patch Allocation:")
    print("-" * 88)
    print(f"{'Generation':<12} {'Status':<12} {'Range':<10} {'Active Patches':<16} {'Target Chip Families'}")
    print("-" * 88)
    
    for gen, info in GENERATIONS.items():
        patches = discovered.get(gen, [])
        low, high = info["patch_range"]
        rng = f"{low:04d}..{high:04d}"
        active = f"{len(patches)} patch(es)" if patches else "0 (staged)"
        print(f"{gen:<12} {info['status']:<12} {rng:<10} {active:<16} {info['chips']}")
    
    print("-" * 88)
    print(f"{'all':<12} {'aggregate':<12} {'0001..0049':<10} {sum(len(v) for k, v in discovered.items() if k != 'unassigned')} patch(es)       Unified driver for all supported chips")
    print("-" * 88)
    
    if args.verbose:
        print("\nDetailed Generation Patch Breakdown:")
        for gen, info in GENERATIONS.items():
            print(f"\n[{gen.upper()}] - {info['name']}")
            print(f"  Description: {info['description']}")
            print(f"  Target Subdevs: {', '.join(info['subdev_targets'])}")
            patches = discovered.get(gen, [])
            if patches:
                for p in patches:
                    touched = inspect_touched_files(p)
                    print(f"    - {p.name} (touches: {', '.join(touched)})")
            else:
                print("    (No patches authored yet; ready for staged insertion)")

def cmd_check_isolation(args):
    """Verifies patch application and clean architectural isolation between generations."""
    log("INFO", "Validating architectural file-path isolation across chip generations...")
    discovered = discover_available_patches()
    
    file_map = {}
    has_conflict = False
    
    for gen, patches in discovered.items():
        if gen in ("unassigned", "universal"):
            continue
        for p in patches:
            touched = inspect_touched_files(p)
            for f in touched:
                if f in file_map and file_map[f] != gen:
                    log("FAIL", f"Architectural collision on '{f}': touched by both '{file_map[f]}' and '{gen}'!")
                    has_conflict = True
                file_map[f] = gen
                
    if not has_conflict:
        log("PASS", "Zero collisions detected! Generation-specific subdev files are strictly isolated.")
        
    # Also verify strict patch application against stock source
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        source_dir = tmp_path / "nouveau-source"
        
        with tarfile.open(SOURCE_TAR, "r:gz") as tar:
            tar.extractall(path=tmp_path)
            
        universal_patches = discovered.get("universal", [])
        for p in universal_patches:
            res = subprocess.run(["patch", "--fuzz=0", "-Np1", "-s", "-d", str(source_dir)],
                                 input=p.read_bytes(), capture_output=True)
            if res.returncode != 0:
                log("FAIL", f"Universal patch '{p.name}' failed strict --fuzz=0 application!")
                return 1
        log("PASS", f"All {len(universal_patches)} universal baseline patches applied cleanly with --fuzz=0.")
        
        # Test each generation on top of universal baseline
        for gen, patches in discovered.items():
            if gen in ("universal", "unassigned") or not patches:
                continue
            gen_tree = tmp_path / f"test-{gen}"
            shutil.copytree(source_dir, gen_tree)
            gen_ok = True
            for p in patches:
                res = subprocess.run(["patch", "--fuzz=0", "-Np1", "-s", "-d", str(gen_tree)],
                                     input=p.read_bytes(), capture_output=True)
                if res.returncode != 0:
                    log("FAIL", f"Generation '{gen}' patch '{p.name}' failed --fuzz=0 on top of universal baseline!")
                    gen_ok = False
                    break
            if gen_ok:
                log("PASS", f"Generation '{gen}': {len(patches)} patch(es) applied cleanly on top of universal tree.")
    return 0

def cmd_build_patch(args):
    """Generates a standalone monolithic patch file for a specific generation profile."""
    gen = args.generation
    patches = get_patches_for_generation(gen)
    log("INFO", f"Generating consolidated patch for generation '{gen}' ({len(patches)} patches)...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        orig_extract = tmp_path / "orig"
        patched_extract = tmp_path / "patched"
        orig_dir = tmp_path / "a"
        patched_dir = tmp_path / "b"
        
        with tarfile.open(SOURCE_TAR, "r:gz") as tar:
            tar.extractall(path=orig_extract)
            tar.extractall(path=patched_extract)
            
        (orig_extract / "nouveau-source").rename(orig_dir)
        (patched_extract / "nouveau-source").rename(patched_dir)
            
        for p in patches:
            res = subprocess.run(["patch", "--fuzz=0", "-Np1", "-s", "-d", str(patched_dir)],
                                 input=p.read_bytes(), capture_output=True)
            if res.returncode != 0:
                log("FAIL", f"Failed applying {p.name}: {res.stderr.decode()}")
                return 1
                
        diff_res = subprocess.run(
            ["diff", "-ruN", "a", "b"],
            cwd=str(tmp_path), capture_output=True, text=True
        )
        
        # diff returns 1 when differences exist
        patch_content = diff_res.stdout
        out_file = Path(args.out) if args.out else REPO_ROOT / f"nouveau-{gen}.patch"
        out_file.write_text(patch_content, encoding="utf-8")
        log("PASS", f"Built monolithic patch for '{gen}': {out_file} ({len(patch_content.splitlines())} lines)")
        
        if out_file.resolve() == (REPO_ROOT / "nouveau.patch").resolve():
            pkgbuild = REPO_ROOT / "PKGBUILD"
            if pkgbuild.exists():
                import hashlib
                h = hashlib.sha256(patch_content.encode("utf-8")).hexdigest()
                pb_text = pkgbuild.read_text(encoding="utf-8")
                import re
                pb_text = re.sub(
                    r"('[a-f0-9]{64}'\s*\n\s*)'[a-f0-9]{64}'(\s*\n\s*'7f0d3d86)",
                    r"\g<1>'" + h + r"'\2",
                    pb_text
                )
                pkgbuild.write_text(pb_text, encoding="utf-8")
                log("INFO", f"Synchronized nouveau.patch sha256 in PKGBUILD ({h[:16]}...)")

def cmd_build_tree(args):
    """Extracts nouveau-source.tar.gz and applies generation patches to a target directory."""
    gen = args.generation
    patches = get_patches_for_generation(gen)
    out_dir = Path(args.out)
    
    if out_dir.exists():
        if not args.force:
            log("FAIL", f"Target directory already exists: {out_dir}. Use --force to overwrite.")
            return 1
        shutil.rmtree(out_dir)
        
    out_dir.mkdir(parents=True, exist_ok=True)
    log("INFO", f"Extracting base source and applying '{gen}' patch queue to: {out_dir}...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        with tarfile.open(SOURCE_TAR, "r:gz") as tar:
            tar.extractall(path=tmpdir)
        src = Path(tmpdir) / "nouveau-source"
        for p in patches:
            res = subprocess.run(["patch", "--fuzz=0", "-Np1", "-s", "-d", str(src)],
                                 input=p.read_bytes(), capture_output=True)
            if res.returncode != 0:
                log("FAIL", f"Failed applying {p.name}: {res.stderr.decode()}")
                return 1
        shutil.copytree(src, out_dir, dirs_exist_ok=True)
        
    log("PASS", f"Source tree for generation '{gen}' ready at: {out_dir}")
    return 0

def detect_kernel_build_dirs():
    """Finds available kernel build header directories on the local machine."""
    dirs = [Path(p) for p in glob.glob("/usr/lib/modules/*/build") if os.path.isdir(p)]
    return sorted(dirs)

def compile_source_tree(source_dir: Path, kdir: Path):
    """Compiles nouveau.ko out-of-tree against a kernel build directory."""
    kconfig = kdir / ".config"
    autoconf = kdir / "include" / "config" / "auto.conf"
    is_clang = False
    
    for conf in (kconfig, autoconf):
        if conf.is_file():
            try:
                if "CONFIG_CC_IS_CLANG=y" in conf.read_text(errors="ignore"):
                    is_clang = True
                    break
            except Exception:
                pass
                
    make_cmd = ["make", f"-j{os.cpu_count() or 4}", "-C", str(kdir), f"M={source_dir}"]
    if is_clang:
        make_cmd.append("LLVM=1")
    make_cmd.extend(["CONFIG_DRM_NOUVEAU=m", "modules"])
    
    t0 = time.time()
    res = subprocess.run(make_cmd, capture_output=True, text=True)
    elapsed = time.time() - t0
    
    ko_path = source_dir / "nouveau.ko"
    if res.returncode == 0 and ko_path.is_file():
        return True, elapsed, ""
    return False, elapsed, res.stderr or res.stdout

def cmd_test_generation(args):
    """Tests patch application and compilation for a specific chip generation."""
    gen = args.generation
    kdirs = [Path(args.kdir)] if args.kdir else detect_kernel_build_dirs()
    if not kdirs:
        log("FAIL", "No kernel build directories found. Specify with --kdir <path>.")
        return 1
        
    patches = get_patches_for_generation(gen)
    log("INFO", f"Testing generation '{gen}' ({len(patches)} patches) across {len(kdirs)} kernel(s)...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        source_dir = tmp_path / "nouveau-source"
        with tarfile.open(SOURCE_TAR, "r:gz") as tar:
            tar.extractall(path=tmp_path)
            
        for p in patches:
            res = subprocess.run(["patch", "--fuzz=0", "-Np1", "-s", "-d", str(source_dir)],
                                 input=p.read_bytes(), capture_output=True)
            if res.returncode != 0:
                log("FAIL", f"Patch '{p.name}' failed to apply: {res.stderr.decode()}")
                return 1
        log("PASS", f"Patches for '{gen}' applied with strict --fuzz=0.")
        
        all_passed = True
        for kd in kdirs:
            kver = kd.parent.name
            log("INFO", f"Compiling nouveau.ko ({gen}) against {kver}...")
            # Work on a clean copy
            bdir = tmp_path / f"build-{kver}"
            shutil.copytree(source_dir, bdir)
            ok, elapsed, err = compile_source_tree(bdir, kd)
            if ok:
                log("PASS", f"Compiled nouveau.ko [{gen}] ({kver}) in {elapsed:.1f}s")
            else:
                log("FAIL", f"Failed compiling [{gen}] ({kver}):\n{err[:500]}")
                all_passed = False
                
        return 0 if all_passed else 1

def cmd_test_matrix(args):
    """Executes the full 2D matrix build test (Chip Generations x Target Kernels)."""
    kdirs = [Path(args.kdir)] if args.kdir else detect_kernel_build_dirs()
    if not kdirs:
        log("FAIL", "No kernel build directories found. Specify with --kdir <path>.")
        return 1
        
    generations_to_test = ["universal", "fermi", "all"]
    matrix_results = []
    
    log("INFO", "=" * 60)
    log("INFO", "Running Multi-Generation Chip Matrix Test Suite")
    log("INFO", f"Generations: {', '.join(generations_to_test)}")
    log("INFO", f"Kernels:     {', '.join(k.parent.name for k in kdirs)}")
    log("INFO", "=" * 60)
    
    for gen in generations_to_test:
        patches = get_patches_for_generation(gen)
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            source_dir = tmp_path / "nouveau-source"
            with tarfile.open(SOURCE_TAR, "r:gz") as tar:
                tar.extractall(path=tmp_path)
                
            patch_ok = True
            for p in patches:
                res = subprocess.run(["patch", "--fuzz=0", "-Np1", "-s", "-d", str(source_dir)],
                                     input=p.read_bytes(), capture_output=True)
                if res.returncode != 0:
                    patch_ok = False
                    break
                    
            for kd in kdirs:
                kver = kd.parent.name
                if not patch_ok:
                    matrix_results.append({
                        "generation": gen,
                        "kernel": kver,
                        "status": "FAIL (patch)",
                        "elapsed": 0.0,
                    })
                    continue
                    
                bdir = tmp_path / f"build-{gen}-{kver}"
                shutil.copytree(source_dir, bdir)
                ok, elapsed, err = compile_source_tree(bdir, kd)
                matrix_results.append({
                    "generation": gen,
                    "kernel": kver,
                    "status": "PASS" if ok else "FAIL (build)",
                    "elapsed": elapsed,
                })
                
    print("\n" + "=" * 68)
    print("CHIP GENERATION × KERNEL COMPILATION MATRIX SUMMARY")
    print("=" * 68)
    print(f"{'Chip Generation':<18} {'Kernel Release':<30} {'Status':<12} {'Time'}")
    print("-" * 68)
    for r in matrix_results:
        time_str = f"{r['elapsed']:.1f}s" if r['elapsed'] > 0 else "-"
        print(f"{r['generation']:<18} {r['kernel']:<30} {r['status']:<12} {time_str}")
    print("=" * 68)
    
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(matrix_results, indent=2), encoding="utf-8")
        log("INFO", f"Matrix results written to {args.json_out}")
        
    failures = [r for r in matrix_results if not r["status"].startswith("PASS")]
    return 1 if failures else 0

def main():
    parser = argparse.ArgumentParser(
        description="nouveau-dkms Multi-Generation Chip Matrix & Patch Queue Builder",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    # list
    p_list = subparsers.add_parser("list", help="List supported chip generations and patch allocations")
    p_list.add_argument("-v", "--verbose", action="store_true", help="Show detailed file paths")
    p_list.set_defaults(func=cmd_list)
    
    # check-isolation
    p_iso = subparsers.add_parser("check-isolation", help="Verify clean architectural file isolation between generations")
    p_iso.set_defaults(func=cmd_check_isolation)
    
    # build-patch
    p_patch = subparsers.add_parser("build-patch", help="Generate consolidated monolithic patch for a generation")
    p_patch.add_argument("generation", choices=list(GENERATIONS.keys()) + ["all"], help="Target generation")
    p_patch.add_argument("-o", "--out", help="Output patch file path")
    p_patch.set_defaults(func=cmd_build_patch)
    
    # build-tree
    p_tree = subparsers.add_parser("build-tree", help="Extract and build source tree for a generation target")
    p_tree.add_argument("generation", choices=list(GENERATIONS.keys()) + ["all"], help="Target generation")
    p_tree.add_argument("-o", "--out", required=True, help="Destination directory")
    p_tree.add_argument("-f", "--force", action="store_true", help="Overwrite destination if it exists")
    p_tree.set_defaults(func=cmd_build_tree)
    
    # test-generation
    p_test_gen = subparsers.add_parser("test-generation", help="Test patch application & compile for one generation")
    p_test_gen.add_argument("generation", choices=list(GENERATIONS.keys()) + ["all"], help="Target generation")
    p_test_gen.add_argument("--kdir", help="Target kernel build directory (/usr/lib/modules/*/build)")
    p_test_gen.set_defaults(func=cmd_test_generation)
    
    # test-matrix
    p_matrix = subparsers.add_parser("test-matrix", help="Run 2D matrix build test (all active generations x kernels)")
    p_matrix.add_argument("--kdir", help="Filter target kernel build directory")
    p_matrix.add_argument("--json-out", help="Write matrix results to JSON file")
    p_matrix.set_defaults(func=cmd_test_matrix)
    
    args = parser.parse_args()
    return args.func(args)

if __name__ == "__main__":
    sys.exit(main() or 0)
