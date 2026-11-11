import { describe, expect, it } from "vitest";
import { formatCompactMoney, formatCountdown, formatMoney, formatPercent, formatSignedMoney } from "./format";

describe("money formatting (GLOSSARY.md)", () => {
  it("uses lakh/crore grouping for rupees", () => {
    expect(formatMoney(1234567.89, "INR")).toBe("₹12,34,567.89");
    expect(formatMoney(1234567.89, "USD")).toBe("$1,234,567.89");
  });
  it("compacts to L / Cr and K / M", () => {
    expect(formatCompactMoney(1_230_000, "INR")).toBe("₹12.3 L");
    expect(formatCompactMoney(12_000_000, "INR")).toBe("₹1.2 Cr");
    expect(formatCompactMoney(1_000_000, "INR")).toBe("₹10 L");
    expect(formatCompactMoney(1_200_000, "USD")).toBe("$1.2M");
    expect(formatCompactMoney(100_000, "USD")).toBe("$100K");
    expect(formatCompactMoney(-250_000, "INR")).toBe("−₹2.5 L");
  });
  it("signs changes with a true minus", () => {
    expect(formatSignedMoney(3210, "INR", 0)).toBe("+₹3,210");
    expect(formatSignedMoney(-186.4, "USD")).toBe("−$186.40");
  });
});

describe("percent and countdown", () => {
  it("always shows a sign", () => {
    expect(formatPercent(0.042)).toBe("+4.2%");
    expect(formatPercent(-0.018)).toBe("−1.8%");
    expect(formatPercent(0)).toBe("0.0%");
  });
  it("formats countdowns compactly", () => {
    expect(formatCountdown(4 * 3600 + 12 * 60)).toBe("4h 12m");
    expect(formatCountdown(2 * 86400 + 3 * 3600)).toBe("2d 3h");
    expect(formatCountdown(45)).toBe("45s");
    expect(formatCountdown(-5)).toBe("0s");
  });
});
