import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

test("drag/drop, actual printed OCR, contextual correction, rules, persistence and export", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const external = [];
  page.on("request", (r) => {
    if (
      /^https?:/.test(r.url()) &&
      !r.url().startsWith("http://127.0.0.1:4173/")
    )
      external.push(r.url());
  });
  await page.goto("./");
  await expect(
    page.getByRole("heading", { name: "Drop an image." }),
  ).toBeVisible();
  await page.locator("#auto-recognize").uncheck();
  await page.evaluate(async () => {
    const canvas = document.createElement("canvas");
    canvas.width = 1200;
    canvas.height = 350;
    const c = canvas.getContext("2d");
    c.fillStyle = "white";
    c.fillRect(0, 0, 1200, 350);
    c.fillStyle = "black";
    c.font = "42px Arial";
    c.fillText("A peace of cake is on the table.", 70, 100);
    c.fillText('She said "The notebook is ready."', 70, 180);
    const blob = await new Promise((r) => canvas.toBlob(r, "image/png"));
    const transfer = new DataTransfer();
    transfer.items.add(
      new File([blob], "Dropped notes.png", { type: "image/png" }),
    );
    window.dispatchEvent(
      new DragEvent("drop", {
        dataTransfer: transfer,
        bubbles: true,
        cancelable: true,
      }),
    );
  });
  await expect(page.locator("#document-title")).toHaveText("Dropped notes.png");
  await page.locator("#recognize").click();
  await expect(page.locator("#editor")).toHaveValue(
    /A peace of cake is on the table\./,
    { timeout: 120000 },
  );
  await expect(page.locator("#recognize")).toBeEnabled();
  await page.locator("#editor").evaluate((el) => {
    el.focus();
    const i = el.value.indexOf("peace");
    el.setSelectionRange(i, i + 5);
    el.dispatchEvent(new Event("select"));
  });
  await expect(page.locator("#dictionary-state")).not.toHaveText(
    "LOADING LOCAL DICTIONARY…",
  );
  await page.locator("#lookup").fill("peace");
  await page.locator("#lookup-form").evaluate((el) => el.requestSubmit());
  await expect(page.locator(".suggestion").first()).toHaveText("piece");
  await page.setViewportSize({ width: 1600, height: 1000 });
  await page.screenshot({ path: "../docs/web-workbench.png", fullPage: true });
  await page.locator("#apply-suggestion").click();
  await expect(page.locator("#editor")).toHaveValue(/A piece of cake/);
  await page.locator("#rules").click();
  await page.locator('[data-rule="commaBefore"]').check();
  await page.locator("#apply-rules").click();
  await page.locator("#approve-rules").click();
  await expect(page.locator("#editor")).toHaveValue(
    /She said, "The notebook is ready\."/,
  );
  await expect(page.locator("#save-state")).toHaveText("SAVED IN THIS BROWSER");
  await page.reload();
  await expect(page.locator("#editor")).toHaveValue(/A piece of cake/);
  await expect(page.locator("#dictionary-state")).toHaveText(
    "ENGLISH / LOCAL CONTEXT MODEL",
  );
  await page.locator("#export").click();
  const download = page.waitForEvent("download");
  await page.locator("#export-txt").click();
  expect((await download).suggestedFilename()).toBe("Dropped notes.txt");
  expect(errors).toEqual([]);
  expect(external).toEqual([]);
});

test("stopping first-use OCR preserves manual edits", async ({ page }) => {
  await page.goto("./");
  await page.locator("#sample").click();
  await expect(page.locator("#cancel")).toBeVisible();
  await page.locator("#cancel").click();
  await page.locator("#editor").fill("My manual transcription must survive.");
  await expect(page.locator("#save-state")).toHaveText("SAVED IN THIS BROWSER");
  await page.reload();
  await expect(page.locator("#editor")).toHaveValue(
    "My manual transcription must survive.",
  );
});

test("responsive empty workspace fits a phone without horizontal overflow", async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("./");
  await expect(page.locator("#browse")).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
});

test("actual browser handwriting inference loads local quantized models", async ({
  page,
}) => {
  test.setTimeout(300000);
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("./");
  await page.locator("#auto-recognize").uncheck();
  if (process.env.HANDWRITING_FIXTURE) {
    await page.locator("#file-input").setInputFiles({
      name: "Model smoke test.png",
      mimeType: "image/png",
      buffer: readFileSync(process.env.HANDWRITING_FIXTURE),
    });
    await expect(page.locator("#document-title")).toHaveText(
      "Model smoke test.png",
    );
  } else {
    await page.evaluate(async () => {
      const canvas = document.createElement("canvas");
      canvas.width = 1200;
      canvas.height = 180;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "white";
      ctx.fillRect(0, 0, 1200, 180);
      ctx.fillStyle = "black";
      ctx.font = "italic 48px cursive";
      ctx.fillText("The notebook is ready.", 60, 105);
      const blob = await new Promise((r) => canvas.toBlob(r, "image/png"));
      const transfer = new DataTransfer();
      transfer.items.add(
        new File([blob], "Model smoke test.png", { type: "image/png" }),
      );
      window.dispatchEvent(
        new DragEvent("drop", { dataTransfer: transfer, bubbles: true }),
      );
    });
    await expect(page.locator("#document-title")).toHaveText(
      "Model smoke test.png",
    );
  }
  await page.locator("#engine").selectOption("handwriting");
  await page.locator("#select-region").click();
  const box = await page.locator("#image-canvas").boundingBox();
  await page.mouse.move(box.x + 3, box.y + 3);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width - 3, box.y + box.height - 3, {
    steps: 8,
  });
  await page.mouse.up();
  await expect(page.locator("#region-badge")).toHaveText("REGION → INSERT");
  page.once("dialog", (dialog) => dialog.accept());
  await page.locator("#recognize").click();
  await expect(page.locator("#editor")).not.toHaveValue("", {
    timeout: 240000,
  });
  await expect(page.locator("#recognize")).toBeEnabled({ timeout: 240000 });
  expect((await page.locator("#editor").inputValue()).toLowerCase()).toContain(
    process.env.HANDWRITING_EXPECTED || "notebook",
  );
  expect(errors).toEqual([]);
});
