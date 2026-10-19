import { useCallback, useEffect, useState } from 'react';
import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardActions from '@mui/material/CardActions';
import CardContent from '@mui/material/CardContent';
import Chip from '@mui/material/Chip';
import CircularProgress from '@mui/material/CircularProgress';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogContentText from '@mui/material/DialogContentText';
import DialogTitle from '@mui/material/DialogTitle';
import Fab from '@mui/material/Fab';
import FormControlLabel from '@mui/material/FormControlLabel';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableRow from '@mui/material/TableRow';
import Typography from '@mui/material/Typography';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import EditIcon from '@mui/icons-material/Edit';
import LogoutIcon from '@mui/icons-material/Logout';
import { api, ApiError, Settings, StreamConfig } from '../api';
import LoginForm from '../components/LoginForm';
import StreamDialog from '../components/StreamDialog';

function source(s: StreamConfig) {
  return `${s.type.toUpperCase()} ${s.host}:${s.port}` + (s.type === 'dmr' ? ` · TG ${s.talkgroup}` : '');
}

// ========== NET CARD (manage) ==========
function NetRow({ s, onEdit, onDelete, onToggle }: {
  s: StreamConfig;
  onEdit: () => void;
  onDelete: () => void;
  onToggle: (enabled: boolean) => void;
}) {
  return (
    <Card variant="outlined">
      <CardContent sx={{ pb: 1 }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: 'center', flexWrap: 'wrap' }}>
          <Typography variant="h6" component="h3" sx={{ flexGrow: 1 }}>
            {s.name}
          </Typography>
          <Chip size="small" variant="outlined" label={s.mount} />
          {s.record && <Chip size="small" variant="outlined" label={s.transcribe ? 'Records + transcribes' : 'Records'} />}
        </Stack>
        <Typography variant="body2" color="text.secondary">
          {source(s)}
        </Typography>
      </CardContent>
      <CardActions disableSpacing sx={{ justifyContent: 'space-between', flexWrap: 'wrap', px: 2 }}>
        <FormControlLabel
          control={<Switch checked={s.enabled} onChange={(e) => onToggle(e.target.checked)} />}
          label={s.enabled ? 'Running' : 'Stopped'}
        />
        <Stack direction="row" spacing={1}>
          <Button color="error" startIcon={<DeleteIcon />} onClick={onDelete}>
            Delete
          </Button>
          <Button startIcon={<EditIcon />} onClick={onEdit}>
            Edit
          </Button>
        </Stack>
      </CardActions>
    </Card>
  );
}

// ========== SETTINGS (read-only) ==========
function SettingsCard({ settings }: { settings: Settings }) {
  const rows: [string, string][] = [
    ['Callsign', settings.callsign],
    ['DMR ID', settings.dmr_id ? String(settings.dmr_id) : 'not set (needed for DMR)'],
    ['Icecast', settings.icecast.bundled ? `built in, port ${settings.icecast.port}` : 'external'],
    ['Listener URL', settings.icecast.public_url ?? 'this host'],
    ['Bitrate', settings.icecast.bitrate],
    ['Transcription', settings.transcription.enabled
      ? `${settings.transcription.backend}, ${settings.transcription.model}`
      : 'off'],
  ];
  return (
    <Card variant="outlined">
      <CardContent>
        <Typography variant="h6" component="h2" gutterBottom>
          Settings
        </Typography>
        <Table size="small">
          <TableBody>
            {rows.map(([k, v]) => (
              <TableRow key={k}>
                <TableCell component="th" sx={{ fontWeight: 500, width: '40%' }}>{k}</TableCell>
                <TableCell sx={{ wordBreak: 'break-all' }}>{v}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 1 }}>
          These come from hamcast's environment variables (the Docker or Unraid template) and need a restart to change.
        </Typography>
      </CardContent>
    </Card>
  );
}

export default function Manage() {
  const [admin, setAdmin] = useState<boolean | null>(null);
  const [streams, setStreams] = useState<StreamConfig[]>([]);
  const [dmrId, setDmrId] = useState<number | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialog, setDialog] = useState<{ open: boolean; editing: StreamConfig | null }>({ open: false, editing: null });
  const [deleting, setDeleting] = useState<StreamConfig | null>(null);

  const handle = (err: unknown) => {
    if (err instanceof ApiError && err.status === 401) setAdmin(false);
    else setError((err as Error).message);
  };

  const load = useCallback(async () => {
    try {
      const [r, st] = await Promise.all([api.streams(), api.settings()]);
      setStreams(r.streams);
      setDmrId(r.dmr_id);
      setSettings(st);
      setAdmin(true);
      setError(null);
    } catch (err) {
      handle(err);
    }
  }, []);

  useEffect(() => {
    api.me().then((m) => (m.admin ? load() : setAdmin(false)), handle);
  }, [load]);

  const toggle = async (s: StreamConfig, enabled: boolean) => {
    try {
      await api.updateStream(s.id, { ...s, enabled });
      await load();
    } catch (err) {
      handle(err);
    }
  };

  const remove = async () => {
    if (!deleting) return;
    try {
      await api.deleteStream(deleting.id);
      setDeleting(null);
      await load();
    } catch (err) {
      handle(err);
    }
  };

  if (admin === null) return <CircularProgress />;
  if (!admin) return <LoginForm onSignedIn={load} />;

  return (
    <Stack spacing={3} sx={{ pb: 10 }}>
      <Stack direction="row" sx={{ alignItems: 'center' }}>
        <Typography variant="h5" component="h2" sx={{ flexGrow: 1 }}>
          Nets
        </Typography>
        <Button
          startIcon={<LogoutIcon />}
          onClick={() => api.logout().then(() => setAdmin(false))}
        >
          Sign out
        </Button>
      </Stack>
      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
      {streams.length === 0 && <Alert severity="info">No nets yet. Add one with the + button.</Alert>}
      {streams.map((s) => (
        <NetRow
          key={s.id}
          s={s}
          onEdit={() => setDialog({ open: true, editing: s })}
          onDelete={() => setDeleting(s)}
          onToggle={(enabled) => toggle(s, enabled)}
        />
      ))}
      {settings && <SettingsCard settings={settings} />}

      <Fab
        color="primary"
        aria-label="Add a net"
        onClick={() => setDialog({ open: true, editing: null })}
        sx={{ position: 'fixed', right: 24, bottom: 24 }}
      >
        <AddIcon />
      </Fab>

      <StreamDialog
        open={dialog.open}
        editing={dialog.editing}
        dmrId={dmrId}
        onClose={() => setDialog({ open: false, editing: null })}
        onSaved={() => { setDialog({ open: false, editing: null }); load(); }}
      />

      {/* ========== DELETE CONFIRMATION ========== */}
      <Dialog open={!!deleting} onClose={() => setDeleting(null)}>
        <DialogTitle>Delete {deleting?.name}?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Its stream stops now. Recordings and transcripts already saved are kept.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleting(null)}>Cancel</Button>
          <Button color="error" variant="contained" onClick={remove}>Delete</Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
