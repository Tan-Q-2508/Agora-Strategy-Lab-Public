import "@fontsource-variable/inter";
import "@fontsource/jetbrains-mono/400.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router";
import App from "./App";
import { reloadOnStaleBuild } from "./lib/staleBuild";
import { ThemeProvider } from "./lib/theme";
import "./styles/index.css";

reloadOnStaleBuild();

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <ThemeProvider>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </ThemeProvider>
    </StrictMode>,
  );
}
