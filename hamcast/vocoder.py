"""ctypes binding to libhcmbe.so (mbelib plus native/hcmbe.c).

One Vocoder per audio stream: mbelib carries synthesis state between frames,
so two streams sharing an instance would bleed into each other.
"""

import ctypes
import os
from pathlib import Path

SAMPLES_PER_FRAME = 160  # 20 ms at 8 kHz

# mbelib's unvoiced-synthesis quality, 1-64. DroidStar and DSD use 3.
UV_QUALITY = 3


def _load() -> ctypes.CDLL:
    candidates = [
        os.environ.get("HAMCAST_LIBHCMBE"),
        str(Path(__file__).resolve().parent.parent / "native" / "libhcmbe.so"),
        "/usr/local/lib/libhcmbe.so",
    ]
    for path in candidates:
        if path and Path(path).exists():
            lib = ctypes.CDLL(path)
            break
    else:
        raise OSError("libhcmbe.so not found; run native/build.sh or set HAMCAST_LIBHCMBE")

    lib.hc_new.restype = ctypes.c_void_p
    lib.hc_reset.argtypes = [ctypes.c_void_p]
    lib.hc_free.argtypes = [ctypes.c_void_p]
    for name in ("hc_decode_ambe2450", "hc_decode_ambe2400", "hc_decode_imbe4400"):
        fn = getattr(lib, name)
        fn.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_int]
        fn.restype = ctypes.c_int
    return lib


_lib = None


def _get_lib() -> ctypes.CDLL:
    global _lib
    if _lib is None:
        _lib = _load()
    return _lib


class Vocoder:
    def __init__(self) -> None:
        self._lib = _get_lib()
        self._state = self._lib.hc_new()
        self._pcm = (ctypes.c_short * SAMPLES_PER_FRAME)()

    def reset(self) -> None:
        """Call at the start of each transmission so it doesn't inherit the last one's state."""
        self._lib.hc_reset(self._state)

    def _run(self, fn, bits: bytes) -> bytes:
        fn(self._state, bits, self._pcm, UV_QUALITY)
        return bytes(self._pcm)

    def decode_ambe2450(self, bits49: bytes) -> bytes:
        """49 one-bit-per-byte values -> 320 bytes of s16le PCM."""
        return self._run(self._lib.hc_decode_ambe2450, bits49)

    def decode_ambe2400(self, bits49: bytes) -> bytes:
        return self._run(self._lib.hc_decode_ambe2400, bits49)

    def decode_imbe4400(self, bits88: bytes) -> bytes:
        return self._run(self._lib.hc_decode_imbe4400, bits88)

    def __del__(self) -> None:
        if getattr(self, "_state", None):
            self._lib.hc_free(self._state)
            self._state = None
