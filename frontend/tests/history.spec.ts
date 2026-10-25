import { expect, test, type Page } from "@playwright/test";

const result = {
  summary_bullets: ["A saved summary"],
  key_details: "Complete saved details",
  sources: [
    { title: "Example source", url: "https://example.com", snippet_used: null },
  ],
  caveats: ["A saved caveat"],
  citations: [
    {
      bullet_index: 0,
      source_url: "https://example.com",
      excerpt: "Exact evidence",
    },
  ],
};

async function submit(page: Page, text: string) {
  await page.getByRole("textbox").fill(text);
  await page.getByRole("button", { name: "SUMMARIZE" }).click();
  await expect(
    page.getByRole("heading", { name: text, exact: true }),
  ).toBeVisible();
}

async function storedRecords(page: Page) {
  return page.evaluate(async () => {
    const { loadHistory } = await import("/src/history.ts");
    return loadHistory();
  });
}

test.beforeEach(async ({ page }) => {
  await page.route("**/api/research", (route) =>
    route.fulfill({ json: result }),
  );
  await page.goto("/");
  await expect(
    page.getByRole("button", { name: "+ New research" }),
  ).toBeEnabled();
});

test("automatically saves full results, restores after reload, and deletes durably", async ({
  page,
}) => {
  let requests = 0;
  page.on("request", (request) => {
    if (request.url().endsWith("/api/research")) requests++;
  });
  await submit(page, "First topic");
  await expect(
    page.getByRole("button", { name: "First topic", exact: false }).first(),
  ).toHaveAttribute("aria-current", "page");
  await page.getByRole("button", { name: "+ New research" }).click();
  await submit(page, "Second topic");
  expect(await storedRecords(page)).toMatchObject([
    { inputName: "Second topic", inputType: "topic", result },
    { inputName: "First topic", inputType: "topic", result },
  ]);
  await page.reload();
  const history = page.getByRole("navigation", { name: "Saved summaries" });
  await expect(history.locator("li").first()).toContainText("Second topic");
  await history.getByRole("button", { name: /^First topic/ }).click();
  await expect(page.getByText("Complete saved details")).toBeVisible();
  await expect(page.getByText("A saved caveat")).toBeVisible();
  await page.getByText("Source 1 · Evidence").click();
  await expect(page.getByText("Exact evidence")).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("history-desktop.png"),
    fullPage: true,
  });
  expect(requests).toBe(2);
  // Removing another record leaves the currently displayed result intact.
  await page
    .getByRole("button", { name: "Delete Second topic", exact: true })
    .click();
  await expect(history.locator("li")).toHaveCount(1);
  await expect(
    page.getByRole("heading", { name: "First topic", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Delete First topic", exact: true })
    .click();
  await expect(page.getByRole("textbox")).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("Completed summaries will appear here."),
  ).toBeVisible();
  expect(await storedRecords(page)).toEqual([]);
  expect(requests).toBe(2);
});

test("URL and uploaded filename retain their input types without storing the file", async ({
  page,
}) => {
  await submit(page, "https://example.com/article");
  await page.getByRole("button", { name: "+ New research" }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name: "notes.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("Private file contents"),
  });
  await page.getByRole("button", { name: "SUMMARIZE" }).click();
  await expect(
    page.getByRole("heading", { name: "notes.md", exact: true }),
  ).toBeVisible();
  const records = await storedRecords(page);
  expect(records).toMatchObject([
    { inputName: "notes.md", inputType: "file", result },
    { inputName: "https://example.com/article", inputType: "url", result },
  ]);
  expect(JSON.stringify(records)).not.toContain("Private file contents");
});

test("failed research creates no history entry", async ({ page }) => {
  await page.route("**/api/research", (route) =>
    route.fulfill({ status: 502, json: { detail: "Research failed" } }),
  );
  await page.getByRole("textbox").fill("Failed topic");
  await page.getByRole("button", { name: "SUMMARIZE" }).click();
  await expect(
    page.getByText("Research failed", { exact: true }),
  ).toBeVisible();
  expect(await storedRecords(page)).toEqual([]);
});

test("an aborted save warns but preserves the generated result", async ({
  page,
}) => {
  await abortWrites(page);
  await submit(page, "Unsaved topic");
  await expect(page.getByRole("alert")).toContainText("could not be saved");
  await expect(page.getByText("Complete saved details")).toBeVisible();
  expect(await storedRecords(page)).toEqual([]);
});

test("failed deletion retains both the record and the selected result", async ({
  page,
}) => {
  await submit(page, "Keep this topic");
  await abortWrites(page);
  await page
    .getByRole("button", { name: "Delete Keep this topic", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("Could not delete");
  await expect(
    page.getByRole("heading", { name: "Keep this topic", exact: true }),
  ).toBeVisible();
  expect(await storedRecords(page)).toHaveLength(1);
});

test("unavailable IndexedDB does not prevent creating a summary", async ({
  page,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(window, "indexedDB", {
      get() {
        throw new Error("Storage disabled");
      },
    });
  });
  await page.reload();
  await expect(page.getByRole("alert")).toContainText("Could not load history");
  await submit(page, "Still usable");
  await expect(page.getByRole("alert")).toContainText("could not be saved");
  await expect(page.getByText("Complete saved details")).toBeVisible();
});

test("history controls stay disabled during research and saving", async ({
  page,
}) => {
  await submit(page, "Existing topic");
  await page.getByRole("button", { name: "+ New research" }).click();
  let finish!: () => void;
  const pending = new Promise<void>((resolve) => {
    finish = resolve;
  });
  await page.route("**/api/research", async (route) => {
    await pending;
    await route.fulfill({ json: result });
  });
  await page.getByRole("textbox").fill("Pending topic");
  await page.getByRole("button", { name: "SUMMARIZE" }).click();
  await expect(
    page.getByRole("button", { name: "+ New research" }),
  ).toBeDisabled();
  await expect(
    page.getByRole("button", { name: "Delete Existing topic", exact: true }),
  ).toBeDisabled();
  finish();
  await expect(
    page.getByRole("heading", { name: "Pending topic", exact: true }),
  ).toBeVisible();
  expect(await storedRecords(page)).toHaveLength(2);
});

test("sidebar and results fit a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await submit(page, "A very long topic ".repeat(20).trim());
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await expect(page.getByRole("button", { name: /^Delete / })).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("history-mobile.png"),
    fullPage: true,
  });
});

async function abortWrites(page: Page) {
  await page.evaluate(() => {
    const original = IDBDatabase.prototype.transaction;
    IDBDatabase.prototype.transaction = function (
      ...args: Parameters<typeof original>
    ) {
      const transaction = original.apply(this, args);
      if (args[1] === "readwrite") queueMicrotask(() => transaction.abort());
      return transaction;
    };
  });
}
