import { useEffect, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import { fetchState } from './api';
import type { Book, Decision, Order, Position, State } from './types';
import { fmtDur, fmtNum, fmtPct, fmtPx, fmtTime, fmtUsd, shortAddr } from './format';

const POLL_MS = 500;

export default function App() {
  const [state, setState] = useState<State | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [now, setNow] = useState<number>(Date.now() / 1000);
  const [flash, setFlash] = useState<boolean>(false);
  const [lastFlashAt, setLastFlashAt] = useState<number>(0);
  const lastSeenOrderId = useRef<number>(-1);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const s = await fetchState();
        if (cancelled) return;
        setState(s);
        setErr(null);
        const newest = s.orders.length ? s.orders[0].id : -1;
        if (lastSeenOrderId.current < 0) {
          lastSeenOrderId.current = newest;
        } else if (newest > lastSeenOrderId.current) {
          const o = s.orders[0];
          if (o && o.dry_run === 0 && (o.status === 'matched' || o.status === 'filled')) {
            setFlash(false);
            setTimeout(() => {
              setFlash(true);
              setLastFlashAt(Date.now());
            }, 0);
            setTimeout(() => setFlash(false), 5000);
          }
          lastSeenOrderId.current = newest;
        }
      } catch (e) {
        if (!cancelled) setErr(String(e));
      }
    };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 200);
    return () => clearInterval(id);
  }, []);

  const m = state?.market;
  const tRem = m ? Math.max(0, m.end_ts - now) : null;
  const totalEquity =
    (state?.wallet.balance_pusd ?? 0) + (state?.wallet.value_usd ?? 0);
  const pnl = state?.pnl;
  const winRate =
    pnl && pnl.wins + pnl.losses > 0
      ? (pnl.wins / (pnl.wins + pnl.losses)) * 100
      : null;

  return (
    <>
      {flash && <div className="flash-screen" />}
      <div style={shellStyle}>
        <TopBar
          time={now}
          botRunning={state?.bot_running ?? false}
          botMode={state?.bot_mode ?? 'stopped'}
          riskState={state?.risk_state ?? 'OK'}
          err={err}
          lastFlashAt={lastFlashAt}
        />

        <div style={gridStyle}>
          <div style={colStack}>
            <Panel title="WALLET / EQUITY">
              <Row k="DEPOSIT" v={shortAddr(state?.wallet.deposit)} mono />
              <Row k="EOA" v={shortAddr(state?.wallet.eoa)} mono />
              <Sep />
              <Row k="pUSD CASH" v={fmtUsd(state?.wallet.balance_pusd)} hi />
              <Row k="OPEN VALUE" v={fmtUsd(state?.wallet.value_usd)} />
              <Sep />
              <Row k="TOTAL EQUITY" v={fmtUsd(totalEquity)} hi big />
            </Panel>

            <Panel title="P&L · 24H">
              <Row k="REALIZED" v={fmtUsd(pnl?.realized_usd)} colored={pnl?.realized_usd} />
              <Row k="WINS / LOSSES" v={`${pnl?.wins ?? 0} / ${pnl?.losses ?? 0}`} />
              <Row k="WIN RATE" v={fmtPct(winRate ?? null)} />
              <Row k="PENDING" v={String(pnl?.pending ?? 0)} dim />
            </Panel>

            <Panel title="STRATEGY">
              <Row k="LOSER FLOOR" v={`> ${fmtPx(state?.config.loser_floor)}`} mono />
              <Row k="MAX ENTRY" v={`≤ ${fmtPx(state?.config.max_entry_price)}`} mono />
              <Row k="WINDOW" v={`${state?.config.min_t_remaining_sec ?? '?'}–${state?.config.seconds_before_close ?? '?'}s`} mono />
              <Row k="SIZE" v={`${state?.config.order_size_shares ?? '?'} sh`} mono />
              <Sep />
              <Row k="MAX OPEN" v={String(state?.config.max_open_positions ?? '')} mono />
              <Row k="LOSS CAP / DAY" v={fmtUsd(state?.config.max_daily_loss_usd)} mono />
            </Panel>
          </div>

          <div style={colStack}>
            <Panel title={m ? `LIVE MARKET · ${m.market_slug}` : 'NO LIVE MARKET'}>
              {m ? (
                <>
                  <Row
                    k="COUNTDOWN"
                    v={fmtDur(tRem)}
                    hi
                    big
                    colored={tRem != null && tRem < 60 ? 1 : -1}
                  />
                  <BookView
                    label="UP  "
                    book={state?.book_up}
                    cap={state?.config.max_entry_price ?? 0.95}
                    floor={state?.config.loser_floor ?? 0.85}
                  />
                  <BookView
                    label="DOWN"
                    book={state?.book_down}
                    cap={state?.config.max_entry_price ?? 0.95}
                    floor={state?.config.loser_floor ?? 0.85}
                  />
                </>
              ) : (
                <div style={{ color: 'var(--txt-dim)', padding: '6px 0' }}>
                  awaiting next 5-min BTC window<span className="caret">_</span>
                </div>
              )}
            </Panel>

            <Panel title="DECISION LOG · live" flex>
              <DecisionsTable decisions={state?.decisions ?? []} />
            </Panel>
          </div>

          <div style={colStack}>
            <Panel title="OPEN POSITIONS">
              <PositionsTable positions={state?.positions ?? []} />
            </Panel>

            <Panel title="ORDERS · recent" flex>
              <OrdersTable orders={state?.orders ?? []} />
            </Panel>
          </div>
        </div>

        <BottomBar state={state} />
      </div>
    </>
  );
}

function TopBar({
  time, botRunning, botMode, riskState, err, lastFlashAt,
}: { time: number; botRunning: boolean; botMode: string; riskState: string; err: string | null; lastFlashAt: number }) {
  const blink = Date.now() - lastFlashAt < 5000;
  const riskOk = riskState === 'OK';
  const botLabel = !botRunning
    ? 'STOPPED'
    : !riskOk
      ? `LOCKED (${riskState})`
      : 'RUNNING';
  const botColor = !botRunning
    ? 'var(--red)'
    : !riskOk
      ? 'var(--amber)'
      : 'var(--green)';

  // mode chip: green for paper (safe), red for live (real money)
  const modeChip = botMode === 'live'
    ? { label: 'LIVE', bg: '#330000', fg: 'var(--red)', border: 'var(--red)' }
    : botMode === 'paper'
      ? { label: 'PAPER', bg: '#001a0d', fg: 'var(--green)', border: 'var(--green)' }
      : { label: 'OFFLINE', bg: 'transparent', fg: 'var(--txt-dim)', border: 'var(--border-hi)' };

  return (
    <div style={topBarStyle}>
      <span style={{ color: 'var(--amber)', fontWeight: 700 }}>POLY_HFT</span>
      <span style={{ color: 'var(--txt-dim)' }}> · </span>
      <span style={{ color: 'var(--txt-hi)' }}>BTC 5MIN</span>
      <span style={{
        marginLeft: 12,
        padding: '1px 8px',
        border: `1px solid ${modeChip.border}`,
        background: modeChip.bg,
        color: modeChip.fg,
        fontWeight: 700,
        letterSpacing: '1.5px',
        fontSize: 10,
      }}>{modeChip.label}</span>
      <span style={spacer} />
      <span style={{ color: botColor, fontWeight: 600 }}>
        ● BOT {botLabel}
      </span>
      <span style={{ color: 'var(--txt-dim)', margin: '0 12px' }}>|</span>
      <span style={{ color: err ? 'var(--red)' : 'var(--green)' }}>
        ● {err ? 'API ERR' : 'API OK'}
      </span>
      {blink && (
        <>
          <span style={{ color: 'var(--txt-dim)', margin: '0 12px' }}>|</span>
          <span style={{ color: 'var(--amber-bright)', fontWeight: 700 }}>◆ TRADE FIRED</span>
        </>
      )}
      <span style={spacer} />
      <span style={{ color: 'var(--txt)' }}>{fmtTime(time)}</span>
    </div>
  );
}

function BottomBar({ state }: { state: State | null }) {
  const errs = state?.errors || {};
  const errKeys = Object.keys(errs);
  return (
    <div style={bottomBarStyle}>
      <span style={{ color: 'var(--txt-dim)' }}>POLL 500ms</span>
      <span style={{ color: 'var(--txt-dim)', margin: '0 12px' }}>·</span>
      <span style={{ color: 'var(--txt-dim)' }}>
        DECISIONS {state?.decisions.length ?? 0} · ORDERS {state?.orders.length ?? 0}
      </span>
      <span style={spacer} />
      {errKeys.length > 0 && (
        <span style={{ color: 'var(--red)' }}>ERR: {errKeys.join(', ')}</span>
      )}
    </div>
  );
}

function Panel({
  title, children, flex,
}: { title: string; children: ReactNode; flex?: boolean }) {
  return (
    <div style={{
      border: '1px solid var(--border)',
      background: 'var(--bg-panel)',
      display: 'flex',
      flexDirection: 'column',
      flex: flex ? 1 : 'unset',
      minHeight: 0,
    }}>
      <div style={panelTitleStyle}>{title}</div>
      <div style={{ padding: '6px 10px', flex: flex ? 1 : 'unset', overflow: 'auto' }}>
        {children}
      </div>
    </div>
  );
}

function Row({
  k, v, hi, big, dim, mono, colored,
}: {
  k: string; v: ReactNode; hi?: boolean; big?: boolean;
  dim?: boolean; mono?: boolean; colored?: number | null;
}) {
  let color: string = hi ? 'var(--txt-hi)' : dim ? 'var(--txt-dim)' : 'var(--txt)';
  if (typeof colored === 'number') {
    color = colored > 0 ? 'var(--green)' : colored < 0 ? 'var(--red)' : color;
  }
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', padding: '2px 0' }}>
      <span style={{ color: 'var(--txt-dim)', letterSpacing: '0.5px' }}>{k}</span>
      <span style={{
        color,
        fontFamily: mono ? 'inherit' : undefined,
        fontSize: big ? 16 : undefined,
        fontWeight: big ? 700 : 500,
      }}>{v}</span>
    </div>
  );
}

function Sep() {
  return <div style={{ height: 1, background: 'var(--border)', margin: '4px 0' }} />;
}

function BookView({
  label, book, cap, floor,
}: { label: string; book: Book | null | undefined; cap: number; floor: number }) {
  const ask = book?.best_ask ?? null;
  let askColor = 'var(--txt)';
  if (ask != null) {
    if (ask > cap) askColor = 'var(--txt-dim)';
    else if (ask > floor) askColor = 'var(--amber-bright)';
    else askColor = 'var(--txt-dim)';
  }
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '3px 0', borderTop: '1px dashed var(--border)' }}>
      <span style={{ color: 'var(--txt-dim)', width: 36 }}>{label}</span>
      <span style={{ color: 'var(--txt-dim)' }}>bid</span>
      <span style={{ color: 'var(--green)' }}>{fmtPx(book?.best_bid)}</span>
      <span style={{ color: 'var(--txt-dim)' }}>×{fmtNum(book?.bid_size, 0)}</span>
      <span style={spacer} />
      <span style={{ color: 'var(--txt-dim)' }}>ask</span>
      <span style={{ color: askColor, fontWeight: 700 }}>{fmtPx(ask)}</span>
      <span style={{ color: 'var(--txt-dim)' }}>×{fmtNum(book?.ask_size, 0)}</span>
    </div>
  );
}

function actionColor(a: string): string {
  if (a === 'BUY') return 'var(--green)';
  if (a.startsWith('SKIP')) return 'var(--txt-dim)';
  return 'var(--txt)';
}

function DecisionsTable({ decisions }: { decisions: Decision[] }) {
  if (!decisions.length) return <Empty>no decisions yet<span className="caret">_</span></Empty>;
  return (
    <table style={tableStyle}>
      <thead>
        <tr>
          <Th>TIME</Th>
          <Th>MARKET</Th>
          <Th>SIDE</Th>
          <Th right>T_REM</Th>
          <Th right>ASK</Th>
          <Th>ACTION</Th>
          <Th>REASON</Th>
        </tr>
      </thead>
      <tbody>
        {decisions.slice(0, 40).map((d) => (
          <tr key={d.id} style={{ background: d.action === 'BUY' ? 'rgba(0,255,127,0.04)' : undefined }}>
            <Td dim>{fmtTime(d.ts)}</Td>
            <Td dim>{(d.market_slug || '').replace('btc-updown-5m-', '…')}</Td>
            <Td>{d.side ?? '—'}</Td>
            <Td right>{fmtNum(d.t_remaining, 1)}s</Td>
            <Td right>{fmtPx(d.ask_price)}</Td>
            <Td color={actionColor(d.action)} bold>{d.action}</Td>
            <Td dim>{d.reason}</Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function OrdersTable({ orders }: { orders: Order[] }) {
  if (!orders.length) return <Empty>no orders yet<span className="caret">_</span></Empty>;
  return (
    <table style={tableStyle}>
      <thead>
        <tr>
          <Th>TIME</Th>
          <Th>MARKET</Th>
          <Th>SIDE</Th>
          <Th right>SIZE</Th>
          <Th right>PX</Th>
          <Th>STATUS</Th>
          <Th right>FILLED $</Th>
        </tr>
      </thead>
      <tbody>
        {orders.slice(0, 20).map((o) => {
          const ok = o.status === 'matched' || o.status === 'filled';
          return (
            <tr key={o.id}>
              <Td dim>{fmtTime(o.ts)}</Td>
              <Td dim>{(o.market_slug || '').replace('btc-updown-5m-', '…')}</Td>
              <Td>{o.side}</Td>
              <Td right>{fmtNum(o.size, 0)}</Td>
              <Td right>{fmtPx(o.price)}</Td>
              <Td color={ok ? 'var(--green)' : o.status === 'error' ? 'var(--red)' : 'var(--amber)'} bold>{o.status}</Td>
              <Td right>{fmtUsd(o.filled_size)}</Td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function PositionsTable({ positions }: { positions: Position[] }) {
  if (!positions.length) return <Empty>no open positions<span className="caret">_</span></Empty>;
  return (
    <table style={tableStyle}>
      <thead>
        <tr>
          <Th>TITLE</Th>
          <Th>SIDE</Th>
          <Th right>SIZE</Th>
          <Th right>PX</Th>
          <Th right>VAL</Th>
        </tr>
      </thead>
      <tbody>
        {positions.map((p, i) => (
          <tr key={i}>
            <Td dim>{(p.title || '').replace(/^Bitcoin Up or Down - /, '')}</Td>
            <Td>{p.outcome}</Td>
            <Td right>{fmtNum(p.size, 2)}</Td>
            <Td right>{fmtPx(p.curPrice)}</Td>
            <Td right>{fmtUsd((p.size ?? 0) * (p.curPrice ?? 0))}</Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Th({ children, right }: { children: ReactNode; right?: boolean }) {
  return (
    <th style={{
      textAlign: right ? 'right' : 'left',
      padding: '4px 8px',
      color: 'var(--txt-dim)',
      fontWeight: 400,
      borderBottom: '1px solid var(--border)',
      fontSize: 10,
      letterSpacing: '0.8px',
      position: 'sticky',
      top: 0,
      background: 'var(--bg-panel)',
    }}>{children}</th>
  );
}

function Td({
  children, right, dim, color, bold,
}: { children: ReactNode; right?: boolean; dim?: boolean; color?: string; bold?: boolean }) {
  return (
    <td style={{
      textAlign: right ? 'right' : 'left',
      padding: '3px 8px',
      color: color || (dim ? 'var(--txt-dim)' : 'var(--txt)'),
      fontWeight: bold ? 700 : 400,
      borderBottom: '1px solid rgba(255,255,255,0.02)',
      whiteSpace: 'nowrap',
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      maxWidth: 240,
    }}>{children}</td>
  );
}

function Empty({ children }: { children: ReactNode }) {
  return <div style={{ color: 'var(--txt-dim)', padding: '8px 4px' }}>{children}</div>;
}

const shellStyle: CSSProperties = { height: '100vh', display: 'grid', gridTemplateRows: '28px 1fr 22px' };
const topBarStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', padding: '0 12px',
  borderBottom: '1px solid var(--border-hi)', background: 'var(--bg-panel)',
  fontSize: 11, letterSpacing: '0.5px',
};
const bottomBarStyle: CSSProperties = {
  display: 'flex', alignItems: 'center', padding: '0 12px',
  borderTop: '1px solid var(--border-hi)', background: 'var(--bg-panel)',
  fontSize: 10, letterSpacing: '0.5px',
};
const gridStyle: CSSProperties = {
  display: 'grid',
  gridTemplateColumns: '300px 1fr 420px',
  gap: 6, padding: 6, height: '100%', overflow: 'hidden',
};
const colStack: CSSProperties = { display: 'flex', flexDirection: 'column', gap: 6, minHeight: 0 };
const panelTitleStyle: CSSProperties = {
  background: 'var(--border)', color: 'var(--amber)',
  padding: '3px 10px', fontSize: 10, letterSpacing: '1.2px', fontWeight: 600,
};
const spacer: CSSProperties = { flex: 1 };
const tableStyle: CSSProperties = { width: '100%', borderCollapse: 'collapse', fontSize: 11 };
