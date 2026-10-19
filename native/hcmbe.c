/*
 * hcmbe.c - thin decode-only wrapper around mbelib for hamcast.
 *
 * mbelib (ISC license, https://github.com/szechyjs/mbelib) is a clean-room
 * software implementation of the IMBE/AMBE voice codecs. Its API needs three
 * mbe_parms structs carried across frames, and Python's ctypes would otherwise
 * have to mirror that struct's layout. This shim owns the state instead, so
 * the Python side only ever passes bits in and gets 160 PCM samples out.
 *
 * Every decode call takes one 20 ms voice frame and writes 160 signed 16-bit
 * samples at 8 kHz.
 */
#include <stdlib.h>
#include "mbelib.h"

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

/* AMBE+2 3600x2450 (DMR, YSF V/D mode 2). ambe_d: 49 chars, one bit each,
 * already FEC-decoded. Returns mbelib's error count. */
int hc_decode_ambe2450(hc_state *s, char *ambe_d, short *pcm, int uvquality)
{
    int errs = 0, errs2 = 0;
    char err_str[64];
    mbe_processAmbe2450Data(pcm, &errs, &errs2, err_str, ambe_d,
                            &s->cur, &s->prev, &s->prev_enhanced, uvquality);
    return errs2;
}

/* AMBE 3600x2400 (D-Star). ambe_d: 49 chars, one bit each. */
int hc_decode_ambe2400(hc_state *s, char *ambe_d, short *pcm, int uvquality)
{
    int errs = 0, errs2 = 0;
    char err_str[64];
    mbe_processAmbe2400Data(pcm, &errs, &errs2, err_str, ambe_d,
                            &s->cur, &s->prev, &s->prev_enhanced, uvquality);
    return errs2;
}

/* IMBE 7200x4400 (YSF Voice FR / "VW", P25). imbe_d: 88 chars, one bit each. */
int hc_decode_imbe4400(hc_state *s, char *imbe_d, short *pcm, int uvquality)
{
    int errs = 0, errs2 = 0;
    char err_str[64];
    mbe_processImbe4400Data(pcm, &errs, &errs2, err_str, imbe_d,
                            &s->cur, &s->prev, &s->prev_enhanced, uvquality);
    return errs2;
}
