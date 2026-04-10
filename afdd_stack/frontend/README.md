# Frontend (React)

This folder is the web UI for Open FDD. If you are new to React, think of this app as:

- **pages** (`DashboardPage`, `SitePage`)
- **reusable UI pieces** (`components/ui`)
- **data loaders** (`hooks/*`)

The app is built with [React](https://react.dev/), [TypeScript](https://www.typescriptlang.org/docs/), and [Vite](https://vite.dev/guide/).

## Quick start

1. Install dependencies:

```bash
npm install
```

2. Start the dev server:

```bash
npm run dev
```

3. Open the URL shown in your terminal (usually `http://localhost:5173`).

By default, API calls are proxied to `http://localhost:8000` (configured in `vite.config.ts`).

## Environment variables

- `VITE_API_TARGET`: backend base URL for local development proxy (default: `http://localhost:8000`)
- `VITE_OFDD_API_KEY`: optional API key sent as Bearer auth and websocket token

Example:

```bash
VITE_API_TARGET=http://localhost:8000 VITE_OFDD_API_KEY=your_key npm run dev
```

## What the app does

- Route `/`: shows the system dashboard and all sites
- Route `/sites/:siteId`: shows one site with tabs for equipment, points, faults, and trending data
- Fetches data from backend endpoints like `/sites`, `/equipment`, `/points`, `/faults/*`
- Opens a websocket (`/ws/events`) to refresh data when events arrive

## Project structure

```text
frontend/
  src/
    main.tsx                 # app entry point
    App.tsx                  # providers + routes
    components/
      dashboard/             # dashboard screen components
      site/                  # site details screen components
      ui/                    # shared reusable UI building blocks
    hooks/                   # data fetching and websocket hooks
    lib/                     # API helper + utilities
    types/                   # API TypeScript types
    index.css                # global styles
  vite.config.ts             # dev server + API/websocket proxy
```

## How data flows (simple view)

1. UI components render a page.
2. Components call hooks (for example `useSites`, `useActiveFaults`).
3. Hooks call `apiFetch` in `src/lib/api.ts`.
4. [TanStack Query](https://tanstack.com/query/latest/docs/framework/react/overview) caches data and manages loading/error states.
5. `useWebSocket` listens for backend events and tells TanStack Query to refetch relevant data.

## Helpful docs

- [React: Learn](https://react.dev/learn)
- [Vite guide](https://vite.dev/guide/)
- [React Router](https://reactrouter.com/home)
- [TanStack Query (React)](https://tanstack.com/query/latest/docs/framework/react/overview)
- [TypeScript handbook](https://www.typescriptlang.org/docs/handbook/intro.html)
- [Tailwind CSS](https://tailwindcss.com/docs)
- [Recharts](https://recharts.org/en-US/)
