// Runs before first paint (plain <script> in <head>): apply the saved UI theme so the
// page never flashes the wrong colors. Light ("blueprint") is the default.
(function () {
  let t = "light";
  try { t = localStorage.getItem("openfdd-ui-theme") === "dark" ? "dark" : "light"; } catch { /* storage blocked */ }
  document.documentElement.dataset.theme = t;
})();
