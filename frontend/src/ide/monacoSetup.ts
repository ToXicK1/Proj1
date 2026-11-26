// Monaco, bundled locally (Phase 2). @monaco-editor/react would otherwise download Monaco from a public CDN at run
// time; the IDE must work offline and load no code from third parties, so the loader is pointed at the pinned local
// package and Vite bundles the language workers (docs/rebuild/DEPENDENCIES.md).
import { loader } from "@monaco-editor/react";
import * as monaco from "monaco-editor";
import EditorWorker from "monaco-editor/editor/editor.worker.js?worker";
import CssWorker from "monaco-editor/language/css/css.worker.js?worker";
import HtmlWorker from "monaco-editor/language/html/html.worker.js?worker";
import JsonWorker from "monaco-editor/language/json/json.worker.js?worker";
import TsWorker from "monaco-editor/language/typescript/ts.worker.js?worker";

declare global {
  interface Window { MonacoEnvironment?: { getWorker(workerId: string, label: string): Worker } }
}

self.MonacoEnvironment = {
  getWorker(_workerId: string, label: string): Worker {
    if (label === "json") return new JsonWorker();
    if (label === "css" || label === "scss" || label === "less") return new CssWorker();
    if (label === "html" || label === "handlebars" || label === "razor") return new HtmlWorker();
    if (label === "typescript" || label === "javascript") return new TsWorker();
    return new EditorWorker();
  },
};

loader.config({ monaco });

const LANGUAGES: Record<string, string> = {
  py: "python", js: "javascript", mjs: "javascript", cjs: "javascript", ts: "typescript", tsx: "typescript",
  jsx: "javascript", json: "json", md: "markdown", html: "html", css: "css", yaml: "yaml", yml: "yaml",
  toml: "ini", cfg: "ini", ini: "ini", txt: "plaintext", svg: "xml", sql: "sql", sh: "shell",
};

export function languageOf(path: string): string {
  const extension = path.includes(".") ? path.split(".").pop()!.toLowerCase() : "";
  return LANGUAGES[extension] ?? "plaintext";
}
