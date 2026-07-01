import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import { EditorView } from "@codemirror/view";
import { tags as t } from "@lezer/highlight";

/** Light SQL editor palette — matches common doc-style SQL screenshots. */
export const sqlEditorTheme = EditorView.theme(
  {
    "&": {
      backgroundColor: "#f8f8f8",
      color: "#000000",
    },
    ".cm-scroller": {
      fontFamily: 'ui-monospace, "SF Mono", Menlo, Consolas, monospace',
      lineHeight: "1.55",
    },
    ".cm-content": {
      padding: "0.75rem 0",
      caretColor: "#000000",
    },
    ".cm-line": {
      padding: "0 1rem",
    },
    ".cm-gutters": {
      backgroundColor: "#f0f0f0",
      color: "#999999",
      border: "none",
      minWidth: "2.75rem",
    },
    ".cm-gutterElement": {
      padding: "0 0.55rem 0 0",
      textAlign: "right",
    },
    ".cm-activeLine": {
      backgroundColor: "#efefef",
    },
    ".cm-activeLineGutter": {
      backgroundColor: "#e8e8e8",
    },
    ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
      backgroundColor: "#b3d4fc !important",
    },
    ".cm-cursor": {
      borderLeftColor: "#000000",
    },
  },
  { dark: false },
);

export const sqlSyntaxHighlight = syntaxHighlighting(
  HighlightStyle.define([
    { tag: [t.keyword, t.modifier, t.controlKeyword], color: "#990055", fontWeight: "500" },
    { tag: [t.operator, t.compareOperator, t.logicOperator], color: "#990055" },
    { tag: [t.bool, t.null], color: "#000000" },
    { tag: t.number, color: "#d14" },
    { tag: t.string, color: "#0077aa" },
    { tag: [t.variableName, t.name, t.propertyName, t.typeName], color: "#000000" },
    { tag: [t.comment, t.lineComment, t.blockComment], color: "#998877", fontStyle: "italic" },
    { tag: t.punctuation, color: "#000000" },
  ]),
);
