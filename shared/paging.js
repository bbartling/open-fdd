/**
 * The ONE pager the Open-FDD hooks use for NF list routes (point/query, sites, ...).
 *
 * Why it exists (#1550): NF 3.10.x `POST /api/v1/point/query` returns `totalCount` but NO `nextPageToken`; it pages
 * with `pageOffset`. A loop that only follows a next-page token reads the first page (500 records) and stops, with
 * no error. On a site whose model layer grew past 500 records the SITE record fell off the first page, the run saw
 * "0 equipment" and wrote nothing. This pager never trusts a single signal:
 *
 *   1. a `nextPageToken`, when the response has one, is followed (a repeated token is an error, not a loop);
 *   2. otherwise `pageOffset` paging: advance by the records received until `totalCount` is reached, or an empty
 *      page comes back. When the response has no `totalCount`, a short page (fewer than `pageSize`) also ends it;
 *   3. a page that adds nothing new (the server ignored `pageOffset` and sent page 1 again) is an error;
 *   4. fewer records than `totalCount` after an empty page is an error (short read), never a silent truncation;
 *   5. a hard cap (`maxRecords`, `maxPages`) ends in a loud PagingError, never a partial result.
 *
 * ONE source for every runtime (shared/paging.js, copied by scripts/nf/sync_shared.py): plain JS with no dependencies,
 * CommonJS in the NF hook runtime (`require('./lib/paging.js')`) and the classic global `OfddPaging` in the pages
 * (static/paging.js, loaded before nf.js, whose `pageAll` / `queryAll` use it).
 */
(function (root) {
'use strict';

const DEFAULT_PAGE_SIZE = 500;
const DEFAULT_MAX_RECORDS = 200000;
const DEFAULT_MAX_PAGES = 1000;

class PagingError extends Error {
  /** @param {string} message */
  constructor(message) {
    super(message);
    this.name = 'PagingError';
    this.paging = true;
  }
}

/** @param {any} r a record: the identity used to spot a page that repeats (uuid, else id, else the JSON). */
const identity = (r) => (r && (r.uuid || r.id)) || JSON.stringify(r);

/** @param {any} v totalCount as NF sends it (a string such as "994", a number, or absent) @returns {number | null} */
function totalOf(v) {
  if (v === undefined || v === null || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) && n >= 0 ? n : null;
}

/**
 * Every record of a paged NF list route.
 * @param {(params: { pageSize: number, pageOffset?: number, pageToken?: string }) => Promise<any>} fetchPage
 *        one request; resolves to the response body (not the HTTP wrapper)
 * @param {{ key?: string, pageSize?: number, maxRecords?: number, maxPages?: number, what?: string }} [opts]
 *        key = the array field of the response (default "points"); what = route name for messages
 * @returns {Promise<any[]>}
 */
async function pageAll(fetchPage, opts = {}) {
  const key = opts.key || 'points';
  const pageSize = opts.pageSize > 0 ? opts.pageSize : DEFAULT_PAGE_SIZE;
  const maxRecords = opts.maxRecords > 0 ? opts.maxRecords : DEFAULT_MAX_RECORDS;
  const maxPages = opts.maxPages > 0 ? opts.maxPages : DEFAULT_MAX_PAGES;
  const what = opts.what || 'NF list';
  /** @type {any[]} */
  const out = [];
  const seen = new Set();
  const tokens = new Set();
  let token = '';
  let offset = 0;        // records received so far (the next pageOffset)
  let total = null;      // totalCount, when the route reports one
  for (let pages = 0; ; pages += 1) {
    if (pages >= maxPages || offset >= maxRecords) {
      throw new PagingError(`${what}: paging cap reached after ${offset} records in ${pages} pages `
        + `(totalCount ${total === null ? 'unknown' : total}); refusing to continue with a partial result. Narrow the query`);
    }
    /** @type {{ pageSize: number, pageOffset?: number, pageToken?: string }} */
    const params = { pageSize };
    if (token) params.pageToken = token;
    else if (offset > 0) params.pageOffset = offset;
    const page = (await fetchPage(params)) || {};
    const recs = Array.isArray(page[key]) ? page[key] : [];
    const t = totalOf(page.totalCount);
    if (t !== null) total = t;
    let added = 0;
    for (const r of recs) {
      const id = identity(r);
      if (seen.has(id)) continue;
      seen.add(id);
      out.push(r);
      added += 1;
    }
    if (recs.length && !added) {
      throw new PagingError(`${what}: page ${pages + 1} repeated records already read (the server ignored `
        + `${token ? 'pageToken' : `pageOffset ${offset}`}); refusing to loop`);
    }
    offset += recs.length;
    const next = page.nextPageToken || '';
    if (next) {
      if (tokens.has(next)) throw new PagingError(`${what}: nextPageToken repeated; refusing to loop`);
      tokens.add(next);
      token = next;
      continue;
    }
    token = '';
    if (!recs.length) break;                          // empty page: the end (checked against totalCount below)
    if (total !== null) {
      if (offset >= total) break;                     // everything the route says it has
    } else if (recs.length < pageSize) {
      break;                                          // no totalCount: a short page is the last one
    }
  }
  if (total !== null && offset < total) {
    throw new PagingError(`${what}: read ${offset} of totalCount ${total} records, then the server returned an empty page; `
      + 'refusing to continue with a partial result');
  }
  // the route's own count rides along (not enumerable: the array stays a plain list) for "read N of M" messages
  Object.defineProperty(out, 'totalCount', { value: total, enumerable: false });
  return out;
}

/**
 * POST /api/v1/point/query, all pages. `body` is the query (layer, structuredQuery, ...); paging fields are ours.
 * @param {{ post: (path: string, body: any) => Promise<any> }} http NF SDK http (post resolves to { data })
 * @param {any} body
 * @param {{ pageSize?: number, maxRecords?: number, maxPages?: number }} [opts]
 * @returns {Promise<any[]>}
 */
function queryPoints(http, body, opts = {}) {
  return pageAll(async (p) => {
    const res = await http.post('/api/v1/point/query', { ...body, ...p });
    return res && res.data;
  }, { ...opts, key: 'points', what: 'point/query' });
}

/**
 * GET a list route (e.g. /api/v1/sites), all pages. `base` may already carry a query string.
 * @param {{ get: (path: string) => Promise<any> }} http
 * @param {string} base
 * @param {string} key the response's array field ("sites")
 * @param {{ pageSize?: number, maxRecords?: number, maxPages?: number }} [opts]
 * @returns {Promise<any[]>}
 */
function listAll(http, base, key, opts = {}) {
  return pageAll(async (p) => {
    const q = [`pageSize=${p.pageSize}`];
    if (p.pageOffset) q.push(`pageOffset=${p.pageOffset}`);
    if (p.pageToken) q.push(`pageToken=${encodeURIComponent(p.pageToken)}`);
    const res = await http.get(base + (base.includes('?') ? '&' : '?') + q.join('&'));
    return res && res.data;
  }, { ...opts, key, what: base.split('?')[0].replace(/^\/api\/v1\//, '') });
}

const api = { pageAll, queryPoints, listAll, PagingError, DEFAULT_PAGE_SIZE };
if (typeof module !== 'undefined' && module.exports) module.exports = api;
else root.OfddPaging = api;
})(typeof self !== 'undefined' ? self : globalThis);
