#!/usr/bin/env node
import { readFile } from 'node:fs/promises';
import { chromium } from 'playwright';
import axe from 'axe-core';

const WCAG_22_AA_TAGS = ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22a', 'wcag22aa'];
const EXPECTED_ROUTE_COUNT = 37;

function usage() {
  return 'Usage: node tools/audit_candidate.mjs --base-url http://127.0.0.1:8000 --manifest quality/route-manifest.json';
}

function parseArguments(argv) {
  const values = {};
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!['--base-url', '--manifest'].includes(key) || !value || value.startsWith('--') || values[key]) throw new Error(usage());
    values[key] = value;
  }
  if (Object.keys(values).length !== 2) throw new Error(usage());
  return values;
}

function parseBaseUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error('--base-url must be a valid URL');
  }
  if (!['http:', 'https:'].includes(url.protocol) || !['localhost', '127.0.0.1', '[::1]'].includes(url.hostname) || url.username || url.password || url.search || url.hash) {
    throw new Error('--base-url must be an HTTP(S) localhost loopback URL without credentials, query, or fragment');
  }
  return url;
}

function parseRoutes(text) {
  let manifest;
  try {
    manifest = JSON.parse(text);
  } catch {
    throw new Error('manifest is not valid JSON');
  }
  if (!manifest || !Array.isArray(manifest.routes) || manifest.routes.length !== EXPECTED_ROUTE_COUNT || new Set(manifest.routes).size !== EXPECTED_ROUTE_COUNT || manifest.routes.some((route) => typeof route !== 'string' || !route.startsWith('/') || route.startsWith('//'))) {
    throw new Error(`manifest must contain exactly ${EXPECTED_ROUTE_COUNT} unique absolute routes`);
  }
  return manifest.routes;
}

function reportRouteFailure(route, message) {
  console.error(`${route}: ${message}`);
}

async function auditRoute(browser, baseUrl, route) {
  const target = new URL(route, baseUrl);
  const page = await browser.newPage();
  const navigationFailures = [];
  page.on('framenavigated', (frame) => {
    if (frame === page.mainFrame() && frame.url() !== 'about:blank' && new URL(frame.url()).origin !== baseUrl.origin) {
      navigationFailures.push(`external navigation to ${frame.url()}`);
    }
  });
  try {
    const response = await page.goto(target.href, { waitUntil: 'load' });
    if (!response) throw new Error('navigation did not produce an HTTP response');
    if (response.status() < 200 || response.status() >= 300) throw new Error(`HTTP ${response.status()}`);
    if (new URL(response.url()).origin !== baseUrl.origin) throw new Error(`external redirect to ${response.url()}`);
    if (navigationFailures.length) throw new Error(navigationFailures.join('; '));
    try {
      await page.addScriptTag({ content: axe.source });
    } catch (error) {
      throw new Error(`axe script injection failed: ${error.message}`);
    }
    const results = await page.evaluate(async (tags) => window.axe.run(document, { runOnly: { type: 'tag', values: tags } }), WCAG_22_AA_TAGS);
    return results.violations.filter((violation) => ['critical', 'serious'].includes(violation.impact));
  } finally {
    await page.close();
  }
}

async function main() {
  const args = parseArguments(process.argv.slice(2));
  const baseUrl = parseBaseUrl(args['--base-url']);
  const routes = parseRoutes(await readFile(args['--manifest'], 'utf8'));
  const browser = await chromium.launch({ headless: true });
  const failures = [];
  try {
    for (const route of routes) {
      try {
        const violations = await auditRoute(browser, baseUrl, route);
        for (const violation of violations) {
          const nodes = violation.nodes.map((node) => node.target.join(' ')).join(', ');
          failures.push({ route, rule: violation.id, impact: violation.impact, nodes });
        }
      } catch (error) {
        failures.push({ route, rule: 'navigation-or-injection', impact: 'failure', nodes: error.message });
      }
    }
  } finally {
    await browser.close();
  }
  if (failures.length) {
    for (const failure of failures) reportRouteFailure(failure.route, `${failure.impact} ${failure.rule}: ${failure.nodes}`);
    throw new Error(`Accessibility audit failed with ${failures.length} route/rule failure(s).`);
  }
  console.log(`Accessibility audit passed for ${routes.length} manifest routes (WCAG 2.2 AA axe tags).`);
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
