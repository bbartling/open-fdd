import { ApiClientError } from "./client";

export type JobRunStatus =
  | "QUEUED"
  | "RUNNING"
  | "SUCCEEDED"
  | "FAILED"
  | "CANCELLED"
  | "STALE";

export const TERMINAL_RUN_STATUSES: ReadonlySet<string> = new Set([
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
  "STALE",
]);

export function isTerminalRunStatus(status: string): boolean {
  return TERMINAL_RUN_STATUSES.has(status);
}

export type PollOptions = {
  intervalMs?: number;
  timeoutMs?: number;
  signal?: AbortSignal;
  isTerminal: (value: TGeneric) => boolean;
};

type TGeneric = unknown;

export async function pollUntil<T>(
  fetchStatus: () => Promise<T>,
  opts: {
    intervalMs?: number;
    timeoutMs?: number;
    signal?: AbortSignal;
    isTerminal: (value: T) => boolean;
  },
): Promise<T> {
  const intervalMs = opts.intervalMs ?? 1000;
  const timeoutMs = opts.timeoutMs ?? 120_000;
  const started = Date.now();

  // eslint-disable-next-line no-constant-condition
  while (true) {
    if (opts.signal?.aborted) {
      throw new ApiClientError("poll aborted", {
        code: "async.aborted",
        retryable: false,
        requestId: "local",
        status: 499,
      });
    }
    const value = await fetchStatus();
    if (opts.isTerminal(value)) {
      return value;
    }
    if (Date.now() - started > timeoutMs) {
      throw new ApiClientError("poll timed out", {
        code: "async.timeout",
        retryable: true,
        requestId: "local",
        status: 408,
      });
    }
    await sleep(intervalMs, opts.signal);
  }
}

function sleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(t);
        reject(
          new ApiClientError("poll aborted", {
            code: "async.aborted",
            retryable: false,
            requestId: "local",
            status: 499,
          }),
        );
      },
      { once: true },
    );
  });
}

/** Backoff hint: retryable API errors should wait longer. */
export function nextIntervalMs(err: unknown, baseMs: number): number {
  if (err instanceof ApiClientError && err.retryable) {
    return Math.min(baseMs * 2, 10_000);
  }
  return baseMs;
}
