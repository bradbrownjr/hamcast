"""Forward error correction used by YSF framing.

Ported from the GPL MMDVM code by Jonathan Naylor G4KLX as carried in
DroidStar (Doug McLain AD8DP): Golay24128.cpp, YSFConvolution.cpp, CRCenc.cpp.
The Golay decoding table and the CRC table are generated at import time from
their defining polynomials instead of being pasted in; tests/test_fec.py
checks them against encode/decode round trips.
"""

# ========== Golay (23,12) / (24,12) ==========

_X22 = 0x00400000
_X11 = 0x00000800
_MASK12 = 0xFFFFF800
_GENPOL = 0x00000C75


def _syndrome_23127(pattern: int) -> int:
    """Remainder of pattern / GENPOL (Golay24128.cpp::get_syndrome_23127)."""
    aux = _X22
    if pattern >= _X11:
        while pattern & _MASK12:
            while not (aux & pattern):
                aux >>= 1
            pattern ^= (aux // _X11) * _GENPOL
    return pattern


def _build_decoding_table() -> list[int]:
    # Every correctable error pattern (weight <= 3 over 23 bits) keyed by its
    # syndrome. The (23,12) Golay code is perfect, so this fills all 2048 slots.
    table = [0] * 2048
    table[0] = 0
    for a in range(23):
        p = 1 << a
        table[_syndrome_23127(p)] = p
        for b in range(a + 1, 23):
            p2 = p | (1 << b)
            table[_syndrome_23127(p2)] = p2
            for c in range(b + 1, 23):
                p3 = p2 | (1 << c)
                table[_syndrome_23127(p3)] = p3
    return table


_DECODING_TABLE_23127 = _build_decoding_table()


def golay23127_encode(data: int) -> int:
    return (data << 11) | _syndrome_23127(data << 11)


def golay23127_decode(code: int) -> int:
    code ^= _DECODING_TABLE_23127[_syndrome_23127(code)]
    return code >> 11


def golay24128_encode(data: int) -> int:
    code = golay23127_encode(data) << 1
    # Overall parity bit makes the (24,12) extended code.
    return code | (bin(code).count("1") & 1)


def golay24128_decode_bytes(b: bytes) -> int:
    code = (b[0] << 16) | (b[1] << 8) | b[2]
    return golay23127_decode(code >> 1)


# ========== CRC-16 CCITT (CRCenc.cpp::checkCCITT162) ==========


def _build_ccitt_table() -> list[int]:
    table = []
    for i in range(256):
        crc = i << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
        table.append(crc & 0xFFFF)
    return table


_CCITT16_TABLE = _build_ccitt_table()


def crc_ccitt162(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc = ((crc << 8) & 0xFFFF) ^ _CCITT16_TABLE[(crc >> 8) ^ byte]
    return (~crc) & 0xFFFF


def check_ccitt162(buf: bytes) -> bool:
    """CRC over all but the last two bytes, stored big-endian in those two."""
    crc = crc_ccitt162(buf[:-2])
    return buf[-2] == (crc >> 8) and buf[-1] == (crc & 0xFF)


# ========== YSF rate-1/2, K=5 convolutional code (YSFConvolution.cpp) ==========

_BRANCH1 = (0, 0, 0, 0, 1, 1, 1, 1)
_BRANCH2 = (0, 1, 1, 0, 0, 1, 1, 0)
_K = 5
_M = 2


def viterbi_decode(symbol_pairs, n_bits: int) -> bytearray:
    """Hard-decision Viterbi decode of (s0, s1) pairs into n_bits MSB-first."""
    old = [0] * 16
    decisions = []
    for s0, s1 in symbol_pairs:
        new = [0] * 16
        d = 0
        for i in range(8):
            j = i * 2
            metric = (_BRANCH1[i] ^ s0) + (_BRANCH2[i] ^ s1)
            m0 = old[i] + metric
            m1 = old[i + 8] + (_M - metric)
            dec0 = 1 if m0 >= m1 else 0
            new[j] = m1 if dec0 else m0
            m0 = old[i] + (_M - metric)
            m1 = old[i + 8] + metric
            dec1 = 1 if m0 >= m1 else 0
            new[j + 1] = m1 if dec1 else m0
            d |= (dec1 << (j + 1)) | (dec0 << j)
        decisions.append(d)
        old = new

    out = bytearray((n_bits + 7) // 8)
    state = 0
    idx = len(decisions)
    n = n_bits
    while n > 0:
        n -= 1
        idx -= 1
        bit = (decisions[idx] >> (state >> (9 - _K))) & 1
        state = (bit << 7) | (state >> 1)
        if bit:
            out[n >> 3] |= 0x80 >> (n & 7)
    return out


def conv_encode(data: bytes, n_bits: int) -> bytearray:
    """Encoder counterpart, used only by tests to exercise the decoder."""
    out = bytearray((n_bits * 2 + 7) // 8)
    d1 = d2 = d3 = d4 = 0
    k = 0
    for i in range(n_bits):
        d = (data[i >> 3] >> (7 - (i & 7))) & 1
        g1 = (d + d3 + d4) & 1
        g2 = (d + d1 + d2 + d4) & 1
        d4, d3, d2, d1 = d3, d2, d1, d
        for g in (g1, g2):
            if g:
                out[k >> 3] |= 0x80 >> (k & 7)
            k += 1
    return out
