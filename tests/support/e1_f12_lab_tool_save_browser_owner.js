'use strict';

const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');

const TRANSPORT_SETTLEMENTS = ['rejected', 'fulfilled'];
const HTTP_RESULTS = ['rejected', 'ok'];
const JSON_SETTLEMENTS = ['fulfilled', 'rejected'];
const DOMAIN_RESULTS = ['missing', 'false', 'truthy-nonliteral', 'confirmed'];

function deriveCases() {
  const rows = [];
  for (const transport of TRANSPORT_SETTLEMENTS) {
    if (transport === 'rejected') {
      rows.push(caseFromDecisions({ transport }));
      continue;
    }
    for (const http of HTTP_RESULTS) {
      for (const json of JSON_SETTLEMENTS) {
        if (json === 'rejected') {
          rows.push(caseFromDecisions({ transport, http, json }));
          continue;
        }
        if (http === 'rejected') {
          rows.push(caseFromDecisions({ transport, http, json }));
          continue;
        }
        for (const domain of DOMAIN_RESULTS) {
          rows.push(caseFromDecisions({ transport, http, json, domain }));
        }
      }
    }
  }
  return rows;
}

function caseFromDecisions(decisions) {
  if (decisions.transport === 'rejected') {
    return {
      id: 'transport-rejected',
      decisions,
      expected: { keyRetained: true, keyCleared: false, eventClass: 'transport-rejected', eventType: 'error' },
    };
  }
  if (decisions.json === 'rejected') {
    const prefix = decisions.http === 'ok' ? 'http-ok' : 'http-rejected';
    const id = `${prefix}-json-rejected`;
    return { id, decisions, expected: { keyRetained: true, keyCleared: false, eventClass: id, eventType: 'error' } };
  }
  if (decisions.http === 'rejected') {
    const id = 'http-rejected-json-resolved';
    return { id, decisions, expected: { keyRetained: true, keyCleared: false, eventClass: id, eventType: 'error' } };
  }
  const id = `http-ok-domain-${decisions.domain}`;
  if (decisions.domain === 'confirmed') {
    return { id, decisions, expected: { keyRetained: false, keyCleared: true, eventClass: 'success', eventType: 'success' } };
  }
  return {
    id,
    decisions,
    expected: { keyRetained: true, keyCleared: false, eventClass: 'domain-unconfirmed', eventType: 'error' },
  };
}

function publicCase(row) {
  return { id: row.id, expected: row.expected };
}

function extractUniqueFunction(source, name) {
  const escaped = name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(`(^|[^A-Za-z0-9_$])function\\s+${escaped}\\s*\\(`, 'gm');
  const matches = Array.from(source.matchAll(pattern));
  if (matches.length !== 1) throw new Error('function-extraction-count');
  const start = matches[0].index + matches[0][1].length;
  const open = source.indexOf('{', start);
  if (open < 0) throw new Error('function-extraction-open');

  let depth = 0;
  let quote = '';
  let lineComment = false;
  let blockComment = false;
  let escapedChar = false;
  for (let index = open; index < source.length; index += 1) {
    const char = source[index];
    const next = source[index + 1] || '';
    if (lineComment) {
      if (char === '\n') lineComment = false;
      continue;
    }
    if (blockComment) {
      if (char === '*' && next === '/') { blockComment = false; index += 1; }
      continue;
    }
    if (quote) {
      if (escapedChar) { escapedChar = false; continue; }
      if (char === '\\') { escapedChar = true; continue; }
      if (char === quote) quote = '';
      continue;
    }
    if (char === '/' && next === '/') { lineComment = true; index += 1; continue; }
    if (char === '/' && next === '*') { blockComment = true; index += 1; continue; }
    if (char === '\'' || char === '"' || char === '`') { quote = char; continue; }
    if (char === '{') depth += 1;
    if (char === '}') {
      depth -= 1;
      if (depth === 0) return source.slice(start, index + 1);
    }
  }
  throw new Error('function-extraction-close');
}

function extractLabToolSaveUrl(source) {
  const matches = Array.from(source.matchAll(/\bLAB_TOOL_SAVE\s*:\s*(['"])([^'"]+)\1/g));
  if (matches.length !== 1) throw new Error('api-extraction-count');
  return matches[0][2];
}

function bodyForDomain(domain) {
  if (domain === 'missing') return {};
  if (domain === 'false') return { ok: false };
  if (domain === 'truthy-nonliteral') return { ok: 1 };
  if (domain === 'confirmed') return { ok: true };
  throw new Error('unknown-domain');
}

async function readInput() {
  const chunks = [];
  for await (const chunk of process.stdin) chunks.push(chunk);
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

async function runCase(input) {
  const row = deriveCases().find(candidate => candidate.id === input.caseId);
  if (!row) throw new Error('unknown-case');
  if (typeof input.host !== 'string' || !input.host || typeof input.key !== 'string' || !input.key) {
    throw new Error('invalid-input');
  }

  const appPath = path.resolve(input.appPath);
  const source = fs.readFileSync(appPath, 'utf8');
  const ltSaveConfig = extractUniqueFunction(source, 'ltSaveConfig');
  const ltEl = extractUniqueFunction(source, '_ltEl');
  const saveUrl = extractLabToolSaveUrl(source);
  const launchOptions = { headless: true };
  const executableOverride = process.env.PVE_FREQ_PLAYWRIGHT_CHROMIUM_EXECUTABLE;
  if (executableOverride) launchOptions.executablePath = executableOverride;

  const browser = await chromium.launch(launchOptions);
  try {
    const context = await browser.newContext();
    try {
      const page = await context.newPage();
      await page.setContent('<input id="f12-lt-host"><input id="f12-lt-key" type="password">');
      await page.evaluate(({ decisions, host, key, saveUrl: exactSaveUrl }) => {
        const sentinelClasses = {
          F12_TRANSPORT_REJECTED: 'transport-rejected',
          F12_HTTP_REJECTED_JSON_RESOLVED: 'http-rejected-json-resolved',
          F12_HTTP_REJECTED_JSON_REJECTED: 'http-rejected-json-rejected',
          F12_HTTP_OK_JSON_REJECTED: 'http-ok-json-rejected',
          'Tool config save was not confirmed': 'domain-unconfirmed',
          'Tool config saved': 'success',
        };
        window.__f12Owner = { decisions, exactSaveUrl, dispatchCount: 0, urlMatches: true, events: [] };
        window.API = { LAB_TOOL_SAVE: exactSaveUrl };
        document.getElementById('f12-lt-host').value = host;
        document.getElementById('f12-lt-key').value = key;
        window.toast = function toast(message, type) {
          const eventClass = sentinelClasses[String(message)] || 'unclassified';
          window.__f12Owner.events.push({ type: String(type || 'info'), eventClass });
        };
        window._authFetch = function _authFetch(url) {
          window.__f12Owner.dispatchCount += 1;
          window.__f12Owner.urlMatches = window.__f12Owner.urlMatches && url === exactSaveUrl;
          if (decisions.transport === 'rejected') {
            return Promise.reject(new Error('F12_TRANSPORT_REJECTED'));
          }
          const ok = decisions.http === 'ok';
          return Promise.resolve({
            ok,
            json: function json() {
              if (decisions.json === 'rejected') {
                const message = ok ? 'F12_HTTP_OK_JSON_REJECTED' : 'F12_HTTP_REJECTED_JSON_REJECTED';
                return Promise.reject(new Error(message));
              }
              if (!ok) return Promise.resolve({ error: 'F12_HTTP_REJECTED_JSON_RESOLVED' });
              if (decisions.domain === 'missing') return Promise.resolve({});
              if (decisions.domain === 'false') return Promise.resolve({ ok: false });
              if (decisions.domain === 'truthy-nonliteral') return Promise.resolve({ ok: 1 });
              return Promise.resolve({ ok: true });
            },
          });
        };
      }, { decisions: row.decisions, host: input.host, key: input.key, saveUrl });
      await page.addScriptTag({ content: `${ltEl}\n${ltSaveConfig}` });
      return await page.evaluate(async ({ caseId, key }) => {
        const returned = window.ltSaveConfig('truenas', 'f12-');
        const thenable = Boolean(returned && typeof returned.then === 'function');
        if (thenable) await returned;
        await Promise.resolve();
        const state = window.__f12Owner;
        const successCount = state.events.filter(event => event.type === 'success').length;
        const errorCount = state.events.filter(event => event.type === 'error').length;
        const postSettlementKey = document.getElementById('f12-lt-key').value;
        return {
          caseId,
          dispatchCount: state.dispatchCount,
          urlMatches: state.urlMatches,
          thenable,
          keyRetained: postSettlementKey === key,
          keyCleared: postSettlementKey === '',
          eventClasses: state.events.map(event => event.eventClass),
          successCount,
          errorCount,
          terminalErrorClass: errorCount === 1 ? state.events.find(event => event.type === 'error').eventClass : null,
        };
      }, { caseId: row.id, key: input.key });
    } finally {
      await context.close();
    }
  } finally {
    await browser.close();
  }
}

async function main() {
  if (process.argv.includes('--list')) {
    process.stdout.write(`${JSON.stringify(deriveCases().map(publicCase))}\n`);
    return;
  }
  const input = await readInput();
  const result = await runCase(input);
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

main().catch(() => {
  process.stderr.write('{"error":"f12-browser-owner-failed"}\n');
  process.exitCode = 2;
});
