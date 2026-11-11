import { expect, test } from "@playwright/test";

// SPEC §13 on practice data: the chart toggle, a chat request that runs the lab, and the desk.
test("Kairos reads a chart, runs a backtest from chat and starts its desk", async ({ page, request }) => {
  await request.put("/api/settings", { data: { onboarding_done: true, markets: ["US"] } });
  const job = await (await request.post("/api/data/refresh", { data: { market: "US", timeframes: ["1d"] } })).json();
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${job.job_id}`)).json()).status, { timeout: 120_000 })
    .toBe("done");

  // 1. Charts: switching Kairos on draws its reading and shows the verdict panel.
  await page.goto("/charts?symbol=AAPL&market=US&tf=1d&kairos=1");
  const panel = page.getByRole("complementary", { name: "Kairos's reading of this chart" });
  await expect(panel).toBeVisible({ timeout: 60_000 });
  await expect(panel.getByText("Kairos reads AAPL")).toBeVisible();
  await expect(panel.getByText(/^Score/)).toBeVisible();
  await expect(panel.getByText(/Likely range · next \d+ candles/)).toBeVisible();

  // 2. Chat: one plain-English request creates a strategy, backtests it and opens the results.
  await page.keyboard.press("Control+j");
  const chat = page.getByRole("complementary", { name: /Kairos, your trading agent/ });
  await expect(chat).toBeVisible();
  await chat.getByLabel("Message Kairos").fill("Backtest MACD momentum on AAPL and MSFT over 3 years");
  await chat.getByRole("button", { name: "Send" }).click();
  await expect(chat.getByText(/^Created “/)).toBeVisible({ timeout: 60_000 });
  await expect(page).toHaveURL(/\/backtests\/\d+$/, { timeout: 120_000 });
  await expect(page.getByText("Total return", { exact: true })).toBeVisible();
  await expect(chat.getByText("Kairos is a research tool, not financial advice. Paper money only.").first()).toBeVisible();
  await page.keyboard.press("Control+j");

  // 3. The desk: Kairos paper trades a watchlist on its own and keeps a diary.
  await page.goto("/paper/desk");
  await expect(page.getByRole("heading", { name: "Kairos desk", level: 1 })).toBeVisible();
  await page.getByRole("radio", { name: "US" }).click();
  await page.getByRole("button", { name: "Start the Kairos desk" }).click();
  await expect(page).toHaveURL(/\/paper\/desk\/\d+$/, { timeout: 120_000 });
  await expect(page.getByText("Kairos trades this on its own")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Kairos's diary" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "What Kairos learned" })).toBeVisible();
  await page.getByRole("button", { name: "Stop" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Stop paper trading" }).click();
  await expect(page.getByText("Stopped", { exact: true })).toBeVisible();
});
