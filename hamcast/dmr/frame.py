"""DMR voice burst decoding: 33-byte burst -> three AMBE+2 frames.

A voice burst is 264 bits: 108 bits of AMBE, 48 bits of sync or embedded
signalling, then 108 more bits of AMBE. The three 72-bit AMBE frames are
bits 0-71, bits 72-107 + 156-191, and bits 192-263 (MMDVMHost
AMBEFEC.cpp::regenerateDMR).

Each 72-bit frame is still interleaved, FEC-coded and whitened. It is
deinterleaved here into mbelib-neo's ambe_fr[4][24] layout, and the library
does the Golay correction and de-whitening so it knows how damaged the frame
was. The deinterleave schedule is DSD's (ISC license, include/dmr_const.h,
as carried in mbelib-neo tools/quality/mbe_quality_dvsi.c): interleaved bit
2i lands at [ROW_HIGH[i]][COL_HIGH[i]] and bit 2i+1 at
[ROW_LOW[i]][COL_LOW[i]]. tests/test_dmr_frame.py checks it against
MMDVMHost's DMR_A/B/C_TABLE.
"""

from ..bits import read_bit

BURST_BYTES = 33

_ROW_HIGH = (0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1,
             0, 1, 0, 1, 0, 2, 0, 2, 0, 2, 0, 2, 0, 2, 0, 2, 0, 2)
_COL_HIGH = (23, 10, 22, 9, 21, 8, 20, 7, 19, 6, 18, 5, 17, 4, 16, 3, 15, 2,
             14, 1, 13, 0, 12, 10, 11, 9, 10, 8, 9, 7, 8, 6, 7, 5, 6, 4)
_ROW_LOW = (0, 2, 0, 2, 0, 2, 0, 2, 0, 3, 0, 3, 1, 3, 1, 3, 1, 3,
            1, 3, 1, 3, 1, 3, 1, 3, 1, 3, 1, 3, 1, 3, 1, 3, 1, 3)
_COL_LOW = (5, 3, 4, 2, 3, 1, 2, 0, 1, 13, 0, 12, 22, 11, 21, 10, 20, 9,
            19, 8, 18, 7, 17, 6, 16, 5, 15, 4, 14, 3, 13, 2, 12, 1, 11, 0)

# Interleaved bit n (0-71) -> flat index into ambe_fr[4][24].
AMBE_FR_INDEX = [0] * 72
for _i in range(36):
    AMBE_FR_INDEX[2 * _i] = _ROW_HIGH[_i] * 24 + _COL_HIGH[_i]
    AMBE_FR_INDEX[2 * _i + 1] = _ROW_LOW[_i] * 24 + _COL_LOW[_i]
del _i


def _burst_bit(n: int) -> int:
    """Position in the 264-bit burst of AMBE bit n (0-215), skipping the
    48-bit sync/embedded field in the middle."""
    return n + 48 if n >= 108 else n


def decode_voice_burst(burst: bytes) -> list[bytes]:
    """Three AMBE+2 frames from a 33-byte voice burst, each laid out as
    ambe_fr[4][24] (96 one-bit bytes)."""
    frames = []
    for f in range(3):
        fr = bytearray(96)
        for n in range(72):
            fr[AMBE_FR_INDEX[n]] = read_bit(burst, _burst_bit(72 * f + n))
        frames.append(bytes(fr))
    return frames
