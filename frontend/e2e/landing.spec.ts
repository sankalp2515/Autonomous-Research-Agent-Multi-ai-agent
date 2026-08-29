import { test, expect } from "@playwright/test";

// The landing page is where conversion happens — it must show the product's
// promise (a verified claim + its evidence) and let a visitor into the app.
test.describe("Landing page", () => {
  test("shows the value proposition and the verified-claim proof card", async ({ page }) => {
    await page.goto("/");

    // Headline thesis.
    await expect(
      page.getByRole("heading", { name: /can.?t.*make things up/i })
    ).toBeVisible();

    // The rendered proof card — the differentiator, shown on the fold.
    // Anchor on the proof card's own nodes, not on the words: "verified claim"
    // appears in the copy several times over, and a text match makes the gate
    // fail on a marketing edit that changed nothing about the card.
    await expect(page.locator(".vlp-proof-title")).toHaveText("Verified claim");
    await expect(page.locator(".vlp-proof-nli")).toContainText("0.94");

    // Fabrication-vs-verified contrast band.
    await expect(page.getByText("Typical AI research tool")).toBeVisible();
  });

  test("‘Start researching’ enters the workspace", async ({ page }) => {
    // The app loads its shell after entry — mock the calls it makes so no
    // backend is needed.
    await page.route("**/api/projects*", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
    await page.route("**/api/orgs", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: "[]" }));
    await page.route("**/api/invites/accept", (r) =>
      r.fulfill({ status: 200, contentType: "application/json", body: '{"joined":0,"orgs":[]}' }));

    await page.goto("/");
    await page.getByRole("button", { name: /start researching/i }).click();

    // Landing hero is gone; the app shell (⌘K search) is present.
    await expect(page.getByRole("heading", { name: /can.?t.*make things up/i })).toHaveCount(0);
    await expect(page.getByText(/Search/).first()).toBeVisible();
  });
});
