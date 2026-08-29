import { Component, type ErrorInfo, type ReactNode } from "react";
import { captureError } from "../telemetry";

type Props = { children: ReactNode };
type State = { error: Error | null };

// App-wide crash guard. Without this, a render throw in ANY view unmounts the
// whole tree and the user is left on a white screen with no way back. Here we
// catch it, report it to telemetry, and show a branded recovery surface that
// lets the user reload or return to a known-good route.
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    captureError(error, { componentStack: info.componentStack });
  }

  private reset = () => {
    // Clear the hash back to the workspace root so we don't re-crash on the
    // same route, then reload for a clean tree.
    window.location.hash = "#/";
    window.location.reload();
  };

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="crash">
        <div className="crash-card">
          <span className="logo crash-logo">V</span>
          <h1>Something broke on this screen</h1>
          <p>
            This isn’t your data — your projects and corpus are safe on the server.
            The page hit an unexpected error and stopped rendering. Reloading
            usually clears it.
          </p>
          <div className="crash-actions">
            <button className="btn btn-accent" onClick={this.reset}>Reload workspace</button>
            <a className="btn btn-ghost" href="mailto:support@veriscope.app">Contact support</a>
          </div>
          <details className="crash-details">
            <summary>Technical details</summary>
            <pre>{this.state.error.message}</pre>
          </details>
        </div>
      </div>
    );
  }
}
