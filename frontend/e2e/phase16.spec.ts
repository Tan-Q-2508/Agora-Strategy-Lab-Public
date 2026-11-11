import { expect, test } from "@playwright/test";

// Phase 16 on practice data: the look-ahead check in the editor, the tear sheet on a backtest,
// and a momentum portfolio planned on the whole index.
test("Look-ahead check, tear sheet and a momentum portfolio", async ({ page, request }) => {
  await request.put("/api/settings", { data: { onboarding_done: true, markets: ["US"] } });
  const job = await (await request.post("/api/data/refresh", { data: { market: "US", timeframes: ["1d"] } })).json();
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${job.job_id}`)).json()).status, { timeout: 120_000 })
    .toBe("done");
  const made = await (await request.post("/api/strategies", { data: { name: "Dip buyer", market: "US", template_key: "rsi_mean_reversion" } })).json();

  // the look-ahead check, one click in the editor
  await page.goto(`/strategies/${made.strategy.id}`);
  await page.getByRole("button", { name: "Run the check" }).click();
  await expect(page.getByText("No look-ahead found.")).toBeVisible({ timeout: 150_000 });

  // the tear sheet of a backtest
  const run = await (await request.post("/api/backtests", { data: { strategy_version_id: made.version.id, symbols: ["AAPL", "NVDA", "SPY"] } })).json();
  await expect
    .poll(async () => (await (await request.get(`/api/backtests/${run.run_id}`)).json()).status, { timeout: 150_000 })
    .toBe("done");
  await page.goto(`/backtests/${run.run_id}`);
  await expect(page.getByText("How much could be luck")).toBeVisible();
  await expect(page.getByText(/plausible \(90% range\)/)).toBeVisible();
  await expect(page.getByText("The deepest falls")).toBeVisible();

  // a momentum portfolio: one sleeve on the whole index
  await page.goto("/portfolio");
  await page.getByRole("button", { name: "New portfolio" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("radio", { name: "US ($)" }).click();
  await dialog.getByRole("radio", { name: "Momentum" }).click();
  await dialog.getByLabel("Budget").fill("50000");
  await dialog.getByRole("button", { name: "Plan it" }).click();
  await expect(page.getByText(/the whole index \(re-ranked monthly\)/).first()).toBeVisible({ timeout: 150_000 });
  await expect(page.getByText("Do the sleeves still hold up?")).toBeVisible();
  await page.screenshot({ path: "test-results/phase16.png", fullPage: true });
});
