import CodeMirror from "@uiw/react-codemirror";
import { sql } from "@codemirror/lang-sql";
import { oneDark } from "@codemirror/theme-one-dark";
import { EditorView } from "@codemirror/view";
import { useMemo } from "react";
import { useTheme } from "../contexts/theme-context";

const lightSqlTheme = EditorView.theme(
  {
    "&": {
      backgroundColor: "#f1f5f9",
      color: "#0f172a",
    },
    ".cm-content": {
      caretColor: "#0369a1",
      fontSize: "15px",
      lineHeight: "1.6",
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    },
    ".cm-cursor, .cm-dropCursor": {
      borderLeftColor: "#0369a1",
    },
    "&.cm-focused .cm-selectionBackground, .cm-selectionBackground, .cm-content ::selection": {
      backgroundColor: "#bae6fd !important",
    },
    ".cm-gutters": {
      backgroundColor: "#e2e8f0",
      color: "#475569",
      borderRight: "1px solid #cbd5e1",
    },
    ".cm-activeLineGutter": {
      backgroundColor: "#dbeafe",
    },
    ".cm-activeLine": {
      backgroundColor: "#e0f2fe",
    },
  },
  { dark: false },
);

const darkSqlTheme = EditorView.theme(
  {
    ".cm-content": {
      fontSize: "15px",
      lineHeight: "1.6",
      fontFamily: "ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace",
    },
  },
  { dark: true },
);

type Props = {
  value: string;
  onChange: (value: string) => void;
  height?: string;
  readOnly?: boolean;
};

export default function SqlCodeEditor({ value, onChange, height = "320px", readOnly }: Props) {
  const { theme } = useTheme();

  const extensions = useMemo(
    () => [
      sql(),
      theme === "dark" ? [oneDark, darkSqlTheme] : lightSqlTheme,
      EditorView.lineWrapping,
    ],
    [theme],
  );

  return (
    <div className="sql-code-editor-wrap code-editor-surface">
      <CodeMirror
        value={value}
        height={height}
        theme={theme === "dark" ? "dark" : "light"}
        extensions={extensions}
        readOnly={readOnly}
        onChange={onChange}
        basicSetup={{
          lineNumbers: true,
          foldGutter: true,
          highlightActiveLine: true,
          indentOnInput: true,
          bracketMatching: true,
        }}
      />
    </div>
  );
}
