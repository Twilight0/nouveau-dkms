#!/usr/bin/env python3
"""
Decode the NVIDIA proprietary PMU memory-reclock script streamed through
PDAEMON.DATA (0x10a1c4) in a demmio-decoded mmiotrace, and optionally emit
the equivalent nouveau ramfuc C code.

Script framing (reverse engineered from GF106 / nvidia 390.157 trace):
    header = (nwords << 16) | opcode      # nwords includes the header itself
    0x21  wr32      : (addr, value) pairs
    0x2e  nsec      : delay in nanoseconds
    0x00  set data  : value for following wait
    0x01  set addr  : register for following wait
    0x15  wait      : (mask, timeout_ns) on addr/data set by 0x00/0x01
    0x14  vblank    : (head, timeout_ns)
    0x20  block     : (1,0)=block host, (0,0)=unblock
    0x34  marker    : unknown, nouveau ignores (0x0a at start, 0x0b at end)
    0x3a  unknown   : always follows "0x13d8b4 <= 0"; treated as a delay
    0x16  end

Usage:
    decode-pmu-memx.py TRACE [--c] [--block N]
"""
import re
import sys

ANSI = re.compile(r"\x1b\[[0-9;]*m")


def load_blocks(path):
    ev = []
    with open(path, errors="replace") as f:
        for line in f:
            line = ANSI.sub("", line)
            m = re.search(r"MMIO32 W 0x10a1c([04]) (0x[0-9a-f]+)", line)
            if m:
                ev.append((m.group(1) == "0", int(m.group(2), 16)))
    blocks, cur, idx = [], [], None
    for is_index, v in ev:
        if is_index:
            if cur:
                blocks.append((idx, cur))
            cur, idx = [], v
        else:
            cur.append(v)
    if cur:
        blocks.append((idx, cur))
    return blocks


def decode(words):
    i, addr, data = 0, None, None
    while i < len(words):
        hdr = words[i]
        n, op = hdr >> 16, hdr & 0xFFFF
        if n == 0 or i + n > len(words):
            yield ("bad", i, hdr)
            return
        body = words[i + 1:i + n]
        if op == 0x21:
            for a, v in zip(body[0::2], body[1::2]):
                yield ("wr", a, v)
        elif op == 0x2E:
            for ns in body:
                yield ("nsec", ns, None)
        elif op == 0x00:
            data = body[0]
        elif op == 0x01:
            addr = body[0]
        elif op == 0x15:
            yield ("wait", addr, (body[0], data, body[1]))
        elif op == 0x14:
            yield ("vblank", body[0], body[1])
        elif op == 0x20:
            yield ("block" if body[0] else "unblock", None, None)
        elif op == 0x34:
            yield ("marker", body[0], None)
        elif op == 0x3A:
            yield ("op3a", body[0], None)
        elif op == 0x16:
            yield ("end", None, None)
        else:
            yield ("unk", op, body)
        i += n


def emit(ops, as_c):
    for kind, a, v in ops:
        if as_c:
            if kind == "wr":
                print(f"\tram_wr32(fuc, 0x{a:06x}, 0x{v:08x});")
            elif kind == "nsec":
                print(f"\tram_nsec(fuc, {a});")
            elif kind == "wait":
                mask, data, to = v
                print(f"\tram_wait(fuc, 0x{a:06x}, 0x{mask:08x}, 0x{data:08x}, {to});")
            elif kind == "vblank":
                print(f"\tram_wait_vblank(fuc);\t/* head {a}, timeout {v} ns */")
            elif kind == "block":
                print("\tram_block(fuc);")
            elif kind == "unblock":
                print("\tram_unblock(fuc);")
            elif kind == "marker":
                print(f"\t/* 0x34 marker 0x{a:02x} */")
            elif kind == "op3a":
                print(f"\tram_nsec(fuc, 10000);\t/* unknown op 0x3a arg {a} */")
            elif kind == "end":
                print("\t/* end */")
            else:
                print(f"\t/* UNKNOWN op 0x{a:02x}: {[hex(x) for x in v]} */")
        else:
            if kind == "wr":
                print(f"  wr32    0x{a:06x} <= 0x{v:08x}")
            elif kind == "wait":
                mask, data, to = v
                print(f"  wait    0x{a:06x} & 0x{mask:08x} == 0x{data:08x}  ({to} ns)")
            elif kind == "vblank":
                print(f"  vblank  head {a}  (timeout {v} ns)")
            else:
                print(f"  {kind:7s} {a if a is not None else ''}")


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    as_c = "--c" in args
    only = None
    if "--block" in args:
        only = int(args[args.index("--block") + 1])
    blocks = load_blocks(args[0])
    for bi, (idx, words) in enumerate(blocks):
        ops = list(decode(words))
        if not any(o[0] == "wr" for o in ops):
            continue
        if only is not None and bi != only:
            continue
        print(f"\n/* ===== block {bi}: DATA_INDEX=0x{idx:08x}, {len(words)} words ===== */")
        emit(ops, as_c)


if __name__ == "__main__":
    main()
