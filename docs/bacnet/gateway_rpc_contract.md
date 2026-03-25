---
title: DIY BACnet gateway RPC contract
parent: BACnet
nav_order: 4
---

# DIY BACnet gateway RPC contract

The DIY BACnet gateway at **:8080** is a **JSON-RPC** API, not a plain REST body-per-method API.

This matters because a naive POST like:

```json
{
  "device_instance": 3456790,
  "object_type": "analog-value",
  "object_instance": 1,
  "property_identifier": "present-value"
}
```

will fail with JSON-RPC validation errors.

## Correct shape for `client_read_property`

Use a JSON-RPC envelope:

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "client_read_property",
  "params": {
    "request": {
      "device_instance": 3456790,
      "object_identifier": "analog-value,1",
      "property_identifier": "present-value"
    }
  }
}
```

## Example result

```json
{
  "jsonrpc": "2.0",
  "result": {
    "present-value": 72.0
  },
  "id": 1
}
```

## Why this matters for overnight verification

A malformed request should be classified as **tooling / API-contract mismatch**.

It should **not** be treated as proof that:

- BACnet is down
- the gateway is unreachable
- Open-FDD ingest is broken

Only after using the correct JSON-RPC contract should the overnight workflow make BACnet-side health judgments.

See also [BACnet overview](overview) and Swagger at http://localhost:8080/docs when the stack is running.
