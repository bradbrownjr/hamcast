import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
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
import { api, Heard, listenUrl, Status, StreamStatus } from '../api';
import Conversation, { heardKey } from '../components/Conversation';
import { useStatus } from '../components/useStatus';

// How many messages a card shows before "Show full conversation".
const COLLAPSED = 2;
const GAP = 16; // px between cards
const NARROWEST = 340; // px; below this a card wraps to the next row
const FEW_WIDTH = 480; // px; width of each card when there are only 1 or 2

// ========== CARD GRID ==========
// 3 or more nets: up to 4 per row, stretched to fill it. 1 or 2: a fixed
// width, centered. Every row is as tall as the tallest card, so all cards
// match. On a phone it is always one column.
function gridColumns(count: number) {
  if (count <= 2) {
    return { xs: '1fr', sm: `repeat(${count}, minmax(0, ${FEW_WIDTH}px))` };
  }
  const quarter = `calc((100% - ${3 * GAP}px) / 4)`;
  return `repeat(auto-fit, minmax(min(100%, max(${NARROWEST}px, ${quarter})), 1fr))`;
}

// ========== STATE CHIP ==========
function standbyHint(s: StreamStatus) {
  const parts = ['Not linked right now.'];
  if (s.on_listen) parts.push('Press play to link.');
  if (s.next_link) {
    const when = new Date(s.next_link * 1000).toLocaleString([], {
      weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
    });
    parts.push(`Next scheduled: ${when}.`);
  }
  return parts.join(' ');
}

function StateChip({ s }: { s: StreamStatus }) {
  if (!s.enabled) return <Chip size="small" label="Stopped" />;
  if (s.current) return <Chip size="small" color="error" icon={<MicIcon />} label="On air" />;
  // Shows for nets linked only when needed, while nothing needs them
  if (s.standby) {
    return (
      <Tooltip title={standbyHint(s)}>
        <Chip size="small" color="info" variant="outlined" label="Standby" tabIndex={0} />
      </Tooltip>
    );
  }
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
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardContent sx={{ height: '100%', display: 'flex', flexDirection: 'column', boxSizing: 'border-box' }}>
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
        {/* One line on cards so every card's player lines up; full text on hover and in the dialog */}
        <Typography variant="body2" color="text.secondary" noWrap title={s.description || s.source}>
          {s.description || s.source}
        </Typography>
        <Player s={s} status={status} />

        {/* Takes the spare height, so the button below sits at the bottom of every card */}
        <Box sx={{ flexGrow: 1 }}>
          {heard.length === 0 && !s.current ? (
            <Typography variant="body2" color="text.secondary" sx={{ mt: 1.5 }}>
              Nothing heard yet
            </Typography>
          ) : (
            <Box sx={{ mt: 1 }}>
              <Conversation heard={heard} current={s.current} streamId={s.id} last={COLLAPSED} />
            </Box>
          )}
        </Box>
        {/* Shows when there is more history than the card holds */}
        {heard.length > COLLAPSED && (
          <Button size="small" onClick={onExpand} sx={{ mt: 0.5, ml: -1, alignSelf: 'flex-start' }}>
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

  // ---------- History: live messages plus older pages from disk ----------
  // Everything seen while the dialog is open is kept, so nothing drops out
  // when the live list (the latest 50) moves on, and a transcript that
  // arrives later replaces the earlier copy of its message.
  const [seen, setSeen] = useState<Map<string, Heard>>(new Map());
  const [more, setMore] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [olderError, setOlderError] = useState<string | null>(null);
  const keepPlace = useRef<{ height: number; top: number } | null>(null);

  useEffect(() => {
    setSeen(new Map());
    setMore(true);
    setOlderError(null);
  }, [s?.id]);
  useEffect(() => {
    if (!s?.heard) return;
    setSeen((prev) => {
      const next = new Map(prev);
      for (const h of s.heard ?? []) next.set(heardKey(h), h);
      return next;
    });
  }, [s?.heard]);
  const conversation = useMemo(
    () => [...seen.values()].sort((a, b) => b.started - a.started), // newest first
    [seen],
  );

  const loadOlder = async () => {
    const oldest = conversation[conversation.length - 1];
    if (!s || !oldest) return;
    setLoadingOlder(true);
    try {
      const r = await api.history(s.id, oldest.started);
      const el = scroller.current;
      if (el) keepPlace.current = { height: el.scrollHeight, top: el.scrollTop };
      setSeen((prev) => {
        const next = new Map(prev);
        for (const h of r.heard) if (!next.has(heardKey(h))) next.set(heardKey(h), h);
        return next;
      });
      setMore(r.more);
      setOlderError(null);
    } catch (err) {
      setOlderError((err as Error).message);
    } finally {
      setLoadingOlder(false);
    }
  };
  // Older messages go in above; keep the reader on the message they were reading.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (el && keepPlace.current) {
      el.scrollTop = el.scrollHeight - keepPlace.current.height + keepPlace.current.top;
      keepPlace.current = null;
    }
  }, [conversation]);

  // Changes whenever a new transmission starts or ends.
  const newest = `${s?.heard?.[0] ? heardKey(s.heard[0]) : ''}|${s?.current?.started ?? ''}`;

  const toNewest = () => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  };
  // Keep the newest message in view as the conversation grows, unless the
  // reader has scrolled up into the history.
  useEffect(() => {
    if (following.current) toNewest();
  }, [newest]);
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
            {/* Shows once there is a conversation to page back through */}
            {conversation.length > 0 && (
              <Box sx={{ textAlign: 'center', pb: 1 }}>
                {more ? (
                  <Button size="small" onClick={loadOlder} disabled={loadingOlder}>
                    {loadingOlder ? 'Loading…' : 'Load older'}
                  </Button>
                ) : (
                  <Typography variant="caption" color="text.secondary">Start of the history</Typography>
                )}
                {olderError && <Alert severity="error" sx={{ mt: 1 }}>{olderError}</Alert>}
              </Box>
            )}
            {conversation.length === 0 && !s.current ? (
              <Typography variant="body2" color="text.secondary">Nothing heard yet</Typography>
            ) : (
              <Conversation heard={conversation} current={s.current} streamId={s.id} />
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
      <Box
        sx={{
          display: 'grid',
          gap: `${GAP}px`,
          gridTemplateColumns: gridColumns(status.streams.length),
          gridAutoRows: '1fr',
          justifyContent: 'center',
        }}
      >
        {status.streams.map((s) => (
          <NetCard key={s.id} s={s} status={status} onExpand={() => setExpanded(s.id)} />
        ))}
      </Box>
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
