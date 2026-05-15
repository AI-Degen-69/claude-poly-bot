import type { State } from './types';

export async function fetchState(): Promise<State> {
  const r = await fetch('/api/state', { cache: 'no-store' });
  if (!r.ok) throw new Error(`/api/state ${r.status}`);
  return r.json();
}
