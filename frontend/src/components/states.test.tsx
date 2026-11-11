import { fireEvent, render, screen } from "@testing-library/react";
import { Database } from "lucide-react";
import { describe, expect, it, vi } from "vitest";
import { EmptyState, ErrorState } from "./states";
import { Change } from "./ui/change";

describe("state components", () => {
  it("error state shows message, action, retry and hidden details", () => {
    const retry = vi.fn();
    render(<ErrorState error={{ code: "X", message: "Yahoo is limiting requests.", action: "No action needed.", detail: "429 Too Many Requests" }} onRetry={retry} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Yahoo is limiting requests.");
    expect(screen.getByText("No action needed.")).toBeInTheDocument();
    expect(screen.getByText("Details")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalledOnce();
  });

  it("empty state has a title, explanation and action", () => {
    render(<EmptyState icon={Database} title="No prices" body="Download them." action={<button>Download</button>} />);
    expect(screen.getByText("No prices")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download" })).toBeInTheDocument();
  });

  it("profit and loss never rely on color alone", () => {
    const { rerender } = render(<Change value={5} text="+₹5" />);
    expect(screen.getByText("▲", { exact: false })).toBeInTheDocument();
    expect(screen.getByText("up", { exact: false })).toBeInTheDocument();
    rerender(<Change value={-5} text="−₹5" />);
    expect(screen.getByText("▼", { exact: false })).toBeInTheDocument();
  });
});
