// Probes ways to show `<`, `>` and `"` in a node label. Usage: node probe_lt_quote.mjs <min.js>...
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const ZW = '​';
const CASES = [
  ['raw <', 'n1["Map<string, T>"]'],
  ['< + ZWSP', `n1["Map<${ZW}string, T>"]`],
  ['#lt; #gt;', 'n1["Map#lt;string, T#gt;"]'],
  ['#60; #62;', 'n1["Map#60;string, T#62;"]'],
  ['&lt; &gt;', 'n1["Map&lt;string, T&gt;"]'],
  ['< + space', 'n1["Map< string, T>"]'],
  ['#34;', 'n1["x#34;y"]'],
  ['#quot;', 'n1["x#quot;y"]'],
  ['unquoted x"y', 'n1[x"y]'],
  ['markdown string x"y', 'n1["`x"y`"]'],
  ['raw &amp; text', 'n1["a &amp; b"]'],
];
const browser = await chromium.launch();
for (const file of process.argv.slice(2)) {
  const page = await browser.newPage();
  await page.setContent('<div id="host"></div>');
  await page.addScriptTag({ path: file });
  for (const html of [true, false]) for (const [label, node] of CASES) {
    const r = await page.evaluate(async ({ html, node }) => {
      const m = window.mermaid;
      m.initialize({ startOnLoad: false, htmlLabels: html, flowchart: { htmlLabels: html } });
      try {
        const { svg } = await m.render('x' + Math.random().toString(36).slice(2), 'flowchart LR\n  ' + node + '\n');
        const host = document.getElementById('host'); host.innerHTML = svg;
        return JSON.stringify(host.querySelector('g.node .label').textContent);
      } catch (e) { return 'PARSE ERROR'; }
    }, { html, node });
    console.log(`${file.split('/').slice(-3).join('/')}\thtml=${html}\t${label}\t${r}`);
  }
  await page.close();
}
await browser.close();
