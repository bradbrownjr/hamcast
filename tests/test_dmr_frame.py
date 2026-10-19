import re
from pathlib import Path

from hamcast.bits import write_bit
from hamcast.dmr import frame as dmr
from hamcast.dmr.client import parse_voice, station_config

# MMDVMHost AMBEFEC.cpp: bit positions (within one 72-bit frame) of the
# a (24-bit Golay), b (23-bit Golay) and c (25-bit) words, MSB first.
DMR_A_TABLE = [0, 4, 8, 12, 16, 20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60, 64, 68, 1, 5, 9, 13, 17, 21]
DMR_B_TABLE = [25, 29, 33, 37, 41, 45, 49, 53, 57, 61, 65, 69, 2, 6, 10, 14, 18, 22, 26, 30, 34, 38, 42]
DMR_C_TABLE = [46, 50, 54, 58, 62, 66, 70, 3, 7, 11, 15, 19, 23, 27, 31, 35, 39, 43, 47, 51, 55, 59, 63, 67, 71]


def test_deinterleave_matches_mmdvmhost_golay_words():
    # a -> ambe_fr[0][23..0], b -> ambe_fr[1][22..0], c -> ambe_fr[2][10..0] + ambe_fr[3][13..0]
    expect = {}
    for k, n in enumerate(DMR_A_TABLE):
        expect[n] = 0 * 24 + (23 - k)
    for k, n in enumerate(DMR_B_TABLE):
        expect[n] = 1 * 24 + (22 - k)
    cells = [2 * 24 + (10 - k) for k in range(11)] + [3 * 24 + (13 - k) for k in range(14)]
    for k, n in enumerate(DMR_C_TABLE):
        expect[n] = cells[k]
    assert [expect[n] for n in range(72)] == dmr.AMBE_FR_INDEX


def test_burst_frames_skip_the_middle_sync_field():
    burst = bytearray(33)
    for n in range(108, 156):  # sync / embedded signalling only
        write_bit(burst, n, 1)
    assert all(not any(f) for f in dmr.decode_voice_burst(bytes(burst)))
    burst = bytearray(33)
    write_bit(burst, 156, 1)  # first AMBE bit after the sync field = frame 2, bit 36
    frames = dmr.decode_voice_burst(bytes(burst))
    assert frames[1][dmr.AMBE_FR_INDEX[36]] == 1 and sum(frames[1]) == 1


def test_parse_dmrd():
    data = (b"DMRD" + bytes([7]) + (3123446).to_bytes(3, "big") + (3123).to_bytes(3, "big")
            + bytes(4) + bytes([0x80 | 0x10]) + (0xABCDEF01).to_bytes(4, "big") + bytes(33) + bytes(2))
    pkt = parse_voice(data)
    assert (pkt.src, pkt.dst, pkt.slot, pkt.group, pkt.voice, pkt.stream_id) == (3123446, 3123, 2, True, True, 0xABCDEF01)


def test_station_config_is_294_bytes():
    assert len(station_config("KC1JMH", "hamcast 0.1.0", "https://example.org")) == 294


def test_dmr_plus_options_lists_static_talkgroups():
    from hamcast.stream import DmrStream, dmr_plus_options
    streams = [DmrStream("a", 8801), DmrStream("b", 3123)]
    assert dmr_plus_options(streams) == "StartRef=4000;RelinkTime=60;UserLink=0;TS2_1=3123;TS2_2=8801;"


def test_hotspot_ids_look_up_their_base_id():
    from hamcast.dmr.radioid import base_id
    assert base_id(312344699) == 3123446
    assert base_id(3123446) == 3123446
