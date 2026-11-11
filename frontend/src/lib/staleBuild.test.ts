import { describe, expect, it } from "vitest";
import { shouldReload } from "./staleBuild";

function memory(): Pick<Storage, "getItem" | "setItem"> {
  const m = new Map<string, string>();
  return { getItem: (k) => m.get(k) ?? null, setItem: (k, v) => void m.set(k, v) };
}

describe("reload after an update", () => {
  it("reloads once, then not again within a minute", () => {
    const s = memory();
    expect(shouldReload(1_000_000, s)).toBe(true);
    expect(shouldReload(1_030_000, s)).toBe(false);
    expect(shouldReload(1_061_000, s)).toBe(true);
  });

  it("does nothing when storage is blocked", () => {
    const blocked = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => undefined,
    };
    expect(shouldReload(1_000_000, blocked)).toBe(false);
  });
});
