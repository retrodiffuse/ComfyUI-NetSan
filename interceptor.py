"""
NetSan outbound connection interceptor.

ComfyUI should stay local. This module patches the standard-library ``socket``
so that every *outbound* connection attempt (``connect`` / ``connect_ex``) is
observed. Incoming connections used by ``--listen`` go through ``bind`` /
``accept`` and are deliberately left untouched, so the server keeps working.

Two independent switches:

* ``monitoring`` -- record every non-local connection attempt (default ON).
* ``blocking``   -- refuse every non-local connection attempt (default OFF).

Loopback / link-local / multicast destinations are always allowed so the UI,
internal IPC and LAN discovery keep working. Private LAN ranges can optionally
be allowed. Specific hosts can be added to an allow-list (e.g. after you decide
huggingface.co is fine).
"""

import errno
import ipaddress
import json
import os
import socket
import sys
import threading
import time
from collections import deque, OrderedDict

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
_PLUGIN_NAME = os.path.basename(_PLUGIN_DIR)

# ---------------------------------------------------------------------------
# Shared state
# ---------------------------------------------------------------------------
STATE = {
    "installed": False,
    "monitoring": True,    # record outbound attempts
    "blocking": False,     # refuse outbound attempts
    "allow_private": False,  # treat 10/8, 172.16/12, 192.168/16 as local
    "allowlist": set(),    # explicit hosts / hostnames the user trusts
}

_lock = threading.Lock()
_records = deque(maxlen=3000)          # recent individual attempts
_summary = OrderedDict()               # (ext, target, port) -> aggregated row
_counter = [0]
_hostname_cache = OrderedDict()        # ip -> hostname (from getaddrinfo)
_HOSTCACHE_MAX = 5000


# ---------------------------------------------------------------------------
# Persistence: toggles + allow-list survive restarts
# ---------------------------------------------------------------------------
_KEYS = ("monitoring", "blocking", "allow_private")


def _settings_path():
    # ComfyUI/user/ survives updates and reinstalls of this package.
    try:
        import folder_paths
        d = folder_paths.get_user_directory()
    except Exception:
        d = _PLUGIN_DIR
    return os.path.join(d, "netsan.json")


def _load():
    try:
        with open(_settings_path(), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    for k in _KEYS:
        if isinstance(data.get(k), bool):
            STATE[k] = data[k]
    if isinstance(data.get("allowlist"), list):
        STATE["allowlist"] = {str(h) for h in data["allowlist"]}


def _save():
    path = _settings_path()
    data = {k: STATE[k] for k in _KEYS}
    data["allowlist"] = sorted(STATE["allowlist"])
    try:
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(path + ".tmp", path)  # atomic: a crash never leaves a half-written file
    except OSError as e:
        print("[NetSan] could not save settings:", e)


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------
def _classify(address, family):
    """Return (is_local, host, port)."""
    unix = getattr(socket, "AF_UNIX", None)
    if unix is not None and family == unix:
        return True, str(address), None
    if not isinstance(address, (tuple, list)) or len(address) < 2:
        # Unknown address form -- don't get in the way.
        return True, str(address), None

    host, port = address[0], address[1]
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        h = str(host).lower()
        return h in ("localhost", "localhost.localdomain", ""), str(host), port

    local = (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_unspecified
        or ip.is_multicast
    )
    if not local and ip.is_private and STATE["allow_private"]:
        local = True
    return local, str(host), port


def _is_allowed(host, hostname):
    """True if the user has explicitly trusted this destination."""
    al = STATE["allowlist"]
    if host in al:
        return True
    if hostname:
        if hostname in al:
            return True
        for a in al:
            if a.startswith(".") and hostname.endswith(a):
                return True
            if hostname.endswith("." + a):
                return True
    return False


def _identify_caller():
    """Walk the stack and attribute the connection to a custom node folder."""
    frame = sys._getframe(1)
    fallback = None
    while frame is not None:
        fn = frame.f_code.co_filename or ""
        try:
            af = os.path.abspath(fn)
        except Exception:
            af = fn
        if af == _PLUGIN_DIR or af.startswith(_PLUGIN_DIR + os.sep):  # skip our own frames
            frame = frame.f_back
            continue
        norm = af.replace("\\", "/")
        low = norm.lower()
        idx = low.find("/custom_nodes/")
        if idx != -1:
            rest = norm[idx + len("/custom_nodes/"):]
            ext = rest.split("/", 1)[0]
            if ext and ext != _PLUGIN_NAME:
                return ext, norm
        if fallback is None and "site-packages" not in low and "/lib/" not in low:
            fallback = norm
        frame = frame.f_back
    return "ComfyUI core", fallback


def _record(ext, host, hostname, port, family, blocked, file):
    fam = "IPv6" if family == socket.AF_INET6 else "IPv4"
    target = hostname or host
    now = time.time()
    with _lock:
        _counter[0] += 1
        rec = {
            "id": _counter[0],
            "time": now,
            "extension": ext or "unknown",
            "host": host,
            "hostname": hostname,
            "port": port,
            "family": fam,
            "action": "blocked" if blocked else "allowed",
            "file": file or "",
        }
        _records.append(rec)

        key = (rec["extension"], target, port)
        row = _summary.get(key)
        if row is None:
            row = {
                "extension": rec["extension"],
                "target": target,
                "host": host,
                "hostname": hostname,
                "port": port,
                "count": 0,
                "blocked": 0,
                "first": now,
                "last": now,
            }
            _summary[key] = row
        row["count"] += 1
        if blocked:
            row["blocked"] += 1
        row["last"] = now


def _evaluate(sock, address):
    """Decide what to do with an outbound connect. Returns 'allow' or 'block'."""
    try:
        if not STATE["monitoring"] and not STATE["blocking"]:
            return "allow"
        family = getattr(sock, "family", None)
        is_local, host, port = _classify(address, family)
        if is_local:
            return "allow"

        hostname = _hostname_cache.get(host, "")
        allowed = _is_allowed(host, hostname)
        block = STATE["blocking"] and not allowed
        if STATE["monitoring"] or block:
            ext, file = _identify_caller()
            _record(ext, host, hostname, port, family, block, file)
        return "block" if block else "allow"
    except Exception:
        # Never break real traffic because of a bug in here.
        return "allow"


# ---------------------------------------------------------------------------
# Installation (idempotent)
# ---------------------------------------------------------------------------
def install():
    if STATE["installed"]:
        return

    orig_connect = socket.socket.connect
    orig_connect_ex = socket.socket.connect_ex
    orig_getaddrinfo = socket.getaddrinfo
    orig_gethostbyname = socket.gethostbyname

    def connect(self, *args, **kwargs):
        addr = args[0] if args else kwargs.get("address")
        if _evaluate(self, addr) == "block":
            raise OSError(errno.ECONNREFUSED,
                          "NetSan: outbound connection blocked")
        return orig_connect(self, *args, **kwargs)

    def connect_ex(self, *args, **kwargs):
        addr = args[0] if args else kwargs.get("address")
        if _evaluate(self, addr) == "block":
            return errno.ECONNREFUSED
        return orig_connect_ex(self, *args, **kwargs)

    def getaddrinfo(host, *args, **kwargs):
        res = orig_getaddrinfo(host, *args, **kwargs)
        if host:
            try:
                for item in res:
                    ip = item[4][0]
                    _hostname_cache[ip] = str(host)
                if len(_hostname_cache) > _HOSTCACHE_MAX:
                    _hostname_cache.clear()
            except Exception:
                pass
        return res

    def gethostbyname(host):
        ip = orig_gethostbyname(host)
        if host:
            try:
                _hostname_cache[ip] = str(host)
            except Exception:
                pass
        return ip

    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo
    socket.gethostbyname = gethostbyname

    _load()
    STATE["installed"] = True
    print("[NetSan] outbound connection monitor installed "
          "(monitoring=%s, blocking=%s)" % (STATE["monitoring"], STATE["blocking"]))


# ---------------------------------------------------------------------------
# Public accessors (used by the API routes)
# ---------------------------------------------------------------------------
def current_state():
    return {
        "installed": STATE["installed"],
        "monitoring": STATE["monitoring"],
        "blocking": STATE["blocking"],
        "allow_private": STATE["allow_private"],
        "allowlist": sorted(STATE["allowlist"]),
    }


def set_state(**kw):
    for k in ("monitoring", "blocking", "allow_private"):
        if kw.get(k) is not None:
            STATE[k] = bool(kw[k])
    _save()
    return current_state()


def add_allow(host):
    if host:
        STATE["allowlist"].add(str(host))
        _save()
    return current_state()


def remove_allow(host):
    STATE["allowlist"].discard(str(host))
    _save()
    return current_state()


def get_records(limit=500):
    with _lock:
        recs = list(_records)[-limit:]
        summ = sorted(_summary.values(), key=lambda x: x["last"], reverse=True)
    return recs, summ


def clear_records():
    with _lock:
        _records.clear()
        _summary.clear()
        _counter[0] = 0
