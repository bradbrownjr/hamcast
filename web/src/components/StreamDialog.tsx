import { useEffect, useState } from 'react';
import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import FormControlLabel from '@mui/material/FormControlLabel';
import Grid from '@mui/material/Grid';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import TextField from '@mui/material/TextField';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import useMediaQuery from '@mui/material/useMediaQuery';
import { useTheme } from '@mui/material/styles';
import { api, StreamConfig } from '../api';
import ConnectionFields from './ConnectionFields';
import HostPicker from './HostPicker';

const BLANK: StreamConfig = {
  id: '', name: '', type: 'ysf', host: '', port: 42000, mount: '', description: '',
  record: true, transcribe: true, enabled: true, password: '', talkgroup: 0, slot: 0, options: null,
  connection: 'always', on_listen: true, linger_minutes: 5, lead_minutes: 10, schedule: [], ectlogger_schedule: null,
};

function slug(name: string) {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40);
}

interface Props {
  open: boolean;
  editing: StreamConfig | null; // null = adding a net
  dmrId: number | null;
  ectlogger: boolean; // an ECTLogger site is configured
  onClose: () => void;
  onSaved: () => void;
}

// ========== ADD / EDIT NET DIALOG ==========
export default function StreamDialog({ open, editing, dmrId, ectlogger, onClose, onSaved }: Props) {
  const fullScreen = useMediaQuery(useTheme().breakpoints.down('sm'));
  const [s, setS] = useState<StreamConfig>(BLANK);
  const [idTouched, setIdTouched] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (open) {
      setS(editing ? { ...BLANK, ...editing } : BLANK);
      setIdTouched(!!editing);
      setError(null);
    }
  }, [open, editing]);

  const set = <K extends keyof StreamConfig>(k: K, v: StreamConfig[K]) => setS((p) => ({ ...p, [k]: v }));

  const setName = (name: string) =>
    setS((p) => ({ ...p, name, ...(idTouched ? {} : { id: slug(name) }) }));

  const setType = (type: 'ysf' | 'dmr') =>
    setS((p) => ({ ...p, type, host: '', password: '', port: type === 'ysf' ? 42000 : 62031 }));

  const save = async () => {
    setBusy(true);
    try {
      const body = { ...s, options: s.options?.trim() ? s.options.trim() : null };
      if (editing) await api.updateStream(editing.id, body);
      else await api.createStream(body);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const dmr = s.type === 'dmr';

  return (
    <Dialog open={open} onClose={onClose} fullScreen={fullScreen} maxWidth="sm" fullWidth>
      <DialogTitle>{editing ? `Edit ${editing.name}` : 'Add a net'}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}

          {/* Network type can only be chosen when adding */}
          {!editing && (
            <ToggleButtonGroup exclusive color="primary" value={s.type} onChange={(_, v) => v && setType(v)}>
              <ToggleButton value="ysf">YSF (Fusion)</ToggleButton>
              <ToggleButton value="dmr">DMR</ToggleButton>
            </ToggleButtonGroup>
          )}
          {dmr && !dmrId && (
            <Alert severity="warning">
              DMR needs your DMR ID: set HAMCAST_DMR_ID (your ID plus a two-digit hotspot suffix).
            </Alert>
          )}

          <TextField label="Name" required value={s.name} onChange={(e) => setName(e.target.value)} />
          <TextField
            label="Description"
            value={s.description}
            onChange={(e) => set('description', e.target.value)}
            helperText="Shown to listeners, e.g. Sundays 7:30 PM"
          />

          <HostPicker
            type={s.type}
            onPick={(h) =>
              setS((p) => ({ ...p, host: h.host, port: h.port, ...('password' in h ? { password: h.password } : {}) }))
            }
          />
          <Grid container spacing={2}>
            <Grid size={{ xs: 8 }}>
              <TextField fullWidth label="Host" required value={s.host} onChange={(e) => set('host', e.target.value)} />
            </Grid>
            <Grid size={{ xs: 4 }}>
              <TextField
                fullWidth
                label="Port"
                type="number"
                required
                value={s.port}
                onChange={(e) => set('port', Number(e.target.value))}
              />
            </Grid>
          </Grid>

          {/* ========== DMR-only fields ========== */}
          {dmr && (
            <>
              <TextField
                label="Master password"
                required
                value={s.password}
                onChange={(e) => set('password', e.target.value)}
                helperText="Filled in from the list for public masters"
              />
              <Grid container spacing={2}>
                <Grid size={{ xs: 7 }}>
                  <TextField
                    fullWidth
                    label="Talkgroup"
                    type="number"
                    required
                    value={s.talkgroup || ''}
                    onChange={(e) => set('talkgroup', Number(e.target.value))}
                  />
                </Grid>
                <Grid size={{ xs: 5 }}>
                  <TextField
                    select
                    fullWidth
                    label="Timeslot"
                    helperText="Nets on different timeslots can be heard at once"
                    value={s.slot}
                    onChange={(e) => set('slot', Number(e.target.value))}
                  >
                    <MenuItem value={0}>Either (TS2)</MenuItem>
                    <MenuItem value={1}>1</MenuItem>
                    <MenuItem value={2}>2</MenuItem>
                  </TextField>
                </Grid>
              </Grid>
              <TextField
                label="Login options (advanced)"
                value={s.options ?? ''}
                onChange={(e) => set('options', e.target.value)}
                helperText="Empty = DMR+ static talkgroups. Nets on the same master share these."
              />
            </>
          )}

          <Grid container spacing={2}>
            <Grid size={{ xs: 6 }}>
              <TextField
                fullWidth
                label="ID"
                required
                disabled={!!editing}
                value={s.id}
                onChange={(e) => { setIdTouched(true); set('id', e.target.value); }}
                helperText="Lowercase, digits, dashes"
              />
            </Grid>
            <Grid size={{ xs: 6 }}>
              <TextField
                fullWidth
                label="Stream address"
                value={s.mount}
                placeholder={`/${s.id || 'id'}`}
                onChange={(e) => set('mount', e.target.value)}
                helperText="Icecast mount; empty = /ID"
              />
            </Grid>
          </Grid>

          <ConnectionFields s={s} set={set} ectlogger={ectlogger} />

          <FormControlLabel
            control={<Switch checked={s.record} onChange={(e) => set('record', e.target.checked)} />}
            label="Record each transmission"
          />
          <FormControlLabel
            disabled={!s.record}
            control={<Switch checked={s.record && s.transcribe} onChange={(e) => set('transcribe', e.target.checked)} />}
            label="Transcribe recordings"
          />
          <FormControlLabel
            control={<Switch checked={s.enabled} onChange={(e) => set('enabled', e.target.checked)} />}
            label="Running"
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={save} disabled={busy || !s.name || !s.id || !s.host}>
          {editing ? 'Save' : 'Add net'}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
