import { expect, test } from "@playwright/test";

// SPEC §14 on practice data: Metis researches, tests its ideas on unseen years and keeps what held up.
test("Metis thinks up ideas, tests them and writes them in its notebook", async ({ page, request }) => {
  await request.put("/api/settings", { data: { onboarding_done: true, markets: ["US"] } });
  const job = await (await request.post("/api/data/refresh", { data: { market: "US", timeframes: ["1d"] } })).json();
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${job.job_id}`)).json()).status, { timeout: 120_000 })
    .toBe("done");
  const created = await (await request.post("/api/strategies", { data: { name: "My RSI dips", market: "US", template_key: "rsi_mean_reversion" } })).json();
  const run = await (
    await request.post("/api/backtests", { data: { strategy_version_id: created.version.id, symbols: ["AAPL", "MSFT", "NVDA"] } })
  ).json();
  await expect
    .poll(async () => (await (await request.get(`/api/backtests/${run.run_id}`)).json()).status, { timeout: 120_000 })
    .toBe("done");

  await page.goto("/metis");
  await expect(page.getByRole("heading", { name: "Metis", level: 1 })).toBeVisible();
  await expect(page.getByText("No ideas yet")).toBeVisible();
  await page.getByRole("radio", { name: "On" }).click();
  await page.getByRole("button", { name: "Research now" }).click();
  await expect(page.getByRole("article", { name: "Only trade when a trend is under way" })).toBeVisible({ timeout: 150_000 });
  await expect(page.getByRole("article", { name: "Moving-average trend follower" })).toBeVisible();
  await expect(page.getByText("Exam years: Metis never saw these").first()).toBeVisible();
  await expect(page.getByText("How Metis thought")).toBeVisible();
  await page.screenshot({ path: "test-results/metis.png", fullPage: true });
});
