#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { relative, resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium } from 'playwright';
import { getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs';

const ROOT = resolve(import.meta.dirname, '..');
const PUBLIC_BASE = 'https://taehyeonglim.github.io/edtech/';
const REVEAL_BASE = 'https://unpkg.com/reveal.js@5/';
const REVEAL_FILES = new Map([
  ['dist/reset.css', 'dist/reset.css'], ['dist/reveal.css', 'dist/reveal.css'], ['dist/theme/white.css', 'dist/theme/white.css'],
  ['dist/reveal.js', 'dist/reveal.js'], ['plugin/notes/notes.js', 'plugin/notes/notes.js'],
]);
const PDF_SETTINGS = Object.freeze({ format: 'A4', preferCSSPageSize: true, printBackground: true, margin: { top: '0', right: '0', bottom: '0', left: '0' } });
const usage = () => 'Usage: node tools/export_slide_pdfs.mjs --manifest quality/textbook-contract.yml --root <directory> --provenance <file>';
const sha256 = (value) => createHash('sha256').update(value).digest('hex');

function parseArguments(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const [key, value] = [argv[index], argv[index + 1]];
    if (!['--manifest', '--root', '--provenance'].includes(key) || !value || value.startsWith('--') || values[key]) throw new Error(usage());
    values[key] = value;
  }
  if (Object.keys(values).length !== 3) throw new Error(usage());
  return values;
}
function publicPath(path) {
  const result = relative(ROOT, path);
  if (!result || result === '..' || result.startsWith(`..${sep}`) || resolve(ROOT, result) !== resolve(path)) throw new Error(`path must be inside the repository: ${path}`);
  return result.split(sep).join('/');
}
function parseContract(text) {
  const edges = []; let lectureId;
  for (const line of text.split(/\r?\n/)) {
    const lecture = line.match(/^\s*-\s+lecture_id:\s*(lecture-\d{2})\s*$/);
    if (lecture) { lectureId = lecture[1]; continue; }
    const chapter = line.match(/^\s+chapter_id:\s*(ch\d{2})\s*$/);
    if (chapter && lectureId) { edges.push({ lectureId, chapterId: chapter[1] }); lectureId = undefined; }
  }
  const ids = new Set(edges.map((edge) => edge.lectureId));
  if (ids.size !== 10 || edges.some(({ lectureId: id, chapterId }) => !/^lecture-(0[1-9]|10)$/.test(id) || !/^ch\d{2}$/.test(chapterId))) throw new Error('manifest must define textbook edges for exactly ten lectures');
  return [...ids].sort().map((id) => ({ lectureId: id, deck: `chapters/chapter-${id.slice(-2)}/slides/deck.html`, chapters: edges.filter((edge) => edge.lectureId === id).map((edge) => edge.chapterId).sort() }));
}
function textbookUrl(chapterId) {
  const chapter = Number(chapterId.slice(2)); const part = chapter <= 2 ? 1 : chapter <= 5 ? 2 : chapter <= 8 ? 3 : 4;
  return `${PUBLIC_BASE}book/part${part}/ch${String(chapter).padStart(2, '0')}/`;
}
async function pdfPageCount(pdf) {
  const document = await getDocument({ data: new Uint8Array(pdf) }).promise;
  try { return document.numPages; } finally { await document.destroy(); }
}
async function revealAssets() {
  return new Map(await Promise.all([...REVEAL_FILES].map(async ([requestPath, filePath]) => [`${REVEAL_BASE}${requestPath}`, await readFile(resolve(ROOT, 'node_modules/reveal.js', filePath))])));
}

async function main() {
  const args = parseArguments(process.argv.slice(2));
  const [manifest, outputRoot, provenancePath] = [resolve(args['--manifest']), resolve(args['--root']), resolve(args['--provenance'])];
  const manifestText = await readFile(manifest, 'utf8');
  const [lectures, assets, toolSource] = await Promise.all([parseContract(manifestText), revealAssets(), readFile(new URL(import.meta.url))]);
  await mkdir(outputRoot, { recursive: true }); await mkdir(resolve(provenancePath, '..'), { recursive: true });
  const browser = await chromium.launch({ headless: true }); const records = [];
  try {
    for (const lecture of lectures) {
      const deckPath = resolve(ROOT, lecture.deck); const deckHtml = await readFile(deckPath, 'utf8'); const pdfPath = resolve(outputRoot, `${lecture.lectureId}.pdf`); const page = await browser.newPage();
      try {
        await page.route(/^https?:/, (route) => { const bytes = assets.get(route.request().url()); return bytes ? route.fulfill({ body: bytes }) : route.abort(); });
        await page.goto(`${pathToFileURL(deckPath).href}?print-pdf`, { waitUntil: 'load' });
        await page.waitForFunction(() => window.Reveal?.isPrintView?.() && document.querySelectorAll('.pdf-page').length > 0, { timeout: 15000 });
        const slideCount = (deckHtml.match(/<section\b/gi) ?? []).length;
        const renderState = await page.evaluate(async ({ chapters }) => {
          await document.fonts.ready;
          if (!window.Reveal || typeof window.Reveal.isReady !== 'function') throw new Error('Reveal failed to load');
          await new Promise((ready, reject) => { if (window.Reveal.isReady()) return ready(); window.Reveal.on('ready', ready); setTimeout(() => reject(new Error('Reveal.initialize did not complete')), 15000); });
          const lazyImages = [...document.querySelectorAll('img[data-src]')];
          const imageLoads = lazyImages.map((image) => new Promise((resolve) => {
            image.addEventListener('load', resolve, { once: true });
            image.addEventListener('error', resolve, { once: true });
          }));
          for (const image of lazyImages) {
            image.src = image.dataset.src;
            image.dataset.lazyLoaded = '';
            delete image.dataset.src;
          }
          await Promise.all(imageLoads);
          const failedImages = [...document.images].filter((image) => image.currentSrc && !image.naturalWidth);
          if (failedImages.length) throw new Error(`Unable to load ${failedImages.length} image(s) for PDF export`);
          await new Promise((ready) => requestAnimationFrame(ready));
          const footer = document.createElement('nav'); footer.setAttribute('aria-label', '교재 본문 링크'); footer.style.cssText = 'position:fixed;right:8mm;bottom:5mm;z-index:99999;font:9pt sans-serif';
          for (const chapterId of chapters) { const chapter = Number(chapterId.slice(2)); const part = chapter <= 2 ? 1 : chapter <= 5 ? 2 : chapter <= 8 ? 3 : 4; const link = document.createElement('a'); link.href = `https://taehyeonglim.github.io/edtech/book/part${part}/ch${String(chapter).padStart(2, '0')}/`; link.textContent = `교재 ${chapter}장`; link.style.cssText = 'margin-left:4mm;color:#102a43;background:#fff'; footer.append(link); }
          document.body.append(footer);
          return { sections: document.querySelectorAll('section').length, height: document.documentElement.scrollHeight };
        }, lecture);
        await page.pdf({ ...PDF_SETTINGS, path: pdfPath });
        const pdf = await readFile(pdfPath); const pageCount = await pdfPageCount(pdf);
        if (!slideCount || pageCount < slideCount || pageCount > slideCount + 2) throw new Error(`${lecture.lectureId}: PDF page count ${pageCount} is not plausible for ${slideCount} slides; render ${JSON.stringify(renderState)}`);
        records.push({ lectureId: lecture.lectureId, deck: lecture.deck, pdf: publicPath(pdfPath), textbookBacklinks: lecture.chapters.map(textbookUrl), htmlSha256: sha256(deckHtml), pdfSha256: sha256(pdf), slideCount, pageCount });
      } finally { await page.close(); }
    }
  } finally { await browser.close(); }
  const provenance = { schemaVersion: 2, kind: 'slide-pdf-provenance', manifest: publicPath(manifest), manifestSha256: sha256(manifestText), outputRoot: publicPath(outputRoot), tool: 'tools/export_slide_pdfs.mjs', toolSha256: sha256(toolSource), settings: PDF_SETTINGS, settingsSha256: sha256(JSON.stringify(PDF_SETTINGS)), revealVersion: '5.1.0', slides: records };
  await writeFile(provenancePath, `${JSON.stringify(provenance, null, 2)}\n`);
}
main().catch((error) => { console.error(error.message); process.exitCode = 1; });
