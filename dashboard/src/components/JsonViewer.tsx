/**
 * A read-only JSON viewer for raw provider payloads.
 *
 * Highlighting is done by escaping first and then tokenizing the escaped text,
 * so a provider string can never inject markup into the page.
 */
import { useMemo, useState } from "react";

function escapeHtml(text: string): string {
  return text.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]!);
}

function highlight(json: string): string {
  return escapeHtml(json).replace(
    /("(\\u[a-zA-Z0-9]{4}|\\[^u]|[^\\"])*"(\s*:)?|\b(true|false|null)\b|-?\d+(?:\.\d*)?(?:[eE][+-]?\d+)?)/g,
    (match) => {
      if (/^"/.test(match)) return `<span class="${/:$/.test(match) ? "k" : "s"}">${match}</span>`;
      if (/true|false|null/.test(match)) return `<span class="b">${match}</span>`;
      return `<span class="n">${match}</span>`;
    },
  );
}

export function JsonViewer({ value, maxChars = 200000 }: { value: unknown; maxChars?: number }) {
  const [expanded, setExpanded] = useState(false);
  const text = useMemo(() => {
    if (typeof value === "string") return value;
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  }, [value]);

  const truncated = text.length > maxChars;
  const shown = truncated && !expanded ? `${text.slice(0, maxChars)}\n…` : text;

  return (
    <div className="stack">
      <pre className="json" dangerouslySetInnerHTML={{ __html: highlight(shown) }} />
      <div className="row small muted">
        <span className="mono">{text.length.toLocaleString("en-US")} characters</span>
        {truncated && (
          <button className="sm ghost" onClick={() => setExpanded((v) => !v)}>
            {expanded ? "Collapse" : "Show all"}
          </button>
        )}
        <button
          className="sm ghost"
          onClick={() => navigator.clipboard?.writeText(text)}
        >
          Copy
        </button>
      </div>
    </div>
  );
}
