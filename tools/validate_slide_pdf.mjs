#!/usr/bin/env node
import { createHash } from 'node:crypto';
import { readFile } from 'node:fs/promises';
import { relative, resolve, sep } from 'node:path';
import { getDocument } from 'pdfjs-dist/legacy/build/pdf.mjs';

const ROOT = resolve(import.meta.dirname, '..');
const PUBLIC_BASE = 'https://taehyeonglim.github.io/edtech/';
const PDF_SETTINGS = Object.freeze({ format: 'A4', preferCSSPageSize: true, printBackground: true, margin: { top: '0', right: '0', bottom: '0', left: '0' } });
const usage = () => 'Usage: node tools/validate_slide_pdf.mjs --manifest quality/textbook-contract.yml --root <directory> --provenance <file>';
const sha256 = (value) => createHash('sha256').update(value).digest('hex');
function parseArguments(argv) { const values = {}; for (let i = 0; i < argv.length; i += 2) { const [key, value] = [argv[i], argv[i + 1]]; if (!['--manifest', '--root', '--provenance'].includes(key) || !value || value.startsWith('--') || values[key]) throw new Error(usage()); values[key] = value; } if (Object.keys(values).length !== 3) throw new Error(usage()); return values; }
function repositoryPath(path) { const result = relative(ROOT, path); if (!result || result === '..' || result.startsWith(`..${sep}`) || resolve(ROOT, result) !== resolve(path)) throw new Error(`path must be inside the repository: ${path}`); return result.split(sep).join('/'); }
function parseContract(text) { const mappings = new Map(); let lectureId; for (const line of text.split(/\r?\n/)) { const lecture = line.match(/^\s*-\s+lecture_id:\s*(lecture-\d{2})\s*$/); if (lecture) { lectureId = lecture[1]; continue; } const chapter = line.match(/^\s+chapter_id:\s*(ch\d{2})\s*$/); if (chapter && lectureId) { mappings.set(lectureId, [...(mappings.get(lectureId) ?? []), chapter[1]]); lectureId = undefined; } } if (mappings.size !== 10) throw new Error('manifest must define textbook edges for exactly ten lectures'); return mappings; }
function textbookUrl(chapterId) { const chapter = Number(chapterId.slice(2)); const part = chapter <= 2 ? 1 : chapter <= 5 ? 2 : chapter <= 8 ? 3 : 4; return `${PUBLIC_BASE}book/part${part}/ch${String(chapter).padStart(2, '0')}/`; }
async function inspectPdf(pdf) {
  const document = await getDocument({ data: new Uint8Array(pdf) }).promise;
  try {
    const urls = new Set(), signatures = [];
    for (let pageNumber = 1; pageNumber <= document.numPages; pageNumber += 1) {
      const page = await document.getPage(pageNumber);
      const [annotations, text] = await Promise.all([page.getAnnotations(), page.getTextContent()]);
      for (const annotation of annotations) if (annotation.subtype === 'Link' && typeof annotation.url === 'string') urls.add(annotation.url);
      const signature = text.items.map((item) => item.str).join(' ').replace(/\s+/g, ' ').trim().slice(0, 180);
      if (!signature) throw new Error(`page ${pageNumber} has no extractable text`);
      signatures.push(signature);
    }
    return { pageCount: document.numPages, urls, signatures };
  } finally { await document.destroy(); }
}
async function main() {
  const args = parseArguments(process.argv.slice(2)); const manifestPath = resolve(args['--manifest']), root = resolve(args['--root']), provenancePath = resolve(args['--provenance']);
  const [manifest, provenanceText, exporterSource] = await Promise.all([readFile(manifestPath, 'utf8'), readFile(provenancePath, 'utf8'), readFile(resolve(ROOT, 'tools/export_slide_pdfs.mjs'))]);
  const expected = parseContract(manifest); let provenance;
  try { provenance = JSON.parse(provenanceText); } catch { throw new Error('provenance is not valid JSON'); }
  if (!provenance || provenance.schemaVersion !== 2 || provenance.kind !== 'slide-pdf-provenance' || provenance.revealVersion !== '5.1.0' || !Array.isArray(provenance.slides)) throw new Error('provenance has an invalid schema');
  if (provenance.manifest !== repositoryPath(manifestPath) || provenance.manifestSha256 !== sha256(manifest)) throw new Error('provenance manifest digest does not match');
  if (provenance.outputRoot !== repositoryPath(root) || provenance.slides.length !== 10) throw new Error('provenance output root or PDF count does not match');
  if (provenance.settingsSha256 !== sha256(JSON.stringify(PDF_SETTINGS)) || JSON.stringify(provenance.settings) !== JSON.stringify(PDF_SETTINGS)) throw new Error('provenance PDF settings digest does not match');
  if (provenance.tool !== 'tools/export_slide_pdfs.mjs' || provenance.toolSha256 !== sha256(exporterSource)) throw new Error('provenance tool digest does not match');
  const seen = new Set(), errors = [];
  for (const record of provenance.slides) {
    if (!record || typeof record.lectureId !== 'string' || seen.has(record.lectureId) || !expected.has(record.lectureId)) { errors.push('provenance has an invalid lecture record'); continue; }
    seen.add(record.lectureId); const expectedPath = `${repositoryPath(root)}/${record.lectureId}.pdf`, deck = `chapters/chapter-${record.lectureId.slice(-2)}/slides/deck.html`;
    if (record.pdf !== expectedPath || record.deck !== deck) { errors.push(`${record.lectureId}: PDF or deck path does not match contract`); continue; }
    let pdf; try { pdf = await readFile(resolve(ROOT, record.pdf)); } catch { errors.push(`${record.lectureId}: PDF is missing`); continue; }
    if (sha256(pdf) !== record.pdfSha256) errors.push(`${record.lectureId}: PDF digest does not match provenance`);
    const html = await readFile(resolve(ROOT, deck)); if (sha256(html) !== record.htmlSha256) errors.push(`${record.lectureId}: HTML digest does not match provenance`);
    const links = expected.get(record.lectureId).map(textbookUrl); if (JSON.stringify(record.textbookBacklinks) !== JSON.stringify(links)) errors.push(`${record.lectureId}: provenance textbook backlinks do not match manifest`);
    const inspected = await inspectPdf(pdf);
    if (!Number.isInteger(record.slideCount) || record.slideCount < 1 || !Number.isInteger(record.pageCount) || record.pageCount < record.slideCount || record.pageCount > record.slideCount + 2 || inspected.pageCount !== record.pageCount) errors.push(`${record.lectureId}: page count is not the recorded plausible slide count`);
    for (const link of links) if (!inspected.urls.has(link)) errors.push(`${record.lectureId}: missing textbook backlink annotation ${link}`);
    const repeated = new Map(); for (const signature of inspected.signatures) repeated.set(signature, (repeated.get(signature) ?? 0) + 1);
    if ([...repeated.values()].some((count) => count > 1)) errors.push(`${record.lectureId}: repeated page title/text signature indicates overlapping PDF pages`);
  }
  if (seen.size !== expected.size) errors.push('provenance does not cover all ten lectures');
  if (errors.length) throw new Error(errors.join('\n'));
  console.log(`Slide PDF validation passed: 10 PDFs with ${provenance.slides.map((record) => `${record.lectureId}=${record.pageCount}`).join(', ')}.`);
}
main().catch((error) => { console.error(error.message); process.exitCode = 1; });
