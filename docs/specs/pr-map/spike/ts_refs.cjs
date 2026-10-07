// Spike: resolve references to a function with TypeScript's LanguageService.findReferences.
const ts = require(process.argv[2]);
const path = require("path"), fs = require("fs");
const [, , , tsconfigPath, file, name] = process.argv;
const t0 = Date.now();
const cfg = ts.getParsedCommandLineOfConfigFile(tsconfigPath, {}, { ...ts.sys, onUnRecoverableConfigFileDiagnostic: () => {} });
const files = new Map(cfg.fileNames.map(f => [f, 0]));
const host = {
  getScriptFileNames: () => cfg.fileNames, getScriptVersion: () => "0",
  getScriptSnapshot: f => fs.existsSync(f) ? ts.ScriptSnapshot.fromString(fs.readFileSync(f, "utf8")) : undefined,
  getCurrentDirectory: () => path.dirname(tsconfigPath), getCompilationSettings: () => cfg.options,
  getDefaultLibFileName: o => ts.getDefaultLibFilePath(o), fileExists: ts.sys.fileExists, readFile: ts.sys.readFile,
  readDirectory: ts.sys.readDirectory, directoryExists: ts.sys.directoryExists, getDirectories: ts.sys.getDirectories,
};
const ls = ts.createLanguageService(host, ts.createDocumentRegistry());
const abs = path.resolve(file), text = fs.readFileSync(abs, "utf8");
const pos = text.search(new RegExp(`function ${name}\\b`)) + "function ".length;
const groups = ls.findReferences(abs, pos) || [];
const refs = groups.flatMap(g => g.references).filter(r => !r.isDefinition);
console.log(`files in program=${cfg.fileNames.length} references to ${name}=${refs.length} seconds=${((Date.now()-t0)/1000).toFixed(1)}`);
for (const r of refs.slice(0, 6)) { const sf = ls.getProgram().getSourceFile(r.fileName); const lc = sf.getLineAndCharacterOfPosition(r.textSpan.start); console.log(" ", path.relative(process.cwd(), r.fileName) + ":" + (lc.line + 1)); }
