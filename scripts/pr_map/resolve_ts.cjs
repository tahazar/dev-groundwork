// pr-map's TypeScript resolver: answers "where is this defined?" with the TypeScript LanguageService.
//
// Design: docs/specs/pr-map/design.md, Pipeline step 7, "TypeScript".
// Usage: node resolve_ts.cjs <repository root> <JSON list of workspace package directories>
//
// Reads one JSON request per line on stdin and writes one JSON answer per line on stdout.
// Files are relative to the repository root; lines are 1-based; columns are 0-based UTF-16
// code units, TypeScript's own unit (resolve.py converts to and from characters).
//   {"id", "op": "definition" | "references", "file", "line", "column"}
//     -> {"id", "locations": [{"file", "line", "column", "kind", "name", "local"}]}
//     file is absolute; kind is DefinitionInfo.kind ("" for a reference); name is the definition's
//     qualified name, or a reference's text; local marks a parameter or a declaration inside a function
//   {"id", "op": "assignable", "source": {file, line, column}, "target": {file, line, column}}
//     source names a class, target a member of an interface
//     -> {"id", "assignable": bool}
//   {"id", "op": "trace", "file", "line", "column"} -> {"id", "traced": "library" | "repository" | ""}
//   any request that fails -> {"id", "error": "<what was being done>: <reason>"}
//
// It loads the typescript package pinned in this directory's package.json (5.9.3, research.md
// C14, C36): TypeScript 7 does not ship this API under the same entry point (C15).

"use strict";

const fs = require("fs");
const path = require("path");
const readline = require("readline");
// Only the copy `npm ci` installs next to this file: a global or parent typescript may be another version.
const ts = require(path.join(__dirname, "node_modules", "typescript"));

const root = path.resolve(process.argv[2]);
const packageDirs = JSON.parse(process.argv[3] || "[]").map((dir) => path.resolve(root, dir));

const unix = (file) => file.split(path.sep).join("/");

// Every package name in the repository: an import of one is never a library import (design, step 6).
const packageNames = new Set();
// Workspace package name -> its source entry, absolute (design, step 7; C38 to C40). Without it, a
// call into another package resolves to that package's built declaration file, and only after a build.
// Built on first use, so a broken package tsconfig becomes an error answer naming it, not a crash.
let workspace;

const registry = ts.createDocumentRegistry(); // shared, so lib files are parsed once for every tsconfig
const services = new Map(); // tsconfig path, or the repository root when no tsconfig is found -> Service

function workspacePaths() {
  if (workspace) return workspace;
  const found = {};
  for (const dir of packageDirs) {
    let pkg;
    try {
      pkg = JSON.parse(fs.readFileSync(path.join(dir, "package.json"), "utf8"));
    } catch {
      continue; // not a readable package.json: not a package this mapping can serve
    }
    if (typeof pkg.name === "string") packageNames.add(pkg.name);
    const types = pkg.types || pkg.typings;
    const config = path.join(dir, "tsconfig.json");
    if (typeof pkg.name !== "string" || typeof types !== "string" || !fs.existsSync(config)) continue;
    const parsed = parseConfig(config);
    const outDir = parsed.options.outDir;
    const rootDir = parsed.options.rootDir || commonDirectory(parsed.fileNames);
    const built = path.resolve(dir, types);
    if (!outDir || !rootDir || path.relative(outDir, built).startsWith("..")) continue;
    const stem = path.join(rootDir, path.relative(outDir, built)).replace(/\.d\.([mc]?)ts$/, ".$1ts");
    const source = [stem, stem.replace(/\.ts$/, ".tsx")].find((file) => fs.existsSync(file));
    if (source) found[pkg.name] = unix(source);
  }
  workspace = found;
  return found;
}

// The deepest directory holding every non-declaration source file: TypeScript's rootDir when none is set.
function commonDirectory(files) {
  const sources = files.filter((file) => !/\.d\.[mc]?ts$/.test(file)).map((file) => path.dirname(path.resolve(file)));
  if (!sources.length) return undefined;
  let common = sources[0];
  for (const dir of sources) {
    while (path.relative(common, dir).startsWith("..")) common = path.dirname(common);
  }
  return common;
}

function parseConfig(file) {
  const host = {
    ...ts.sys,
    onUnRecoverableConfigFileDiagnostic: (diagnostic) => {
      throw new Error(`reading ${file}: ${ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n")}`);
    },
  };
  return ts.getParsedCommandLineOfConfigFile(file, {}, host);
}

// A `paths` key matches a module name exactly, or with its one `*` standing for any text.
function pathsKeyMatches(key, name) {
  const star = key.indexOf("*");
  if (star < 0) return key === name;
  const prefix = key.slice(0, star);
  const suffix = key.slice(star + 1);
  return name.length >= prefix.length + suffix.length && name.startsWith(prefix) && name.endsWith(suffix);
}

class Service {
  constructor(config) {
    let options, files;
    if (config) {
      const parsed = parseConfig(config);
      options = parsed.options;
      files = parsed.fileNames;
    } else {
      // No tsconfig.json: what an empty one at the repository root would give, default options included.
      const parsed = ts.parseJsonConfigFileContent({}, ts.sys, root);
      options = parsed.options;
      files = parsed.fileNames;
    }
    const own = options.paths || {};
    const paths = { ...own };
    for (const [name, source] of Object.entries(workspacePaths())) {
      // The project's own paths win when both name a package (design, step 7).
      if (!Object.keys(own).some((key) => pathsKeyMatches(key, name))) paths[name] = [source];
    }
    this.options = { ...options, paths };
    this.files = new Set(files.map((file) => unix(path.resolve(file))));
    this.version = 0;
    const directory = config ? path.dirname(config) : root;
    const host = {
      getProjectVersion: () => String(this.version),
      getScriptFileNames: () => [...this.files],
      getScriptVersion: () => "0", // files do not change while pr-map runs
      getScriptSnapshot: (file) =>
        fs.existsSync(file) ? ts.ScriptSnapshot.fromString(fs.readFileSync(file, "utf8")) : undefined,
      getCurrentDirectory: () => directory,
      getCompilationSettings: () => this.options,
      getDefaultLibFileName: (o) => ts.getDefaultLibFilePath(o),
      fileExists: ts.sys.fileExists,
      readFile: ts.sys.readFile,
      readDirectory: ts.sys.readDirectory,
      directoryExists: ts.sys.directoryExists,
      getDirectories: ts.sys.getDirectories,
    };
    this.ls = ts.createLanguageService(host, registry);
  }

  // The source file of an absolute path, added to the root files when the tsconfig does not include it
  // (a test directory outside `include`), so that its references resolve.
  sourceFile(file) {
    if (!fs.existsSync(file)) throw new Error(`${file} does not exist`);
    if (!this.files.has(file)) {
      this.files.add(file);
      this.version += 1;
    }
    const source = this.ls.getProgram().getSourceFile(file);
    if (!source) throw new Error(`the TypeScript program has no source file ${file}`);
    return source;
  }
}

// The LanguageService of the nearest tsconfig.json at or above the file, up to the repository root.
function serviceFor(file) {
  let dir = path.dirname(file);
  let config;
  for (;;) {
    const candidate = path.join(dir, "tsconfig.json");
    if (fs.existsSync(candidate)) {
      config = candidate;
      break;
    }
    if (dir === root || path.dirname(dir) === dir || path.relative(root, dir).startsWith("..")) break;
    dir = path.dirname(dir);
  }
  const key = config || root;
  if (!services.has(key)) services.set(key, new Service(config));
  return services.get(key);
}

function locate(where) {
  const file = unix(path.resolve(root, where.file));
  const service = serviceFor(file);
  const source = service.sourceFile(file);
  const position = positionOf(source, where.line, where.column);
  return { file, service, source, position };
}

// Lines here end at "\n" only, as in resolve.py and tree-sitter. TypeScript's own line map also breaks at
// "\r", U+2028 and U+2029, which would shift every line below one of them.
function lineStarts(source) {
  if (!source.newlineStarts) {
    const starts = [0];
    for (let i = source.text.indexOf("\n"); i >= 0; i = source.text.indexOf("\n", i + 1)) starts.push(i + 1);
    source.newlineStarts = starts;
  }
  return source.newlineStarts;
}

function positionOf(source, line, column) {
  const starts = lineStarts(source);
  if (!(line >= 1 && line <= starts.length)) throw new Error(`line ${line} is outside the file's ${starts.length} lines`);
  const end = line < starts.length ? starts[line] - 1 : source.text.length;
  if (column > end - starts[line - 1]) throw new Error(`column ${column} is past the end of line ${line}`);
  return starts[line - 1] + column;
}

function lineAndColumn(source, position) {
  const starts = lineStarts(source);
  let line = 0;
  while (line + 1 < starts.length && starts[line + 1] <= position) line += 1;
  return { line: line + 1, column: position - starts[line] };
}

// The innermost node whose text (without leading trivia) contains position.
function nodeAt(source, position) {
  let found = source;
  const visit = (node) => {
    if (node.getStart(source) <= position && position < node.getEnd()) {
      found = node;
      ts.forEachChild(node, visit);
    }
  };
  ts.forEachChild(source, visit);
  return found;
}

function location(service, file, start, kind, name) {
  const source = service.ls.getProgram().getSourceFile(file);
  const { line, column } = lineAndColumn(source, start);
  return { file, line, column, kind, name, local: isLocal(nodeAt(source, start)) };
}

// A parameter, a type parameter, or a declaration inside a function body: something no box can be.
function isLocal(node) {
  const declaration = node.parent;
  if (!declaration) return false;
  if (ts.isParameter(declaration) || ts.isTypeParameterDeclaration(declaration)) return true;
  if (declaration.name !== node) return false;
  for (let up = declaration.parent; up; up = up.parent) {
    if (ts.isFunctionLike(up)) return true;
  }
  return false;
}

function definition(request) {
  const { file, service, position } = locate(request);
  const found = service.ls.getDefinitionAtPosition(file, position) || [];
  // A module's container name is its quoted path ("/repo/src/lib".target): left out.
  const name = (d) => (d.containerName && !d.containerName.startsWith('"') ? `${d.containerName}.${d.name}` : d.name);
  return { locations: found.map((d) => location(service, unix(d.fileName), d.textSpan.start, d.kind, name(d))) };
}

function references(request) {
  const { file, service, position } = locate(request);
  const groups = service.ls.findReferences(file, position) || [];
  const locations = [];
  for (const group of groups) {
    for (const ref of group.references) {
      if (ref.isDefinition) continue;
      const text = service.ls.getProgram().getSourceFile(ref.fileName).text;
      const name = text.slice(ref.textSpan.start, ref.textSpan.start + ref.textSpan.length);
      locations.push(location(service, unix(ref.fileName), ref.textSpan.start, "", name));
    }
  }
  return { locations };
}

// Whether the class named at source is assignable to the interface holding the function member named at
// target (design, step 6, "TypeScript, structural"; C63, C64). A data member is never related.
function assignable(request) {
  const from = locate(request.source);
  const targetFile = unix(path.resolve(root, request.target.file));
  from.service.sourceFile(targetFile); // the interface may sit outside the class's project
  const program = from.service.ls.getProgram(); // after any added root file, so its nodes are current
  const checker = program.getTypeChecker();
  const cls = nodeAt(program.getSourceFile(from.file), from.position).parent;
  if (!cls || !(ts.isClassDeclaration(cls) || ts.isClassExpression(cls)) || cls.name === undefined) {
    throw new Error(`no class is named at ${request.source.file}:${request.source.line}:${request.source.column}`);
  }
  const targetSource = program.getSourceFile(targetFile);
  const at = positionOf(targetSource, request.target.line, request.target.column);
  const member = nodeAt(targetSource, at).parent;
  if (!member || !(ts.isMethodSignature(member) || ts.isPropertySignature(member))) return { assignable: false };
  if (!ts.isInterfaceDeclaration(member.parent)) return { assignable: false };
  if (ts.isPropertySignature(member) && !checker.getTypeAtLocation(member).getCallSignatures().length) {
    return { assignable: false };
  }
  if (member.parent.typeParameters || cls.typeParameters) {
    // A generic type's declared form leaves its parameters open, so `Users` is not assignable to
    // `Repo<T>` although it fits `Repo<string>`. Without the instantiation the call uses, the class is
    // not ruled out: related, which only ever gives a possible arrow.
    return { assignable: true };
  }
  const classType = checker.getTypeAtLocation(cls.name);
  const ifaceType = checker.getTypeAtLocation(member.parent.name);
  return { assignable: checker.isTypeAssignableTo(classType, ifaceType) };
}

// Where the leftmost name at a site comes from (design, step 6, "Library calls"): the import it names,
// through one `const`/`let`/`var` assigned once or a parameter's type annotation. A bare specifier that
// is neither a workspace package nor a `paths` key of the project is a library.
function trace(request) {
  const { file, service, source, position } = locate(request);
  const checker = service.ls.getProgram().getTypeChecker();
  const specifier = importOf(leftmost(nodeAt(source, position)), checker, service, file, true);
  if (specifier === undefined) return { traced: "" };
  if (specifier.startsWith(".") || path.isAbsolute(specifier)) return { traced: "repository" };
  workspacePaths();
  const ownPackage = [...packageNames].some((name) => specifier === name || specifier.startsWith(name + "/"));
  const pathsKey = Object.keys(service.options.paths || {}).some((key) => pathsKeyMatches(key, specifier));
  return { traced: ownPackage || pathsKey ? "repository" : "library" };
}

// The first name of an expression: `program` in `program.action`, `Command` in `new Command().action`.
function leftmost(node) {
  if (node.parent && ts.isPropertyAccessExpression(node.parent) && node.parent.name === node) node = node.parent;
  if (ts.isTypeReferenceNode(node)) node = node.typeName;
  for (;;) {
    if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) node = node.expression;
    else if (ts.isCallExpression(node) || ts.isNewExpression(node)) node = node.expression;
    else if (ts.isNonNullExpression(node) || ts.isParenthesizedExpression(node)) node = node.expression;
    else if (ts.isQualifiedName(node)) node = node.left;
    else break;
  }
  return ts.isIdentifier(node) ? node : undefined;
}

function importOf(name, checker, service, file, follow) {
  if (!name) return undefined;
  const symbol = checker.getSymbolAtLocation(name);
  const declaration = symbol && symbol.declarations && symbol.declarations.length === 1 && symbol.declarations[0];
  if (!declaration) return undefined;
  let holder = declaration;
  while (holder && !ts.isImportDeclaration(holder) && !ts.isImportEqualsDeclaration(holder)) {
    if (!(ts.isImportSpecifier(holder) || ts.isNamedImports(holder) || ts.isImportClause(holder) || ts.isNamespaceImport(holder))) {
      holder = undefined;
      break;
    }
    holder = holder.parent;
  }
  if (holder && ts.isImportDeclaration(holder)) return holder.moduleSpecifier.text;
  if (holder && ts.isImportEqualsDeclaration(holder) && ts.isExternalModuleReference(holder.moduleReference)) {
    return holder.moduleReference.expression.text;
  }
  if (!follow) return undefined;
  if (ts.isVariableDeclaration(declaration) && ts.isIdentifier(declaration.name) && declaration.initializer) {
    const writes = (service.ls.getReferencesAtPosition(file, declaration.name.getStart()) || []).filter(
      (ref) => ref.isWriteAccess,
    );
    if (writes.length !== 1) return undefined; // assigned more than once: not traced
    return importOf(leftmost(declaration.initializer), checker, service, file, false);
  }
  if (ts.isParameter(declaration) && declaration.type) {
    return importOf(leftmost(declaration.type), checker, service, file, false);
  }
  return undefined;
}

const OPS = { definition, references, assignable, trace };

function answer(line) {
  let request;
  try {
    request = JSON.parse(line);
  } catch (error) {
    return { id: null, error: `reading the request ${JSON.stringify(line)}: ${error.message}` };
  }
  const op = OPS[request.op];
  if (!op) return { id: request.id, error: `unknown op ${JSON.stringify(request.op)}` };
  try {
    return { id: request.id, ...op(request) };
  } catch (error) {
    const where = request.source || request;
    return { id: request.id, error: `${request.op} at ${where.file}:${where.line}:${where.column}: ${error.message}` };
  }
}

readline.createInterface({ input: process.stdin }).on("line", (line) => {
  if (line.trim()) process.stdout.write(JSON.stringify(answer(line)) + "\n");
});
