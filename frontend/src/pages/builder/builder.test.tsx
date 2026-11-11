import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { blankVisual, conditionText, defaultCompare, operandText, type VisualDefinition } from "../../lib/strategy";
import { RulesPanel } from "./RulesPanel";

function Harness({ onChange }: { onChange: (d: VisualDefinition) => void }) {
  const [d, setD] = useState(blankVisual("IN"));
  return (
    <RulesPanel
      d={d}
      issues={[{ path: ["entry", "long", "right", "value"], where: "Buy rule › right side", message: "must be at least 0.", hint: "Use a larger value.", severity: "error" }]}
      onChange={(n) => {
        setD(n);
        onChange(n);
      }}
    />
  );
}

describe("block builder", () => {
  it("adds a buy rule that reads like a sentence and shows its fix hint", () => {
    let last: VisualDefinition | null = null;
    render(<Harness onChange={(d) => (last = d)} />);
    fireEvent.click(screen.getByRole("button", { name: "Add a buy rule" }));
    expect(last!.entry.long).toEqual(defaultCompare());
    expect(screen.getByText(/must be at least 0\. Use a larger value\./)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Left side: RSI\(14\)/ })).toBeInTheDocument();
  });

  it("describes rules in plain words, including parameters by name", () => {
    const params = [{ name: "level", label: "Oversold level", type: "int" as const, default: 30, min: 5, max: 45 }];
    expect(operandText({ kind: "number", value: "$level" }, undefined, params)).toBe("Oversold level");
    expect(conditionText(defaultCompare())).toBe("RSI(14) crosses below 30");
    expect(operandText({ kind: "price", field: "close", offset: 1, times: 1.02 })).toBe("Close × 1.02 (1 candle ago)");
    expect(operandText({ kind: "price", field: "close", chart: "1w" })).toBe("Close on the weekly chart");
  });

  it("offers a short-sell rule only when shorting is allowed", () => {
    render(<Harness onChange={() => undefined} />);
    expect(screen.queryByRole("button", { name: "Add a short-sell rule" })).not.toBeInTheDocument(); // India delivery
  });
});
