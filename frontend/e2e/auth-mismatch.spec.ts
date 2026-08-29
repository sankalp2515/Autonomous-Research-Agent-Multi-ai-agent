import { test, expect } from "@playwright/test";

// Regression for the "Sign-in required, but no sign-in form" dead end: when the
// backend requires auth (401) but this build has no Supabase keys, the app must
// show a clear config notice, not a broken workspace.
test("shows a config notice when the API requires auth but the build has no Supabase keys", async ({ page }) => {
  await page.route("**/api/projects*", (r) =>
    r.fulfill({ status: 401, contentType: "application/json", body: '{"error":"unauthorized"}' }));
  await page.route("**/api/orgs", (r) => r.fulfill({ status: 401, body: "" }));
  await page.route("**/api/invites/accept", (r) => r.fulfill({ status: 401, body: "" }));

  await page.addInitScript(() => sessionStorage.setItem("vs_entered", "1"));
  await page.goto("/");

  await expect(page.getByText(/Sign-in is required, but not configured/i)).toBeVisible();
  await expect(page.getByText(/VITE_SUPABASE_URL/)).toBeVisible();
});
