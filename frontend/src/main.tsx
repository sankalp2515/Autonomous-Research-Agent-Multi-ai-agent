import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import ErrorBoundary from "./components/ErrorBoundary";
import { initTelemetry } from "./telemetry";
import "./styles.css";
// Optional skin, scoped to :root[data-skin="glass"]. See src/skin.ts to revert.
import "./skins/glass.css";
import { applySkin } from "./skin";

initTelemetry();
applySkin();

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </React.StrictMode>
);
