export function fmtUsd(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return '—';
  const sign = n < 0 ? '-' : '';
  return sign + '$' + Math.abs(n).toFixed(digits);
}

export function fmtNum(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toFixed(digits);
}

export function fmtPx(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toFixed(3);
}

export function fmtPct(n: number | null | undefined, digits = 1): string {
  if (n == null || Number.isNaN(n)) return '—';
  return n.toFixed(digits) + '%';
}

export function fmtTime(ts: number | undefined | null): string {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('en-US', { hour12: false });
}

export function fmtDur(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return '—';
  if (seconds < 0) return 'CLOSED';
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

export function shortAddr(a: string | undefined | null): string {
  if (!a) return '—';
  return a.slice(0, 6) + '…' + a.slice(-4);
}
