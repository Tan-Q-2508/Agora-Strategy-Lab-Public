/**
 * Monaco set up for Agora: bundled locally (no CDN), Python only, one editor worker.
 * Loaded on demand by the code editor so other screens stay small.
 */
import { loader } from "@monaco-editor/react";
import EditorWorker from "monaco-esm/editor/editor.worker.js?worker";
import * as monaco from "./monacoBundle";

declare global {
  interface Window {
    MonacoEnvironment?: { getWorker: (id: string, label: string) => Worker };
  }
}

window.MonacoEnvironment = { getWorker: () => new EditorWorker() };
loader.config({ monaco });

export { monaco };
