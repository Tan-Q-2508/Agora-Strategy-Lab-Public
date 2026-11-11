/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

// The built app (dist/) is committed and served by FastAPI, so the user never needs Node
// (D-12). During development, `npm run dev` proxies API calls to the running backend.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    // Monaco's export map hides its CSS files; this alias reaches its ESM sources directly
    // so only the editor parts Agora needs are bundled (see src/lib/monacoBundle.ts).
    alias: { "monaco-esm": fileURLToPath(new URL("./node_modules/monaco-editor/esm/vs", import.meta.url)) },
  },
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765",
      "/ws": { target: "ws://127.0.0.1:8765", ws: true },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // Served from the user's own disk, not the internet, so a larger first chunk is fine;
    // chart-heavy screens are still split out and loaded on demand.
    chunkSizeWarningLimit: 800,
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./src/test-setup.ts"],
    css: false,
    testTimeout: 30_000,
    maxWorkers: 2, // the laptop: 16 test files at once starve each other (all pass with 2)
  },
});
