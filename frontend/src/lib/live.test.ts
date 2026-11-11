import { describe, expect, it, vi } from "vitest";
import { onHello } from "./live";

describe("the live channel", () => {
  it("reloads the tab only when Agora has restarted (D-111)", () => {
    const reload = vi.fn();
    onHello(111, reload); // first hello: remember this server
    onHello(111, reload); // a dropped connection to the same server: nothing to do
    expect(reload).not.toHaveBeenCalled();
    onHello(222, reload); // Agora was restarted: load the new version
    expect(reload).toHaveBeenCalledTimes(1);
    onHello(undefined, reload);
    expect(reload).toHaveBeenCalledTimes(1);
  });
});
