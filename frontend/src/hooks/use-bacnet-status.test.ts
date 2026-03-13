import { describe, it, expect } from "vitest";
import { SERVER_HELLO_REQUEST_INIT } from "./use-bacnet-status";

/**
 * Unit tests for the BACnet server_hello request shape used by useBacnetStatus.
 *
 * CONTEXT (for maintainers and AI): The Open-FDD backend /bacnet/server_hello endpoint
 * expects a JSON body. FastAPI's Body(dict) validator requires the request to have
 * Content-Type: application/json. If the frontend omits this header, the API returns
 * 422 Unprocessable Entity, the useQuery fails, and the StackStatusStrip shows the
 * BACnet status dot as red (offline) even when the gateway is reachable. These tests
 * exist to prevent that regression — do not remove Content-Type or change the method/body
 * without updating the backend to accept the new shape and then updating these tests.
 */
describe("useBacnetStatus / SERVER_HELLO_REQUEST_INIT", () => {
  it("uses POST method so the API route receives a body", () => {
    // The backend defines POST /bacnet/server_hello with body: dict = Body(default={}).
    // GET or a POST without the right body would not match or would fail validation.
    expect(SERVER_HELLO_REQUEST_INIT.method).toBe("POST");
  });

  it("sets Content-Type: application/json so FastAPI parses the body as JSON", () => {
    // Without this header, FastAPI does not parse the body as JSON and returns 422.
    // That caused the BACnet status dot to stay red until we added the header (see
    // use-bacnet-status.ts and open_fdd/platform/api/bacnet.py).
    const headers = SERVER_HELLO_REQUEST_INIT.headers as Record<string, string>;
    expect(headers).toBeDefined();
    expect(headers["Content-Type"]).toBe("application/json");
  });

  it("sends an empty JSON object body so the API uses default gateway URL", () => {
    // The endpoint accepts optional {"url": "http://..."}. Empty object means use
    // server default (e.g. OFDD_BACNET_SERVER_URL or config). Body must be a string
    // for fetch(); we use JSON.stringify({}) so the payload is valid JSON.
    expect(SERVER_HELLO_REQUEST_INIT.body).toBe("{}");
  });

  it("keeps request init shape stable for apiFetch (method, headers, body)", () => {
    // Sanity check: the object has the keys that apiFetch and the API expect.
    // If someone changes the shape (e.g. renames or omits a key), this fails.
    expect(SERVER_HELLO_REQUEST_INIT).toMatchObject({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
  });
});
