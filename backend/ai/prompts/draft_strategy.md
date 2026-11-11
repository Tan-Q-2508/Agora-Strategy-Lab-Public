<!-- prompt: draft_strategy · version 3 -->
Turn the user's idea into an Agora strategy. Reply with JSON only, matching the schema:
- "explanation": one short paragraph in plain English saying what the rules do.
- "unsupported": things from the idea that Agora can't do (empty list if none). Never invent
  indicators or blocks that aren't in the list below; leave them out and name them here.
- "definition": the strategy, using only these indicators (key: settings):
$indicators

Market: $market. Allowed timeframes: 1d, 1h, 15m, 5m, 1m. Products: India delivery (held for
days, long only) or intraday (same day); US cash. Rules compare operands: a price field
("open", "high", "low", "close", "volume"), an indicator ({"kind": "indicator", "name": key,
"params": {...}}) or a number. Comparisons: above, below, at_least, at_most, crosses_above,
crosses_below.

Several conditions that must all be true go in a group: {"type": "all", "conditions": [ ... ]}
("any" for either-or). Price is {"kind": "price", "field": "close"}. Stops and targets go inside
"exit", never as rules: "stop_loss", "take_profit" and "trailing_stop" each look like
{"kind": "percent", "value": 5} (5% from the entry price; "atr" with a value of 2 means 2 × ATR),
and "max_bars": 20 leaves after 20 candles. Leave out anything else the idea doesn't mention,
with one exception: protect every strategy with a trailing stop, which follows the price and never
moves back, so winners keep most of their gain: "trailing_stop": {"kind": "atr", "value": 3} (3 × ATR
behind the best price; 2–2.5 for short swings), unless the idea gives its own trailing stop or says
not to use one.

Here is a valid example for a different idea:
```json
$example
```

The user's idea: $idea
