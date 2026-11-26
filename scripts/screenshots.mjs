// Reproducible README screenshots against a running stack (docker compose up -d --wait).
//   node scripts/screenshots.mjs
// Uses the seeded demo account; writes PNGs to docs/screenshots/.
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(path.join(here, "../frontend/package.json"));
const { chromium } = require("@playwright/test");

const WEB = process.env.WEB_URL ?? "http://localhost:20700";
const OUT = path.join(here, "../docs/screenshots");
const viewport = { width: 1440, height: 900 };

async function login(context) {
  const page = await context.newPage();
  await page.goto(`${WEB}/login`);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.getByTestId("meeting-list").waitFor();
  return page;
}

async function openMeeting(page, title) {
  await page.goto(`${WEB}/meetings`);
  await page.getByTestId("meeting-list").waitFor();
  await page.getByTestId("meeting-list").getByText(title, { exact: true }).click();
  await page.getByText("Executive summary").waitFor();
  await page.locator("[aria-label='Audio waveform'] >> nth=0").waitFor();
  await page.waitForTimeout(1200); // waveform paint
}

const shot = (page, name, opts = {}) => page.screenshot({ path: path.join(OUT, `${name}.png`), ...opts });

const browser = await chromium.launch();
try {
  // ---------------- light mode
  const light = await browser.newContext({ viewport, colorScheme: "light", deviceScaleFactor: 1 });
  const page = await login(light);

  await page.goto(`${WEB}/meetings`);
  await page.getByTestId("meeting-list").waitFor();
  await page.waitForTimeout(500);
  await shot(page, "meetings");

  await openMeeting(page, "Q3 Launch Planning");
  await page.evaluate(() => window.scrollTo(0, 0));
  await shot(page, "meeting-notes", { fullPage: true });

  await page.getByRole("tab", { name: "Transcript" }).click();
  await page.getByText("Good point. We decided to keep the pricing", { exact: false }).click();
  await page.waitForTimeout(1500);
  await page.getByRole("button", { name: "Pause" }).click().catch(() => {});
  await page.waitForTimeout(300);
  await shot(page, "transcript");

  const nav = page.getByRole("navigation", { name: "Main", exact: true });
  await nav.getByRole("link", { name: "Task board", exact: true }).click();
  await page.getByTestId("column-todo").waitFor();
  await page.waitForTimeout(500);
  await shot(page, "task-board");

  await nav.getByRole("link", { name: "Ask", exact: true }).click();
  await page.getByLabel("Question", { exact: true }).fill("What did we decide about pricing?");
  await page.getByRole("button", { name: "Send question" }).click();
  await page.getByTestId("answer").waitFor();
  await page.waitForTimeout(600);
  await shot(page, "ask");

  await nav.getByRole("link", { name: "Usage", exact: true }).click();
  await page.getByText("Minutes transcribed per day").waitFor();
  await page.waitForTimeout(1200);
  await shot(page, "usage");
  await light.close();

  // ---------------- dark mode
  const dark = await browser.newContext({ viewport, colorScheme: "dark", deviceScaleFactor: 1 });
  const dpage = await login(dark);
  await openMeeting(dpage, "Weekly Engineering Sync");
  await shot(dpage, "meeting-notes-dark");
  await dark.close();
} finally {
  await browser.close();
}
console.log("screenshots written to", OUT);
