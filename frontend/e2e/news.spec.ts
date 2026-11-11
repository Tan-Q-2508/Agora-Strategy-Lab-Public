import { expect, test } from "@playwright/test";

// Phase 10: the live News screen on practice news, and its place on Home.
test("News shows risk gauges, headlines and the desk's news guard", async ({ page, request }) => {
  await request.put("/api/settings", { data: { onboarding_done: true } });
  await page.goto("/news");
  await expect(page.getByRole("heading", { name: "News", level: 1 })).toBeVisible();
  for (const place of ["India", "US", "World"]) {
    await expect(page.getByText(`News risk · ${place}`)).toBeVisible({ timeout: 60_000 });
  }
  await expect(page.getByRole("meter", { name: "News risk" }).first()).toBeVisible();
  await expect(page.getByText("Kairos's news guard")).toBeVisible();
  // practice headlines arrive, read for topic and severity
  await expect(page.getByText("Oil prices rise as OPEC+ extends output cuts").first()).toBeVisible({ timeout: 60_000 });
  await page.getByRole("button", { name: "Geopolitics" }).click();
  await expect(page.getByText("Border tensions flare between two neighbours; markets watch closely").first()).toBeVisible();
  await page.getByPlaceholder("Search headlines").fill("ceasefire");
  await expect(page.getByText("Ceasefire talks make progress, officials say").first()).toBeVisible();
  await page.goto("/");
  await expect(page.getByText("News risk")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open News" })).toBeVisible();
});
