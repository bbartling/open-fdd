# Frontend build strategy

## Source

- **Path:** `workspace/dashboard/`
- **Stack:** React 19, TypeScript, Vite 8, Vitest
- **Package:** `openfdd-operator-dashboard` v0.2.0

## Output

- **Path:** `frontend/` (repo root)
- **Configured in:** `workspace/dashboard/vite.config.ts` → `build.outDir`
- **Docker:** `ENV VITE_OUT_DIR=../frontend` in Dockerfile dashboard stage

## Scripts (package.json)

| Script | Command | CI |
| --- | --- | --- |
| `dev` | `vite` | no |
| `build` | `vite build` | yes |
| `preview` | `vite preview` | no |
| `test` | `vitest run` | yes (rust-ci / ci.yml) |

No `lint` script today — do not invent failing lint CI until ESLint is added.

## CI integration

- `ci.yml` / `rust-ci.yml`: `npm ci && npm run build && npm test`
- `rust-ghcr.yml`: build + verify `frontend/index.html` exists before publish

## Assets preserved across builds

`emptyOutDir: false` in Vite config keeps hand-maintained files like `frontend/style.css`.

## Do not

- Create a separate production frontend GHCR image by default.
- Commit generated `frontend/assets/*` unless repo convention changes (Docker builds fresh).
