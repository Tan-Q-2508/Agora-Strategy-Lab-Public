/** jsdom has no canvas: a minimal stand-in for echarts/core in tests. */
import { vi } from "vitest";

export const use = vi.fn();
export const init = vi.fn(() => ({ setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }));
