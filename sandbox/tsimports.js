// Imports of TypeScript/JavaScript files, through the TypeScript compiler's own parser (Codebase Explorer).
// Reads {path: source} as JSON on stdin; writes {path: {status, imports: [{spec, kind, line, dynamic?, type_only?}]}}.
// Kinds: import, re_export, require, dynamic_import. A require()/import() whose argument is not a string literal is
// recorded as dynamic, with no target. Deterministic; runs with no network.
"use strict";
const ts = require(process.env.AIDLC_TS_PATH || "/opt/runner/node_modules/typescript");

function kindOf(path) {
  if (path.endsWith(".tsx")) return ts.ScriptKind.TSX;
  if (path.endsWith(".jsx")) return ts.ScriptKind.JSX;
  if (/\.(js|mjs|cjs)$/.test(path)) return ts.ScriptKind.JS;
  return ts.ScriptKind.TS;
}

function analyse(path, text) {
  const source = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, kindOf(path));
  const out = [];
  const line = (node) => source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1;
  const literal = (node) => (node && (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) ? node.text : null);
  function visit(node) {
    if (ts.isImportDeclaration(node) && literal(node.moduleSpecifier) !== null) {
      out.push({ spec: literal(node.moduleSpecifier), kind: "import", line: line(node),
        type_only: Boolean(node.importClause && node.importClause.isTypeOnly) });
    } else if (ts.isExportDeclaration(node) && node.moduleSpecifier && literal(node.moduleSpecifier) !== null) {
      out.push({ spec: literal(node.moduleSpecifier), kind: "re_export", line: line(node), type_only: Boolean(node.isTypeOnly) });
    } else if (ts.isImportEqualsDeclaration(node) && ts.isExternalModuleReference(node.moduleReference)) {
      const spec = literal(node.moduleReference.expression);
      out.push(spec === null ? { spec: "", kind: "require", line: line(node), dynamic: true } : { spec, kind: "require", line: line(node) });
    } else if (ts.isCallExpression(node)) {
      const isImport = node.expression.kind === ts.SyntaxKind.ImportKeyword;
      const isRequire = ts.isIdentifier(node.expression) && node.expression.text === "require" && node.arguments.length === 1;
      if (isImport || isRequire) {
        const spec = literal(node.arguments[0]);
        const kind = isImport ? "dynamic_import" : "require";
        out.push(spec === null ? { spec: "", kind, line: line(node), dynamic: true } : { spec, kind, line: line(node) });
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  const broken = source.parseDiagnostics && source.parseDiagnostics.length > 0;
  return { status: broken ? "parsed_with_errors" : "parsed", imports: out };
}

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => { input += chunk; });
process.stdin.on("end", () => {
  const files = JSON.parse(input || "{}");
  const result = {};
  for (const [path, text] of Object.entries(files)) {
    try { result[path] = analyse(path, text); }
    catch (e) { result[path] = { status: "parse_error", imports: [], error: String(e).slice(0, 160) }; }
  }
  process.stdout.write(JSON.stringify(result));
});
