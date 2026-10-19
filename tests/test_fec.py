import random

from hamcast.bits import read_bit, write_bit
from hamcast.fec import (
    check_ccitt162,
    conv_encode,
    crc_ccitt162,
    golay24128_decode_bytes,
    golay24128_encode,
    viterbi_decode,
)
from hamcast.ysf import frame as ysf


def test_ccitt_table_matches_droidstar():
    # First entries of CCITT16_TABLE2 in DroidStar CRCenc.cpp.
    from hamcast.fec import _CCITT16_TABLE
    assert _CCITT16_TABLE[:8] == [0x0000, 0x1021, 0x2042, 0x3063, 0x4084, 0x50A5, 0x60C6, 0x70E7]
    assert _CCITT16_TABLE[16:20] == [0x1231, 0x0210, 0x3273, 0x2252]


def test_golay_corrects_up_to_three_errors():
    rng = random.Random(1)
    for _ in range(500):
        data = rng.getrandbits(12)
        code = golay24128_encode(data)
        for bit in rng.sample(range(1, 24), rng.randint(0, 3)):  # bit 0 is parity, ignored by decode
            code ^= 1 << bit
        assert golay24128_decode_bytes(code.to_bytes(3, "big")) == data


def test_viterbi_round_trip_with_errors():
    rng = random.Random(2)
    for _ in range(50):
        data = bytearray(rng.getrandbits(8) for _ in range(12)) + b"\x00"  # 96 bits + 4 tail
        enc = conv_encode(data, 100)
        for pos in rng.sample(range(200), 3):
            enc[pos >> 3] ^= 0x80 >> (pos & 7)
        pairs = [(read_bit(enc, 2 * i), read_bit(enc, 2 * i + 1)) for i in range(100)]
        assert viterbi_decode(pairs, 96)[:12] == data[:12]


def _encode_fich(fi: int, fn: int, ft: int, dt: int) -> bytes:
    """Build a 120-byte frame with a valid FICH, mirroring YSFFICH.cpp::encode."""
    fich = bytearray(6)
    fich[0] = (fi << 6)
    fich[1] = (fn << 3) | ft
    fich[2] = dt
    crc = crc_ccitt162(fich[:4])
    fich[4], fich[5] = crc >> 8, crc & 0xFF
    assert check_ccitt162(bytes(fich))
    b = [((fich[0] << 4) & 0xFF0) | (fich[1] >> 4), ((fich[1] << 8) & 0xF00) | fich[2],
         ((fich[3] << 4) & 0xFF0) | (fich[4] >> 4), ((fich[4] << 8) & 0xF00) | fich[5]]
    conv = bytearray()
    for word in b:
        conv += golay24128_encode(word).to_bytes(3, "big")
    conv += b"\x00"
    convolved = conv_encode(conv, 100)
    frame = bytearray(ysf.FRAME_LEN)
    body = bytearray(ysf.FRAME_LEN - ysf.SYNC_LEN)
    j = 0
    for n in ysf._FICH_INTERLEAVE:
        write_bit(body, n, read_bit(convolved, j))
        write_bit(body, n + 1, read_bit(convolved, j + 1))
        j += 2
    frame[ysf.SYNC_LEN:] = body
    return bytes(frame)


def test_fich_round_trip():
    for fi, fn, ft, dt in [(0, 0, 7, 2), (1, 3, 7, 2), (2, 7, 7, 3), (1, 5, 6, 0)]:
        f = ysf.decode_fich(_encode_fich(fi, fn, ft, dt))
        assert f is not None
        assert (f.fi, f.fn, f.ft, f.dt) == (fi, fn, ft, dt)


def test_fich_rejects_garbage():
    rng = random.Random(3)
    bad = sum(ysf.decode_fich(bytes(rng.getrandbits(8) for _ in range(120))) is None for _ in range(50))
    assert bad >= 49
