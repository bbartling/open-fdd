---
name: typescript
description: Type-check the app's plain JavaScript with JSDoc and tsc; where configs live and how to add a file.
---
# TypeScript (JSDoc, no build step)

NF serves `nf-app/static`, `nf-app/hooks`, `lite/static` and `lite/hooks` as plain JS, so types are JSDoc comments checked by `tsc --noEmit` (TypeScript 7.0.2, `checkJs`, never converted to `.ts`).

1. Run: `cd nf-app && npm ci && npm run typecheck` (full) and `npm run typecheck:lite` (Lite uses nf-app's compiler). CI runs both.
2. One tsconfig per program, because classic scripts of different pages redeclare the same top-level names (`$`, `GENERIC`, ...):
   `nf-app/tsconfig.json` (index.html, in its script load order), `.chart`, `.tree`, `.hooks` (CommonJS hooks); same four in `lite/`.
   Shared options: `tsconfig.base.json` (`allowJs`, `checkJs`, `strict: false`, `noImplicitAny: false`).
3. Globals the page scripts share live in `types/globals.d.ts` (`echarts: any`, `ofddUnits`, `AnyEl` = what `$(id)` returns).
   Data shapes (`OfddPoint`, `OfddModel`, `OfddEquip`, `CatalogRule`, `FddCatalog`, `RcxViewDef`, `RcxContext`) are in `nf-app/types/shapes.d.ts`.
   `types/hooks.d.ts` stubs browser globals that `static/sparql.js` guards with `typeof` (hooks program only).
4. Add a file: append it to the right config's `files` (page order = script order), write `@param/@returns/@type` JSDoc,
   cast DOM lookups (`/** @type {HTMLElement} */ (ev.target)`), run the typecheck until 0 errors.
5. CommonJS hooks: `module.exports = Object.assign(fn, { helper })` (not `module.exports.helper = ...`); hide `require()` of vendored code
   with a cast (`require(/** @type {string} */ ('../static/vendor/x.js'))`) so tsc does not follow it.
6. Never list `static/vendor/**`, `hooks/vendor/**` or `lite/static/vendor/**`. `static/echarts-global.js` (imports the vendored ESM build) is in
   no config for that reason; `window.echarts` is declared in globals.
7. `noImplicitAny` stays off (thousands of untyped callbacks); turn it on per file group only when it is clean without `any` noise.
8. No bundler, transpiler or runtime dependency; do not use `any` casts to silence real errors. Then run `node --test nf-app/tests/*.test.mjs lite/tests/*.test.mjs`.
