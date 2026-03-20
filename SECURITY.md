# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | :white_check_mark: |

## Reporting a Vulnerability

**Do not file public GitHub issues for security vulnerabilities.**

Email **security@osojicode.ai** with:

- A description of the vulnerability
- Steps to reproduce
- The impact (what an attacker could do)

**Expected response time:** 48 hours for acknowledgment, 90 days for resolution.

## Scope

Osoji processes codebases and sends content to third-party LLM APIs. Security-relevant areas include:

- The safety scanning module (`osoji safety`) — personal path and secret detection
- Configuration file handling (`.osoji.toml`, `.osoji.local.toml`)
- Observatory bundle export and push (`osoji export`, `osoji push`)
- Dependency supply chain (Python packages)
