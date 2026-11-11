import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mockBackend, renderAt } from "../../test-utils";
import { VersionHistory } from "./VersionHistory";

afterEach(() => vi.unstubAllGlobals());

const V = (version: number, created_by: "user" | "kairos" | "metis", changes: string[], extra: Record<string, unknown> = {}) => ({
  id: version * 10, strategy_id: 3, version, definition: {}, content_hash: `h${version}`, created_at: 1_760_000_000_000 + version, note: "", created_by,
  author_label: { user: "You", kairos: "Kairos", metis: "Metis" }[created_by], parent_version_id: version > 1 ? (version - 1) * 10 : null, changes, evidence: {}, source: "", ...extra,
});

describe("Revisions", () => {
  it("shows who changed what, the evidence, and restores an old revision", async () => {
    const versions = [
      V(3, "metis", ["Added to buys: adx(period=14) at least 20."], { note: "Metis: trend strength", evidence: { verdict: "Held up. In the exam years it made ₹12,300 more after costs." } }),
      V(2, "kairos", ["Stop loss: 8% → 6%."]),
      V(1, "user", ["First version."]),
    ];
    const spy = mockBackend({
      "/api/strategies/3/versions": { versions },
      "POST /api/strategies/3/versions/10/restore": { version: V(4, "user", ["Removed from buys: adx(period=14) at least 20."], { note: "Restored version 1" }) },
    });
    const onLoad = vi.fn();
    renderAt(<VersionHistory strategyId={3} current={3} open onOpenChange={() => undefined} onLoad={onLoad} />);
    const v3 = await screen.findByRole("listitem", { name: "Version 3" });
    expect(within(v3).getByText("Metis")).toBeInTheDocument();
    expect(within(v3).getByText("Added to buys: adx(period=14) at least 20.")).toBeInTheDocument();
    expect(within(v3).getByText(/Evidence: Held up/)).toBeInTheDocument();
    expect(within(v3).queryByRole("button", { name: /Restore/ })).toBeNull(); // the current one
    const v2 = screen.getByRole("listitem", { name: "Version 2" });
    expect(within(v2).getByText("Kairos")).toBeInTheDocument();
    const v1 = screen.getByRole("listitem", { name: "Version 1" });
    expect(within(v1).queryByText("First version.")).toBeNull();
    fireEvent.click(within(v1).getByRole("button", { name: /Restore/ }));
    await waitFor(() => expect(onLoad).toHaveBeenCalled());
    expect(spy.mock.calls.some(([url, init]) => String(url).endsWith("/api/strategies/3/versions/10/restore") && (init as RequestInit | undefined)?.method === "POST")).toBe(true);
  });
});
