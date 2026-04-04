/** Prefixed browser-console helpers for BACnet troubleshooting (MSTP / IP). */

export const BACNET_LOG_PREFIX = "[OpenFDD BACnet]";

export function bacnetConsoleInfo(message: string, data?: Record<string, unknown>): void {
  if (data !== undefined) {
    console.info(`${BACNET_LOG_PREFIX} ${message}`, data);
  } else {
    console.info(`${BACNET_LOG_PREFIX} ${message}`);
  }
}

export function bacnetConsoleWarn(message: string, data?: Record<string, unknown>): void {
  if (data !== undefined) {
    console.warn(`${BACNET_LOG_PREFIX} ${message}`, data);
  } else {
    console.warn(`${BACNET_LOG_PREFIX} ${message}`);
  }
}

export function bacnetConsoleError(message: string, data?: Record<string, unknown>): void {
  if (data !== undefined) {
    console.error(`${BACNET_LOG_PREFIX} ${message}`, data);
  } else {
    console.error(`${BACNET_LOG_PREFIX} ${message}`);
  }
}

export function bacnetConsoleDebug(message: string, data?: unknown): void {
  console.debug(`${BACNET_LOG_PREFIX} ${message}`, data);
}
