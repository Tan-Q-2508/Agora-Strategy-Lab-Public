/** How a trade ended, in plain words. */
export const EXIT_WORDS: Record<string, string> = {
  signal: "Exit rule",
  stop: "Stop-loss",
  target: "Take-profit",
  trailing: "Trailing stop",
  time: "Time exit",
  square_off: "Intraday square-off",
  partial: "Partial profit",
  scale_out: "Partial profit",
};
