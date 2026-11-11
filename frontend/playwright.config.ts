import { defineConfig } from "@playwright/test";
import { existsSync } from "node:fs";

// The cloud image ships Chromium here; on other machines Playwright's own browser is used.
const chromium = "/opt/pw-browsers/chromium";

export default defineConfig({
  testDir: "./e2e",
  timeout: 180_000,
  retries: 0,
  workers: 1, // one practice server and database shared by the tests
  use: {
    baseURL: "http://127.0.0.1:8798",
    viewport: { width: 1440, height: 900 },
    launchOptions: existsSync(chromium) ? { executablePath: chromium } : {},
  },
  webServer: {
    command: "bash ../scripts/e2e_server.sh",
    url: "http://127.0.0.1:8798/api/health",
    timeout: 120_000,
    reuseExistingServer: false,
  },
});
