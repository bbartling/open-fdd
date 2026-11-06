---
name: typescript
description: Type-check the app's plain JavaScript with JSDoc and tsc; add a file to the checked set.
---
# TypeScript (JSDoc, no build step)

NF serves `nf-app/static` and `nf-app/hooks` as plain JS, so types are JSDoc comments checked by `tsc --noEmit`.

1. Run: `cd nf-app && npm ci && npm run typecheck` (CI runs it).
2. Config: `nf-app/tsconfig.json` (`allowJs`, `checkJs`, not strict). It checks only the files listed in `files`
   (`types/globals.d.ts`, `static/units.js`, `static/model.js`, `static/fdd.js` today).
3. To add a file: write JSDoc (`@param`, `@returns`, `@typedef`) for its functions, declare browser globals it relies
   on in `nf-app/types/globals.d.ts`, add the path to `files`, run the typecheck until clean. Files with DOM wiring
   (`export.js`, `sparql.js`) need DOM casts; hooks need `module.exports` typing.
4. Do not add a bundler, transpiler or runtime dependency; do not use `any` casts to silence real errors.

Then run `node --test nf-app/tests/*.test.mjs`.
