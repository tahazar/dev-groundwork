// Spike: constructors, object literals, structural types, overloads and an uninstalled library in TypeScript.
const ts = require(process.argv[2]);
const path = require("path"), fs = require("fs");
const dir = process.argv[3];
const cfg = ts.getParsedCommandLineOfConfigFile(path.join(dir, "tsconfig.json"), {}, { ...ts.sys, onUnRecoverableConfigFileDiagnostic: () => {} });
const host = {
  getScriptFileNames: () => cfg.fileNames, getScriptVersion: () => "0",
  getScriptSnapshot: (f) => (fs.existsSync(f) ? ts.ScriptSnapshot.fromString(fs.readFileSync(f, "utf8")) : undefined),
  getCurrentDirectory: () => dir, getCompilationSettings: () => cfg.options,
  getDefaultLibFileName: (o) => ts.getDefaultLibFilePath(o), fileExists: ts.sys.fileExists, readFile: ts.sys.readFile,
  readDirectory: ts.sys.readDirectory, directoryExists: ts.sys.directoryExists, getDirectories: ts.sys.getDirectories,
};
const ls = ts.createLanguageService(host, ts.createDocumentRegistry());
const show = (f, start) => { const sf = ls.getProgram().getSourceFile(f); const lc = sf.getLineAndCharacterOfPosition(start); return `${path.basename(f)}:${lc.line + 1}:${lc.character + 1}`; };
const lib = path.join(dir, "lib.ts"), use = path.join(dir, "use.ts");
const libText = fs.readFileSync(lib, "utf8"), useText = fs.readFileSync(use, "utf8");
for (const [label, needle, off] of [["constructor", "constructor(", 0], ["fake.run (object literal)", "{ run() {} };", 2], ["S.run (structural)", "class S { run", 10]]) {
  const refs = (ls.findReferences(lib, libText.indexOf(needle) + off) || []).flatMap((g) => g.references).filter((r) => !r.isDefinition && r.fileName === use);
  console.log(`findReferences ${label}: uses in use.ts =`, refs.map((r) => show(use, r.textSpan.start) + ` "${useText.substr(r.textSpan.start, r.textSpan.length)}"`));
}
for (const [label, needle, off] of [["new Foo", "new Foo", 4], ["ov(1)", "ov(1)", 0], ["s.run", "s.run", 2], ["Command (bare specifier, not installed)", "new Command", 4]]) {
  const defs = ls.getDefinitionAtPosition(use, useText.indexOf(needle) + off) || [];
  console.log(`getDefinitionAtPosition ${label}:`, defs.map((d) => `${show(d.fileName, d.textSpan.start)} ${d.kind}`));
}
