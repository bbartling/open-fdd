#!/usr/bin/env node
/** CI contract: Overview/shell stretch full width (Streamlit-like). */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "../frontend/web/src/styles");
const tokens = readFileSync(join(root, "tokens.css"), "utf8");
const css = readFileSync(join(root, "app.css"), "utf8");

function mustMatch(label, text, re) {
  if (!re.test(text)) {
    console.error(`FAIL ${label}: ${re}`);
    process.exit(1);
  }
  console.log(`OK ${label}`);
}

mustMatch("tokens --content-max-width", tokens, /--content-max-width:\s*none/);
mustMatch("app-content max-width", css, /\.app-content\s*\{[^}]*max-width:\s*none/s);
mustMatch(
  "overview-populated max-width",
  css,
  /\.overview-populated\s*\{[^}]*max-width:\s*none/s,
);
