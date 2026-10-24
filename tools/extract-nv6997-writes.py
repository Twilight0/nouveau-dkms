#!/usr/bin/env python3
"""Extract the MMIO write sequence from _nv006997rm disassembly.

Usage:
    python3 extract-nv6997-writes.py testing/nv340_nv006997rm_disasm.txt

Convention (340.108 RM, inferred from surrounding code):
    ESI = register address (mov $imm,%esi)
    EDX = value: immediate (mov $imm,%edx), struct field (mov MEM,%edx),
          or computed (register move). RDI = adapter cookie.
    Direct near `call T` after the ESI/EDX setup = register-write helper.

Output: ordered `addr <- value-source (call@addr)` list.
"""
import re
import sys

path = sys.argv[1] if len(sys.argv) > 1 else 'testing/nv340_nv006997rm_disasm.txt'
lines = open(path).read().splitlines()

writes = []
edx = None
for i, l in enumerate(lines):
    m = re.search(r'mov\s+\$(0x[0-9a-f]+),%esi', l)
    if m:
        addr = m.group(1)
        for l2 in lines[i + 1:i + 7]:
            m2 = re.search(r'call\s+([0-9a-f]+)\s', l2)
            if m2 and '*(' not in l2:
                writes.append((m2.group(1), addr, edx))
                edx = None
                break
        continue
    m = re.search(r'mov\s+\$(0x[0-9a-f]+),%edx', l)
    if m:
        edx = ('imm', m.group(1))
        continue
    m = re.search(r'mov\s+([\w\(\)%\.]+),%edx', l)
    if m and 'xor' not in l:
        edx = ('mem', m.group(1))
        continue
    if re.match(r'\s*[0-9a-f]+:\s*31 d2', l):
        edx = ('zero', '0')
        continue

print(f'{len(writes)} register writes in _nv006997rm call order:')
for call, addr, val in writes:
    src = f'{val[0]}:{val[1]}' if val else '?'
    print(f'  {addr} <- {src}   (call@{call})')
