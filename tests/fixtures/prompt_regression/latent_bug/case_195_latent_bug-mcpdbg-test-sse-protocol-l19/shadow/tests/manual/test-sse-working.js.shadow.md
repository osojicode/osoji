# tests\manual\test-sse-working.js
@source-hash: 4e1cd03d43af6d14
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:07:24Z

## Manual SSE Integration Test Script

Manual test script for validating SSE (Server-Sent Events) connection and session-based JSON-RPC messaging against a locally running server on `localhost:3001`.

### Purpose
End-to-end test of the SSE transport layer: establishes an SSE connection, extracts a session ID from a `connection/established` event, then fires a JSON-RPC `tools/list` POST request using that session ID. Keeps the process alive via `process.stdin.resume()` (L124) so async SSE messages are observable.

### Flow
1. **SSE Connect (L28–62):** `http.get` to `/sse` with `Accept: text/event-stream` header. Receives streaming chunks.
2. **Session Extraction (L47–55):** Parses each chunk with `parseSSEData`; watches for `message.method === 'connection/established'` containing `params.sessionId`.
3. **POST Trigger (L52–54):** After 1 second delay, calls `testPostRequest(sessionId)`.
4. **POST Request (L69–121):** Sends JSON-RPC 2.0 `tools/list` request to `POST /sse` with `X-Session-ID` header. Logs response and attempts JSON parse.
5. **Completion (L109–111):** 2-second timeout after POST response; prompts user to Ctrl+C.

### Key Symbols
- `parseSSEData(chunk)` **(L9–25):** Splits raw SSE chunk by `\n`, extracts `data: ` prefixed lines, JSON-parses each, silently drops non-JSON lines. Returns array of parsed message objects.
- `testPostRequest(sessionId)` **(L69–121):** Constructs and fires a JSON-RPC 2.0 POST to `/sse` with session correlation via `X-Session-ID` header. Logs raw and parsed response.
- `sseRequest` **(L28):** Active `http.ClientRequest` for the SSE stream; kept alive for the duration of the process.
- `SSE_URL` **(L4):** Hardcoded target `http://localhost:3001/sse`.

### Notable Patterns
- **Session correlation via custom header:** `X-Session-ID` is used rather than a query param or cookie.
- **POST to same `/sse` endpoint:** Both SSE stream and JSON-RPC commands share the same URL path — server differentiates by HTTP method.
- **No timeout/cleanup:** SSE connection and process never terminate automatically; requires manual Ctrl+C.
- **Silent JSON parse failures:** `parseSSEData` swallows non-JSON `data:` lines (L18–20), which is intentional for SSE keep-alive pings.
