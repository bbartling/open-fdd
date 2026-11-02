import js from "@eslint/js";
import globals from "globals";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import jsxA11y from "eslint-plugin-jsx-a11y";
import tseslint from "typescript-eslint";

export default tseslint.config(
  {
    ignores: [
      "dist/**",
      "node_modules/**",
      "playwright-report/**",
      "test-results/**",
      // Vendored browser assets (e.g. plotly.min.js) — not app source.
      "public/**",
    ],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["src/**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
    },
    plugins: {
      react,
      "react-hooks": reactHooks,
      "react-refresh": reactRefresh,
      "jsx-a11y": jsxA11y,
    },
    settings: {
      react: { version: "19.0" },
    },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
      // React 19 compiler rules — demote until pages migrate off effect-setState (P1-M2-B).
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/refs": "off",
      "react/jsx-key": "error",
      "react/no-array-index-key": "error",
      "react/no-danger": "error",
      ...jsxA11y.flatConfigs.recommended.rules,
      "react-refresh/only-export-components": [
        "warn",
        { allowConstantExport: true },
      ],
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/no-explicit-any": "error",
      "no-restricted-syntax": [
        "error",
        {
          selector:
            "CallExpression[callee.object.name='document'][callee.property.name='getElementById']",
          message:
            "Do not read or write the document with getElementById. Use a React ref. main.tsx is the SPA mount exception.",
        },
      ],
    },
  },
  {
    files: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    rules: {
      // Tests query the mounted document. Product code does not.
      "no-restricted-syntax": "off",
    },
  },
);
