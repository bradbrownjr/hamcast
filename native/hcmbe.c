/*
 * hcmbe.c - thin decode-only wrapper around mbelib-neo for hamcast.
 *
 * mbelib-neo (GPL-2.0-or-later, https://github.com/arancormonk/mbelib-neo)
 * is a maintained mbelib fork: FFT unvoiced synthesis, regenerated voiced
 * phase and TIA-102.BABA frame repeat/mute handling. On a live YSF capture
 * it removed the full-scale pops stock mbelib produced and transcribed
 * better through Whisper, so it replaced stock mbelib.
 *
 * Its API needs three mbe_parms structs carried across frames, and Python's
 * ctypes would otherwise have to mirror that struct's layout. This shim owns
 * the state instead, so the Python side only passes bits in and gets 160
 * signed 16-bit samples (20 ms at 8 kHz) out. Each call returns the frame's
 * corrected-error total.
 */
#include <stdlib.h>
#include "mbelib-neo/mbelib.h"

typedef struct {
    mbe_parms cur;
    mbe_parms prev;
    mbe_parms prev_enhanced;
} hc_state;

hc_state *hc_new(void)
{
    hc_state *s = calloc(1, sizeof(hc_state));
    if (s)
        mbe_initMbeParms(&s->cur, &s->prev, &s->prev_enhanced);
    return s;
}

void hc_reset(hc_state *s)
{
    mbe_initMbeParms(&s->cur, &s->prev, &s->prev_enhanced);
}

void hc_free(hc_state *s)
{
    free(s);
}

/* AMBE+2 3600x2450 (DMR, YSF V/D mode 2). ambe_d: 49 FEC-decoded bits, one per char. */
int hc_decode_ambe2450(hc_state *s, const char *ambe_d, short *pcm)
{
    mbe_process_result r;
    mbe_initProcessResult(&r);
    return mbe_processAmbe2450Data(pcm, &r, ambe_d, &s->cur, &s->prev, &s->prev_enhanced);
}

/* AMBE 3600x2400 (D-STAR). ambe_d: 49 FEC-decoded bits, one per char. */
int hc_decode_ambe2400(hc_state *s, const char *ambe_d, short *pcm)
{
    mbe_process_result r;
    mbe_initProcessResult(&r);
    return mbe_processAmbe2400Data(pcm, &r, ambe_d, &s->cur, &s->prev, &s->prev_enhanced);
}

/* IMBE 7200x4400 (YSF Voice FR / "VW", P25 phase 1). imbe_fr: the raw
 * 144-bit frame as imbe_fr[8][23], one bit per char, still FEC-coded and
 * PN-whitened; the library corrects and de-whitens it and uses the error
 * count to repeat or mute a damaged frame. */
int hc_decode_imbe7200x4400(hc_state *s, const char *imbe_fr, short *pcm)
{
    mbe_process_result r;
    char imbe_d[88];
    mbe_initProcessResult(&r);
    return mbe_processImbe7200x4400Frame(pcm, &r, (const char (*)[23])imbe_fr, imbe_d,
                                         &s->cur, &s->prev, &s->prev_enhanced);
}
