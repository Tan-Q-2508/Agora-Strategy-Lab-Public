import Editor, { type OnMount } from "@monaco-editor/react";
import { BookOpen } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Button } from "../../components/ui/button";
import { Card, CardHeader, CardTitle } from "../../components/ui/card";
import { readChartTokens } from "../../components/charts/tokens";
import { useTheme } from "../../lib/theme";
import type { IndicatorInfo, Issue } from "../../lib/strategy";
import { CTX, POSITION, SERIES, SIZE, STOP, type ApiItem } from "./agoraApi";
import { useCatalog } from "./useCatalog";
import { monaco } from "../../lib/monaco";

type Monaco = typeof monaco;

let registered = false;
let catalogRef: Record<string, IndicatorInfo> | null = null;

function suggestions(m: Monaco, items: ApiItem[], range: InstanceType<Monaco["Range"]>) {
  return items.map((it) => ({
    label: it.name,
    kind: it.kind === "method" ? m.languages.CompletionItemKind.Method : m.languages.CompletionItemKind.Property,
    insertText: it.insert,
    insertTextRules: m.languages.CompletionItemInsertTextRule.InsertAsSnippet,
    detail: it.detail,
    documentation: it.doc,
    range,
  }));
}

function register(m: Monaco) {
  if (registered) return;
  registered = true;
  m.languages.registerCompletionItemProvider("python", {
    triggerCharacters: ["."],
    provideCompletionItems(model, position) {
      const before = model.getValueInRange({ startLineNumber: position.lineNumber, startColumn: 1, endLineNumber: position.lineNumber, endColumn: position.column });
      const word = model.getWordUntilPosition(position);
      const range = new m.Range(position.lineNumber, word.startColumn, position.lineNumber, word.endColumn);
      const tail = before.slice(0, before.length - word.word.length);
      if (/ctx\.ind\.$/.test(tail)) {
        const cat = catalogRef ? Object.values(catalogRef) : [];
        return {
          suggestions: cat.map((i) => {
            const args = [...(i.uses_source ? ["ctx.close"] : []), ...i.params.map((p) => `${p.name}=${p.default}`)];
            let snippet = 0;
            const text = `${i.key}(${args.map((a) => `\${${++snippet}:${a}}`).join(", ")})`;
            return {
              label: i.key,
              kind: m.languages.CompletionItemKind.Function,
              insertText: text,
              insertTextRules: m.languages.CompletionItemInsertTextRule.InsertAsSnippet,
              detail: i.outputs.length > 1 ? `lines: ${i.outputs.map((o) => o.key).join(", ")}` : i.label,
              documentation: i.description,
              range,
            };
          }),
        };
      }
      if (/ctx\.size\.$/.test(tail)) return { suggestions: suggestions(m, SIZE, range) };
      if (/ctx\.stop\.$/.test(tail)) return { suggestions: suggestions(m, STOP, range) };
      if (/(ctx\.)?position\.$/.test(tail)) return { suggestions: suggestions(m, POSITION, range) };
      if (/ctx\.$/.test(tail)) return { suggestions: suggestions(m, CTX, range) };
      if (/[\w)\]]\.$/.test(tail)) return { suggestions: suggestions(m, SERIES, range) };
      return { suggestions: [] };
    },
  });
}

/** Monaco only accepts #rrggbb(aa); CSS minifiers shorten colours (#fff) or use rgb(). */
function hex6(color: string): string {
  const el = document.createElement("span");
  el.style.color = color;
  document.body.appendChild(el);
  const rgb = getComputedStyle(el).color;
  el.remove();
  const m = rgb.match(/[\d.]+/g)?.map(Number) ?? [0, 0, 0];
  const [r = 0, g = 0, b = 0, a = 1] = m;
  const hex = (n: number) => Math.round(n).toString(16).padStart(2, "0");
  return `#${hex(r)}${hex(g)}${hex(b)}${a < 1 ? hex(a * 255) : ""}`;
}

function defineThemes(m: Monaco) {
  const t = readChartTokens();
  const base = { "editor.background": hex6(t.surface), "editorLineNumber.foreground": hex6(t.fgSubtle), "editor.lineHighlightBackground": hex6(t.accentSoft) };
  m.editor.defineTheme("agora-light", { base: "vs", inherit: true, rules: [{ token: "keyword", foreground: "c4501a" }], colors: base });
  m.editor.defineTheme("agora-dark", { base: "vs-dark", inherit: true, rules: [{ token: "keyword", foreground: "f07a3e" }], colors: base });
}

/** Monaco editor for code strategies, with Agora API autocomplete and inline errors. */
export function CodePanel({ code, onChange, issues }: { code: string; onChange: (code: string) => void; issues: Issue[] }) {
  const catalog = useCatalog();
  const { resolved } = useTheme();
  const editorRef = useRef<Parameters<OnMount>[0] | null>(null);
  const [showRef, setShowRef] = useState(false);
  useEffect(() => {
    catalogRef = catalog;
  }, [catalog]);

  const onMount: OnMount = (editor, m) => {
    editorRef.current = editor;
    register(m as unknown as Monaco);
    defineThemes(m as unknown as Monaco);
    m.editor.setTheme(resolved === "dark" ? "agora-dark" : "agora-light");
  };

  useEffect(() => {
    defineThemes(monaco);
    monaco.editor.setTheme(resolved === "dark" ? "agora-dark" : "agora-light");
  }, [resolved]);

  useEffect(() => {
    const model = editorRef.current?.getModel();
    if (!model) return;
    const markers = issues
      .filter((i) => i.path[0] === "code")
      .map((i) => {
        const line = typeof i.path[1] === "number" ? i.path[1] : 1;
        return {
          startLineNumber: line,
          endLineNumber: line,
          startColumn: 1,
          endColumn: model.getLineMaxColumn(Math.min(line, model.getLineCount())),
          message: `${i.message} ${i.hint}`,
          severity: i.severity === "error" ? monaco.MarkerSeverity.Error : monaco.MarkerSeverity.Warning,
        };
      });
    monaco.editor.setModelMarkers(model, "agora", markers);
  }, [issues]);

  return (
    <Card className="min-h-0 overflow-hidden">
      <CardHeader>
        <CardTitle>Code</CardTitle>
        <Button size="sm" variant="ghost" onClick={() => setShowRef((v) => !v)} aria-expanded={showRef}>
          <BookOpen aria-hidden="true" />
          {showRef ? "Hide" : "Show"} API reference
        </Button>
      </CardHeader>
      <div className="flex min-h-0">
        <div className="h-[600px] min-w-0 flex-1 border-t border-hairline">
          <Editor
            language="python"
            value={code}
            onChange={(v) => onChange(v ?? "")}
            onMount={onMount}
            loading={<div className="p-5 text-small text-fg-muted">Loading the editor…</div>}
            options={{ fontFamily: "JetBrains Mono, monospace", fontSize: 13, minimap: { enabled: false }, scrollBeyondLastLine: false, tabSize: 4, automaticLayout: true, wordWrap: "on" }}
          />
        </div>
        {showRef && (
          <aside className="h-[600px] w-[300px] shrink-0 overflow-y-auto border-t border-l border-hairline p-4 text-small" aria-label="Agora API reference">
            <p className="m-0 mb-2 font-semibold">on_bar(ctx) runs once per closed candle, per stock.</p>
            {[...CTX, ...POSITION.map((p) => ({ ...p, name: `position.${p.name}` }))].map((it) => (
              <div key={it.name} className="mb-2">
                <code className="font-mono text-tiny text-accent-strong">ctx.{it.name}</code>
                <p className="m-0 text-tiny text-fg-muted">{it.doc}</p>
              </div>
            ))}
            <p className="m-0 mt-3 text-tiny text-fg-subtle">Allowed imports: math, statistics. No files, internet or clock. Limits: 200,000 steps and 0.5 s per candle.</p>
          </aside>
        )}
      </div>
    </Card>
  );
}
