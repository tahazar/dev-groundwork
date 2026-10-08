// For each mermaid.min.js given, renders `__init__` and `a*b*c` raw in a quoted label and prints the displayed text.
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const browser = await chromium.launch();
for (const file of process.argv.slice(2)) {
  const page = await browser.newPage();
  await page.setContent('<div id="host"></div>');
  await page.addScriptTag({ path: file });
  const out = [];
  for (const html of [true, false]) {
    const r = await page.evaluate(async (html) => {
      const m = window.mermaid;
      m.initialize({ startOnLoad: false, htmlLabels: html, flowchart: { htmlLabels: html } });
      const { svg } = await m.render('x' + Math.random().toString(36).slice(2), 'flowchart LR\n  a["__init__ a*b*c"]\n');
      const host = document.getElementById('host'); host.innerHTML = svg;
      return host.querySelector('g.node .label').textContent;
    }, html);
    out.push(`html=${html}: ${JSON.stringify(r)}`);
  }
  console.log(file.split('/').pop(), out.join('  '));
  await page.close();
}
await browser.close();
