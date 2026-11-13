// Open-FDD Lite tabs. The whole dashboard (top bar, equip pickers, tab router, Overview, Charts, Points, BACnet Server,
// Model & RDF, live loop) is the shared shell shared/static/app-core.js, loaded before this file. Lite has no tabs of
// its own on top of it, so this file only starts the app.

if (typeof document !== "undefined" && document.documentElement) main().catch(showErr);
