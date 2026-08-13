#!/usr/bin/env node
import { chromium } from "playwright";
import fs from "node:fs/promises";
import path from "node:path";

const args = process.argv.slice(2);
const valueAfter = (flag, fallback) => {
  const index = args.indexOf(flag);
  return index >= 0 && args[index + 1] ? args[index + 1] : fallback;
};
const baseUrl = valueAfter("--base-url", "http://127.0.0.1:4173").replace(/\/$/, "");
const output = path.resolve(valueAfter("--output", "/tmp/edtech-visual-qa"));

const focus = {
  "01": ["course-system-focus", "teacher-design-focus"],
  "02": ["alan-turing-focus", "tim-berners-lee-focus"],
  "03": ["four-flows-focus", "immersive-classroom-focus"],
  "04": ["systems-thinking-focus", "addie-iteration-focus"],
  "05": ["learning-conditions-focus", "nine-events-focus"],
  "06": ["interdependence-focus", "jigsaw-classroom-focus", "team-models-focus"],
  "07": ["arcs-classroom-focus", "self-determination-focus", "flow-classroom-focus"],
  "08": ["cognitive-overload-focus", "expertise-guidance-focus", "multimedia-processing-focus"],
  "09": ["dashboard-teacher-focus", "ai-ethics-focus"],
  "10": ["verification-focus", "equity-focus"]
};

const textbookRoutes = [
  "part1/ch01/", "part1/ch02/", "part2/ch03/", "part2/ch04/", "part2/ch05/",
  "part3/ch06/", "part3/ch07/", "part3/ch08/", "part4/ch09/", "part4/ch10/", "part4/ch11/"
];

await fs.mkdir(path.join(output, "slides"), { recursive: true });
await fs.mkdir(path.join(output, "textbook"), { recursive: true });

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });

for (const [chapter, ids] of Object.entries(focus)) {
  for (const id of ids) {
    await page.goto(`${baseUrl}/chapters/chapter-${chapter}/slides/deck.html#${id}`, { waitUntil: "networkidle" });
    const slide = page.locator(`[data-slide-id="${id}"]`);
    await slide.waitFor({ state: "visible" });
    await slide.locator("img").evaluateAll((images) => Promise.all(images.map((image) => image.decode())));
    await page.waitForTimeout(600);
    await page.screenshot({ path: path.join(output, "slides", `${chapter}-${id}.png`) });
  }
}

for (const route of textbookRoutes) {
  await page.goto(`${baseUrl}/book/${route}`, { waitUntil: "networkidle" });
  const figure = page.locator("figure.chapter-visual").first();
  await figure.scrollIntoViewIfNeeded();
  await figure.locator("img").evaluate((image) => image.decode());
  await page.waitForTimeout(250);
  const slug = route.replace(/\/$/, "").replace("/", "-");
  await figure.screenshot({ path: path.join(output, "textbook", `${slug}.png`) });
}

const renderContactSheet = async (folder, fileName, columns, width, height) => {
  const files = (await fs.readdir(path.join(output, folder)))
    .filter((name) => name.endsWith(".png") && name !== "zz-pad.png")
    .sort();
  const items = (await Promise.all(files.map(async (name) => {
    const data = await fs.readFile(path.join(output, folder, name));
    const src = `data:image/png;base64,${data.toString("base64")}`;
    return `<figure><img src="${src}" alt=""><figcaption>${name.replace(/\.png$/, "")}</figcaption></figure>`;
  }))).join("");
  await page.setViewportSize({ width: columns * width + 48, height: 900 });
  await page.setContent(`<!doctype html><style>
    *{box-sizing:border-box}body{margin:0;padding:18px;background:#e9eaed;font:11px system-ui;color:#1d1d1f}
    main{display:grid;grid-template-columns:repeat(${columns},${width}px);gap:8px}
    figure{margin:0;background:white;border:1px solid rgba(0,0,0,.12);border-radius:8px;overflow:hidden}
    img{display:block;width:${width}px;height:${height}px;object-fit:contain;background:white}
    figcaption{padding:5px 8px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  </style><main>${items}</main>`, { waitUntil: "load" });
  await page.locator("img").evaluateAll((images) => Promise.all(images.map((image) => image.decode())));
  await page.screenshot({ path: path.join(output, fileName), fullPage: true });
};

await renderContactSheet("slides", "slide-contact-sheet.png", 5, 288, 180);
await renderContactSheet("textbook", "textbook-contact-sheet.png", 4, 320, 210);

await browser.close();
console.log(`Visual QA screenshots written to ${output}`);
