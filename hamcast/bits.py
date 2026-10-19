"""MSB-first bit access on byte buffers, matching the READ_BIT/WRITE_BIT macros
used throughout the MMDVM / DroidStar C++ code this project ports from."""


def read_bit(buf: bytes, i: int) -> int:
    return (buf[i >> 3] >> (7 - (i & 7))) & 1


def write_bit(buf: bytearray, i: int, bit: int) -> None:
    mask = 0x80 >> (i & 7)
    if bit:
        buf[i >> 3] |= mask
    else:
        buf[i >> 3] &= ~mask & 0xFF
