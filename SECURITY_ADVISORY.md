# 🛡️ Security Vulnerability & Audit Advisory
**Target Repository**: `bbartling/open-fdd`
**Audit Date**: `2026-09-10 20:19:53 UTC`
**Target Bounty**: $25

## 📋 Executive Summary of Findings

| Severity | Category | Description | File Location |
|---|---|---|---|
| **High** | Exposed Secret / Key Leak | Generic API/Secret Key | `edge/src/auth/jwt.rs:119` |
| **High** | Exposed Secret / Key Leak | Generic API/Secret Key | `edge/src/auth/login.rs:170` |

## 🔍 Proof of Concept (PoC) & Details

### Finding #1: Generic API/Secret Key
- **File**: `edge/src/auth/jwt.rs` (Line 119)
- **Severity Level**: `High`
- **Evidence Snippet**: `secret: "tes...[REDACTED]`
- **Impact**: Potential unauthorized access, data exposure, or client-side integrity risks.
- **Remediation**: Sanitize inputs, enforce explicit origin checks, and rotate exposed credentials immediately.

### Finding #2: Generic API/Secret Key
- **File**: `edge/src/auth/login.rs` (Line 170)
- **Severity Level**: `High`
- **Evidence Snippet**: `secret: "tes...[REDACTED]`
- **Impact**: Potential unauthorized access, data exposure, or client-side integrity risks.
- **Remediation**: Sanitize inputs, enforce explicit origin checks, and rotate exposed credentials immediately.
