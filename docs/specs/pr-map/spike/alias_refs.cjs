// Spike: does findReferences on a definition include uses through a renamed import, a default import, and an interface?
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
const lib = path.join(dir, "lib.ts"), text = fs.readFileSync(lib, "utf8");
for (const [label, needle] of [["named export readClip", "function readClip"], ["default export loadSet", "function loadSet"], ["Impl.run", "class Impl extends Mid { run"]]) {
  const pos = text.indexOf(needle) + needle.length - (needle.endsWith("run") ? 3 : needle.split(" ").pop().length);
  const groups = ls.findReferences(lib, pos) || [];
  const uses = groups.flatMap((g) => g.references).filter((r) => !r.isDefinition && r.fileName.endsWith("use.ts"));
  const sf = ls.getProgram().getSourceFile(path.join(dir, "use.ts"));
  console.log(`${label}: uses in use.ts =`, uses.map((r) => { const lc = sf.getLineAndCharacterOfPosition(r.textSpan.start); return `${lc.line + 1}:${lc.character + 1} "${sf.text.substr(r.textSpan.start, r.textSpan.length)}"`; }));
}
