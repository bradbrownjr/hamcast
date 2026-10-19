import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Divider from '@mui/material/Divider';
import Grid from '@mui/material/Grid';
import List from '@mui/material/List';
import ListItem from '@mui/material/ListItem';
import ListItemText from '@mui/material/ListItemText';
import Stack from '@mui/material/Stack';
import Typography from '@mui/material/Typography';
import HeadphonesIcon from '@mui/icons-material/Headphones';
import MicIcon from '@mui/icons-material/Mic';
import { Heard, listenUrl, Status, StreamStatus } from '../api';
import { useStatus } from '../components/useStatus';

function clock(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

// ========== STATE CHIP ==========
function StateChip({ s }: { s: StreamStatus }) {
  if (!s.enabled) return <Chip size="small" label="Stopped" />;
  if (s.current) return <Chip size="small" color="error" icon={<MicIcon />} label="On air" />;
  if (s.linked) return <Chip size="small" color="primary" label="Linked" />;
  return <Chip size="small" color="warning" variant="outlined" label="Connecting" />;
}

// ========== RECENTLY HEARD ==========
function HeardRow({ h, streamId }: { h: Heard; streamId: string }) {
  const via = h.gateway ? ` via ${h.gateway}` : '';
  return (
    <ListItem disableGutters alignItems="flex-start" sx={{ display: 'block' }}>
      <ListItemText
        primary={`${h.talker}${via}`}
        secondary={`${clock(h.started)}  ${h.seconds}s`}
        slotProps={{ primary: { sx: { fontWeight: 500 } } }}
      />
      {h.transcript && (
        <Typography variant="body2" color="text.secondary" sx={{ fontStyle: 'italic', mb: 0.5 }}>
          "{h.transcript}"
        </Typography>
      )}
      {h.recording && (
        <audio
          controls
          preload="none"
          src={`/recordings/${streamId}/${h.recording}`}
          style={{ width: '100%', height: 32 }}
        />
      )}
    </ListItem>
  );
}

// ========== NET CARD ==========
function NetCard({ s, status }: { s: StreamStatus; status: Status }) {
  const url = listenUrl(s, status);
  const heard = (s.heard ?? []).slice(0, 10); // newest first
  return (
    <Card variant="outlined" sx={{ height: '100%' }}>
      <CardContent>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', mb: 0.5 }}>
          <Typography variant="h6" component="h2" sx={{ flexGrow: 1 }}>
            {s.name}
          </Typography>
          <StateChip s={s} />
        </Stack>
        <Typography variant="body2" color="text.secondary">
          {s.description || s.source}
        </Typography>

        {/* Shows the station transmitting right now */}
        {s.current && (
          <Alert severity="success" icon={<MicIcon />} sx={{ mt: 2 }}>
            {s.current.talker}
            {s.current.gateway ? ` via ${s.current.gateway}` : ''}
          </Alert>
        )}

        {s.enabled && url && (
          <Box sx={{ mt: 2 }}>
            <audio controls preload="none" src={url} style={{ width: '100%' }} />
            <Stack direction="row" spacing={1} sx={{ alignItems: 'center', color: 'text.secondary' }}>
              <HeadphonesIcon fontSize="small" />
              <Typography variant="caption">
                {s.listeners ?? 0} listening · <a href={url} style={{ color: 'inherit' }}>{url}</a>
              </Typography>
            </Stack>
          </Box>
        )}

        {heard.length > 0 && (
          <>
            <Divider sx={{ my: 2 }} />
            <Typography variant="subtitle2" gutterBottom>
              Recently heard
            </Typography>
            <List dense disablePadding>
              {heard.map((h) => (
                <HeardRow key={`${h.talker}-${h.started}`} h={h} streamId={s.id} />
              ))}
            </List>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export default function Listen() {
  const { status, error } = useStatus();

  if (!status) {
    return error ? <Alert severity="error">{error}</Alert> : <CircularProgress />;
  }
  if (status.streams.length === 0) {
    return <Alert severity="info">No nets yet. Add one on the Manage page.</Alert>;
  }
  return (
    <>
      {error && <Alert severity="warning" sx={{ mb: 2 }}>Lost contact with hamcast: {error}</Alert>}
      <Grid container spacing={2}>
        {status.streams.map((s) => (
          <Grid key={s.id} size={{ xs: 12, md: 6 }}>
            <NetCard s={s} status={status} />
          </Grid>
        ))}
      </Grid>
      {status.transcribing != null && status.transcribing > 0 && (
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2 }}>
          Transcribing {status.transcribing} transmission{status.transcribing === 1 ? '' : 's'}…
        </Typography>
      )}
    </>
  );
}
