import type { ReactNode } from "react";

type Props = {
  lines: { text: string; kind?: "error" | "warn" | "ok" | "prompt" }[];
  placeholder?: string;
  footer?: ReactNode;
};

export default function RuleLabConsole({ lines, placeholder, footer }: Props) {
  return (
    <div className="rule-lab-console-wrap panel">
      <div className="rule-lab-console-head">
        <h3 className="panel-title">Console &amp; traceback</h3>
        {footer}
      </div>
      <div className="rule-lab-console" role="log" aria-live="polite">
        {lines.length ? (
          lines.map((line, i) => (
            <div key={`${i}-${line.text.slice(0, 24)}`} className={`console-line ${line.kind || ""}`}>
              {line.kind === "prompt" ? ">>> " : null}
              {line.text}
            </div>
          ))
        ) : (
          <div className="console-line muted">{placeholder || "Lint or Test to run against live feather data."}</div>
        )}
      </div>
    </div>
  );
}

export function consoleTextToLines(text: string): { text: string; kind?: "error" | "warn" | "ok" | "prompt" }[] {
  if (!text.trim()) return [];
  return text.split("\n").map((raw) => {
    const textLine = raw;
    if (raw.startsWith("[error]") || raw.includes("Traceback") || raw.includes("SyntaxError") || raw.includes("IndentationError")) {
      return { text: textLine.replace(/^\[error\]\s*/, ""), kind: "error" as const };
    }
    if (raw.startsWith(">>>")) {
      return { text: raw.replace(/^>>>\s*/, ""), kind: "prompt" as const };
    }
    if (raw.startsWith("Lint OK")) {
      return { text: textLine, kind: "ok" as const };
    }
    if (raw.startsWith("warning ") || raw.includes("not allowed")) {
      return { text: textLine, kind: "warn" as const };
    }
    return { text: textLine };
  });
}
