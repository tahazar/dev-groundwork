// Renders nodes with stroke-only classDefs in each theme and prints computed fill, text colour, stroke and contrast ratios.
// Usage: node theme_contrast.mjs <mermaid.min.js>
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const SRC = `flowchart LR
  p["plain: neighbour\\nf.py:1"]
  c["changed: foo\\nf.py:2"]
  a["added: bar\\nf.py:3"]
  r["removed: baz\\nf.py:4"]
  n["neighbour: qux\\ng.py:5"]
  p --> c --> a --> r --> n
  classDef changed stroke:#9a6700,stroke-width:3px
  classDef added stroke:#1a7f37,stroke-width:3px
  classDef removed stroke:#cf222e,stroke-width:3px,stroke-dasharray:6 4
  classDef neighbour stroke-dasharray:3 3
  class c changed
  class a added
  class r removed
  class n neighbour
`;
const PAGES = { 'github-light': '#ffffff', 'github-dark': '#0d1117' };
const lum = (rgb) => { const [r, g, b] = rgb.map(v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
const parse = (s) => { if (s.startsWith('#')) { const h = s.length === 4 ? s.slice(1).split('').map(x => x + x).join('') : s.slice(1); return [0, 2, 4].map(i => parseInt(h.slice(i, i + 2), 16)); } const m = s.match(/[\d.]+/g); return m ? m.slice(0, 3).map(Number) : null; };
const ratio = (x, y) => { const [a, b] = [lum(parse(x)), lum(parse(y))].sort((p, q) => q - p); return ((a + 0.05) / (b + 0.05)).toFixed(2); };
const browser = await chromium.launch();
const page = await browser.newPage();
await page.setContent('<div id="host"></div>');
await page.addScriptTag({ path: process.argv[2] });
for (const theme of ['default', 'neutral', 'dark']) for (const html of [true, false]) {
  const nodes = await page.evaluate(async ({ theme, html, SRC }) => {
    const m = window.mermaid;
    m.initialize({ startOnLoad: false, theme, htmlLabels: html, flowchart: { htmlLabels: html } });
    const { svg } = await m.render('t' + Math.random().toString(36).slice(2), SRC);
    const host = document.getElementById('host'); host.innerHTML = svg;
    return [...host.querySelectorAll('g.node')].map(g => {
      const shape = getComputedStyle(g.querySelector('rect.label-container, rect.basic, rect'));
      const textEl = g.querySelector('.label foreignObject span, .label foreignObject div, .label text');
      const ts = getComputedStyle(textEl);
      return { cls: g.getAttribute('class'), fill: shape.fill, stroke: shape.stroke, strokeWidth: shape.strokeWidth, dash: shape.strokeDasharray, text: html ? ts.color : ts.fill };
    });
  }, { theme, html, SRC });
  for (const n of nodes) {
    const pageRatios = Object.entries(PAGES).map(([k, bg]) => `stroke/${k}=${ratio(n.stroke, bg)}`).join(' ');
    console.log(`theme=${theme} html=${html} ${n.cls.replace('node default ', '')}: fill=${n.fill} text=${n.text} text/fill=${ratio(n.text, n.fill)} stroke=${n.stroke} width=${n.strokeWidth} dash=${n.dash} stroke/fill=${ratio(n.stroke, n.fill)} ${pageRatios}`);
  }
}
await browser.close();
