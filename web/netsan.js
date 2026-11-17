import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

// ---------------------------------------------------------------------------
// tiny fetch helpers (api.fetchApi handles ComfyUI's base path)
// ---------------------------------------------------------------------------
async function apiGet(path) {
  const r = await api.fetchApi(path);
  return r.json();
}
async function apiPost(path, body) {
  const r = await api.fetchApi(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return r.json();
}

const css = `
#netsan-btn{position:fixed;right:16px;bottom:16px;z-index:1000;
  font:600 12px/1.2 system-ui,sans-serif;padding:8px 12px;border-radius:8px;
  border:1px solid #444;background:#1f2430;color:#e6e6e6;cursor:pointer;
  box-shadow:0 2px 8px rgba(0,0,0,.4)}
#netsan-btn.armed{background:#7a1f1f;border-color:#c0392b}
#netsan-panel{position:fixed;right:16px;bottom:60px;z-index:1000;width:640px;
  max-width:calc(100vw - 32px);max-height:72vh;display:none;flex-direction:column;
  background:#171b24;color:#e6e6e6;border:1px solid #333;border-radius:10px;
  box-shadow:0 8px 32px rgba(0,0,0,.5);font:12px/1.4 system-ui,sans-serif;overflow:hidden}
#netsan-panel.open{display:flex}
#netsan-panel header{display:flex;align-items:center;gap:8px;padding:10px 12px;
  background:#0f1218;border-bottom:1px solid #2a2f3a}
#netsan-panel header b{flex:1;font-size:13px}
.ns-toggle{padding:6px 10px;border-radius:6px;border:1px solid #444;cursor:pointer;
  background:#232838;color:#dfe6f0;font-weight:600}
.ns-toggle.on{background:#215c2e;border-color:#2ecc71;color:#eafff0}
.ns-toggle.block.on{background:#7a1f1f;border-color:#e74c3c;color:#ffecec}
.ns-sub{display:flex;gap:10px;align-items:center;padding:8px 12px;
  border-bottom:1px solid #2a2f3a;color:#9aa4b2}
.ns-sub label{display:flex;gap:5px;align-items:center;cursor:pointer}
.ns-body{overflow:auto;padding:0}
table.ns{width:100%;border-collapse:collapse}
table.ns th,table.ns td{text-align:left;padding:6px 8px;border-bottom:1px solid #232838;
  vertical-align:top}
table.ns th{position:sticky;top:0;background:#0f1218;color:#8b95a3;font-weight:600;
  font-size:11px;text-transform:uppercase;letter-spacing:.03em}
table.ns td.num{text-align:right;font-variant-numeric:tabular-nums}
.ns-ext{color:#ffd27a;font-weight:600}
.ns-target{color:#9cd0ff}
.ns-blocked{color:#ff8a8a;font-weight:600}
.ns-allow{cursor:pointer;color:#7fd6a0;border:1px solid #2c5;background:transparent;
  border-radius:5px;padding:2px 6px;font-size:11px}
.ns-empty{padding:24px;text-align:center;color:#8b95a3}
.ns-foot{padding:8px 12px;border-top:1px solid #2a2f3a;display:flex;gap:8px;
  align-items:center;color:#8b95a3}
.ns-foot button{background:#232838;color:#dfe6f0;border:1px solid #444;border-radius:6px;
  padding:5px 9px;cursor:pointer}
`;

function fmtTime(t) {
  const d = new Date(t * 1000);
  return d.toLocaleTimeString();
}

app.registerExtension({
  name: "NetSan.Monitor",
  async setup() {
    const style = document.createElement("style");
    style.textContent = css;
    document.head.appendChild(style);

    const btn = document.createElement("button");
    btn.id = "netsan-btn";
    btn.textContent = "🛡️ NetSan";
    document.body.appendChild(btn);

    const panel = document.createElement("div");
    panel.id = "netsan-panel";
    panel.innerHTML = `
      <header>
        <b>🛡️ Network Sanitary check</b>
        <button class="ns-toggle monitor" data-key="monitoring">👁️ Monitor</button>
        <button class="ns-toggle block" data-key="blocking">⛔ Block outgoing</button>
      </header>
      <div class="ns-sub">
        <label><input type="checkbox" data-key="allow_private"> allow private LAN</label>
        <span style="flex:1"></span>
        <span class="ns-count"></span>
      </div>
      <div class="ns-body"></div>
      <div class="ns-foot">
        <button class="ns-clear">Clear log</button>
        <span style="flex:1"></span>
        <span class="ns-status"></span>
      </div>`;
    document.body.appendChild(panel);

    const body = panel.querySelector(".ns-body");
    const status = panel.querySelector(".ns-status");
    const count = panel.querySelector(".ns-count");
    let timer = null;
    let state = { monitoring: true, blocking: false, allow_private: false };

    function paintToggles() {
      panel.querySelectorAll(".ns-toggle").forEach((el) => {
        el.classList.toggle("on", !!state[el.dataset.key]);
      });
      panel.querySelector('[data-key="allow_private"]').checked = !!state.allow_private;
      btn.classList.toggle("armed", !!state.blocking);
      btn.textContent = state.blocking ? "⛔ NetSan (blocking)" : "🛡️ NetSan";
    }

    function paintRows(summary) {
      if (!summary || !summary.length) {
        body.innerHTML = `<div class="ns-empty">No outbound connection attempts recorded yet.<br>
          Extensions that phone home will appear here.</div>`;
        return;
      }
      const rows = summary.map((s) => {
        const port = s.port == null ? "" : s.port;
        const blocked = s.blocked
          ? `<span class="ns-blocked">${s.blocked} blocked</span>`
          : "";
        const host = s.hostname && s.hostname !== s.host
          ? `<div style="color:#6f7b8a">${escapeHtml(s.host)}</div>` : "";
        return `<tr>
          <td class="ns-ext">${escapeHtml(s.extension)}</td>
          <td><span class="ns-target">${escapeHtml(s.target)}</span>:${port}${host}</td>
          <td class="num">${s.count}</td>
          <td>${blocked}</td>
          <td>${fmtTime(s.last)}</td>
          <td><button class="ns-allow" data-host="${escapeHtml(s.hostname || s.host)}">Allow</button></td>
        </tr>`;
      }).join("");
      body.innerHTML = `<table class="ns"><thead><tr>
        <th>Extension</th><th>Destination</th><th>Attempts</th><th></th>
        <th>Last</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
    }

    async function refresh() {
      try {
        const data = await apiGet("/netsan/log");
        state = data.state;
        paintToggles();
        paintRows(data.summary);
        const total = data.summary.reduce((a, s) => a + s.count, 0);
        const blk = data.summary.reduce((a, s) => a + s.blocked, 0);
        count.textContent = `${data.summary.length} destinations · ${total} attempts · ${blk} blocked`;
        status.textContent = "updated " + new Date().toLocaleTimeString();
      } catch (e) {
        status.textContent = "error: " + e.message;
      }
    }

    function open() {
      panel.classList.add("open");
      refresh();
      timer = setInterval(refresh, 2000);
    }
    function close() {
      panel.classList.remove("open");
      if (timer) clearInterval(timer);
      timer = null;
    }

    btn.addEventListener("click", () =>
      panel.classList.contains("open") ? close() : open());

    panel.querySelectorAll(".ns-toggle").forEach((el) => {
      el.addEventListener("click", async () => {
        const key = el.dataset.key;
        state = await apiPost("/netsan/state", { [key]: !state[key] });
        paintToggles();
      });
    });

    panel.querySelector('[data-key="allow_private"]').addEventListener("change", async (e) => {
      state = await apiPost("/netsan/state", { allow_private: e.target.checked });
      paintToggles();
    });

    panel.querySelector(".ns-clear").addEventListener("click", async () => {
      await apiPost("/netsan/clear", {});
      refresh();
    });

    body.addEventListener("click", async (e) => {
      const b = e.target.closest(".ns-allow");
      if (!b) return;
      await apiPost("/netsan/allow", { host: b.dataset.host });
      refresh();
    });

    // sync initial state so the button reflects blocking without opening
    try { state = await apiGet("/netsan/state"); paintToggles(); } catch (_) {}
  },
});

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
