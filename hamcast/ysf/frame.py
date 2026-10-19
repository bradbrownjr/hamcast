"""YSF (System Fusion) air-frame decoding: FICH, V/D mode 2 ("DN") voice and
Voice FR ("VW") voice.

Ported from DroidStar's ysf.cpp / YSFFICH.cpp (GPL, Doug McLain AD8DP, based
on MMDVM by Jonathan Naylor G4KLX). A YSF frame is 120 bytes: 5 sync bytes,
25 FICH bytes, then 90 bytes of payload carrying five 20 ms voice frames.
"""

from dataclasses import dataclass

from ..bits import read_bit, write_bit
from ..fec import check_ccitt162, golay24128_decode_bytes, viterbi_decode

SYNC_LEN = 5
FICH_LEN = 25
FRAME_LEN = 120

# FICH frame indicator
FI_HEADER = 0
FI_COMMUNICATIONS = 1
FI_TERMINATOR = 2

# FICH data type
DT_VD_MODE1 = 0
DT_DATA_FR = 1
DT_VD_MODE2 = 2  # "DN": AMBE+2, what DMR cross-mode traffic arrives as
DT_VOICE_FR = 3  # "VW": IMBE

_FICH_INTERLEAVE = [
    0, 40, 80, 120, 160, 2, 42, 82, 122, 162, 4, 44, 84, 124, 164,
    6, 46, 86, 126, 166, 8, 48, 88, 128, 168, 10, 50, 90, 130, 170,
    12, 52, 92, 132, 172, 14, 54, 94, 134, 174, 16, 56, 96, 136, 176,
    18, 58, 98, 138, 178, 20, 60, 100, 140, 180, 22, 62, 102, 142, 182,
    24, 64, 104, 144, 184, 26, 66, 106, 146, 186, 28, 68, 108, 148, 188,
    30, 70, 110, 150, 190, 32, 72, 112, 152, 192, 34, 74, 114, 154, 194,
    36, 76, 116, 156, 196, 38, 78, 118, 158, 198,
]

_INTERLEAVE_26_4 = [r + 4 * c for r in range(4) for c in range(26)]

_WHITENING = bytes([
    0x93, 0xD7, 0x51, 0x21, 0x9C, 0x2F, 0x6C, 0xD0, 0xEF, 0x0F,
    0xF8, 0x3D, 0xF1, 0x73, 0x20, 0x94, 0xED, 0x1E, 0x7C, 0xD8,
])

_IMBE_INTERLEAVE = [
    0, 7, 12, 19, 24, 31, 36, 43, 48, 55, 60, 67, 72, 79, 84, 91, 96, 103, 108, 115, 120, 127, 132, 139,
    1, 6, 13, 18, 25, 30, 37, 42, 49, 54, 61, 66, 73, 78, 85, 90, 97, 102, 109, 114, 121, 126, 133, 138,
    2, 9, 14, 21, 26, 33, 38, 45, 50, 57, 62, 69, 74, 81, 86, 93, 98, 105, 110, 117, 122, 129, 134, 141,
    3, 8, 15, 20, 27, 32, 39, 44, 51, 56, 63, 68, 75, 80, 87, 92, 99, 104, 111, 116, 123, 128, 135, 140,
    4, 11, 16, 23, 28, 35, 40, 47, 52, 59, 64, 71, 76, 83, 88, 95, 100, 107, 112, 119, 124, 131, 136, 143,
    5, 10, 17, 22, 29, 34, 41, 46, 53, 58, 65, 70, 77, 82, 89, 94, 101, 106, 113, 118, 125, 130, 137, 142,
]

# The 144 de-interleaved VW bits in transmission order are c0-c3 (Golay 23
# bits each), c4-c6 (Hamming 15 bits each) and c7 (7 uncoded bits). mbelib
# wants them as imbe_fr[8][23] with each vector's first bit at its highest
# index (imbe7200x4400.c::mbe_eccImbe7200x4400Data).
_VW_VECTOR_LENGTHS = (23, 23, 23, 23, 15, 15, 15, 7)
_VW_TO_IMBE_FR = [0] * 144
_n = 0
for _v, _length in enumerate(_VW_VECTOR_LENGTHS):
    for _k in range(_length):
        _VW_TO_IMBE_FR[_n] = _v * 23 + (_length - 1 - _k)
        _n += 1
del _n, _v, _length, _k


@dataclass
class Fich:
    fi: int  # frame indicator
    fn: int  # frame number within the superframe
    ft: int  # frame total
    dt: int  # data type


def decode_fich(frame: bytes) -> Fich | None:
    """Viterbi + Golay + CRC decode of the FICH; None when the CRC fails."""
    body = frame[SYNC_LEN:]
    pairs = []
    for n in _FICH_INTERLEAVE:
        pairs.append((read_bit(body, n), read_bit(body, n + 1)))
    out = viterbi_decode(pairs, 96)
    b0 = golay24128_decode_bytes(out[0:3])
    b1 = golay24128_decode_bytes(out[3:6])
    b2 = golay24128_decode_bytes(out[6:9])
    b3 = golay24128_decode_bytes(out[9:12])
    fich = bytes([
        (b0 >> 4) & 0xFF,
        ((b0 << 4) & 0xF0) | ((b1 >> 8) & 0x0F),
        b1 & 0xFF,
        (b2 >> 4) & 0xFF,
        ((b2 << 4) & 0xF0) | ((b3 >> 8) & 0x0F),
        b3 & 0xFF,
    ])
    if not check_ccitt162(fich):
        return None
    return Fich(
        fi=(fich[0] >> 6) & 0x03,
        fn=(fich[1] >> 3) & 0x07,
        ft=fich[1] & 0x07,
        dt=fich[2] & 0x03,
    )


def _majority(a: int, b: int, c: int) -> int:
    return 1 if a + b + c >= 2 else 0


def decode_vd2_voice(frame: bytes) -> list[bytes]:
    """Five AMBE+2 frames from a V/D mode 2 frame, each as 49 one-bit bytes.

    DroidStar takes only the middle bit of each 3x repetition triplet; a
    majority vote is used here instead, which is identical on clean network
    frames and better on any that picked up RF errors before the gateway.
    """
    data = frame[SYNC_LEN + FICH_LEN:]
    voices = []
    offset = 40  # skip DCH(0)
    for _ in range(5):
        vch = bytearray(13)
        for i, n in enumerate(_INTERLEAVE_26_4):
            write_bit(vch, i, read_bit(data, offset + n))
        for i in range(13):
            vch[i] ^= _WHITENING[i]

        bits = []
        # 27 repetition-coded bits (a: 12, b: 12, c: 3) then 22 uncoded bits.
        for i in range(27):
            bits.append(_majority(read_bit(vch, 3 * i), read_bit(vch, 3 * i + 1), read_bit(vch, 3 * i + 2)))
        for i in range(22):
            bits.append(read_bit(vch, 81 + i))
        voices.append(bytes(bits))
        offset += 144
    return voices


def decode_vw_voice(frame: bytes, fich: "Fich | None") -> list[bytes]:
    """Raw IMBE 7200x4400 frames from a Voice FR frame, each laid out as
    mbelib's imbe_fr[8][23] (184 one-bit bytes). FEC and de-whitening are
    left to mbelib so it knows how damaged each frame was.

    Normally five. The first frame after the header (FN 0, FT 1) carries 45
    bytes of data in its first half and only two voice channels, at payload
    offsets 54 and 72 (MMDVMHost YSFControl.cpp, "the first packet after the
    header is odd", and YSFPayload.cpp::processVoiceFRModeAudio2)."""
    data = frame[SYNC_LEN + FICH_LEN:]
    first = 3 if fich is not None and fich.fn == 0 and fich.ft == 1 else 0
    voices = []
    for j in range(first, 5):
        vch = data[j * 18:(j + 1) * 18]
        fr = bytearray(8 * 23)
        for i, n in enumerate(_IMBE_INTERLEAVE):
            fr[_VW_TO_IMBE_FR[i]] = read_bit(vch, n)
        voices.append(bytes(fr))
    return voices
