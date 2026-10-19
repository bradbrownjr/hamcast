import { useEffect, useState } from 'react';
import { api, Status } from '../api';

/** /api/status, refreshed every few seconds while the page is open. */
export function useStatus(intervalMs = 3000) {
  const [status, setStatus] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api.status().then(
        (s) => { if (alive) { setStatus(s); setError(null); } },
        (e: Error) => { if (alive) setError(e.message); },
      );
    load();
    const timer = window.setInterval(load, intervalMs);
    return () => { alive = false; window.clearInterval(timer); };
  }, [intervalMs]);

  return { status, error };
}
