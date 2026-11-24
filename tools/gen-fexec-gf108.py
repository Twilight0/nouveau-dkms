#!/usr/bin/env python3
"""
Build fexec_code_gf108.inc: the resident Falcon executor for the Quadro 600
(GF108 / NVC1, PCI 10de:0df8 subsys 103c:0835, VBIOS 70.08.2a.00.01).

No Falcon assembler is used.  The GF106M image (fexec_code.inc) is reused
byte for byte: its boot code, command loop and helpers stay where they are
(wr32 0x0e35, rd32 0x0dde, wait 0x0cd0, delay 0x0cec, vblank-spin 0x0cf7,
block 0x0d06, unblock 0x0d7d, error 0x00f7).  The two GF106M script bodies
become dead code; the cmd-1 / cmd-2 call sites (0x009c / 0x00a3) are
re-pointed at new straight-line script bodies appended after the helpers.
Every new instruction is one of the encodings already present in the image:

    f1 r7 lo hi   mov  rN imm16          f1 r3 lo hi   sethi rN imm16
    f5 21 lo hi   call abs16             f8 00         ret
    f5 0e lo hi   bra  rel16 (from insn start)

plus verbatim copies of helper fragments (wait loop, unblock body, DEAD
write).  The script ops come from NVIDIA 390.157's own PMU memx scripts
(testing/gf108_quadro600_pmu_memx_decoded.txt, blocks 20, 28, 54;
61 and 69 are checked to be 28-minus-one-write and == 54)
and the host writes the blob made right before / after each script
(BAR0 mmiotrace of the same runs; timestamps quoted below are from the
first capture (112.x s) and the full-cycle capture (107.x / 207.x s)).

Commands of the resulting image (SCRATCH3 = 0x10a084):
    0  probe: report DONE (0xE1EC0001), touch nothing, stay resident
    1  block 28: 324 MHz (MPLL, either form) -> 800 MHz (MPLL)
    2  "to 324": 0x137360 bit 0 set (boot mdiv bypass) -> block 20,
       clear (MPLL 800) -> block 54 (800 -> 324).  The host checks the
       exact start state before sending either command.
SCRATCH2 = 0x10a080: 0xE1EC0001 done, 0xDEAD0108 in-block failure (FB
pause released + engine gating restored), 0xDEAD0020 block-20 PLL lock
timeout before the FB block (DRAM untouched), 0xDEAD0000 legacy path
(MMIO port timeout inside a helper; state unknown).

Usage (BASE = fexec_code.inc from a tree patched through 0012):
    gen-fexec-gf108.py BASE testing/gf108_quadro600_pmu_memx_decoded.txt \
        nvkm/subdev/fb/fexec_code_gf108.inc [LISTING.txt]
"""
import re
import sys

# ---------------------------------------------------------------- helpers
H_WR32, H_RD32, H_WAIT, H_DELAY = 0x0e35, 0x0dde, 0x0cd0, 0x0cec
H_VBL, H_BLOCK, H_UNBLOCK, H_ERR, H_POLL = 0x0cf7, 0x0d06, 0x0d7d, 0x00f7, 0x00d1
CALL_CMD1, CALL_CMD2 = 0x009c, 0x00a3

WAIT_BOUND = 0x00020000      # iterations; NVIDIA asks 64 us, GF106M image uses 0x100000
OP3A_ITERS = 676             # per unit; the validated GF106M translation of "op3a n"


def nsec_iters(ns):
    # GF106M image: 1000 ns -> 100 iterations (3 insns/iter @ ~203 MHz = 67,
    # so >= 1.48x margin, never shorter than asked).
    return max(1, (ns + 9) // 10)


def load_image(path):
    words = [int(w, 16) for w in re.findall(r'0x([0-9a-f]{8})', open(path).read())]
    return bytearray(b''.join(w.to_bytes(4, 'little') for w in words))


def parse_blocks(path):
    blocks, cur = {}, None
    for line in open(path):
        m = re.match(r'/\* ===== block (\d+):', line)
        if m:
            cur = blocks.setdefault(int(m.group(1)), [])
            continue
        if cur is None:
            continue
        t = line.split()
        if not t:
            continue
        k = t[0]
        if k == 'wr32':
            cur.append(('wr', int(t[1], 16), int(t[3], 16)))
        elif k == 'nsec':
            cur.append(('nsec', int(t[1])))
        elif k == 'wait':
            cur.append(('wait', int(t[1], 16), int(t[3], 16), int(t[5], 16)))
        elif k == 'vblank':
            cur.append(('vblank', int(t[2])))
        elif k in ('block', 'unblock', 'end'):
            cur.append((k,))
        elif k == 'marker':
            cur.append(('marker', int(t[1])))
        elif k == 'op3a':
            cur.append(('op3a', int(t[1])))
        else:
            raise SystemExit('unknown op line: ' + line)
    return blocks


# Host-side writes the blob made around each PMU script (BAR0 mmiotrace).
# Identical before both scripts (112.749184.. and 112.767764..):
PRE_PHY = [(0x10f468, 0x00001005), (0x10f420, 0x00000042), (0x10f430, 0x00000040),
           (0x10f400, 0x00001707), (0x10f410, 0x00000307), (0x10f444, 0x04cc881f),
           (0x001548, 0x80000102)]
# Before block 20 only (112.749235/237): 0x132000 rewrite + clear bit 1.
PRE_20 = PRE_PHY + [(0x132000, 0x18010002), (0x132000, 0x18010000)]
PRE_28 = PRE_PHY
# After block 20 (112.763119..112.763167, 112.763858 0x1548, 112.764615 0x10f050)
POST_20 = [(0x132018, 0x10001000), (0x10f824, 0x004079e7), (0x10f824, 0x004079e7),
           (0x10f808, 0x08020004), (0x001548, 0x00000102),
           (0x10f468, 0x00001005), (0x10f420, 0x00000042), (0x10f430, 0x00000040),
           (0x10f400, 0x00001707), (0x10f410, 0x00000307), (0x10f444, 0x04cc881f),
           (0x001548, 0x00000101), (0x001548, 0x80000101), (0x10f050, 0xff000450)]
# Around block 54 (= block 69; 107.807109..107.811838 and
# 207.801518..207.810035, identical): 0x10f050 before, 0x1548 = 0x101 written
# ~0.45 ms after the kick (PMU in its pre-block vblank wait), then the 324 PHY
# set twice with 0x132018/0x10f824/0x10f808 in between.
PHY_324 = [(0x10f468, 0x00001005), (0x10f420, 0x00000042), (0x10f430, 0x00000040),
           (0x10f400, 0x00001707), (0x10f410, 0x00000307), (0x10f444, 0x04cc881f)]
PRE_54 = [(0x10f050, 0xff000450)] + PRE_PHY
MID_54 = [(0x001548, 0x00000101)]
POST_54 = ([(0x001548, 0x80000101)] + PHY_324 +
           [(0x132018, 0x10001000), (0x10f824, 0x00407867), (0x10f824, 0x004079e7),
            (0x10f808, 0x08020004), (0x001548, 0x00000102)] + PHY_324 +
           [(0x001548, 0x00000101), (0x001548, 0x80000101)])
# After block 28 (112.780112..112.780146, 112.780354 0x10f050)
POST_28 = [(0x10f824, 0x00401e67), (0x001548, 0x00000102),
           (0x10f468, 0x00020020), (0x10f420, 0x00000043), (0x10f430, 0x00000041),
           (0x10f400, 0x0000171f), (0x10f410, 0x00000107), (0x10f444, 0x04cc883f),
           (0x001548, 0x00000101), (0x001548, 0x80000101), (0x10f050, 0xff001050)]


# ------------------------------------------------------------ encoders
def mov(reg, v):
    v &= 0xffffffff
    lo, hi = v & 0xffff, v >> 16
    return bytes([0xf1, (reg << 4) | 7, lo & 0xff, lo >> 8,
                  0xf1, (reg << 4) | 3, hi & 0xff, hi >> 8])


def call(t):
    return bytes([0xf5, 0x21, t & 0xff, t >> 8])


def bra16(pc, target):
    rel = (target - pc) & 0xffff
    return bytes([0xf5, 0x0e, rel & 0xff, rel >> 8])


RET = bytes([0xf8, 0x00])


class Script:
    def __init__(self, base):
        self.base, self.b, self.ops = base, bytearray(), []

    def pc(self):
        return self.base + len(self.b)

    def wr(self, a, v):
        self.ops.append(('wr', a, v))
        self.b += mov(14, a) + mov(13, v) + call(H_WR32)

    def delay(self, iters, why):
        self.ops.append(('delay', iters, why))
        self.b += mov(7, iters) + call(H_DELAY)

    def wait(self, a, mask, val, helper):
        self.ops.append(('wait', a, mask, val, helper))
        self.b += mov(14, a) + mov(5, mask) + mov(4, val) + mov(7, WAIT_BOUND) + call(helper)

    def call(self, t, what):
        self.ops.append((what,))
        self.b += call(t)

    def ret(self):
        self.ops.append(('ret',))
        self.b += RET


def emit_block(s, ops, pre, post, wait_helper_pre, wait_helper_in, skipped, mid=()):
    """mid: host writes the blob made while the PMU sat in the pre-block
    vblank wait; emitted right before the first vblank op."""
    for a, v in pre:
        s.wr(a, v)
    blocked = False
    for op in ops:
        if op[0] == 'vblank' and mid:
            for a, v in mid:
                s.wr(a, v)
            mid = ()
        k = op[0]
        if k == 'wr':
            _, a, v = op
            if a == 0x13d834:
                # always directly followed by op3a; see op3a below
                skipped.append('wr32 0x13d834 <= 0x%08x (dropped, paired with op3a)' % v)
                continue
            s.wr(a, v)
        elif k == 'nsec':
            s.delay(nsec_iters(op[1]), 'nsec %d' % op[1])
        elif k == 'op3a':
            s.delay(OP3A_ITERS * op[1], 'op3a %d' % op[1])
        elif k == 'wait':
            _, a, mask, val = op[:4]
            s.wait(a, mask, val, wait_helper_in if blocked else wait_helper_pre)
        elif k == 'vblank':
            s.call(H_VBL, 'vblank-spin')
        elif k == 'block':
            s.call(H_BLOCK, 'block')
            blocked = True
        elif k == 'unblock':
            s.call(H_UNBLOCK, 'unblock')
            blocked = False
        elif k == 'marker':
            skipped.append('marker %d (dropped)' % op[1])
        elif k == 'end':
            pass
    assert not blocked
    for a, v in post:
        s.wr(a, v)
    s.ret()


# --------------------------------------------------- independent decoder
def decode(img, start, stop_at_ret=True):
    """Decode only the forms this generator emits; anything else is fatal."""
    regs, out, pc = {}, [], start
    names = {H_WR32: 'wr', H_WAIT: 'wait', 'w_in': 'wait_in', H_DELAY: 'delay',
             H_VBL: 'vblank-spin', H_BLOCK: 'block', H_UNBLOCK: 'unblock'}
    while True:
        b0, b1 = img[pc], img[pc + 1]
        if b0 == 0xf1 and (b1 & 0xf) == 7:
            regs[b1 >> 4] = img[pc + 2] | img[pc + 3] << 8
            if regs[b1 >> 4] & 0x8000:
                regs[b1 >> 4] |= 0xffff0000
            pc += 4
        elif b0 == 0xf1 and (b1 & 0xf) == 3:
            r = b1 >> 4
            regs[r] = (regs[r] & 0xffff) | ((img[pc + 2] | img[pc + 3] << 8) << 16)
            pc += 4
        elif b0 == 0xf5 and b1 == 0x21:
            t = img[pc + 2] | img[pc + 3] << 8
            out.append((t, dict(regs)))
            pc += 4
        elif b0 == 0xf8 and b1 == 0x00:
            out.append(('ret', None))
            return out, pc + 2
        else:
            raise SystemExit('decode: unexpected byte %02x %02x at %04x' % (b0, b1, pc))


def main():
    base_path, memx_path, out_path = sys.argv[1:4]
    listing = sys.argv[4] if len(sys.argv) > 4 else None
    img = load_image(base_path)

    # Sanity: the image is exactly the GF106M executor we analysed.
    expect = {
        CALL_CMD1: call(0x010e), CALL_CMD2: call(0x06be),
        H_WAIT: bytes.fromhex('f5 21 de 0d fd d5 04 b8 d4 06 f4 0b 10 b6 72 01 b0 76 00 f4 1b ed f5 0e 11 f4 f8 00'.replace(' ', '')),
        H_UNBLOCK: bytes.fromhex(('f1 97 e4 07 b6 94 06 f0 b7 04 d0 9b 00 bd 04 f1 73 00 01 f1 97 c0 07 b6 94 06'
                                  ' cf 99 00 f0 94 04 b0 96 00 f4 0b 10 b6 72 01 b0 76 00 f4 1b e7 f5 0e 4b f3'
                                  ' f1 67 f0 26 b9 6e 02 f5 21 de 0d f1 77 01 00 fd d7 05 f5 21 35 0e'
                                  ' f1 67 20 16 b9 6e 02 f5 21 de 0d f1 77 a3 0a fd d7 05 f5 21 35 0e f8 00').replace(' ', '')),
        0x0d77: bra16(0x0d77, H_ERR),
        H_ERR: bytes.fromhex('f1 97 80 00 b6 94 06 f1 b7 00 00 f1 b3 ad de d0 9b 00 bd 04 f4 0e c6'.replace(' ', '')),
        H_POLL: bytes.fromhex('f1 97 84 00 b6 94 06 f1 77 c8 00'.replace(' ', '')),
        H_DELAY: bytes.fromhex('b6 72 01 b0 76 00 f4 1b fa f8 00'.replace(' ', '')),
        H_VBL: bytes.fromhex('f1 77 e8 03 b6 72 01 b0 76 00 f4 1b fa f8 00'.replace(' ', '')),
        H_BLOCK: bytes.fromhex('f1 67 20 16 f1 77 5d f5 f1 73 ff ff'.replace(' ', '')),
        H_WR32: bytes.fromhex('f1 07 a0 07 b6 04 06 d0 0e 00'.replace(' ', '')),
        H_RD32: bytes.fromhex('f1 07 a0 07 b6 04 06 d0 0e 00'.replace(' ', '')),
    }
    for at, want in expect.items():
        if bytes(img[at:at + len(want)]) != want:
            raise SystemExit('base image mismatch at 0x%04x' % at)
    last = max(i for i in range(len(img)) if img[i])
    assert last == 0x0e8c and bytes(img[0x0e8c:0x0e8e]) == RET, hex(last)
    end = 0x0e8e                                          # final helper's "ret"
    del img[end:]
    while len(img) % 16:
        img.append(0)

    blocks = parse_blocks(memx_path)
    if sorted(blocks) != [20, 28, 54, 61, 69]:
        raise SystemExit('expected blocks 20 28 54 61 69, got %r' % sorted(blocks))
    # 54 and 69 (both 800 -> 324) are identical; 61 (second 324 -> 800, started
    # from the post-54 MPLL-324 state) is 28 minus its first write, 0x137310 =
    # 0x81200608, which that state already holds.  Replay 28 and 54.
    assert blocks[54] == blocks[69], '54 != 69'
    assert blocks[28][0] == ('wr', 0x137310, 0x81200608) and blocks[28][1:] == blocks[61], '28 vs 61'

    # --- error handler for failures inside the FB block (err_in) -------------
    err_in = len(img)
    unblock = bytes(img[H_UNBLOCK:H_UNBLOCK + 0x61])      # 0x0d7d..0x0ddd
    # 1) release FB_PAUSE + bounded ack poll; timeout falls through (no error loop)
    part1 = bytearray(unblock[0:0x2f])                    # up to the timeout bra at 0x0dac
    assert bytes(unblock[0x2f:0x33]) == bytes.fromhex('f50e4bf3')
    part1 += bra16(err_in + 0x2f, err_in + 0x33)          # = "fall through"
    # 2) restore engine gating 0x26f0 |= 1, 0x1620 |= 0xaa3 (0x0db0..0x0ddb)
    part2 = unblock[0x33:0x5f]
    assert bytes(unblock[0x5f:0x61]) == RET
    # 3) SCRATCH2 = 0xDEAD0108, back to the command loop (copy of 0x00f7 path)
    part3 = bytearray(bytes.fromhex('f19780 00b69406 f1b70801 f1b3adde d09b00 bd04'.replace(' ', '')))
    img += part1 + part2 + part3
    img += bra16(len(img), H_POLL)

    # --- error handler for the pre-block PLL wait in block 20 (err_pre) ------
    err_pre = len(img)
    img += bytes.fromhex('f19780 00b69406 f1b72000 f1b3adde d09b00 bd04'.replace(' ', ''))
    img += bra16(len(img), H_POLL)

    # --- wait helpers: copies of 0x0cd0 with their own timeout targets -------
    def wait_copy(target):
        at = len(img)
        w = bytearray(img[H_WAIT:H_WAIT + 0x1c])
        w[0x16:0x1a] = bra16(at + 0x16, target)
        img.extend(w)
        return at
    wait_in = wait_copy(err_in)
    wait_pre = wait_copy(err_pre)

    # FB_PAUSE ack timeouts inside block/unblock: release + restore instead of
    # leaving the FB paused (both were "bra 0x00f7").
    assert bytes(img[0x0dac:0x0db0]) == bra16(0x0dac, H_ERR)
    img[0x0d77:0x0d7b] = bra16(0x0d77, err_in)
    img[0x0dac:0x0db0] = bra16(0x0dac, err_in)

    skipped = []
    scripts = []
    for name, n, pre, post, mid in (('cmd1/block28', 28, PRE_28, POST_28, ()),
                                    ('block20', 20, PRE_20, POST_20, ()),
                                    ('block54', 54, PRE_54, POST_54, MID_54)):
        while len(img) % 4:
            img.append(0)
        sc = Script(len(img))
        emit_block(sc, blocks[n], pre, post, wait_pre, wait_in, skipped, mid)
        img += sc.b
        scripts.append((name, sc, pre, post, mid, blocks[n]))
    s28, s20, s54 = (x[1] for x in scripts)

    # --- cmd 2 dispatcher: "go to 324".  The command loop only knows 1 and 2,
    # so cmd 2 picks the script from the clock source the host already checked:
    # 0x137360 bit 0 set (boot mdiv bypass) -> block 20, clear (MPLL 800) -> 54.
    # Encodings as in the image: rd32 call, "and r13 imm16" (0x0e0a),
    # "cmp r13 0" (0x0e21), "bra ne rel16" (0x0e25).
    while len(img) % 4:
        img.append(0)
    disp = len(img)
    d = bytearray(mov(14, 0x137360) + call(H_RD32) +
                  bytes.fromhex('f1d40100') + bytes.fromhex('b0d600'))
    bne_at = disp + len(d)
    d += b'\0\0\0\0'                                       # bra ne -> L20
    d += call(s54.base) + RET
    l20 = disp + len(d)
    d += call(s20.base) + RET
    rel = (l20 - bne_at) & 0xffff
    d[bne_at - disp:bne_at - disp + 4] = bytes([0xf5, 0x1b, rel & 0xff, rel >> 8])
    img += d
    # check the image's own "bra ne rel16" encoding the same way
    assert img[0x0e25:0x0e29] == bytes([0xf5, 0x1b]) + ((H_ERR - 0x0e25) & 0xffff).to_bytes(2, 'little')

    img[CALL_CMD1:CALL_CMD1 + 4] = call(s28.base)
    img[CALL_CMD2:CALL_CMD2 + 4] = call(disp)

    # --- verify by decoding the bytes back ------------------------------------
    lst = []
    for name, s, pre, post, mid, blk in scripts:
        calls, endpc = decode(img, s.base)
        assert endpc == s.base + len(s.b)
        got = []
        for t, r in calls:
            if t == 'ret':
                got.append(('ret',))
            elif t == H_WR32:
                got.append(('wr', r[14], r[13]))
            elif t == H_DELAY:
                got.append(('delay', r[7]))
            elif t in (wait_in, wait_pre):
                assert r[7] == WAIT_BOUND
                got.append(('wait', r[14], r[5], r[4], t))
            elif t == H_VBL:
                got.append(('vblank-spin',))
            elif t == H_BLOCK:
                got.append(('block',))
            elif t == H_UNBLOCK:
                got.append(('unblock',))
            else:
                raise SystemExit('unexpected call target %04x' % t)
        want = [o if o[0] != 'delay' else o[:2] for o in s.ops]
        if got != want:
            raise SystemExit('round-trip mismatch in ' + name)
        # against the trace: every non-dropped write in order, host writes
        # around it, and the delay / wait / block skeleton
        trace_wr = [(a, v) for (k, *r) in blk if k == 'wr' for a, v in [r] if a != 0x13d834]
        got_wr = [(o[1], o[2]) for o in got if o[0] == 'wr']
        if mid:
            iv = next(i for i, o in enumerate(blk) if o[0] == 'vblank')
            nb = len([1 for o in blk[:iv] if o[0] == 'wr' and o[1] != 0x13d834])
            trace_wr = trace_wr[:nb] + list(mid) + trace_wr[nb:]
        assert got_wr == pre + trace_wr + post, name
        skel = [o[0] for o in blk if o[0] in ('wait', 'block', 'unblock', 'vblank')]
        gskel = [{'vblank-spin': 'vblank'}.get(o[0], o[0]) for o in got
                 if o[0] in ('wait', 'block', 'unblock', 'vblank-spin')]
        assert skel == gskel, name
        tw = [o for o in blk if o[0] == 'wait']
        assert [(o[1], o[2], o[3]) for o in tw] == [(o[1], o[2], o[3]) for o in got if o[0] == 'wait']
        lst.append('/* %s @ 0x%04x, %d bytes */' % (name, s.base, len(s.b)))
        for o in s.ops:
            if o[0] == 'wr':
                lst.append('  wr32    0x%06x <= 0x%08x' % (o[1], o[2]))
            elif o[0] == 'delay':
                lst.append('  delay   %d iters   (%s)' % (o[1], o[2]))
            elif o[0] == 'wait':
                lst.append('  wait    0x%06x & 0x%08x == 0x%08x  bound 0x%x  %s' %
                           (o[1], o[2], o[3], WAIT_BOUND,
                            'in-block -> 0xDEAD0108 + release' if o[4] == wait_in else 'pre-block -> 0xDEAD0020'))
            else:
                lst.append('  ' + o[0])
    lst.append('/* cmd 2 dispatcher @ 0x%04x: rd32(0x137360) & 1 ? block20 @ 0x%04x : block54 @ 0x%04x */'
               % (disp, s20.base, s54.base))
    lst.append('  ' + bytes(img[disp:disp + len(d)]).hex(' '))

    # call sites
    assert bytes(img[CALL_CMD1:CALL_CMD1 + 4]) == call(s28.base)
    assert bytes(img[CALL_CMD2:CALL_CMD2 + 4]) == call(disp)
    assert len(img) <= 0x6000

    while len(img) % 4:
        img.append(0)
    words = [int.from_bytes(img[i:i + 4], 'little') for i in range(0, len(img), 4)]
    with open(out_path, 'w') as f:
        f.write('/* Resident Falcon executor for the Quadro 600 (GF108, 10de:0df8 103c:0835).\n'
                ' * GENERATED by tools/gen-fexec-gf108.py from the GF106M fexec_code.inc\n'
                ' * (helpers reused verbatim) and NVIDIA 390.157 PMU memx blocks 20/28/54\n'
                ' * captured on that card.  Do not edit by hand.\n'
                ' *   cmd 0: probe (DONE, no register writes)\n'
                ' *   cmd 1: block 28, 324 MHz (MPLL, either form) -> 800 MHz\n'
                ' *   cmd 2: to 324 MHz: 0x137360 bit 0 set (boot bypass) -> block 20,\n'
                ' *          clear (MPLL 800) -> block 54\n'
                ' * block28 @ 0x%04x, block20 @ 0x%04x, block54 @ 0x%04x, cmd2 dispatch @ 0x%04x,\n'
                ' * err_in @ 0x%04x, err_pre @ 0x%04x, wait_in @ 0x%04x, wait_pre @ 0x%04x, %d bytes */\n'
                % (s28.base, s20.base, s54.base, disp, err_in, err_pre, wait_in, wait_pre, len(img)))
        f.write('static const u32 fexec_code_gf108[] = {\n')
        for i in range(0, len(words), 4):
            f.write('\t' + ', '.join('0x%08x' % w for w in words[i:i + 4]) + ',\n')
        f.write('};\n')
    if listing:
        with open(listing, 'w') as f:
            f.write('\n'.join(lst) + '\n\n/* dropped from the NVIDIA scripts */\n')
            f.write('\n'.join('  ' + x for x in skipped) + '\n')
    print('ok: %d bytes, block28 @ %04x (%d B), block20 @ %04x (%d B), block54 @ %04x (%d B), disp @ %04x'
          % (len(img), s28.base, len(s28.b), s20.base, len(s20.b), s54.base, len(s54.b), disp))


if __name__ == '__main__':
    main()
