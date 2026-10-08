// Renders a 6-box file map and a 25-box function map as LR and TB and reports SVG size and the
// font size the 16px labels shrink to when the SVG is scaled to a 358px column (390px phone minus 16px gutters).
// Usage: node phone_width.mjs <mermaid.min.js>
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const { chromium } = require('/opt/node22/lib/node_modules/playwright');
const COLUMN = 358;
function fileMap(dir) {
  const files = ['scripts/pr_map/render.py', 'scripts/pr_map/graph.py', 'scripts/pr_map/cli.py', 'scripts/pr_map/ts_refs.mjs', 'scripts/pr_map/py_refs.py', 'tests/test_render.py'];
  const st = ['changed', 'changed', 'added', 'unchanged', 'unchanged', 'changed'];
  const L = [`flowchart ${dir}`];
  files.forEach((f, i) => L.push(`  f${i}["${st[i]}\\n${f}"]`));
  [[2, 0, 3], [0, 1, 5], [1, 3, 2], [1, 4, 1], [5, 0, 4], [2, 1, 1]].forEach(([a, b, n]) => L.push(`  f${a} -->|${n}| f${b}`));
  return L.join('\n') + '\n';
}
function functionMapShort(dir) {
  // Same graph with short labels: own-file constructs show only `:line`, neighbours show the file's basename.
  return functionMap(dir).replace(/scripts\/pr_map\/render\.py:/g, ':').replace(/scripts\/pr_map\//g, '');
}
function fileMapShort(dir) {
  // File map with the directory on its own line, so the widest line is shorter.
  return fileMap(dir).replace(/\\n(scripts\/pr_map\/|tests\/)/g, '\\n$1\\n');
}
function functionMap(dir) {
  // 5 changed constructs in one file, each with 4 one-step neighbours in other files: 25 boxes.
  const L = [`flowchart ${dir}`];
  const changed = ['mermaid', 'escape', 'diagrams', '_groups', '_parts'];
  changed.forEach((c, i) => L.push(`  c${i}["changed: ${c}\\nscripts/pr_map/render.py:${100 + i * 20}"]`));
  let k = 0;
  changed.forEach((c, i) => {
    for (let j = 0; j < 4; j++, k++) {
      const caller = j < 2;
      L.push(`  n${k}["${caller ? 'caller' : 'callee'}: helper_${k}\\nscripts/pr_map/mod_${j}.py:${10 + k}"]`);
      L.push(caller ? `  n${k} --> c${i}` : `  c${i} --> n${k}`);
    }
  });
  return L.join('\n') + '\n';
}
const browser = await chromium.launch();
const page = await browser.newPage();
await page.setContent('<div id="host"></div>');
await page.addScriptTag({ path: process.argv[2] });
for (const [name, gen] of [['file map, 6 boxes', fileMap], ['file map, dir on own line', fileMapShort], ['function map, 25 boxes', functionMap], ['function map, short labels', functionMapShort]]) for (const dir of ['LR', 'TB']) for (const html of [true, false]) {
  const box = await page.evaluate(async ({ src, html }) => {
    const m = window.mermaid;
    m.initialize({ startOnLoad: false, theme: 'dark', htmlLabels: html, flowchart: { htmlLabels: html } });
    const { svg } = await m.render('w' + Math.random().toString(36).slice(2), src);
    const vb = svg.match(/viewBox="([^"]+)"/)[1].split(' ').map(Number);
    return { w: vb[2], h: vb[3] };
  }, { src: gen(dir), html });
  const scale = Math.min(1, COLUMN / box.w);
  console.log(`${name}\t${dir}\thtmlLabels=${html}\twidth=${box.w.toFixed(0)}\theight=${box.h.toFixed(0)}\tscale@${COLUMN}px=${scale.toFixed(2)}\tfont=${(16 * scale).toFixed(1)}px\tscaled height=${(box.h * scale).toFixed(0)}px`);
}
await browser.close();
