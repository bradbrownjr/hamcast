import { FormEvent, useState } from 'react';
import Alert from '@mui/material/Alert';
import Button from '@mui/material/Button';
import Card from '@mui/material/Card';
import CardContent from '@mui/material/CardContent';
import Stack from '@mui/material/Stack';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import { api } from '../api';

export default function LoginForm({ onSignedIn }: { onSignedIn: () => void }) {
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.login(password);
      onSignedIn();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card variant="outlined" sx={{ maxWidth: 420, mx: 'auto' }}>
      <CardContent component="form" onSubmit={submit}>
        <Stack spacing={2}>
          <Typography variant="h6" component="h2">
            Sign in to manage nets
          </Typography>
          <Typography variant="body2" color="text.secondary">
            The password is HAMCAST_ADMIN_PASSWORD, or the one hamcast generated in
            admin-password.txt in its data folder.
          </Typography>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField
            type="password"
            label="Password"
            autoComplete="current-password"
            autoFocus
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
          <Button type="submit" variant="contained" size="large" disabled={busy || !password}>
            Sign in
          </Button>
        </Stack>
      </CardContent>
    </Card>
  );
}
