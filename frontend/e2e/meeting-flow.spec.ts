import { expect, test } from "@playwright/test";
import path from "node:path";

const DEMO_AUDIO = path.resolve(__dirname, "../../backend/app/seed_data/demo_meeting.wav");

test("upload a meeting, watch it process, review notes, board and ask", async ({ page }) => {
  const email = `e2e-${Date.now()}@example.com`;

  await page.goto("/register");
  await page.getByLabel("Name").fill("E2E Tester");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("e2e-password-123");
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page.getByRole("heading", { name: "Meetings" })).toBeVisible();
  await expect(page.getByText("No meetings yet")).toBeVisible();

  await page.getByRole("button", { name: "New meeting" }).first().click();
  await page.getByLabel("Title").fill("E2E Launch Sync");
  await page.getByLabel("Audio or video file").setInputFiles(DEMO_AUDIO);
  await page.getByRole("button", { name: "Upload & process" }).click();

  // Detail page: live pipeline progress, then AI notes
  await page.waitForURL(/\/meetings\/[0-9a-f]{32}$/);
  await expect(page.getByRole("heading", { name: /E2E Launch Sync/ })).toBeVisible();
  await expect(page.getByText("Executive summary")).toBeVisible({ timeout: 90_000 });
  await expect(page.getByText("Ready")).toBeVisible();
  const items = page.getByTestId("action-items").locator("li");
  await expect(items).toHaveCount(4);
  await expect(page.getByText("Fix the payment bugs")).toBeVisible();
  await expect(page.getByText(/We decided to keep the pricing/)).toBeVisible();

  // Transcript synced with waveform; rename a speaker
  await page.getByRole("tab", { name: "Transcript" }).click();
  await expect(page.getByRole("list", { name: "Transcript" }).getByRole("button")).toHaveCount(13);
  await page.getByText("How long will the payment fixes take?").click();
  await page.getByRole("button", { name: "Rename Speaker 2" }).click();
  await page.getByLabel("New name for Speaker 2").fill("Marcus");
  await page.getByRole("button", { name: "Save name" }).click();
  await expect(page.getByRole("list", { name: "Speakers" }).getByText("Marcus")).toBeVisible();

  // Kanban board
  await page.getByRole("link", { name: "Task board" }).click();
  await expect(page.getByTestId("column-todo").getByText("Fix the payment bugs")).toBeVisible();
  await page.getByLabel("Status for Fix the payment bugs").selectOption("done");
  await expect(page.getByTestId("column-done").getByText("Fix the payment bugs")).toBeVisible();

  // Ask your meetings (RAG with citations)
  await page.getByRole("link", { name: "Ask" }).click();
  await page.getByLabel("Question").fill("What did we decide about pricing?");
  await page.getByRole("button", { name: "Send question" }).click();
  const answer = page.getByTestId("answer");
  await expect(answer).toContainText("twenty nine dollars");
  await expect(answer.getByRole("link", { name: /Source 1: E2E Launch Sync/ })).toBeVisible();

  // Usage dashboard
  await page.getByRole("link", { name: "Usage" }).click();
  await expect(page.getByText("Minutes transcribed").first()).toBeVisible();
  await expect(page.getByText("1.2").first()).toBeVisible();
});

test("seeded demo account can sign in and see processed meetings", async ({ page }) => {
  await page.goto("/login");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Meetings" })).toBeVisible();
  await expect(page.getByTestId("meeting-list")).toContainText("Q3 Launch Planning");
  await expect(page.getByTestId("meeting-list")).toContainText("Design Review: Onboarding v2");
});
