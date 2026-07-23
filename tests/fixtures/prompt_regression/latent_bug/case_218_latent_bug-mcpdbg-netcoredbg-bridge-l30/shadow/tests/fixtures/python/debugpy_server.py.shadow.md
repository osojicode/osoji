# tests\fixtures\python\debugpy_server.py
@source-hash: eb704ccddd15836b
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:46Z

## Purpose
A standalone test fixture script that simulates a minimal debugpy/DAP (Debug Adapter Protocol) server for integration testing of MCP Server debugpy connections. Listens on a TCP socket, parses DAP-framed messages, and returns hardcoded stub responses.

## Key Functions

### `signal_handler(sig, frame)` (L12–15)
Handles `SIGINT`/`SIGTERM` gracefully by printing a shutdown message and calling `sys.exit(0)`.

### `send_dap_response(conn, request_id, command, body=None)` (L17–31)
Serializes a DAP response envelope to JSON, prepends the `Content-Length` header, and sends it over `conn` via `sendall`. The `seq` field is set to `request_id + 1`; `request_seq` echoes `request_id`. `body` is included only when truthy.

### `handle_connection(conn, addr)` (L33–112)
Handles one synchronous (blocking) TCP connection end-to-end:
- Reads raw bytes into a buffer; splits on `\r\n\r\n` to extract DAP message frames.
- Parses `Content-Length` from the header (L52–56) to know when a full message body has arrived.
- Dispatches on `message["command"]` (L71–100):
  - `"initialize"` → responds with a capability map (L72–86)
  - `"launch"` → empty success response (L88)
  - `"configurationDone"` → empty success response (L90)
  - `"threads"` → returns a single fake thread `[{id:1, name:"MainThread"}]` (L92–94)
  - `"disconnect"` → responds then breaks out of the read loop (L95–97)
  - Anything else → generic empty success response (L100)
- On `json.JSONDecodeError`, logs and continues (L102–103).
- Always closes `conn` in `finally` (L111).

### `main()` (L114–145)
Entry point:
- Parses `--port` CLI arg (default `5678`) via `argparse` (L119).
- Registers `SIGINT`/`SIGTERM` handlers (L125–126).
- Creates a TCP socket bound to `127.0.0.1:<port>`, sets `SO_REUSEADDR`, listens with backlog 5 (L129–132).
- Prints `"Debugpy server is listening!"` to stdout (L135) — this sentinel string is likely consumed by test harness readiness detection.
- Accepts connections sequentially (single-threaded); calls `handle_connection` per connection (L139–140).
- Closes the server socket in `finally` (L144).

## Architecture Notes
- **Single-threaded**: connections are handled one at a time; no threading or async I/O.
- **Simplified DAP parser**: only handles the `Content-Length` header line; ignores other headers like `Content-Type`.
- **Fixture-only**: hardcoded capability flags and a single fake thread — not suitable for production use.
- The `"Debugpy server is listening!"` print (L135) acts as a readiness signal for test orchestration.
- Bound exclusively to `127.0.0.1` (loopback), appropriate for local test use.
