import { expect, test } from "@playwright/test";

// Phase 18: ready-made watchlists, your own list, the World screen and the Home card.
test("Watchlists, World and Kairos and Metis on Home", async ({ page, request }) => {
  await request.put("/api/settings", { data: { onboarding_done: true } });
  await page.goto("/watchlists");
  await expect(page.getByRole("heading", { name: "Watchlists", level: 1 })).toBeVisible();
  const lists = page.getByRole("navigation", { name: "Watchlists" });
  await expect(lists.getByText("Indices")).toBeVisible({ timeout: 60_000 });
  await lists.getByRole("link", { name: /Nifty IT/ }).click();
  await expect(page.getByRole("heading", { name: "Nifty IT", level: 2 })).toBeVisible();
  await expect(page.getByRole("link", { name: "TCS" })).toBeVisible();
  await page.getByRole("button", { name: /Copy to my lists/ }).click();
  await expect(page.getByRole("heading", { name: "My Nifty IT", level: 2 })).toBeVisible();
  await expect(page.getByText(/^10 stocks/)).toBeVisible();
  await page.getByLabel("Add stocks").fill("RELIANCE");
  await page.getByLabel("Add stocks").press("Enter");
  await expect(page.getByText("Added.")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByRole("link", { name: "RELIANCE" })).toBeVisible();
  await page.goto("/world");
  await expect(page.getByRole("heading", { name: "World", level: 1 })).toBeVisible();
  await expect(page.getByText("What past events actually did")).toBeVisible({ timeout: 60_000 });
  await page.goto("/");
  await expect(page.getByText("Kairos and Metis")).toBeVisible();
});
