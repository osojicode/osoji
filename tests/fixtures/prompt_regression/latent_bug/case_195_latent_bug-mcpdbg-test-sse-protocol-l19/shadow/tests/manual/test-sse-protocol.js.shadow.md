# tests\manual\test-sse-protocol.js
@source-hash: f605948329bd3daf
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:08:21Z

## Purpose
Manual integration test script for verifying SSE (Server-Sent Events) protocol behavior of an MCP SDK server running on `localhost:3001`. Establishes an SSE connection, extracts a session ID from the `endpoint` event, then fires a JSON-RPC `tools/list` POST request with that session ID to validate the full SSE+POST handshake flow.

## Key Elements

### Constants
- `SSE_URL` (L4): Hardcoded target — `http://localhost:3001/sse`. Requires a local MCP server to be running.

### `parseSSEEvents(chunk)` (L9–26)
Parses a raw SSE data chunk (Buffer or string) into an array of `{event, data}` objects. Splits on `\n`, accumulates `event:` and `data:` fields, and flushes each complete event on a blank line. **Note:** only pushes events when `currentEvent.event` is present — data-only events (no `event:` field) are silently dropped.

### SSE connection setup (L29–72)
- Issues a `GET` to `SSE_URL` with `Accept: text/event-stream` and `Cache-Control: no-cache` headers (L29–34).
- On `data` chunks (L40–63): calls `parseSSEEvents`, then checks for `event === 'endpoint'`. Extracts `sessionId` via regex `/sessionId=([a-f0-9-]+)/` (L51). Schedules `testPostRequest(sessionId)` 1 second later via `setTimeout` (L57–59).
- Error handling on both response stream (L65–67) and request object (L70–72).

### `testPostRequest(sessionId)` (L75–120)
Sends a JSON-RPC 2.0 `tools/list` request (L78–82) via HTTP POST to `localhost:3001/sse` (L84–94). Passes `sessionId` via `X-Session-ID` header (L92). Logs response status, headers, and body. Does not close the SSE connection — instructs user to wait for an SSE-channel response and press Ctrl+C.

### Process keep-alive (L123)
`process.stdin.resume()` keeps the Node.js event loop alive so the SSE connection persists after the POST completes.

## Protocol Flow
1. GET `/sse` → receive `endpoint` SSE event containing `?sessionId=<uuid>`
2. Extract session ID from endpoint URL
3. POST `/sse` with `X-Session-ID` header and JSON-RPC `tools/list` body
4. Expect JSON-RPC response to arrive on the open SSE channel

## Dependencies
- Node.js built-in `http` module only — no external dependencies.
- Requires a running MCP SDK server at `localhost:3001`.

## Architectural Notes
- This is a **manual** test script (not automated/assertion-based); output is purely console-logged.
- The POST path is also `/sse` (L87), not a separate `/message` endpoint — this may not match all MCP SDK server configurations.
- The 1-second `setTimeout` (L57) before the POST is an arbitrary delay to ensure the SSE stream is fully established before sending the request.