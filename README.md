# ComfyUI-NetSan — Network Sanitary check

Keep ComfyUI **local**. NetSan watches every outbound network connection that
ComfyUI and its custom nodes try to make, tells you **which extension** is
reaching out and **where to**, and can **block** all of it with one button —
while leaving `--listen` (incoming connections) fully working.

Use it to catch packages that phone home or exfiltrate data. If, say, a
"Facebook" node quietly opens a connection to a Facebook backend, it shows up
here immediately.

## What it does

- **👁️ Monitor** — records every attempt to connect to a non-local address,
  attributed to the `custom_nodes/<extension>` that made the call. On by default.
- **⛔ Block outgoing** — refuses every non-local connection (raises
  `ConnectionRefusedError`). Off by default so nothing breaks until you decide.
- **Saved across restarts** — the toggles and allow-list are stored in
  `ComfyUI/user/netsan.json`, so once blocking is on it stays on.
- **Allow-list** — click *Allow* on any destination you trust (e.g.
  `huggingface.co`), or tick *allow private LAN* to permit `192.168.x` etc.

Loopback (`127.0.0.1`, `::1`), link-local and multicast are always allowed so
the UI, internal IPC and LAN discovery keep working.

### Why incoming still works

Incoming connections from `--listen` are accepted through the socket
`bind()`/`accept()` path. NetSan only intercepts the **outbound** `connect()`
path, so blocking outgoing traffic never affects your ability to reach the UI
from another machine.

## Install

Search for **NetSan** in ComfyUI-Manager, or clone into your ComfyUI `custom_nodes` folder and restart ComfyUI:

```
cd ComfyUI/custom_nodes
git clone https://github.com/retrodiffuse/ComfyUI-NetSan.git
```

No Python dependencies beyond what ComfyUI already ships.

## Usage

A **🛡️ NetSan** button appears at the bottom-right of the ComfyUI window.
Click it to open the panel:

- Toggle **Monitor** / **Block outgoing** at the top.
- The table lists each destination: extension, host:port, attempt count, how
  many were blocked, and when it last happened.
- Click **Allow** to whitelist a destination you trust.
- The NetSan button turns **red** whenever blocking is armed.

## How it works (technical)

On load, NetSan monkey-patches the standard-library `socket`:

- `socket.socket.connect` / `connect_ex` — evaluated on every outbound
  connection. When blocking is on and the target isn't local/allow-listed, it
  raises `ECONNREFUSED` (or returns it, for `connect_ex`).
- `socket.getaddrinfo` / `gethostbyname` — used only to remember which hostname
  an IP came from, so the log can show `evil.example.com` instead of a bare IP.
  No extra network calls are made.

The calling extension is identified by walking the Python stack for a frame
under `custom_nodes/<name>/`. Anything with no such frame is attributed to
`ComfyUI core`.

### Limitations

- Catches connections made from **Python** (requests, urllib, aiohttp,
  http.client, raw sockets — all route through `socket.connect`). It does not
  block a node that shells out to an external binary (`curl`, `git`, …); those
  run in their own process.
- A node that opens a connection *at import time before NetSan loads* may not be
  caught. Restart with NetSan present to monitor from the next launch.
- This is a monitoring/triage aid, not a hardened firewall. For strong
  isolation, run ComfyUI without network access at the OS/container level.

## API

All routes are served under the ComfyUI origin:

| Method | Path              | Purpose                                  |
|--------|-------------------|------------------------------------------|
| GET    | `/netsan/state`   | current toggles + allow-list             |
| POST   | `/netsan/state`   | set `monitoring` / `blocking` / `allow_private` |
| GET    | `/netsan/log`     | `{records, summary, state}`              |
| POST   | `/netsan/clear`   | clear the log                            |
| POST   | `/netsan/allow`   | `{host}` → add to allow-list             |
| POST   | `/netsan/unallow` | `{host}` → remove from allow-list        |

## License

MIT
