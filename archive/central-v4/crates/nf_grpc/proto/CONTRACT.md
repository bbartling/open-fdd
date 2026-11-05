# NF native gRPC read contract (W6a)

Pinned from the Buf Schema Registry module `buf.build/normalframework/nf`.
This note is the read-only surface Open-FDD compiles. It does not wire ingest.

## Pin

| Field | Value |
| --- | --- |
| Module | `buf.build/normalframework/nf` |
| Label resolved | `main` |
| Commit | `38f497f826214f09a483e288a78d28d4` |
| Commit time (UTC) | `2026-09-22T13:56:18.282143Z` |
| BSR digest | `b5` `PHQrdiVZ5uf/ln+bAFnTnPEXs2SkeeXXDbPd6pjbwTT89JDlAZeOiLn7I8qGCDgg3LcdPkKDO7qmomM04cLIhg==` |
| Archive | `https://buf.build/normalframework/nf/archive/38f497f826214f09a483e288a78d28d4.zip` |
| Archive sha256 | `0efd0ef90964be351a1cbb5dccb26c41bfcf3d0d06529471d2cdf253e92b55c0` |

The archive sha256 is the immutable module zip for that commit (same bytes as `main` on 2026-10-26). The crate vendors only the files the point read RPCs import. It does not compile BACnet, Modbus, Fox, or Sparkplug protos from the same module.

Machine-checked file hashes (sha256 of the vendored bytes):

```
file-sha256: f97826fb955974289d4dee4ae4464a9f0422722d82045864dad58d883bb61409 normalgw/hpl/v1/point.proto
file-sha256: 46f1ec9ab2afa0bb49631e98e435b45ac14c698ddc9b5aa1b18038c202dcab81 normalgw/hpl/v1/unit.proto
file-sha256: 6fad1eaee9cccd63b70c06cacfd17f4a4dde21ea75dee5258225a063c1e99426 normalgw/hpl/v1/timeseries.proto
file-sha256: c40e5a3d702442d85b6db30183e559a3d5de12027758cb978aaf1047d7677682 normalgw/annotations/auth.proto
file-sha256: d3d3b4bbe80c0481c35507376f5653fcfdfcbdc7f168aab097f25ae643b7ebe8 google/api/annotations.proto
file-sha256: 3a03b75d44da595247911f62209beb19d7ecec31f3adf83d4dd2d7219f25aff2 google/api/http.proto
```

`build.rs` refuses to compile when a vendored file does not match those lines.

## License

The published commit has no `LICENSE` file. A BSR download of license-typed files for this commit returned none.

`normalgw/hpl/v1/point.proto`, `unit.proto`, `timeseries.proto`, and `normalgw/annotations/auth.proto` carry no copyright line and no SPDX identifier in this commit. Other files in the same module that this crate does not vendor state `Copyright (c) Normal Software, Inc.` The Normal Framework files are pinned as the published contract text. This repository does not relicense them.

`google/api/annotations.proto` and `google/api/http.proto` are Copyright 2015 Google LLC and are under the Apache License, Version 2.0, as stated in those files.

The Rust in `crates/nf_grpc` (everything except `proto/`) is MIT, the same as the Open-FDD workspace.

## Read RPCs

Service `normalgw.hpl.v1.PointManager` in `normalgw/hpl/v1/point.proto`.

| RPC | REST binding in the proto | Auth option |
| --- | --- | --- |
| `GetPoints` | `GET /api/v1/point/points` and `POST /api/v1/point/query` | `(normalgw.annotations.auth).readonly = true` |
| `GetPointsById` | `GET /api/v1/point/points-id` | `readonly = true` |
| `GetData` | `GET /api/v1/point/data` | `readonly = true` |

`GetPoints` is the point inventory search (layer, structured query, page size, page offset). `GetPointsById` is inventory by point UUID. `GetData` is point history (`uuids`, `from`, `to`, optional resample `method` / `window`, `count`, `reverse`). The proto documents a server cap of 10,000 samples per UUID on `GetData`.

These three RPCs are the only methods the Rust client calls. Write and streaming RPCs on `PointManager` (`AddPointsData`, `AddData`, `UpdatePoints`, `DeletePoints`, `ObserveDataUpdates`, and the rest) stay in the pinned file so the contract compiles as published, and they are not exposed.

## gRPC auth metadata

`normalgw/annotations/auth.proto` extends `google.protobuf.MethodOptions` with field `auth` (number `123197411`) and message `AuthOptions { bool readonly = 1; bool no_auth = 2; }`. A read RPC sets `readonly: true`. That option is how NF marks the method for its Envoy auth check. It is not a metadata key.

Token minting is `normalgw.platform.v1.AuthService.IssueToken` (`POST /api/v1/auth/token`, `no_auth: true`). The pinned comment says it issues a JWT with the `client_credentials` grant and that Envoy does not authenticate that call. `GetScopes` names the scope shape `normalgw.hpl.v1.readonly`.

The read client does not call `IssueToken`. The caller passes an access token that was already issued. On every `GetPoints`, `GetPointsById`, and `GetData` call the client sets one metadata entry:

- key: `authorization`
- value: `Bearer <access_token>`

That is the HTTP/2 form of the `Authorization` header documented for the same token on the REST point routes. The token is not written to `Debug`, `Display`, or error text. An empty token is `auth_not_configured` and no RPC is sent.

## Client limits

`NfReadClient::connect` accepts only an `https` endpoint with no userinfo. TLS uses rustls with native and webpki roots and certificate verification left on. There is no setting to skip verification.

Each RPC sets a deadline (`grpc-timeout`) and a max decoded response size. A tonic "decoded message length too large" failure is `response_too_large`. Other gRPC status codes map to one category each (`unauthenticated` to `auth_failed`, `permission_denied` to `forbidden`, `resource_exhausted` to `throttled`, `deadline_exceeded`, `unavailable`, `invalid_argument`, `not_found`, `unimplemented`, `internal`, `cancelled`, and the remaining codes to `transport` or `contract`). Status message text from the server is not copied into the error.
