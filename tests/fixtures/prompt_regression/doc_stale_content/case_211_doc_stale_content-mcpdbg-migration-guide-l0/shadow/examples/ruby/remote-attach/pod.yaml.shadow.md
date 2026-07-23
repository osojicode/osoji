# examples\ruby\remote-attach\pod.yaml
@source-hash: 4d776a7c0fb265d2
@impl-hash: 63d30090ad7704f2
@generated: 2026-07-22T22:06:32Z

## Kubernetes Pod Manifest — Ruby Remote Debugging Demo

**File role:** Configuration — defines a Kubernetes Pod resource for a remote Ruby debugger attach workflow.

### Purpose
Declares a single-container Kubernetes Pod (`ruby-remote-attach`) that runs a locally-built Ruby image pre-configured to listen on debugger port `12345`. Intended as a demo companion to the `mcp-debugger` project's remote-attach example.

### Key Resource Details

- **apiVersion / kind (L8–9):** `v1 / Pod` — bare Pod (no Deployment/ReplicaSet wrapper), suitable for one-shot demo use.
- **Pod name (L11):** `ruby-remote-attach` — used in `kubectl port-forward pod/ruby-remote-attach 12345:12345` as shown in the header comment.
- **Label (L13):** `app: ruby-remote-attach` — single selector label; not wired to a Service in this file.
- **Container name (L16):** `app`
- **Image (L17):** `ruby-remote-attach:demo` — must be built locally before applying; the comment at L2–3 shows the required `docker build` command.
- **imagePullPolicy: Never (L18):** Forces the kubelet to use the locally cached image only; prevents an attempted registry pull that would fail for a local-only tag.
- **containerPort (L20):** `12345` — the Ruby debugger listen port. Exposed via `kubectl port-forward` to `127.0.0.1:12345` so `mcp-debugger` can attach.

### Usage Workflow (from header comments L1–7)
1. `docker build -t ruby-remote-attach:demo examples/ruby/remote-attach`
2. `kubectl apply -f examples/ruby/remote-attach/pod.yaml`
3. `kubectl port-forward pod/ruby-remote-attach 12345:12345`
4. Attach `mcp-debugger` to `127.0.0.1:12345`

### Constraints & Notes
- `imagePullPolicy: Never` means the image **must** exist in the local container runtime before `kubectl apply`; if missing, the Pod will fail with `ErrImageNeverPull`.
- No liveness/readiness probes, resource limits, or restart policies are specified — this is a minimal demo manifest, not production-ready.
- No accompanying Service manifest; port-forwarding is the only access mechanism documented here.