import { test, expect } from "@playwright/test";

// With the API mocked, the workspace should list the user's projects — proving
// the app renders real data end to end (routing → fetch → render) without any
// backend running.
test("workspace lists projects returned by the API", async ({ page }) => {
  await page.route("**/api/projects*", (r) =>
    r.fulfill({
      status: 200, contentType: "application/json",
      body: JSON.stringify([{
        id: "p1", name: "RAG hallucination survey", description: "",
        org_id: null, documents: 3, runs: 1, created_at: new Date().toISOString(),
      }]),
    }));
  await page.route("**/api/orgs", (r) =>
    r.fulfill({ status: 200, contentType: "application/json",
      body: JSON.stringify([{ id: "o1", name: "Personal workspace", personal: true, role: "owner" }]) }));
  await page.route("**/api/invites/accept", (r) =>
    r.fulfill({ status: 200, contentType: "application/json", body: '{"joined":0,"orgs":[]}' }));

  // Skip the landing gate so we land directly in the workspace.
  await page.addInitScript(() => sessionStorage.setItem("vs_entered", "1"));
  await page.goto("/");

  await expect(page.getByText("RAG hallucination survey").first()).toBeVisible();
});
