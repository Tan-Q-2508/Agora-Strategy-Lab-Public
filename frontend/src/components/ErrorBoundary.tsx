import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "./ui/button";
import { Card } from "./ui/card";

interface State {
  error: Error | null;
}

/**
 * If a screen crashes, show a plain-English message instead of a blank page (CLAUDE.md §5).
 * The rest of the app (sidebar, top bar) keeps working.
 */
export class ErrorBoundary extends Component<{ children: ReactNode; resetKey?: string }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Screen crashed", error, info.componentStack);
  }

  componentDidUpdate(prev: { resetKey?: string }): void {
    if (prev.resetKey !== this.props.resetKey && this.state.error) this.setState({ error: null });
  }

  render(): ReactNode {
    if (!this.state.error) return this.props.children;
    return (
      <Card role="alert" className="mx-auto mt-10 max-w-xl gap-4 p-8">
        <h1 className="m-0 text-heading font-semibold">This screen ran into a problem</h1>
        <p className="m-0 text-body text-fg-muted">Nothing was lost. Reload the screen to try again; if it keeps happening, create a support bundle in Settings → Diagnostics.</p>
        <div className="flex gap-2.5">
          <Button variant="primary" onClick={() => window.location.reload()}>
            Reload
          </Button>
          <Button variant="ghost" onClick={() => this.setState({ error: null })}>
            Try without reloading
          </Button>
        </div>
        <details className="text-small text-fg-muted">
          <summary className="cursor-pointer">Details</summary>
          <code className="mt-2 block font-mono text-tiny whitespace-pre-wrap">{String(this.state.error.stack ?? this.state.error)}</code>
        </details>
      </Card>
    );
  }
}
