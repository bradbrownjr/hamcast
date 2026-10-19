import { useEffect, useState } from 'react';
import Autocomplete from '@mui/material/Autocomplete';
import TextField from '@mui/material/TextField';
import { api, DmrHost, YsfHost } from '../api';

type Host = YsfHost | DmrHost;

function label(h: Host) {
  return 'description' in h && h.description && h.description !== h.name
    ? `${h.name} (${h.description})`
    : h.name;
}

/** Search Pi-Star's public YSF reflector or DMR master list. */
export default function HostPicker({ type, onPick }: { type: 'ysf' | 'dmr'; onPick: (h: Host) => void }) {
  const [hosts, setHosts] = useState<Host[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    (type === 'ysf' ? api.ysfHosts() : api.dmrHosts()).then(
      (r) => { if (alive) { setHosts(r.hosts); setError(null); } },
      (e: Error) => { if (alive) setError(e.message); },
    ).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [type]);

  return (
    <Autocomplete
      options={hosts}
      loading={loading}
      getOptionLabel={label}
      getOptionKey={(h) => `${h.id}-${h.name}-${h.host}:${h.port}`}
      onChange={(_, h) => h && onPick(h)}
      renderInput={(params) => (
        <TextField
          {...params}
          label={type === 'ysf' ? 'Find a YSF reflector' : 'Find a DMR master'}
          helperText={error ?? 'From the Pi-Star host lists. Or type the host and port below.'}
          error={!!error}
        />
      )}
    />
  );
}
