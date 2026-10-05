import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
// Self-host Source Sans 3 (#1131) — no fonts.googleapis / fonts.gstatic.
import "@fontsource/source-sans-3/400.css";
import "@fontsource/source-sans-3/400-italic.css";
import "@fontsource/source-sans-3/600.css";
import "@fontsource/source-sans-3/700.css";
import App from "./App";
import "./styles/app.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
