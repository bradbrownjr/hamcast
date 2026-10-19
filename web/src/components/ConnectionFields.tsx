import { useEffect, useState } from 'react';
import Alert from '@mui/material/Alert';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import FormControlLabel from '@mui/material/FormControlLabel';
import Grid from '@mui/material/Grid';
import IconButton from '@mui/material/IconButton';
import MenuItem from '@mui/material/MenuItem';
import Stack from '@mui/material/Stack';
import Switch from '@mui/material/Switch';
import TextField from '@mui/material/TextField';
import ToggleButton from '@mui/material/ToggleButton';
import ToggleButtonGroup from '@mui/material/ToggleButtonGroup';
import Typography from '@mui/material/Typography';
import AddIcon from '@mui/icons-material/Add';
import DeleteIcon from '@mui/icons-material/Delete';
import { api, ScheduleRule, StreamConfig } from '../api';

const DAYS = ['sun', 'mon', 'tue', 'wed', 'thu', 'fri', 'sat'];
const DAY_LABEL: Record<string, string> = {
  sun: 'Sun', mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat',
};
const WEEK_LABEL = ['1st', '2nd', '3rd', '4th', '5th'];

type Set = <K extends keyof StreamConfig>(k: K, v: StreamConfig[K]) => void;

// ========== ONE WEEKLY WINDOW ==========
function RuleRow({ rule, onChange, onRemove }: {
  rule: ScheduleRule;
  onChange: (r: ScheduleRule) => void;
  onRemove: () => void;
}) {
  return (
    <Box sx={{ border: 1, borderColor: 'divider', borderRadius: 2, p: 1.5 }}>
      <Stack spacing={1.5}>
        <Stack direction="row" sx={{ alignItems: 'center' }}>
          <ToggleButtonGroup
            size="small"
            color="primary"
            value={rule.days}
            onChange={(_, days: string[]) => onChange({ ...rule, days })}
            aria-label="Days"
            sx={{ flexWrap: 'wrap', flexGrow: 1 }}
          >
            {DAYS.map((d) => (
              <ToggleButton key={d} value={d} sx={{ px: 1 }}>{DAY_LABEL[d]}</ToggleButton>
            ))}
          </ToggleButtonGroup>
          <IconButton aria-label="Remove this time" onClick={onRemove}>
            <DeleteIcon />
          </IconButton>
        </Stack>
        <Grid container spacing={1.5}>
          <Grid size={{ xs: 6 }}>
            <TextField
              fullWidth
              size="small"
              type="time"
              label="Starts"
              value={rule.time}
              onChange={(e) => onChange({ ...rule, time: e.target.value })}
              slotProps={{ inputLabel: { shrink: true } }}
            />
          </Grid>
          <Grid size={{ xs: 6 }}>
            <TextField
              fullWidth
              size="small"
              type="number"
              label="Lasts (minutes)"
              value={rule.minutes}
              onChange={(e) => onChange({ ...rule, minutes: Number(e.target.value) })}
            />
          </Grid>
        </Grid>
        <ToggleButtonGroup
          size="small"
          value={rule.weeks}
          onChange={(_, weeks: number[]) => onChange({ ...rule, weeks: [...weeks].sort() })}
          aria-label="Weeks of the month"
        >
          {WEEK_LABEL.map((w, i) => (
            <ToggleButton key={w} value={i + 1} sx={{ px: 1 }}>{w}</ToggleButton>
          ))}
        </ToggleButtonGroup>
        <Typography variant="caption" color="text.secondary">
          {rule.weeks.length ? 'Only those weeks of the month.' : 'Every week. Pick weeks for e.g. the 3rd Thursday.'}
        </Typography>
      </Stack>
    </Box>
  );
}

// ========== CONNECTION SECTION OF THE NET DIALOG ==========
export default function ConnectionFields({ s, set, ectlogger }: {
  s: StreamConfig;
  set: Set;
  ectlogger: boolean; // an ECTLogger site is configured
}) {
  const [schedules, setSchedules] = useState<{ id: number; name: string }[]>([]);
  const [scheduleError, setScheduleError] = useState<string | null>(null);
  const needed = s.connection === 'needed';

  useEffect(() => {
    if (!ectlogger || !needed) return;
    api.ectloggerSchedules().then(
      (r) => { setSchedules(r.schedules); setScheduleError(null); },
      (e: Error) => setScheduleError(e.message),
    );
  }, [ectlogger, needed]);

  const setRule = (i: number, r: ScheduleRule) => set('schedule', s.schedule.map((x, j) => (j === i ? r : x)));

  return (
    <Stack spacing={2}>
      <Typography variant="subtitle2">Connection</Typography>
      <ToggleButtonGroup
        exclusive
        color="primary"
        value={s.connection}
        onChange={(_, v) => v && set('connection', v)}
      >
        <ToggleButton value="always">Always linked</ToggleButton>
        <ToggleButton value="needed">When needed</ToggleButton>
      </ToggleButtonGroup>

      {/* Shows only for nets linked when needed */}
      {needed && (
        <>
          <Grid container spacing={2} sx={{ alignItems: 'center' }}>
            <Grid size={{ xs: 12, sm: 7 }}>
              <FormControlLabel
                control={<Switch checked={s.on_listen} onChange={(e) => set('on_listen', e.target.checked)} />}
                label="When someone is listening"
              />
            </Grid>
            <Grid size={{ xs: 12, sm: 5 }}>
              <TextField
                fullWidth
                size="small"
                type="number"
                label="Then stay linked (min)"
                disabled={!s.on_listen}
                value={s.linger_minutes}
                onChange={(e) => set('linger_minutes', Number(e.target.value))}
              />
            </Grid>
          </Grid>

          {ectlogger && (
            <TextField
              select
              label="Follow an ECTLogger schedule"
              value={s.ectlogger_schedule ?? ''}
              onChange={(e) => set('ectlogger_schedule', e.target.value === '' ? null : Number(e.target.value))}
              helperText={scheduleError ?? 'Linked from before the net starts until it closes.'}
              error={!!scheduleError}
            >
              <MenuItem value="">None</MenuItem>
              {schedules.map((x) => (
                <MenuItem key={x.id} value={x.id}>{x.name}</MenuItem>
              ))}
            </TextField>
          )}

          <Stack spacing={1}>
            <Typography variant="body2">Scheduled times</Typography>
            {s.schedule.map((r, i) => (
              <RuleRow
                key={i}
                rule={r}
                onChange={(x) => setRule(i, x)}
                onRemove={() => set('schedule', s.schedule.filter((_, j) => j !== i))}
              />
            ))}
            <Button
              startIcon={<AddIcon />}
              sx={{ alignSelf: 'flex-start' }}
              onClick={() => set('schedule', [...s.schedule, { days: [], time: '19:00', minutes: 60, weeks: [] }])}
            >
              Add a time
            </Button>
          </Stack>

          {(s.schedule.length > 0 || s.ectlogger_schedule) && (
            <TextField
              size="small"
              type="number"
              label="Link early (minutes)"
              value={s.lead_minutes}
              onChange={(e) => set('lead_minutes', Number(e.target.value))}
              sx={{ maxWidth: 220 }}
            />
          )}
          {!s.on_listen && s.schedule.length === 0 && !s.ectlogger_schedule && (
            <Alert severity="warning">Turn on listening or add a schedule, or this net never links.</Alert>
          )}
        </>
      )}
    </Stack>
  );
}
