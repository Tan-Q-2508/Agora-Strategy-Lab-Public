/**
 * The Agora mark: a Greek Λ (the roof of the agora's stoa, and the shape of the A) with one
 * candlestick standing under it, whose body sits where the A's crossbar would be. The tile
 * is ink in the light theme and lifted charcoal in the dark one; the candle takes the accent.
 * Small sizes use thicker strokes so the candle still reads as the crossbar.
 */
export function Logo({ size = 28, tile = true }: { size?: number; tile?: boolean }) {
  const small = size <= 24;
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      {tile && <rect width="32" height="32" rx="7.5" fill="var(--logo-tile)" />}
      <path
        d={small ? "M7.6 25 16 6.6l8.4 18.4" : "M8 24.6 16 7.2l8 17.4"}
        fill="none"
        stroke={tile ? "var(--logo-roof)" : "currentColor"}
        strokeWidth={small ? 3.2 : 2.6}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path d={small ? "M16 12v13" : "M16 12.4v12.2"} stroke="var(--accent)" strokeWidth={small ? 2 : 1.4} strokeLinecap="round" />
      <rect x={small ? 13.9 : 14.3} y={small ? 16.4 : 15.6} width={small ? 4.2 : 3.4} height={small ? 5.8 : 5.6} rx={small ? 1 : 0.85} fill="var(--accent)" />
    </svg>
  );
}
