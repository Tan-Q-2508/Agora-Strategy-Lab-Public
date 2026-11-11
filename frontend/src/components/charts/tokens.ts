/** Read the live design tokens so charts always match the current theme. */
export interface ChartTokens {
  fg: string;
  fgMuted: string;
  fgSubtle: string;
  surface: string;
  border: string;
  grid: string;
  accent: string;
  accentSoft: string;
  benchmark: string;
  profit: string;
  loss: string;
  warning: string;
  info: string;
  fontSans: string;
}

function read(style: CSSStyleDeclaration, name: string, fallback: string): string {
  const v = style.getPropertyValue(name).trim();
  return v || fallback;
}

export function readChartTokens(): ChartTokens {
  const s = getComputedStyle(document.documentElement);
  return {
    fg: read(s, "--fg", "#1f1d1a"),
    fgMuted: read(s, "--fg-muted", "#5f5a52"),
    fgSubtle: read(s, "--fg-subtle", "#6b665d"),
    surface: read(s, "--surface", "#ffffff"),
    border: read(s, "--border", "#e7e3da"),
    grid: read(s, "--chart-grid", "#f1eee7"),
    accent: read(s, "--accent", "#e8692c"),
    accentSoft: read(s, "--accent-soft", "#fdf0e8"),
    benchmark: read(s, "--chart-benchmark", "#8a847a"),
    profit: read(s, "--profit", "#1f7a4d"),
    loss: read(s, "--loss", "#b42318"),
    warning: read(s, "--warning", "#b45309"),
    info: read(s, "--info", "#2563eb"),
    fontSans: "Inter Variable, Segoe UI, system-ui, sans-serif",
  };
}

/** Hex "#rrggbb" + alpha 0..1 → "rgba(...)" (charts need explicit alpha colors). */
export function alpha(hex: string, a: number): string {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex.trim());
  if (!m || !m[1]) return hex;
  const n = parseInt(m[1], 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}
