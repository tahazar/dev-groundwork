// Renders one node per (version, config, strategy, name) in Chromium and records the label's displayed text.
// Usage: node escape_matrix.mjs <out.json> <version>=<mermaid.min.js> ...
import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
const require = createRequire(import.meta.url);
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const [out, ...specs] = process.argv.slice(2);
const VERSIONS = Object.fromEntries(specs.map(s => s.split('=')));
const NAMES = ['__init__', 'merge_base', '_private', 'Map<string, T>', 'a*b*c', 'x"y', '#tag', 'a`b`c', '[x]', 'foo\\bar', '~x~', 'a & b', '.groundwork/bin/pr_map.py:12', '_x_', '#count', '$store', 'app/[id]/(group)/page.tsx', '@scope/pkg/index.ts', 'obj.__eq__', 'a < b'];
const LINE2 = 'f.py:1';
const ent = (s, chars) => [...s].map(c => chars.includes(c) ? `#${c.codePointAt(0)};` : c).join('');
const STRATEGIES = {
  a_entities: s => ent(s, '#"<>&`_*~[]\\'),
  b_raw: s => s,
  c_backslash: s => [...s].map(c => c === '"' ? '#34;' : ('\\`*_[]~#<>&'.includes(c) && '\\`*_[]~'.includes(c) ? '\\' + c : c)).join(''),
  d_quote_only: s => ent(s, '"'),
  e_html_entities: s => [...s].map(c => '#"<>&`_*~[]\\'.includes(c) ? `&#${c.codePointAt(0)};` : c).join(''),
  f_markdown_string_raw: s => s, // wrapped in backticks below
  g_quote_hash_lt_amp: s => ent(s, '"#<>&'),
  h_raw_named_lt_gt_quot: s => [...s].map(c => ({ '<': '#lt;', '>': '#gt;', '"': '#quot;' })[c] ?? c).join(''),
};
const CONFIGS = [];
for (const html of [true, false]) for (const theme of ['default', 'dark']) for (const sec of ['strict', 'loose']) CONFIGS.push({ html, theme, sec });
const browser = await chromium.launch();
const results = [];
for (const [ver, dir] of Object.entries(VERSIONS)) {
  const page = await browser.newPage();
  await page.setContent('<html><body><div id="host"></div></body></html>');
  await page.addScriptTag({ path: dir });
  for (const cfg of CONFIGS) for (const [sname, fn] of Object.entries(STRATEGIES)) for (const name of NAMES) {
    const body = fn(name) + '\n' + LINE2;
    const label = sname === 'f_markdown_string_raw' ? '`' + body + '`' : body;
    const src = `flowchart LR\n  n1["${label}"]\n`;
    const r = await page.evaluate(async ({ src, cfg }) => {
      const m = window.mermaid;
      m.initialize({ startOnLoad: false, theme: cfg.theme, securityLevel: cfg.sec, htmlLabels: cfg.html, flowchart: { htmlLabels: cfg.html } });
      const host = document.getElementById('host');
      host.innerHTML = '';
      try {
        const { svg } = await m.render('d' + Math.random().toString(36).slice(2), src);
        host.innerHTML = svg;
        const lab = host.querySelector('g.node .label');
        const fo = lab.querySelector('foreignObject');
        let text;
        if (fo) text = fo.querySelector('div,span').innerText;
        else text = [...lab.querySelectorAll('tspan.text-outer-tspan')].map(t => t.textContent).join('\n');
        return { text, fo: !!fo, strong: !!lab.querySelector('strong,em,[font-weight="bold"],[font-style="italic"]') };
      } catch (e) { return { error: String(e.message || e).split('\n')[0].slice(0, 120) }; }
    }, { src, cfg });
    results.push({ version: ver, ...cfg, strategy: sname, name, source: label, ...r, exact: r.text !== undefined && r.text.replace(/\s+/g, ' ') === (name + ' ' + LINE2).replace(/\s+/g, ' '), exactIgnoringWrap: r.text !== undefined && r.text.replace(/\s/g, '') === (name + LINE2).replace(/\s/g, '') });
  }
  await page.close();
}
await browser.close();
fs.writeFileSync(out, JSON.stringify(results, null, 1));
console.log(results.length, 'renders');
