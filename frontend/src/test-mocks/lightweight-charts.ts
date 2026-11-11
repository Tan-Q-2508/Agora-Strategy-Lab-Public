/** jsdom has no canvas: a minimal stand-in for lightweight-charts in tests. */
import { vi } from "vitest";

const series = () => ({
  setData: vi.fn(),
  priceScale: () => ({ applyOptions: vi.fn() }),
  attachPrimitive: vi.fn(),
  detachPrimitive: vi.fn(),
  createPriceLine: vi.fn(() => ({})),
  removePriceLine: vi.fn(),
  priceToCoordinate: vi.fn(() => 0),
});
export const createChart = vi.fn(() => ({
  addSeries: vi.fn(series),
  removeSeries: vi.fn(),
  timeScale: () => ({ fitContent: vi.fn(), setVisibleLogicalRange: vi.fn(), timeToCoordinate: vi.fn(() => 0), options: () => ({ barSpacing: 6 }) }),
  subscribeCrosshairMove: vi.fn(),
  unsubscribeCrosshairMove: vi.fn(),
  remove: vi.fn(),
}));
export const createSeriesMarkers = vi.fn(() => ({ detach: vi.fn() }));
export const CandlestickSeries = {};
export const HistogramSeries = {};
export const LineSeries = {};
export const ColorType = { Solid: "solid" };
export const CrosshairMode = { Normal: 0 };
