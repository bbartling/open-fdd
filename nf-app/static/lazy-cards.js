// Lazy card drawing for the Overview RCx dashboard (#1643). Each card is drawn only when its element nears the viewport,
// at most `concurrency` at a time. `isLive()` is checked before every start: once it is false (a newer render, or the
// user left the tab) the observer is disconnected and queued cards are dropped. Cards already drawing finish; their
// results are discarded by the caller's own run check. Returns a stop() function.

/**
 * @param {{ els: HTMLElement[], draw: (i: number) => Promise<unknown>, isLive: () => boolean, onDone?: () => void,
 *   concurrency?: number, rootMargin?: string, Observer?: typeof IntersectionObserver }} opts
 * @returns {() => void}
 */
function lazyDrawCards({ els, draw, isLive, onDone, concurrency = 2, rootMargin = "600px 0px", Observer = IntersectionObserver }) {
  /** @type {number[]} */
  const queue = [];
  let active = 0, left = els.length, stopped = false;
  /** @type {IntersectionObserver} */
  let io;
  const stop = () => { stopped = true; queue.length = 0; if (io) io.disconnect(); };
  const pump = () => {
    if (stopped) return;
    if (!isLive()) { stop(); return; }
    while (active < concurrency && queue.length) {
      const i = /** @type {number} */ (queue.shift());
      active++;
      Promise.resolve()
        .then(() => draw(i))
        .catch(() => {})
        .finally(() => {
          active--;
          if (--left === 0 && !stopped && onDone) onDone();
          pump();
        });
    }
  };
  io = new Observer((entries) => {
    for (const en of entries) {
      if (!en.isIntersecting) continue;
      io.unobserve(en.target);
      queue.push(els.indexOf(/** @type {HTMLElement} */ (en.target)));
    }
    pump();
  }, { rootMargin });
  for (const el of els) io.observe(el);
  if (!els.length && onDone) onDone();
  return stop;
}
