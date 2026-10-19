import { useEffect, useRef, useState } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import Grid from '@mui/material/Grid';
import IconButton from '@mui/material/IconButton';
import Stack from '@mui/material/Stack';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import useMediaQuery from '@mui/material/useMediaQuery';
import { useTheme } from '@mui/material/styles';
import CloseIcon from '@mui/icons-material/Close';
import HeadphonesIcon from '@mui/icons-material/Headphones';
import MicIcon from '@mui/icons-material/Mic';
import OpenInFullIcon from '@mui/icons-material/OpenInFull';
import { listenUrl, Status, StreamStatus } from '../api';
import Conversation from '../components/Conversation';
import { useStatus } from '../components/useStatus';

// How many messages a card shows before "Show full conversation".
const COLLAPSED = 2;

// ========== STATE CHIP ==========
function StateChip({ s }: { s: StreamStatus }) {
  if (!s.enabled) return <Chip size="small" label="Stopped" />;
  if (s.current) return <Chip size="small" color="error" icon={<MicIcon />} label="On air" />;
  if (s.linked) return <Chip size="small" color="primary" label="Linked" />;
  return <Chip size="small" color="warning" variant="outlined" label="Connecting" />;
}

// ========== LIVE PLAYER ==========
function Player({ s, status }: { s: StreamStatus; status: Status }) {
  const url = listenUrl(s, status);
  if (!s.enabled || !url) return null;
  return (
    <Box sx={{ mt: 1.5 }}>
      <audio controls preload="none" src={url} style={{ width: '100%' }} />
      <Stack direction="row" spacing={1} sx={{ alignItems: 'center', color: 'text.secondary', minWidth: 0 }}>
        <HeadphonesIcon fontSize="small" />
        <Typography variant="caption" noWrap>
          {s.listeners ?? 0} listening · <a href={url} style={{ color: 'inherit' }}>{url}</a>
        </Typography>
      </Stack>
    </Box>
  );
}

// ========== NET CARD (collapsed conversation) ==========
function NetCard({ s, status, onExpand }: { s: StreamStatus; status: Status; onExpand: () => void }) {
  const heard = s.heard ?? [];
  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
          <Typography variant="h6" component="h2" sx={{ flexGrow: 1, minWidth: 0 }} noWrap>
            {s.name}
          </Typography>
          <StateChip s={s} />
          <Tooltip title="Full conversation">
            <IconButton size="small" aria-label={`Full conversation for ${s.name}`} onClick={onExpand}>
              <OpenInFullIcon fontSize="small" />
            </IconButton>
          </Tooltip>
        </Stack>
        <Typography variant="body2" color="text.secondary">
          {s.description || s.source}
        </Typography>
        <Player s={s} status={status} />

        {heard.length === 0 && !s.current ? (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
            Nothing heard yet
          </Typography>
        ) : (
          <Box sx={{ mt: 1 }}>
            <Conversation heard={heard} current={s.current} streamId={s.id} last={COLLAPSED} />
          </Box>
        )}
        {/* Shows when there is more history than the card holds */}
        {heard.length > COLLAPSED && (
          <Button size="small" onClick={onExpand} sx={{ mt: 0.5, ml: -1 }}>
            Show full conversation ({heard.length})
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

// ========== FULL CONVERSATION DIALOG ==========
// Reads the net from the live status, so it keeps updating while open.
function ConversationDialog({ s, status, onClose }: { s: StreamStatus | null; status: Status; onClose: () => void }) {
  const fullScreen = useMediaQuery(useTheme().breakpoints.down('sm'));
  const scroller = useRef<HTMLDivElement | null>(null);
  const following = useRef(true); // false while the reader has scrolled up
  const count = (s?.heard?.length ?? 0) + (s?.current ? 1 : 0);

  const toNewest = () => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  };
  // Keep the newest message in view as the conversation grows, unless the
  // reader has scrolled up into the history.
  useEffect(() => {
    if (following.current) toNewest();
  }, [count]);
  const onScroll = () => {
    const el = scroller.current;
    if (el) following.current = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
  };

  return (
    <Dialog
      open={!!s}
      onClose={onClose}
      fullScreen={fullScreen}
      maxWidth="md"
      fullWidth
      // Open at the newest message; before the transition ends there is nothing to scroll yet.
      slotProps={{ transition: { onEnter: () => { following.current = true; }, onEntered: toNewest } }}
    >
      {s && (
        <>
          <DialogTitle component="div">
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center' }}>
              <Typography variant="h6" component="h2" sx={{ flexGrow: 1, minWidth: 0 }} noWrap>
                {s.name}
              </Typography>
              <StateChip s={s} />
              <IconButton aria-label="Close" onClick={onClose}>
                <CloseIcon />
              </IconButton>
            </Stack>
            <Typography variant="body2" color="text.secondary">
              {s.description || s.source}
            </Typography>
            <Player s={s} status={status} />
          </DialogTitle>
          <DialogContent dividers ref={scroller} onScroll={onScroll}>
            {(s.heard ?? []).length === 0 && !s.current ? (
              <Typography variant="body2" color="text.secondary">Nothing heard yet</Typography>
            ) : (
              <Conversation heard={s.heard ?? []} current={s.current} streamId={s.id} />
            )}
          </DialogContent>
        </>
      )}
    </Dialog>
  );
}

export default function Listen() {
  const { status, error } = useStatus();
  const [expanded, setExpanded] = useState<string | null>(null);

  if (!status) {
    return error ? <Alert severity="error">{error}</Alert> : <CircularProgress />;
  }
  if (status.streams.length === 0) {
    return <Alert severity="info">No nets yet. Add one on the Manage page.</Alert>;
  }
  return (
    <>
      {error && <Alert severity="warning" sx={{ mb: 2 }}>Lost contact with hamcast: {error}</Alert>}
      {/* Cards keep their own height, so a quiet net doesn't stretch to match a busy one */}
      <Grid container spacing={2} sx={{ alignItems: 'flex-start' }}>
        {status.streams.map((s) => (
          <Grid key={s.id} size={{ xs: 12, sm: 6, lg: 4, xl: 3 }}>
            <NetCard s={s} status={status} onExpand={() => setExpanded(s.id)} />
          </Grid>
        ))}
      </Grid>
      {status.transcribing != null && status.transcribing > 0 && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2 }}>
          Transcribing {status.transcribing} transmission{status.transcribing === 1 ? '' : 's'}…
        </Typography>
      )}
      <ConversationDialog
        s={status.streams.find((x) => x.id === expanded) ?? null}
        status={status}
        onClose={() => setExpanded(null)}
      />
    </>
  );
}
