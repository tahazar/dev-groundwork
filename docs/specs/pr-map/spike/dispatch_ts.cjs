// Spike: super(...) and new this(...) definitions, constructor references through a subclass, and assignability to an interface.
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
const sf = ls.getProgram().getSourceFile(lib);
const at = (start) => { const lc = sf.getLineAndCharacterOfPosition(start); return `lib.ts:${lc.line + 1}:${lc.character + 1}`; };
for (const needle of ["super(2)", "new this", "this(1)"]) {
  const off = needle === "new this" ? 4 : 0;
  const defs = ls.getDefinitionAtPosition(lib, text.indexOf(needle) + off) || [];
  console.log(`getDefinitionAtPosition ${needle}:`, defs.map((d) => `${at(d.textSpan.start)} ${d.kind}`));
}
const refs = (ls.findReferences(lib, text.indexOf("constructor(public")) || []).flatMap((g) => g.references).filter((r) => !r.isDefinition);
console.log("findReferences Foo constructor:", refs.map((r) => `${at(r.textSpan.start)} "${text.substr(r.textSpan.start, r.textSpan.length)}"`));
const checker = ls.getProgram().getTypeChecker();
const typeOf = (name) => { let t; ts.forEachChild(sf, (n) => { if ((ts.isClassDeclaration(n) || ts.isInterfaceDeclaration(n)) && n.name.text === name) t = checker.getTypeAtLocation(n.name); }); return t; };
for (const name of ["Runner", "Shaped"]) console.log(`isTypeAssignableTo(${name}, Task):`, checker.isTypeAssignableTo(typeOf(name), typeOf("Task")));
