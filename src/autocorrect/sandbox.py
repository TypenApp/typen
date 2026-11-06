"""
Controlled Local Sandbox Server (`http://127.0.0.1:8765`).
Provides a safe, self-contained browser environment (just like `npm run dev` in Node/JS)
to test the real Python `InputSessionManager`, `AutocorrectEngine`, `SentenceCapitaliser`,
`TransactionLedger` (double-Backspace undo), Snippets, Domain Packs, and
Device-Locked Licensing (`MachineGuid` / `IOPlatformUUID` SHA-256 hash) without
hooking the global OS keyboard.
"""

from __future__ import annotations

import argparse
import json
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from autocorrect.daemon.app import AutoCorrectDaemon
from autocorrect.demo_host import DemoSession, EngineHost, SessionPool, normalise_route

# Backwards-compatible name for the per-visitor session record.
SandboxSession = DemoSession

SANDBOX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<title>Typen — Local Sandbox</title>
<style>
  :root {
    --bg: #0f172a;
    --panel: #1e293b;
    --border: #334155;
    --text: #f8fafc;
    --muted: #94a3b8;
    --accent: #3b82f6;
    --green: #10b981;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; padding: 24px;
    font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: var(--bg); color: var(--text);
  }
  .container { max-width: 1080px; margin: 0 auto; display: grid; grid-template-columns: 1.45fr 1fr; gap: 20px; }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 20px; }
  h1 { margin: 0 0 6px 0; font-size: 20px; }
  h2 { margin: 0 0 12px 0; font-size: 15px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
  .sub { color: var(--muted); font-size: 13px; margin-bottom: 16px; }
  textarea {
    width: 100%; height: 220px; background: #090d16; color: var(--text);
    border: 1px solid var(--border); border-radius: 8px; padding: 14px;
    font-size: 16px; line-height: 1.5; resize: vertical; outline: none;
  }
  textarea:focus { border-color: var(--accent); }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
  .chip {
    background: #0f172a; border: 1px solid var(--border); color: var(--muted);
    padding: 6px 10px; border-radius: 6px; font-size: 12px; cursor: pointer;
  }
  .chip:hover { border-color: var(--accent); color: var(--text); }
  .kv { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
  .kv span:first-child { color: var(--muted); }
  .kv code { color: #93c5fd; font-size: 12px; }
  .log {
    margin-top: 12px; max-height: 220px; overflow-y: auto;
    background: #090d16; border: 1px solid var(--border); border-radius: 8px; padding: 10px;
    font-family: monospace; font-size: 12px; color: #cbd5e1;
  }
  .log-item { padding: 4px 0; border-bottom: 1px dashed #1e293b; }
  .badge { background: rgba(16,185,129,0.15); color: var(--green); padding: 2px 8px; border-radius: 99px; font-size: 12px; font-weight: 600; }
</style>
</head>
<body>
<div class="container">
  <div class="card">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <h1>Typen — Local Sandbox</h1>
      <span class="badge" id="edition-badge">14-Day Pro Trial</span>
    </div>
    <div class="sub">
      Controlled browser sandbox connected to your local Python <code>InputSessionManager</code> &amp; <code>AutocorrectEngine</code> (OS global hooks are NOT active in sandbox mode).
    </div>
    <textarea id="editor" placeholder="Type here! Try:&#10;- i receive montly subs becos i am a beast ofa man.&#10;- I went too the market.&#10;- your welcome &#10;- dont forget (then press Backspace TWICE to undo a correction)&#10;- ;sig " autofocus></textarea>
    <div class="chips">
      <button class="chip" onclick="resetSession()">Reset Session Buffer</button>
      <button class="chip" onclick="insertSample('You\'re welcome. Raw eggs is best.')">Try: "You're welcome. Raw eggs is best."</button>
      <button class="chip" onclick="insertSample('I recieved your mesage.')">Try: "I recieved your mesage."</button>
      <button class="chip" onclick="insertSample('I went too the market.')">Try: "I went too the market."</button>
      <button class="chip" onclick="insertSample('your welcome ')">Try: "your welcome "</button>
      <button class="chip" onclick="insertSample(';sig ')">Try Pro Snippet: ";sig "</button>
    </div>
    <div class="log" id="event-log">
      <div class="log-item">Ready. Type in the box above and press Space or punctuation.</div>
    </div>
  </div>

  <div class="card">
    <h2>Live Engine Telemetry</h2>
    <div class="kv"><span>Active Word Buffer</span><code id="st-buffer">(empty)</code></div>
    <div class="kv"><span>Buffer Caret State</span><code id="st-caret">CLEAN</code></div>
    <div class="kv"><span>Sentence Capitaliser</span><code id="st-cap">SENTENCE_START</code></div>
    <div class="kv"><span>Undo Transaction Slot</span><code id="st-undo">None</code></div>
    <div class="kv"><span>Eval Latency (Last Key)</span><code id="st-lat">0.00 ms</code></div>
    <div class="kv"><span>Lexicon Words (mmap)</span><code id="st-words">-</code></div>
  </div>

  <div class="card">
    <h2>My Custom Dictionary</h2>
    <div class="sub">Words here are accepted exactly as typed and never corrected. A word you revert with double-Backspace is noted under <b>Suggested Words</b> below without interrupting your typing.</div>
    <div style="display:flex;gap:8px;">
      <input id="dict-input" type="text" placeholder="Type a word to add…" style="flex:1;background:#090d16;color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 10px;font-size:14px;outline:none;" />
      <button class="chip" id="dict-add" style="color:var(--text);">Add Word</button>
    </div>
    <div id="dict-list" style="margin-top:12px;display:flex;flex-wrap:wrap;gap:8px;"></div>
    <div class="sub" id="dict-empty" style="margin-top:10px;">No custom words yet.</div>

    <h2 style="margin-top:18px;">Suggested 'Add to Dictionary' Words (from Reverts)</h2>
    <div id="dict-suggested-list" style="margin-top:8px;display:flex;flex-wrap:wrap;gap:8px;"></div>
    <div class="sub" id="dict-suggested-empty" style="margin-top:6px;">No reverted word suggestions yet.</div>
  </div>
</div>

<script>
const editor = document.getElementById('editor');
const logBox = document.getElementById('event-log');
// Every visitor (even locally) gets an isolated engine session.
const SESSION_ID = 'local-' + Math.random().toString(36).slice(2, 14) + Date.now().toString(36);
const HEADERS = {'Content-Type': 'application/json', 'X-Session-Id': SESSION_ID};

function addLog(msg) {
  const d = document.createElement('div');
  d.className = 'log-item';
  d.textContent = msg;
  logBox.prepend(d);
}

async function sendKeyToEngine(keyName, charStr) {
  const res = await fetch('/api/key', {
    method: 'POST',
    headers: HEADERS,
    body: JSON.stringify({key_name: keyName, char: charStr})
  });
  return await res.json();
}

function updateTelemetry(data) {
  document.getElementById('st-buffer').textContent = data.current_word || '(empty)';
  document.getElementById('st-caret').textContent = data.buffer_state;
  document.getElementById('st-cap').textContent = data.sentence_state;
  document.getElementById('st-undo').textContent = data.active_undo || 'None';
  document.getElementById('st-lat').textContent = data.latency_ms.toFixed(2) + ' ms';
  document.getElementById('st-words').textContent = data.word_count;
}

// Serialised key processing: every keystroke is handled strictly in order,
// exactly like the synchronous native OS hook. preventDefault() is called
// SYNCHRONOUSLY (before any await) so the browser never inserts the space /
// punctuation itself; the engine's replacement plan is computed against a
// field that does NOT yet contain the delimiter. This is what prevents the
// old '+ new' conjoined text (e.g. 'iI ', 'rReceive').
let keyQueue = Promise.resolve();
function enqueueKey(task) {
  keyQueue = keyQueue.then(task).catch(err => addLog('[ERROR] ' + err));
  return keyQueue;
}

function applyPlanToEditor(plan) {
  const caret = editor.selectionStart;
  const keepStart = Math.max(0, caret - plan.backspaces_to_send);
  editor.value = editor.value.slice(0, keepStart) + plan.text_to_inject + editor.value.slice(editor.selectionEnd);
  const newPos = keepStart + plan.text_to_inject.length;
  editor.setSelectionRange(newPos, newPos);
}

function applyPassThrough(keyName, charStr) {
  const start = editor.selectionStart;
  const end = editor.selectionEnd;
  if (keyName === 'Backspace') {
    if (start === end && start > 0) {
      editor.value = editor.value.slice(0, start - 1) + editor.value.slice(end);
      editor.setSelectionRange(start - 1, start - 1);
    } else if (start !== end) {
      editor.value = editor.value.slice(0, start) + editor.value.slice(end);
      editor.setSelectionRange(start, start);
    }
    return;
  }
  if (!charStr) return;
  editor.value = editor.value.slice(0, start) + charStr + editor.value.slice(end);
  const newPos = start + charStr.length;
  editor.setSelectionRange(newPos, newPos);
}

async function processKey(keyName, charStr) {
  const data = await sendKeyToEngine(keyName, charStr);
  updateTelemetry(data);
  if (data.action === 'SUPPRESS_AND_INJECT' && data.plan) {
    applyPlanToEditor(data.plan);
    if (data.reverted_word) {
      addLog(`[UNDO] Reverted to "${data.reverted_word}" (${data.latency_ms.toFixed(2)} ms) — noted in Suggested Dictionary Words`);
      loadDictionary();
    } else {
      addLog(`[CORRECTED] "${data.plan.original_full}" -> "${data.plan.target_full}" (${data.reason || 'AUTO'}, ${data.latency_ms.toFixed(2)} ms)`);
    }
  } else {
    applyPassThrough(keyName, charStr);
  }
}

editor.addEventListener('keydown', (e) => {
  if (e.ctrlKey || e.altKey || e.metaKey) {
    enqueueKey(async () => {
      const res = await fetch('/api/caret', {method: 'POST', headers: HEADERS});
      updateTelemetry(await res.json());
    });
    return; // let the browser perform the shortcut itself
  }
  let keyName = e.key;
  let charStr = e.key.length === 1 ? e.key : '';
  if (e.key === ' ') { keyName = 'Space'; charStr = ' '; }
  else if (e.key === 'Enter') { keyName = 'Return'; charStr = '\\n'; }
  else if (e.key === 'Backspace') { keyName = 'Backspace'; charStr = ''; }
  else if (e.key.startsWith('Arrow') || e.key === 'Home' || e.key === 'End' || e.key === 'PageUp' || e.key === 'PageDown') {
    // Navigation: let the browser move the caret, but invalidate the engine buffer in-order.
    enqueueKey(async () => {
      const res = await fetch('/api/caret', {method: 'POST', headers: HEADERS});
      updateTelemetry(await res.json());
    });
    return;
  } else if (e.key.length > 1) {
    return; // Shift, CapsLock, F-keys etc. need no engine involvement
  }

  // CRITICAL: suppress the browser's own insertion NOW, synchronously,
  // before the async engine round-trip. We insert pass-through text ourselves.
  e.preventDefault();
  enqueueKey(() => processKey(keyName, charStr));
});

// Clicking moves the caret: invalidate the partial-word buffer (in queue
// order). Clicking into an EMPTY field restarts at a sentence start so the
// first word is capitalised.
editor.addEventListener('mousedown', () => {
  enqueueKey(async () => {
    const url = editor.value === '' ? '/api/reset' : '/api/caret';
    const res = await fetch(url, {method: 'POST', headers: HEADERS});
    updateTelemetry(await res.json());
  });
});

async function resetSession() {
  editor.value = '';
  const res = await fetch('/api/reset', {method: 'POST', headers: HEADERS});
  updateTelemetry(await res.json());
  editor.focus();
}

async function insertSample(sampleText) {
  await resetSession();
  for (const ch of sampleText) {
    editor.focus();
    editor.setSelectionRange(editor.value.length, editor.value.length);
    const keyName = ch === ' ' ? 'Space' : (ch === '\\n' ? 'Return' : ch);
    await processKey(keyName, ch);
  }
  editor.focus();
}

// --- Custom dictionary management -------------------------------------------
async function loadDictionary() {
  const res = await fetch('/api/dictionary', {headers: HEADERS});
  const data = await res.json();
  const list = document.getElementById('dict-list');
  const empty = document.getElementById('dict-empty');
  list.innerHTML = '';
  empty.style.display = data.words.length ? 'none' : 'block';
  for (const word of data.words) {
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.style.cursor = 'default';
    const label = document.createElement('span');
    label.textContent = word;
    const del = document.createElement('button');
    del.textContent = ' ✕';
    del.title = 'Remove "' + word + '" from my dictionary';
    del.style.cssText = 'background:none;border:none;color:#f87171;cursor:pointer;font-size:12px;padding:0 0 0 6px;';
    del.onclick = async () => {
      await fetch('/api/dictionary/delete', {method: 'POST', headers: HEADERS, body: JSON.stringify({word})});
      addLog(`[DICTIONARY] Removed "${word}" — it will be corrected again.`);
      loadDictionary();
    };
    chip.appendChild(label);
    chip.appendChild(del);
    list.appendChild(chip);
  }

  const sugList = document.getElementById('dict-suggested-list');
  const sugEmpty = document.getElementById('dict-suggested-empty');
  const suggested = data.suggested || [];
  sugList.innerHTML = '';
  sugEmpty.style.display = suggested.length ? 'none' : 'block';
  for (const item of suggested) {
    const word = item.word;
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.style.cursor = 'default';
    const label = document.createElement('span');
    label.textContent = item.corrected_to ? `${word} (was → ${item.corrected_to})` : word;
    const addBtn = document.createElement('button');
    addBtn.textContent = ' + Add';
    addBtn.title = 'Add "' + word + '" to my custom dictionary';
    addBtn.style.cssText = 'background:none;border:none;color:#10b981;cursor:pointer;font-size:12px;font-weight:600;padding:0 0 0 6px;';
    addBtn.onclick = async () => {
      await fetch('/api/dictionary/add', {method: 'POST', headers: HEADERS, body: JSON.stringify({word})});
      addLog(`[DICTIONARY] Promoted "${word}" from suggestions into custom dictionary.`);
      loadDictionary();
    };
    const disBtn = document.createElement('button');
    disBtn.textContent = ' ✕';
    disBtn.title = 'Dismiss suggestion';
    disBtn.style.cssText = 'background:none;border:none;color:#94a3b8;cursor:pointer;font-size:12px;padding:0 0 0 4px;';
    disBtn.onclick = async () => {
      await fetch('/api/dictionary/dismiss', {method: 'POST', headers: HEADERS, body: JSON.stringify({word})});
      loadDictionary();
    };
    chip.appendChild(label);
    chip.appendChild(addBtn);
    chip.appendChild(disBtn);
    sugList.appendChild(chip);
  }
}

async function addDictionaryWord() {
  const input = document.getElementById('dict-input');
  const word = input.value.trim();
  if (!word) return;
  await fetch('/api/dictionary/add', {method: 'POST', headers: HEADERS, body: JSON.stringify({word})});
  addLog(`[DICTIONARY] Added "${word}" — it will now be accepted as typed.`);
  input.value = '';
  loadDictionary();
}
document.getElementById('dict-add').addEventListener('click', addDictionaryWord);
document.getElementById('dict-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') { e.preventDefault(); addDictionaryWord(); }
  e.stopPropagation();
});

fetch('/api/reset', {method: 'POST', headers: HEADERS}).then(r => r.json()).then(updateTelemetry);
loadDictionary();
</script>
</body>
</html>
"""


def create_sandbox_daemon(data_dir: Path) -> AutoCorrectDaemon:
    """The full daemon with OS hooks dry-run: exercises licensing, packs and snippets too."""
    daemon = AutoCorrectDaemon(data_dir=data_dir, dry_run_hooks=True)
    daemon.start()
    daemon.resource_manager.set_enabled_domain_packs(
        {"programming", "medicine", "finance", "business", "academic"}
    )
    daemon.snippet_engine.add_snippet(";sig", "Best regards, the Typen team")
    return daemon


class SandboxSessionPool(SessionPool):
    """Per-visitor sessions built from a running daemon's shared components."""

    def __init__(
        self,
        daemon: AutoCorrectDaemon,
        data_dir: Path,
        max_sessions: int = 64,
        idle_ttl_s: float = 30 * 60,
    ) -> None:
        super().__init__(
            daemon.resource_manager,
            daemon.snippet_engine,
            daemon.entitlement_manager,
            data_dir,
            max_sessions=max_sessions,
            idle_ttl_s=idle_ttl_s,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Typen local browser sandbox")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path.home() / ".autocorrect_sandbox",
    )
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    daemon = create_sandbox_daemon(args.data_dir)
    host = EngineHost(
        work_dir=args.data_dir,
        resource_manager=daemon.resource_manager,
        snippet_engine=daemon.snippet_engine,
        entitlement_gate=daemon.entitlement_manager,
    )

    class SandboxHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *log_args: object) -> None:
            return

        def _session_id(self, payload: dict[str, Any]) -> str:
            sid = self.headers.get("X-Session-Id", "")
            if not sid:
                sid = parse_qs(urlsplit(self.path).query).get("session", [""])[0]
            if not sid:
                sid = str(payload.get("session_id", ""))
            return sid

        def _send_json(self, payload: dict[str, Any], status: int = HTTPStatus.OK) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _dispatch(self, payload: dict[str, Any]) -> None:
            route = normalise_route(self.path)
            status, body = host.handle(self.command, route, payload, self._session_id(payload))
            self._send_json(body, status)

        def do_GET(self) -> None:
            route = urlsplit(self.path).path
            if route in ("/", "/index.html"):
                body = SANDBOX_HTML.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            self._dispatch({})

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8")) if raw.strip() else {}
            except json.JSONDecodeError:
                self._send_json({"error": "invalid JSON"}, HTTPStatus.BAD_REQUEST)
                return
            self._dispatch(payload if isinstance(payload, dict) else {})

    url = f"http://{args.host}:{args.port}"
    server = ThreadingHTTPServer((args.host, args.port), SandboxHandler)
    server.daemon_threads = True
    print(f"Typen local sandbox running at: {url}")
    print("Press Ctrl+C to stop the sandbox server.")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down sandbox server...")
    finally:
        server.server_close()
        host.close()
        daemon.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
