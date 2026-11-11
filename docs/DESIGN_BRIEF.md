# DESIGN_BRIEF: how Agora should look and feel

## 1. The bar
Agora should feel like a **premium, modern product**, in the league of Linear, Arc, Stripe
Dashboard, and Claude.ai, not a hobby tool. Calm, confident, fast. A non-technical person
should feel in control within a minute.

## 2. Personality
- **Calm:** warm neutrals, generous whitespace, no visual noise.
- **Precise:** crisp numbers, aligned tables, honest charts.
- **Alive:** subtle, purposeful motion; live data that breathes, never flickers.
- **Friendly:** plain words, helpful empty states, no jargon without a tooltip.

## 3. Visual direction (starting point; final approved in Phase 1.2)
- **Light theme (default):** warm off-white canvas (~#FAF9F6), white surfaces, soft
  warm-gray borders, **orange accent** (~#E8692C range) used sparingly for primary actions
  and focus. Matte, solid colors; no heavy gradients.
- **Dark theme:** warm charcoal (not pure black), same accent, tuned contrast.
- **Semantic colors:** profit green and loss red tuned to be color-blind-safe (pair with
  ▲/▼ icons and +/− signs; never color alone). Amber for warnings, blue for info.
- **Typography:** a modern geometric/neo-grotesque sans for UI (e.g. Inter, Geist, or
  similar), **tabular figures** for all numbers, a mono for code (e.g. JetBrains Mono or
  Geist Mono). Clear type scale; numbers in headline cards large and confident.
- **Shape:** 10–14 px radii on cards, 8 px on controls; soft layered shadows; 1 px hairlines.
- **Icons:** one consistent outline set (Lucide).
- **Density:** comfortable by default; tables offer a compact toggle.

## 4. Layout rules
- Left sidebar navigation (collapsible) + top bar (market status pills for India/US with
  live countdown, data freshness, AI-ready pill, command palette trigger).
- **Fixed-size panels with no overflow or resizing** (user preference): content scrolls
  inside panels, the page itself does not jump. Grid-based dashboards.
- Minimum supported viewport 1366×768; looks best at 1440–1920 wide.
- Every screen has a single clear primary action.

## 5. Motion
- Framer Motion. Durations 150–250 ms for UI, 400–600 ms for page/hero transitions;
  spring easing for drag-and-drop blocks.
- Numbers **tick** smoothly when they change (equity, P&L).
- New fills slide into the feed; chart markers fade in.
- Skeleton shimmer for loading; no spinners longer than 300 ms without a skeleton.
- Respect `prefers-reduced-motion` (disable non-essential animation).

## 6. Charts (the hero of the app)
- **Price charts:** TradingView Lightweight Charts, themed from tokens: candles, volume
  histogram, indicator overlays, entry/exit markers with hover cards, crosshair with a
  floating OHLC legend.
- **Analytics:** ECharts, themed: equity vs benchmark (area with gradient fill under the
  strategy line), underwater drawdown, monthly returns heatmap, P&L distribution,
  charges donut, sweep heatmap.
- Charts animate on first draw, support zoom/pan, and keep axes readable (₹ lakh/crore
  formatting for India, $K/$M for US).
- Every chart has a one-line plain-English caption ("Your strategy vs simply holding the
  Nifty 50").

## 7. Key screens: what makes each great
- **Home:** at-a-glance market status, live paper sessions as rich cards with sparklines,
  "continue where you left off".
- **Strategy builder:** the visual blocks read like a sentence; drag feels physical;
  validation is gentle and inline; the preview chart updates live as rules change.
- **Backtest results:** headline cards → equity chart → honesty panel → details. The
  story reads top to bottom. The plain-English summary sits right under the cards.
- **Paper trading live:** feels alive: ticking equity, pulsing freshness dot, smooth
  fills feed, positions table with live P&L flashes (subtle).

## 8. Words
Use `GLOSSARY.md`. Buttons are verbs ("Run backtest", "Start paper trading"). Errors say
what happened and what to do. Never blame the user.

## 9. Design QA checklist (Phase 8.2)
Checked 2026-10-21 in the cloud on practice data (every screen at 1366×768, light and dark;
no console errors, no page-level horizontal scroll). Fixes made: Data table overflow, headline
numbers wrapping, overlapping date labels on long charts, long parameter labels in blocks.
- [x] Consistent tokens; no hard-coded colors or sizes in components
- [x] WCAG AA contrast in both themes; focus rings visible
- [x] Full keyboard navigation; command palette covers main actions (D-54)
- [x] Tabular figures on every number; correct ₹/$ formatting and locale grouping
- [x] Empty, loading, error and success states for every screen and panel
- [x] No layout shift on data load; panels fixed-size; no page-level horizontal scroll
- [x] Motion smooth; reduced-motion respected (`MotionConfig reducedMotion="user"`, CSS media
      query, charts skip animation). 60 fps to be confirmed on the laptop.
- [x] Profit/loss never conveyed by color alone (arrows + signs)
- [x] Charts themed in both modes; tooltips readable; captions present
- [ ] Looks right at 1366×768 ✔, 1440×900 ✔, 1920×1080 (centred max width; confirm on the
      laptop's own screen, ACCEPTANCE §8)

## 10. Claude Design brief (Phase 1.1)

`/design` was not available in the cloud session, so the directions were drawn as a design
canvas (Claude artifact, private to the user):
**https://claude.ai/artifact/VQFGT86LKQkQg5dyDTC39V**. The source of every artboard is
saved in `docs/design/directions/` (`*.dc.html`, inline styles = exact values), so later
sessions can implement the approved one without the link.

**Brief used:** premium, calm, warm, matte; light by default with an orange accent (D-16);
Inter/Geist-class sans with tabular figures; profit/loss never by color alone; screens:
Home, Strategy builder, Backtest results, Paper trading live; 1366–1920 px desktop.

### Directions offered (Phase 1.2 decision pending)
| | A · Warm Studio (recommended) | B · Graphite | C · Terracotta Editorial |
|---|---|---|---|
| Feel | Calm, friendly, soft shadows, roomy | Crisp pro tool (Linear-like), hairlines, dense | Warm report, cream paper, generous space |
| Canvas / surface | #FAF9F6 / #FFFFFF | #F5F5F3 / #FFFFFF | #F6F1E9 / #FFFDF9 |
| Border | #E7E3DA | #E2E2DE | #E6DDCF |
| Text / muted | #1F1D1A / #5F5A52 | #18181A / #5C5C63 | #2A2420 / #6A5F55 |
| Accent (charts, focus) | #E8692C | #D9541E | #C2532F |
| Button fill (white text, AA) | #C4501A | #18181A | #A9452A |
| Profit / loss | #1F7A4D / #B42318 | #18794E / #C0362C | #2E7351 / #A8322A |
| Dark canvas / surface | #1A1917 / #232220 | #111113 / #18181B | #1E1B18 / #27231F |
| Dark accent / profit / loss | #F07A3E / #4CC38A / #F0645A | #F26B33 / #3DD68C / #FF6B5E | #E07A55 / #5DBB8A / #EE7468 |
| Type | Inter + JetBrains Mono (code) | Geist + Geist Mono (numbers) | Fraunces (headings, hero numbers) + Inter |
| Radii | 8 controls / 12–14 cards / pills | 6 / 10 | 10 / 20–24 / pill buttons |
| Elevation | e1 0 1px 2px rgba(31,29,26,.05); e2 + 0 8px 24px .07; e3 0 12px 40px .14 | none (1 px hairlines) | warm-tinted soft shadows |
| Motion | 150 / 200 / 450 ms, cubic-bezier(.2,.8,.2,1), spring 400/30 for blocks, 600 ms number tick | 120 / 180 / 350 ms, ease-out | 200 / 280 / 550 ms, fades + soft rises |

Accessibility note shared by all three: the bright accent (#E8692C etc.) fails AA as a
background for white text, so primary buttons use the darker "button fill" token and the
bright accent is reserved for chart lines, focus rings and highlights.

### Approved direction
**A · Warm Studio**, approved by the user on 2026-10-21 (D-25). Implemented in
`frontend/src/styles/index.css` (CSS variables for light + `[data-theme="dark"]`, mapped to
Tailwind v4 utilities such as `bg-surface`, `text-fg-muted`, `bg-accent-strong`,
`text-profit`, `shadow-e2`, `rounded-card`) and `frontend/src/lib/motion.ts`. Components use
only these tokens. Fonts are bundled locally (Inter Variable, JetBrains Mono) so the app makes
no request to Google Fonts.

## 11. The logo (Phase 11, D-75)

Designed on a Claude Design canvas (private to the user):
**https://claude.ai/artifact/HnWnAs2BJUn3hM5Nkjyvt7** (the mark, sizes and themes, in the app,
construction and the Kairos mark).

- **Idea:** a Greek capital **Λ**, the roof of the agora's stoa and the shape of an A, with one
  **candlestick** standing under it. The candle's body sits where the A's crossbar would be, so
  the whole reads as "A" while saying *market* and *the moment* (Kairos).
- **Geometry (32-unit box):** Λ `M8 24.6 16 7.2l8 17.4`, stroke 2.6, round caps and joins;
  wick `M16 12.4v12.2`, stroke 1.4; body 3.4 × 5.6 at (14.3, 15.6), radius 0.85. At 24 px and
  below: Λ `M7.6 25 16 6.6l8.4 18.4` stroke 3.2, wick stroke 2, body 4.2 × 5.8 at (13.9, 16.4).
- **Colours:** tile `--logo-tile` (ink #1F1D1A light; #2A2825 dark), roof `--logo-roof`
  (#FAF9F6 / #F4EFE6), candle `--accent`. Wordmark: Inter Bold, tracking −0.02 em.
- **Files:** `frontend/src/components/shell/Logo.tsx` (sidebar, welcome screen),
  `frontend/public/favicon.svg` (small-size geometry), `frontend/src/components/kairos/KairosMark.tsx`
  (the same candle in a ring that opens just before one o'clock).

## 12. The Metis mark (Phase 12, docs/METIS.md)

Metis's emblem is Kairos's ring, closed (Metis thinks between the decisive moments rather than at
one), with a four-pointed spark inside in the accent colour: an idea. Same 24-unit grid, stroke
and colours as the Kairos mark, so the two read as a pair (`components/metis/MetisMark.tsx`).
The sidebar uses a lightbulb icon for the Metis screen, next to the other plain line icons.

## Long content scrolls inside its box (D-212, the user, 2026-11-06)

Every list, feed and table that can grow sits in a `ScrollBox` with a fixed maximum height and
scrolls inside it; the page itself never grows with the data. Pick the height for the content:
`xs` 200 px (short side lists), `sm` 280 (a list inside a card), `md` 380, `lg` 480 (tables),
`xl` 600 (the Kairos diary, session grids), `page` (a page's main list: the window less the
header). Table headers stay in view while the rows scroll.

