// Spike: go-to-definition with TypeScript's LanguageService for a call inside the CLI.
const ts = require(process.argv[2]);
const path = require("path"), fs = require("fs");
const [, , , tsconfigPath, file, line, needle, pathsJson] = process.argv;
const cfg = ts.getParsedCommandLineOfConfigFile(tsconfigPath, {}, { ...ts.sys, onUnRecoverableConfigFileDiagnostic: () => {} });
const host = {
  getScriptFileNames: () => cfg.fileNames, getScriptVersion: () => "0",
  getScriptSnapshot: (f) => (fs.existsSync(f) ? ts.ScriptSnapshot.fromString(fs.readFileSync(f, "utf8")) : undefined),
  getCurrentDirectory: () => path.dirname(tsconfigPath), getCompilationSettings: () => (pathsJson ? { ...cfg.options, paths: JSON.parse(pathsJson) } : cfg.options),
  getDefaultLibFileName: (o) => ts.getDefaultLibFilePath(o), fileExists: ts.sys.fileExists, readFile: ts.sys.readFile,
  readDirectory: ts.sys.readDirectory, directoryExists: ts.sys.directoryExists, getDirectories: ts.sys.getDirectories,
};
const ls = ts.createLanguageService(host, ts.createDocumentRegistry());
const abs = path.resolve(file), text = fs.readFileSync(abs, "utf8");
const lines = text.split("\n");
const col = lines[Number(line) - 1].indexOf(needle);
const pos = lines.slice(0, Number(line) - 1).reduce((n, l) => n + l.length + 1, 0) + col;
const defs = ls.getDefinitionAtPosition(abs, pos) || [];
console.log(`${needle} at ${file}:${line} -> ${defs.length} definition(s)`);
for (const d of defs) {
  const sf = ls.getProgram().getSourceFile(d.fileName);
  const lc = sf.getLineAndCharacterOfPosition(d.textSpan.start);
  console.log("  ", path.relative(process.cwd(), d.fileName) + ":" + (lc.line + 1), d.kind, d.name);
}
