#!/usr/bin/env python3
"""
Build and verify the resident Falcon microcode executor (fexec_code.fuc -> fexec_code.inc)
for Fermi GF106/GF108 DDR3 memory reclocking.

Follows RECLOCKING_NOTES.md §4.25b (Source-Artifact Co-Location Rule) and §10.4
(Zero-Flash In-Falcon WAIT_VBLANK + RMOnDemandVBlank deferral + 0x13d7f4 FB
partition write-buffer flush).
"""

import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FB_DIR = os.path.join(REPO_ROOT, "src", "nouveau-source", "nvkm", "subdev", "fb")
FUC_PATH = os.path.join(FB_DIR, "fexec_code.fuc")
INC_PATH = os.path.join(FB_DIR, "fexec_code.inc")


def assemble_fuc(fuc_path: str) -> list[int]:
    res = subprocess.run(
        ["/usr/bin/envyas", "-m", "falcon", "-V", "fuc3", "-w", fuc_path],
        capture_output=True,
        text=True,
        check=True,
    )
    words = [int(w, 16) for w in re.findall(r"0x[0-9a-fA-F]{8}", res.stdout)]
    # Pad to 64-word (256-byte) Falcon v3 VTLB IMEM page boundary
    npages = (len(words) + 0x3F) >> 6
    total_words = npages * 0x40
    while len(words) < total_words:
        words.append(0x00000000)
    return words


def format_inc(words: list[int]) -> str:
    lines = [
        "/* Native resident Falcon executor for Fermi GF106 DDR3 reclocking",
        " * Source: nvkm/subdev/fb/fexec_code.fuc (assembled via tools/build-fexec.py)",
        " * Includes in-Falcon WAIT_VBLANK leading-edge sync + RMOnDemandVBlank deferral",
        " * and 0x13d7f4 per-partition FB write-buffer flush (_nv031916rm / _nv031754rm).",
        " */",
        "static const u32 fexec_code[] = {",
    ]
    for i in range(0, len(words), 4):
        chunk = words[i : i + 4]
        row = ", ".join(f"0x{w:08x}" for w in chunk)
        lines.append(f"\t{row},")
    lines.append("};")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    if not os.path.exists(FUC_PATH):
        print(f"ERROR: {FUC_PATH} not found", file=sys.stderr)
        return 1
    words = assemble_fuc(FUC_PATH)
    inc_text = format_inc(words)
    with open(INC_PATH, "w") as f:
        f.write(inc_text)
    print(f"Assembled {FUC_PATH} -> {INC_PATH}: {len(words)} words ({len(words) // 64} VTLB pages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
