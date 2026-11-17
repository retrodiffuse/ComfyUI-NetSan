import importlib
import os
import socket
import tempfile

import interceptor


def run():
    path = os.path.join(tempfile.mkdtemp(), "netsan.json")
    orig = (socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo, socket.gethostbyname)

    def fresh():  # simulate a ComfyUI restart
        socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo, socket.gethostbyname = orig
        m = importlib.reload(interceptor)
        m._settings_path = lambda: path
        m.install()
        return m

    i = fresh()
    assert i.STATE["blocking"] is False  # no settings file yet -> defaults
    i.set_state(blocking=True)
    i.add_allow("huggingface.co")

    i = fresh()
    assert i.STATE["blocking"] is True, "blocking must survive a restart"
    assert i.STATE["allowlist"] == {"huggingface.co"}
    s = socket.socket()
    try:
        s.connect(("203.0.113.1", 80))
        raise AssertionError("expected NetSan to block")
    except ConnectionRefusedError:
        pass
    finally:
        s.close()

    open(path, "w").write("{corrupt")
    i = fresh()  # a broken file falls back to defaults instead of crashing ComfyUI
    assert i.STATE["blocking"] is False
    print("ok")


if __name__ == "__main__":
    run()
