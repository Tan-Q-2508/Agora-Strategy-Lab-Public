import { expect, test } from "@playwright/test";

// SPEC §16 on practice data: a budget becomes a portfolio plan, opportunities are searched for.
test("A budget becomes a portfolio plan, and new opportunities are searched for", async ({ page, request }) => {
  await request.put("/api/settings", { data: { onboarding_done: true, markets: ["US"] } });
  const job = await (await request.post("/api/data/refresh", { data: { market: "US", timeframes: ["1d"] } })).json();
  await expect
    .poll(async () => (await (await request.get(`/api/jobs/${job.job_id}`)).json()).status, { timeout: 120_000 })
    .toBe("done");
  await request.post("/api/strategies", { data: { name: "Trend rider", market: "US", template_key: "ma_crossover" } });

  await page.goto("/portfolio");
  await expect(page.getByRole("heading", { name: "Portfolio", level: 1 })).toBeVisible();
  await page.getByRole("button", { name: "New portfolio" }).first().click();
  const dialog = page.getByRole("dialog");
  await dialog.getByRole("radio", { name: "US ($)" }).click();
  await dialog.getByLabel("Budget").fill("1000");
  await dialog.getByRole("button", { name: "Plan it" }).click();
  await expect(page.getByRole("heading", { name: "US portfolio", level: 1 })).toBeVisible();
  // practice prices are random, so the honest answer is often "nothing passed"; either way a plan appears
  await expect(page.getByText(/Nothing passed the tests yet|Invested/).first()).toBeVisible({ timeout: 150_000 });
  await expect(page.getByText(/Portfolio created/)).toBeVisible();
  await page.getByRole("button", { name: "Find new opportunities" }).click();
  await expect(page.getByText(/Tried \d+ strateg/)).toBeVisible({ timeout: 150_000 });
  await page.screenshot({ path: "test-results/portfolio.png", fullPage: true });
});
