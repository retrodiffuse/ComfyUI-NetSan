"""
ComfyUI-NetSan -- Network Sanitary check.

Keep ComfyUI local. Monitor and (optionally) block outbound connections made by
custom nodes so you can see exactly which extension is trying to phone home.

This package registers no graph nodes; it installs a socket-level monitor and a
small set of HTTP routes consumed by the web UI in ./web/netsan.js.
"""

from .interceptor import (
    install,
    current_state,
    set_state,
    add_allow,
    remove_allow,
    get_records,
    clear_records,
)

# Install the outbound monitor as early as possible.
install()

# ---------------------------------------------------------------------------
# HTTP API (served by ComfyUI's aiohttp server)
# ---------------------------------------------------------------------------
try:
    from server import PromptServer
    from aiohttp import web

    routes = PromptServer.instance.routes

    @routes.get("/netsan/state")
    async def _netsan_get_state(request):
        return web.json_response(current_state())

    @routes.post("/netsan/state")
    async def _netsan_set_state(request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        return web.json_response(set_state(**data))

    @routes.get("/netsan/log")
    async def _netsan_log(request):
        try:
            limit = int(request.query.get("limit", 500))
        except (TypeError, ValueError):
            limit = 500
        records, summary = get_records(limit)
        return web.json_response({
            "records": records,
            "summary": summary,
            "state": current_state(),
        })

    @routes.post("/netsan/clear")
    async def _netsan_clear(request):
        clear_records()
        return web.json_response({"ok": True})

    @routes.post("/netsan/allow")
    async def _netsan_allow(request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        return web.json_response(add_allow(data.get("host")))

    @routes.post("/netsan/unallow")
    async def _netsan_unallow(request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        return web.json_response(remove_allow(data.get("host")))

    print("[NetSan] API routes registered under /netsan/*")
except Exception as exc:  # pragma: no cover - defensive
    print("[NetSan] could not register API routes:", exc)


WEB_DIRECTORY = "./web"
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
