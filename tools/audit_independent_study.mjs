// Browser regression checks for the textbook's independent-study path.
import assert from "node:assert/strict";
import { chromium } from "playwright";

const raw = process.argv[process.argv.indexOf("--base-url") + 1];
if (!process.argv.includes("--base-url") || !raw) {
  throw new Error("Usage: node tools/audit_independent_study.mjs --base-url http://127.0.0.1:4173");
}
const base = new URL(raw);
assert(["127.0.0.1", "localhost", "[::1]"].includes(base.hostname), "Use a local candidate");
assert(["http:", "https:"].includes(base.protocol));
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ reducedMotion: "reduce" });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  for (let chapter = 1; chapter <= 11; chapter++) {
    const part = chapter <= 2 ? 1 : chapter <= 5 ? 2 : chapter <= 8 ? 3 : 4;
    const route = `/book/part${part}/ch${String(chapter).padStart(2, "0")}/`;
    const response = await page.goto(new URL(route, base).href);
    assert.equal(response.status(), 200, route);
    const answers = page.locator(".md-typeset details.question");
    const count = await answers.count();
    assert.equal(count, chapter >= 10 ? 6 : 5, `${route}: each question has one explanation`);
    assert.equal(await page.locator("details.question[open]").count(), 0, `${route}: answers start closed`);
    await answers.first().locator("summary").focus();
    await page.keyboard.press("Enter");
    assert.equal(await page.locator("details.question[open]").count(), 1, `${route}: keyboard access`);

    // Check repeated browser print events do not overwrite the original state.
    await page.evaluate(() => {
      window.dispatchEvent(new Event("beforeprint"));
      window.dispatchEvent(new Event("beforeprint"));
    });
    assert.equal(await page.locator("details.question[open]").count(), count, `${route}: print includes all explanations`);
    await page.evaluate(() => window.dispatchEvent(new Event("afterprint")));
    assert.deepEqual(await answers.evaluateAll((items) => items.map((item) => item.open)),
      [true, ...Array(count - 1).fill(false)], `${route}: restore individual choices`);

    for (const width of [1280, 320]) {
      await page.setViewportSize({ width, height: 900 });
      for (const scheme of ["default", "slate"]) {
        await page.locator("body").evaluate((body, value) => body.setAttribute("data-md-color-scheme", value), scheme);
        assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
          `${route}: page overflow at ${width}px in ${scheme}`);
      }
    }
    const localImages = await page.locator(".md-typeset img").evaluateAll((images) =>
      images.map((img) => img.src).filter((src) => new URL(src).origin === location.origin));
    for (const src of new Set(localImages)) {
      assert.equal((await page.request.get(src)).status(), 200, `${route}: missing image ${src}`);
    }
  }
  for (let lecture = 1; lecture <= 10; lecture++) {
    const route = `/chapters/chapter-${String(lecture).padStart(2, "0")}/slides/deck.html#independent-application`;
    assert.equal((await page.goto(new URL(route, base).href)).status(), 200, route);
    await page.locator('[data-slide-id="independent-application"]').waitFor({ state: "visible" });
    for (const width of [320, 375]) {
      await page.setViewportSize({ width, height: 812 });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
        `${route}: lecture overflow at ${width}px`);
    }
    await page.keyboard.press("m");
    assert.equal(await page.locator(".lecture-viewer.is-document-mode").count(), 1,
      `${route}: document mode opens`);
    assert.equal(await page.locator('[data-slide-id="independent-application"]').count(), 1,
      `${route}: application remains available in document mode`);
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1),
      `${route}: document mode overflow`);
    await page.keyboard.press("m");
  }
  assert.deepEqual(errors, [], "No browser script errors");
  console.log("Independent-study audit passed: 11 chapters, 57 explanations, keyboard, print restoration, light/dark at 1280/320px, local images; 10 lecture applications, mobile at 320/375px, document mode.");
} finally {
  await browser.close();
}
