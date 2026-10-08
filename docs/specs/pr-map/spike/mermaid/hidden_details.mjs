// Renders a diagram with labelled edges inside an iframe that sits in a closed <details>, the way
// GitHub embeds Mermaid in an iframe, then opens the details and reports the SVG size and any error.
// Usage: node hidden_details.mjs <mermaid.min.js>
import { createRequire } from 'node:module';
import fs from 'node:fs';
const require = createRequire(import.meta.url);
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const lib = fs.readFileSync(process.argv[2], 'utf8');
const SRC = 'flowchart LR\n  a["changed: foo\\nf.py:1"] -.->|possible| b["callee: bar\\ng.py:2"]\n  a -->|3| c["caller: baz\\nh.py:3"]\n';
const inner = (html) => `<!doctype html><body><pre class="mermaid">${SRC}</pre><script>${lib.replace(/<\/script/g, '<\\/script')}</script><script>
mermaid.initialize({startOnLoad:false, htmlLabels:${html}, flowchart:{htmlLabels:${html}}});
mermaid.run().then(() => { window.done = 'ok'; }, e => { window.done = 'error: ' + e.message; });
</script></body>`;
const browser = await chromium.launch();
for (const html of [true, false]) for (const open of [false, true]) {
  const page = await browser.newPage();
  await page.setContent(`<details ${open ? 'open' : ''}><summary>file</summary><iframe id="f" style="width:600px;height:300px" srcdoc="${inner(html).replace(/&/g, '&amp;').replace(/"/g, '&quot;')}"></iframe></details>`);
  const frame = page.frames()[1];
  await frame.waitForFunction(() => window.done, null, { timeout: 20000 });
  const before = await frame.evaluate(() => window.done);
  if (!open) await page.evaluate(() => { document.querySelector('details').open = true; });
  const after = await frame.evaluate(() => { const s = document.querySelector('svg'); if (!s) return 'no svg'; const b = s.getBoundingClientRect(); return `viewBox=${s.getAttribute('viewBox')} shown=${b.width.toFixed(0)}x${b.height.toFixed(0)} labels=${[...s.querySelectorAll('.edgeLabel')].map(e => e.textContent).join('|')}`; });
  console.log(`htmlLabels=${html} details ${open ? 'open at render' : 'closed at render, opened after'}: render=${before}; ${after}`);
  await page.close();
}
await browser.close();
