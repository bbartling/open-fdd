/**
 * Plotly.js injects <style> nodes at runtime (global rules, mode bar, maplibregl).
 * Strict CSP allows style-src-elem 'self' only — not inline <style> text.
 * Load /plotly.css (same-origin) before plotly.min.js, then redirect Plotly's
 * style sheet handles to that linked stylesheet and skip mounting <style> nodes.
 */
(function () {
  var sharedSheet = null;

  function plotlyStylesheet() {
    if (!sharedSheet) {
      var link = document.querySelector('link[data-plotly-css]');
      sharedSheet = link && link.sheet;
    }
    return sharedSheet;
  }

  function patchStyleElement(el) {
    Object.defineProperty(el, "sheet", {
      get: plotlyStylesheet,
      configurable: true,
    });
    el.appendChild = function () {
      return el;
    };
    try {
      Object.defineProperty(el, "textContent", {
        set: function () {},
        get: function () {
          return "";
        },
      });
      Object.defineProperty(el, "innerHTML", {
        set: function () {},
        get: function () {
          return "";
        },
      });
    } catch (_err) {
      /* older engines */
    }
    return el;
  }

  function isStyleNode(node) {
    return node && String(node.tagName || "").toUpperCase() === "STYLE";
  }

  var origCreate = Document.prototype.createElement;
  var origCreateNS = Document.prototype.createElementNS;
  var origAppend = Node.prototype.appendChild;
  var origInsertBefore = Node.prototype.insertBefore;

  Document.prototype.createElement = function (tagName, options) {
    var el = origCreate.call(this, tagName, options);
    if (String(tagName).toLowerCase() === "style") {
      patchStyleElement(el);
    }
    return el;
  };

  Document.prototype.createElementNS = function (ns, tagName, options) {
    var el = origCreateNS.call(this, ns, tagName, options);
    if (String(tagName).toLowerCase() === "style") {
      patchStyleElement(el);
    }
    return el;
  };

  Node.prototype.appendChild = function (child) {
    if (isStyleNode(child)) {
      return child;
    }
    return origAppend.call(this, child);
  };

  Node.prototype.insertBefore = function (child, ref) {
    if (isStyleNode(child)) {
      return child;
    }
    return origInsertBefore.call(this, child, ref);
  };
})();
