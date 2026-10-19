import { useEffect, useRef, useState } from 'react';
import Box from '@mui/material/Box';
import CircularProgress from '@mui/material/CircularProgress';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import MicIcon from '@mui/icons-material/Mic';
import PauseIcon from '@mui/icons-material/Pause';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import { Heard } from '../api';

function clock(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// ========== RECORDING PLAY BUTTON ==========
// A small play/pause button instead of a full player per row, so a
// collapsed card stays short. The audio loads on first play.
function PlayButton({ src, label }: { src: string; label: string }) {
  const audio = useRef<HTMLAudioElement | null>(null);
  const [playing, setPlaying] = useState(false);

  useEffect(() => () => audio.current?.pause(), []);

  const toggle = () => {
    if (!audio.current) {
      audio.current = new Audio(src);
      audio.current.onended = () => setPlaying(false);
      audio.current.onpause = () => setPlaying(false);
      audio.current.onplay = () => setPlaying(true);
    }
    if (audio.current.paused) void audio.current.play();
    else audio.current.pause();
  };

  return (
    <IconButton size="small" onClick={toggle} aria-label={`${playing ? 'Pause' : 'Play'} ${label}`}>
      {playing ? <PauseIcon fontSize="small" /> : <PlayArrowIcon fontSize="small" />}
    </IconButton>
  );
}

// ========== TRANSCRIPT OR ITS STATUS ==========
function TranscriptLine({ h }: { h: Heard }) {
  if (h.transcript) {
    return <Typography variant="body2">{h.transcript}</Typography>;
  }
  const muted = (text: string) => (
    <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic' }}>{text}</Typography>
  );
  switch (h.transcript_status) {
    case 'queued':
      return muted('Waiting to transcribe');
    case 'transcribing':
      return (
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          <CircularProgress size={12} />
          {muted('Transcribing…')}
        </Stack>
      );
    case 'no_speech':
      return muted('No speech recognized');
    case 'too_short':
      return muted('Too short to transcribe');
    case 'failed':
      return <Typography variant="body2" color="error" sx={{ fontStyle: 'italic' }}>Transcription failed</Typography>;
    default:
      return null; // not transcribed for this net
  }
}

function Message({ h, streamId }: { h: Heard; streamId: string }) {
  const via = h.gateway && h.gateway !== h.talker ? ` via ${h.gateway}` : '';
  return (
    <Box sx={{ py: 1, '& + &': { borderTop: 1, borderColor: 'divider' } }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
        <Typography variant="subtitle2" sx={{ flexGrow: 1, minWidth: 0 }} noWrap>
          {h.talker}
          <Typography component="span" variant="caption" color="text.secondary">{via}</Typography>
        </Typography>
        <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: 'nowrap' }}>
          {clock(h.started)} · {h.seconds}s
        </Typography>
        {h.recording && (
          <PlayButton src={`/recordings/${streamId}/${h.recording}`} label={`${h.talker} at ${clock(h.started)}`} />
        )}
      </Stack>
      <TranscriptLine h={h} />
    </Box>
  );
}

/** One key per transmission, the same whether it came live or from history. */
export function heardKey(h: Heard) {
  return h.id != null ? `id${h.id}` : `t${h.started}`;
}

// ========== CONVERSATION ==========
// Oldest first, like a chat. `last` limits it to the most recent few.
export default function Conversation({ heard, current, streamId, last }: {
  heard: Heard[]; // as the server sends it, newest first
  current: Heard | null | undefined;
  streamId: string;
  last?: number;
}) {
  const ordered = [...heard].reverse();
  const shown = last ? ordered.slice(-last) : ordered;
  return (
    <Box>
      {shown.map((h) => (
        <Message key={heardKey(h)} h={h} streamId={streamId} />
      ))}
      {/* Shows while a station is transmitting */}
      {current && (
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', py: 1, color: 'error.main' }}>
          <MicIcon fontSize="small" />
          <Typography variant="subtitle2">{current.talker}</Typography>
          <Typography variant="caption">transmitting…</Typography>
        </Stack>
      )}
    </Box>
  );
}
