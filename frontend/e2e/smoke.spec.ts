import { expect, test } from "@playwright/test";

// SPEC §12 loop on practice data: create from a template → backtest → read the results.
test("create a strategy from a template, backtest it and see results", async ({ page, request }) => {
  await request.put("/api/settings", { data: { onboarding_done: true, markets: ["US"] } });
  const job = await (await request.post("/api/data/refresh", { data: { market: "US", timeframes: ["1d"] } })).json();
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${job.job_id}`)).json()).status, { timeout: 120_000 })
    .toBe("done");

  await page.goto("/strategies");
  await page.getByRole("button", { name: "Use this" }).first().click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("dialog").getByRole("radio", { name: "US" }).click();
  await page.getByRole("button", { name: "Create strategy" }).click();

  await expect(page).toHaveURL(/\/strategies\/\d+$/);
  await expect(page.getByText("Everything looks right")).toBeVisible();
  await page.getByRole("button", { name: "Backtest this" }).click();

  await expect(page).toHaveURL(/\/backtests\/new\?strategy=\d+/);
  await page.getByRole("radio", { name: "10 years" }).click();
  await page.getByRole("button", { name: "Run backtest" }).click();

  await expect(page).toHaveURL(/\/backtests\/\d+$/, { timeout: 120_000 });
  await expect(page.getByText("Total return")).toBeVisible();
  await expect(page.getByText(/^This strategy (made|lost) /)).toBeVisible();
  await expect(page.getByRole("heading", { name: "How much to trust this" })).toBeVisible();
  await page.getByRole("tab", { name: "Trades" }).click();
  await expect(page.getByRole("link", { name: "Export CSV" })).toBeVisible();

  // The AI helper (canned replies in this test) explains the results as it writes.
  await page.getByRole("button", { name: "Explain this backtest" }).click();
  await expect(page.getByText(/canned reply from the fake AI helper/)).toBeVisible();
  await expect(page.getByText("AI-generated. Check important numbers.")).toBeVisible();

  // …then paper trade it (a fast replay on practice data) and stop it.
  await page.getByRole("link", { name: "Paper trade" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.getByRole("dialog").getByRole("button", { name: "Start paper trading" }).click();
  await expect(page).toHaveURL(/\/paper\/\d+$/);
  await expect(page.getByRole("heading", { name: "Prices and trades" })).toBeVisible();
  await expect(page.getByText("Practice replay", { exact: true })).toBeVisible();
  await expect(page.getByText(/^(Up to date|Waiting for the)/)).toBeVisible({ timeout: 60_000 });
  await expect(page.getByText(/Paper trading started with \d+ stock/)).toBeVisible();
  await page.getByRole("button", { name: "Stop" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Stop paper trading" }).click();
  await expect(page.getByText("Stopped", { exact: true })).toBeVisible();
});
