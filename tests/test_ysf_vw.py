from hamcast.ysf import frame as ysf


def _frame_with_payload(payload: bytes) -> bytes:
    return bytes(ysf.SYNC_LEN + ysf.FICH_LEN) + payload


def test_vw_bit_mapping_is_a_permutation_into_imbe_fr():
    # 144 transmitted bits fill exactly the used cells of imbe_fr[8][23].
    used = {v * 23 + i for v, n in enumerate(ysf._VW_VECTOR_LENGTHS) for i in range(n)}
    assert sorted(ysf._VW_TO_IMBE_FR) == sorted(used)
    assert len(used) == 144


def test_vw_first_bit_of_each_vector_lands_at_its_top_index():
    assert ysf._VW_TO_IMBE_FR[0] == 22            # c0 first bit -> imbe_fr[0][22]
    assert ysf._VW_TO_IMBE_FR[23] == 23 + 22      # c1 first bit -> imbe_fr[1][22]
    assert ysf._VW_TO_IMBE_FR[92] == 4 * 23 + 14  # c4 first bit -> imbe_fr[4][14]
    assert ysf._VW_TO_IMBE_FR[137] == 7 * 23 + 6  # c7 first bit -> imbe_fr[7][6]


def test_vw_channel_count():
    frame = _frame_with_payload(bytes(range(90)))
    assert len(ysf.decode_vw_voice(frame, None)) == 5
    assert len(ysf.decode_vw_voice(frame, ysf.Fich(fi=1, fn=0, ft=0, dt=3))) == 5
    assert len(ysf.decode_vw_voice(frame, ysf.Fich(fi=1, fn=1, ft=1, dt=3))) == 5


def test_vw_first_frame_after_header_skips_its_data_half():
    # FN 0 / FT 1: payload bytes 0-53 are data; voice is channels 3 and 4 only.
    payload = bytes(54) + bytes([0xFF]) * 36
    first = ysf.decode_vw_voice(_frame_with_payload(payload), ysf.Fich(fi=1, fn=0, ft=1, dt=3))
    full = ysf.decode_vw_voice(_frame_with_payload(payload), None)
    assert first == full[3:]
