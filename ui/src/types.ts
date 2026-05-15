export interface Wallet {
  eoa: string;
  deposit: string;
  balance_pusd: number | null;
  value_usd: number | null;
}

export interface Market {
  condition_id: string;
  market_slug: string;
  up_token: string;
  down_token: string;
  start_ts: number;
  end_ts: number;
  tick_size: number;
  neg_risk: boolean;
  t_remaining: number;
}

export interface Book {
  best_bid: number | null;
  bid_size: number;
  best_ask: number | null;
  ask_size: number;
}

export interface Position {
  conditionId: string;
  title?: string;
  outcome?: string;
  size?: number;
  curPrice?: number;
  realizedPnl?: number;
  redeemable?: boolean;
  [k: string]: unknown;
}

export interface Decision {
  id: number;
  ts: number;
  market_slug: string;
  side: string | null;
  t_remaining: number;
  ask_price: number | null;
  ask_size: number | null;
  action: string;
  reason: string;
  dry_run: number;
}

export interface Order {
  id: number;
  ts: number;
  market_slug: string;
  condition_id: string;
  token_id: string;
  side: string;
  size: number;
  price: number;
  order_id: string | null;
  status: string;
  filled_size: number;
  error: string | null;
  dry_run: number;
}

export interface PnL {
  realized_usd: number;
  wins: number;
  losses: number;
  pending: number;
}

export interface Config {
  max_entry_price: number;
  loser_floor: number;
  seconds_before_close: number;
  min_t_remaining_sec: number;
  order_size_shares: number;
  max_open_positions: number;
  max_daily_loss_usd: number;
}

export interface State {
  now: number;
  bot_running: boolean;
  bot_mode: string;       // 'paper' | 'live' | 'stopped' | 'unknown'
  risk_state: string;
  wallet: Wallet;
  market: Market | null;
  book_up: Book | null;
  book_down: Book | null;
  positions: Position[];
  pnl: PnL;
  config: Config;
  decisions: Decision[];
  orders: Order[];
  errors: Record<string, string>;
}
