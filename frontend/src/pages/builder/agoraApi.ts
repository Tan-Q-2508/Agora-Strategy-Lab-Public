/** The strategy API as shown in autocomplete and the reference panel (mirrors runtime.py). */
export interface ApiItem {
  name: string;
  insert: string; // snippet text after the dot
  detail: string;
  doc: string;
  kind: "property" | "method";
}

export const CTX: ApiItem[] = [
  { name: "close", insert: "close", detail: "series", doc: "Closing prices, newest last: ctx.close[-1] is the latest closed candle.", kind: "property" },
  { name: "open", insert: "open", detail: "series", doc: "Opening prices.", kind: "property" },
  { name: "high", insert: "high", detail: "series", doc: "Highest prices.", kind: "property" },
  { name: "low", insert: "low", detail: "series", doc: "Lowest prices.", kind: "property" },
  { name: "volume", insert: "volume", detail: "series", doc: "Traded volume.", kind: "property" },
  { name: "hl2", insert: "hl2", detail: "series", doc: "(high + low) / 2.", kind: "property" },
  { name: "typical", insert: "typical", detail: "series", doc: "(high + low + close) / 3.", kind: "property" },
  { name: "ind", insert: "ind", detail: "indicators", doc: "Every indicator: ctx.ind.rsi(ctx.close, 14), ctx.ind.atr(14) …", kind: "property" },
  { name: "position", insert: "position", detail: "Position | None", doc: "The open trade on this stock, or None. Has side, qty, entry_price, bars_held, profit_pct.", kind: "property" },
  { name: "params", insert: "params", detail: "dict", doc: "The strategy's parameters by name, e.g. ctx.params[\"length\"].", kind: "property" },
  { name: "size", insert: "size", detail: "sizing helpers", doc: "ctx.size.percent_equity(10), fixed_qty(5), fixed_amount(50000), risk_percent(1).", kind: "property" },
  { name: "stop", insert: "stop", detail: "stop helpers", doc: "ctx.stop.percent(5) or ctx.stop.atr(2, 14).", kind: "property" },
  { name: "symbol", insert: "symbol", detail: "str", doc: "The stock's symbol, e.g. \"RELIANCE\".", kind: "property" },
  { name: "time", insert: "time", detail: "int", doc: "The latest candle's open time (UTC milliseconds).", kind: "property" },
  { name: "clock", insert: "clock", detail: "str", doc: "The latest candle's open time as local \"HH:MM\".", kind: "property" },
  { name: "date", insert: "date", detail: "str", doc: "The latest candle's local date, \"YYYY-MM-DD\".", kind: "property" },
  { name: "bar_index", insert: "bar_index", detail: "int", doc: "How many candles came before this one.", kind: "property" },
  { name: "equity", insert: "equity", detail: "float", doc: "The account's current value.", kind: "property" },
  { name: "buy", insert: "buy(size=${1:ctx.size.percent_equity(10)}, stop_loss=${2:None})", detail: "open a long trade", doc: "Buy at the next candle's open. Optional: size, stop_loss, take_profit, trailing_stop, reason, scale_out.", kind: "method" },
  { name: "scale_out", insert: "scale_out([(${1:1}, ${2:50})])", detail: "partial exits", doc: "Partial exits for buy/short: [(1, 50), (2, 25)] sells 50% at 1R and 25% more at 2R (R = the stop distance); the stop moves to the entry after the first. Steps may also be (\"percent\", 3, 33) or (\"atr\", 2, 33).", kind: "method" },
  { name: "short", insert: "short(size=${1:ctx.size.percent_equity(10)}, stop_loss=${2:None})", detail: "open a short trade", doc: "Short-sell at the next candle's open (US, or India intraday).", kind: "method" },
  { name: "sell_all", insert: "sell_all(\"${1:reason}\")", detail: "close the trade", doc: "Close the open trade (long or short) at the next candle's open.", kind: "method" },
  { name: "crosses_above", insert: "crosses_above(${1:a}, ${2:b})", detail: "bool", doc: "True on the candle where a moves from at-or-below b to above it.", kind: "method" },
  { name: "crosses_below", insert: "crosses_below(${1:a}, ${2:b})", detail: "bool", doc: "True on the candle where a moves from at-or-above b to below it.", kind: "method" },
  { name: "above", insert: "above(${1:a}, ${2:b})", detail: "bool", doc: "a is above b on the latest candle (NaN-safe).", kind: "method" },
  { name: "below", insert: "below(${1:a}, ${2:b})", detail: "bool", doc: "a is below b on the latest candle.", kind: "method" },
  { name: "between", insert: "between(${1:x}, ${2:low}, ${3:high})", detail: "bool", doc: "low ≤ x ≤ high on the latest candle.", kind: "method" },
  { name: "time_between", insert: "time_between(\"${1:09:30}\", \"${2:15:00}\")", detail: "bool", doc: "The latest candle opened in this local time window.", kind: "method" },
  { name: "price", insert: "price(\"${1:close}\")", detail: "series", doc: "A price series by name.", kind: "method" },
  { name: "log", insert: "log(${1:message})", detail: "write to the log", doc: "Shows a line in the backtest's strategy log (print works too).", kind: "method" },
];

export const SERIES: ApiItem[] = [
  { name: "last", insert: "last", detail: "float", doc: "The newest value (same as [-1]).", kind: "property" },
  { name: "ago", insert: "ago(${1:1})", detail: "float", doc: "The value k candles ago.", kind: "method" },
  { name: "shift", insert: "shift(${1:1})", detail: "series", doc: "The series as it was k candles ago.", kind: "method" },
  { name: "times", insert: "times(${1:1.02})", detail: "series", doc: "The series multiplied by a number.", kind: "method" },
  { name: "to_list", insert: "to_list(${1:10})", detail: "list", doc: "The last n values, oldest first.", kind: "method" },
];

export const POSITION: ApiItem[] = [
  { name: "side", insert: "side", detail: "\"long\" | \"short\"", doc: "Direction of the open trade.", kind: "property" },
  { name: "qty", insert: "qty", detail: "float", doc: "Number of shares.", kind: "property" },
  { name: "entry_price", insert: "entry_price", detail: "float", doc: "Price paid (as traded).", kind: "property" },
  { name: "entry_time", insert: "entry_time", detail: "int", doc: "When the trade opened (UTC ms).", kind: "property" },
  { name: "bars_held", insert: "bars_held", detail: "int", doc: "Candles since the entry candle.", kind: "property" },
  { name: "profit_pct", insert: "profit_pct", detail: "float", doc: "Unrealised profit in % (negative = losing).", kind: "property" },
];

export const SIZE: ApiItem[] = [
  { name: "percent_equity", insert: "percent_equity(${1:10})", detail: "size", doc: "This % of the account's value.", kind: "method" },
  { name: "fixed_qty", insert: "fixed_qty(${1:10})", detail: "size", doc: "Exactly this many shares.", kind: "method" },
  { name: "fixed_amount", insert: "fixed_amount(${1:50000})", detail: "size", doc: "About this much money.", kind: "method" },
  { name: "risk_percent", insert: "risk_percent(${1:1})", detail: "size", doc: "Lose this % of the account if the stop is hit.", kind: "method" },
];

export const STOP: ApiItem[] = [
  { name: "percent", insert: "percent(${1:5})", detail: "stop", doc: "This % away from the entry price.", kind: "method" },
  { name: "atr", insert: "atr(${1:2}, ${2:14})", detail: "stop", doc: "A multiple of ATR away from the entry price.", kind: "method" },
];
