"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";

/**
 * Live demo.
 *
 * Nothing here simulates autocorrect. Every keystroke is sent to the real
 * Python engine (the same InputSessionManager + AutocorrectEngine the desktop
 * daemon runs) through /api/engine/*, and the engine's replacement plan is
 * applied to the textarea exactly as the OS injector would apply it. If the
 * engine is not reachable the demo says so and shows recorded engine output
 * instead of pretending.
 */

type Mode = "connecting" | "live" | "offline";

interface LogEntry {
  id: number;
  kind: "CORRECTED" | "UNDO" | "DICTIONARY" | "INFO" | "ERROR";
  message: string;
}

interface EnginePlan {
  backspaces_to_send: number;
  text_to_inject: string;
  original_full: string;
  target_full: string;
}

interface EngineResponse {
  action: string;
  plan: EnginePlan | null;
  reason: string | null;
  reverted_word: string | null;
  latency_ms: number;
  current_word: string;
  buffer_state: string;
  sentence_state: string;
  active_undo: string | null;
  word_count: number;
}

interface Health {
  ok: boolean;
  version: string;
  lexicon_version: string;
  word_count: number;
}

interface Dictionary {
  words: string[];
  suggested: Array<{ word: string; corrected_to?: string | null }>;
}

const SAMPLES: Array<{ label: string; text: string }> = [
  { label: "i receive montly subs becos…", text: "i receive montly subs becos i am a beast ofa man. " },
  { label: "its still not woking propaly", text: "Whats up? its still not woking propaly. " },
  { label: "your welcome. raw eggs is best.", text: "your welcome. raw eggs is best. " },
  { label: "I recieved your mesage.", text: "I recieved your mesage. " },
  { label: ";sig", text: ";sig " },
];

/** Output recorded from the engine (1.2.0, lexicon 1.0.9) for the offline notice. */
const RECORDED: Array<{ before: string; after: string }> = [
  { before: "i receive montly subs becos i am a beast ofa man.", after: "I receive monthly subs because I am a beast of a man." },
  { before: "Whats up? its still not woking propaly.", after: "What's up? It's still not working properly." },
  { before: "your welcome. raw eggs is best.", after: "You're welcome. Raw eggs are best." },
  { before: "I recieved your mesage.", after: "I received your message." },
  { before: "dont forget teh milk.", after: "Don't forget the milk." },
];

const MAX_PASTE = 300;

function newSessionId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return "web-" + crypto.randomUUID().replace(/-/g, "").slice(0, 24);
  }
  return "web-" + Math.random().toString(36).slice(2, 14) + Date.now().toString(36);
}

export function InteractiveSandbox() {
  const [mode, setMode] = useState<Mode>("connecting");
  const [health, setHealth] = useState<Health | null>(null);
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [latency, setLatency] = useState<number | null>(null);
  const [dictionary, setDictionary] = useState<Dictionary>({ words: [], suggested: [] });
  const [newWord, setNewWord] = useState("");
  const [busy, setBusy] = useState(false);

  const editorRef = useRef<HTMLTextAreaElement>(null);
  const sessionRef = useRef<string>("");
  const queueRef = useRef<Promise<void>>(Promise.resolve());

  const pushLog = useCallback((kind: LogEntry["kind"], message: string) => {
    setLogs((prev) => [{ id: Date.now() + Math.random(), kind, message }, ...prev.slice(0, 11)]);
  }, []);

  // --- engine transport ------------------------------------------------------
  const call = useCallback(async <T,>(path: string, body?: object): Promise<T> => {
    const res = await fetch(`/api/engine/${path}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json", "X-Session-Id": sessionRef.current },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
    if (!res.ok) {
      const err = new Error(`engine ${res.status}`);
      (err as Error & { status?: number }).status = res.status;
      throw err;
    }
    return (await res.json()) as T;
  }, []);

  const enqueue = useCallback(
    (task: () => Promise<void>) => {
      queueRef.current = queueRef.current.then(task).catch((err: unknown) => {
        const status = (err as { status?: number })?.status;
        if (status === 503) {
          setMode("offline");
          pushLog("ERROR", "Lost connection to the engine.");
        } else {
          pushLog("ERROR", String(err));
        }
      });
      return queueRef.current;
    },
    [pushLog],
  );

  const loadDictionary = useCallback(async () => {
    const d = await call<Dictionary>("api/dictionary");
    setDictionary(d);
  }, [call]);

  // --- connect ---------------------------------------------------------------
  useEffect(() => {
    sessionRef.current = newSessionId();
    let cancelled = false;
    (async () => {
      try {
        const h = await call<Health>("api/health");
        if (cancelled) return;
        setHealth(h);
        setMode("live");
        await call("api/reset", {});
        await loadDictionary();
        pushLog("INFO", `Connected to engine ${h.version}, lexicon ${h.lexicon_version}.`);
      } catch {
        if (!cancelled) setMode("offline");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [call, loadDictionary, pushLog]);

  // --- editor mutations (mirror of the OS injector) --------------------------
  const applyPlan = (plan: EnginePlan) => {
    const ed = editorRef.current;
    if (!ed) return;
    const caret = ed.selectionStart;
    const keep = Math.max(0, caret - plan.backspaces_to_send);
    ed.value = ed.value.slice(0, keep) + plan.text_to_inject + ed.value.slice(ed.selectionEnd);
    const pos = keep + plan.text_to_inject.length;
    ed.setSelectionRange(pos, pos);
  };

  const applyPassThrough = (keyName: string, ch: string) => {
    const ed = editorRef.current;
    if (!ed) return;
    const start = ed.selectionStart;
    const end = ed.selectionEnd;
    if (keyName === "Backspace") {
      if (start === end && start > 0) {
        ed.value = ed.value.slice(0, start - 1) + ed.value.slice(end);
        ed.setSelectionRange(start - 1, start - 1);
      } else if (start !== end) {
        ed.value = ed.value.slice(0, start) + ed.value.slice(end);
        ed.setSelectionRange(start, start);
      }
      return;
    }
    if (!ch) return;
    ed.value = ed.value.slice(0, start) + ch + ed.value.slice(end);
    ed.setSelectionRange(start + ch.length, start + ch.length);
  };

  const processKey = async (keyName: string, ch: string) => {
    const data = await call<EngineResponse>("api/key", { key_name: keyName, char: ch });
    setLatency(data.latency_ms);
    if (data.action === "SUPPRESS_AND_INJECT" && data.plan) {
      applyPlan(data.plan);
      if (data.reverted_word) {
        pushLog("UNDO", `Reverted to "${data.reverted_word}" — added to suggestions.`);
        await loadDictionary();
      } else {
        pushLog(
          "CORRECTED",
          `"${data.plan.original_full.trim()}" → "${data.plan.target_full.trim()}" (${(data.reason ?? "AUTO").toLowerCase().replace(/_/g, " ")}, ${data.latency_ms.toFixed(2)} ms)`,
        );
      }
    } else {
      applyPassThrough(keyName, ch);
    }
  };

  const invalidateCaret = () =>
    enqueue(async () => {
      const ed = editorRef.current;
      await call(ed && ed.value === "" ? "api/reset" : "api/caret", {});
    });

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mode !== "live" || busy) {
      if (busy) e.preventDefault();
      return;
    }
    if (e.ctrlKey || e.altKey || e.metaKey) {
      invalidateCaret();
      return; // browser shortcut (copy, select-all, …)
    }
    let keyName = e.key;
    let ch = e.key.length === 1 ? e.key : "";
    if (e.key === " ") {
      keyName = "Space";
      ch = " ";
    } else if (e.key === "Enter") {
      keyName = "Return";
      ch = "\n";
    } else if (e.key === "Backspace") {
      ch = "";
    } else if (e.key.startsWith("Arrow") || ["Home", "End", "PageUp", "PageDown", "Delete"].includes(e.key)) {
      invalidateCaret();
      return;
    } else if (e.key.length > 1) {
      return; // Shift, CapsLock, F-keys
    }
    // Suppress the browser's own insertion synchronously; the engine decides.
    e.preventDefault();
    enqueue(() => processKey(keyName, ch));
  };

  const typeThroughEngine = async (text: string) => {
    const ed = editorRef.current;
    for (const ch of text) {
      if (ed) ed.setSelectionRange(ed.value.length, ed.value.length);
      const keyName = ch === " " ? "Space" : ch === "\n" ? "Return" : ch;
      await processKey(keyName, ch);
    }
  };

  const onPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (mode !== "live") return;
    e.preventDefault();
    const text = e.clipboardData.getData("text").replace(/\r\n/g, "\n").slice(0, MAX_PASTE);
    if (!text) return;
    setBusy(true);
    enqueue(async () => {
      await typeThroughEngine(text);
    }).finally(() => setBusy(false));
  };

  const runSample = (sample: string) => {
    if (mode !== "live") return;
    setBusy(true);
    enqueue(async () => {
      const ed = editorRef.current;
      if (ed) ed.value = "";
      await call("api/reset", {});
      await typeThroughEngine(sample);
      ed?.focus();
    }).finally(() => setBusy(false));
  };

  const clear = () =>
    enqueue(async () => {
      const ed = editorRef.current;
      if (ed) ed.value = "";
      await call("api/reset", {});
      ed?.focus();
    });

  const dictionaryAction = (action: "add" | "delete" | "dismiss", word: string) =>
    enqueue(async () => {
      const d = await call<Dictionary>(`api/dictionary/${action}`, { word });
      setDictionary(d);
      if (action === "add") pushLog("DICTIONARY", `"${word}" added — accepted as typed.`);
      if (action === "delete") pushLog("DICTIONARY", `"${word}" removed — corrected again.`);
    });

  const addWord = () => {
    const w = newWord.trim();
    if (!w || w.includes(" ")) return;
    setNewWord("");
    dictionaryAction("add", w);
  };

  // --- render ----------------------------------------------------------------
  const status =
    mode === "live" && health
      ? `Live engine ${health.version} · lexicon ${health.lexicon_version} · ${health.word_count.toLocaleString()} words${
          latency !== null ? ` · ${latency.toFixed(2)} ms` : ""
        }`
      : mode === "connecting"
        ? "Connecting to engine…"
        : "Engine offline";

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-zinc-800 px-5 py-3">
        <p className="text-sm text-zinc-300">
          Try it — corrections apply on Space or punctuation. Backspace twice to undo.
        </p>
        <span className="text-xs text-zinc-500">{status}</span>
      </div>

      {mode === "offline" ? (
        <div className="p-5">
          <p className="text-sm text-zinc-300">
            The live demo runs the real engine, and it isn&apos;t reachable from this page right now.
            Rather than imitate it in the browser, here is output recorded from the engine:
          </p>
          <ul className="mt-4 space-y-2 text-sm">
            {RECORDED.map((r) => (
              <li key={r.before} className="grid gap-1 rounded-lg border border-zinc-800 bg-zinc-950 p-3 sm:grid-cols-2">
                <span className="text-zinc-500 line-through decoration-zinc-700">{r.before}</span>
                <span className="text-zinc-100">{r.after}</span>
              </li>
            ))}
          </ul>
          <p className="mt-4 text-xs text-zinc-500">
            To run it live: <code className="text-zinc-300">autocorrect-sandbox --no-browser</code> next to the site
            (or set <code className="text-zinc-300">AUTOCORRECT_ENGINE_URL</code>), or download the beta and type anywhere.
          </p>
        </div>
      ) : (
        <div className="grid gap-6 p-5 lg:grid-cols-[1fr_280px]">
          <div>
            <textarea
              ref={editorRef}
              defaultValue=""
              onKeyDown={onKeyDown}
              onPaste={onPaste}
              onMouseDown={() => mode === "live" && invalidateCaret()}
              rows={5}
              spellCheck={false}
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
              disabled={mode !== "live"}
              placeholder={mode === "live" ? "Type here…" : "Connecting…"}
              className="w-full resize-none rounded-lg border border-zinc-800 bg-zinc-950 p-4 text-sm leading-relaxed text-zinc-100 placeholder-zinc-600 focus:border-zinc-600 focus:outline-none disabled:opacity-60"
            />
            <div className="mt-3 flex flex-wrap gap-2">
              {SAMPLES.map((s) => (
                <button
                  key={s.label}
                  type="button"
                  disabled={mode !== "live" || busy}
                  onClick={() => runSample(s.text)}
                  className="rounded-md border border-zinc-800 px-2.5 py-1 text-xs text-zinc-400 transition hover:border-zinc-600 hover:text-zinc-100 disabled:opacity-50"
                >
                  {s.label}
                </button>
              ))}
              <button
                type="button"
                disabled={mode !== "live" || busy}
                onClick={clear}
                className="px-2.5 py-1 text-xs text-zinc-500 hover:text-zinc-200 disabled:opacity-50"
              >
                Clear
              </button>
            </div>

            <ul className="mt-4 max-h-28 space-y-1 overflow-y-auto text-xs text-zinc-400">
              {logs.length === 0 && <li className="text-zinc-600">Ready.</li>}
              {logs.map((log) => (
                <li key={log.id} className="flex gap-2">
                  <span className="w-20 shrink-0 font-mono uppercase text-zinc-600">{log.kind}</span>
                  <span className={log.kind === "ERROR" ? "text-red-400" : undefined}>{log.message}</span>
                </li>
              ))}
            </ul>
          </div>

          <aside className="text-sm">
            <p className="eyebrow">Your dictionary</p>
            <div className="mt-2 flex gap-2">
              <input
                type="text"
                value={newWord}
                disabled={mode !== "live"}
                onChange={(e) => setNewWord(e.target.value)}
                onKeyDown={(e) => {
                  e.stopPropagation();
                  if (e.key === "Enter") addWord();
                }}
                placeholder="Add a word"
                className="min-w-0 flex-1 rounded-md border border-zinc-800 bg-zinc-950 px-3 py-1.5 text-xs text-zinc-100 placeholder-zinc-600 focus:border-zinc-600 focus:outline-none disabled:opacity-60"
              />
              <button
                type="button"
                disabled={mode !== "live"}
                onClick={addWord}
                className="rounded-md border border-zinc-700 px-3 py-1.5 text-xs text-zinc-200 hover:bg-zinc-900 disabled:opacity-50"
              >
                Add
              </button>
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {dictionary.words.length === 0 && (
                <span className="text-xs text-zinc-600">Words here are never corrected.</span>
              )}
              {dictionary.words.map((word) => (
                <span
                  key={word}
                  className="inline-flex items-center gap-1.5 rounded-md border border-zinc-800 px-2 py-0.5 text-xs text-zinc-300"
                >
                  {word}
                  <button
                    type="button"
                    onClick={() => dictionaryAction("delete", word)}
                    className="text-zinc-500 hover:text-zinc-200"
                    aria-label={`Remove ${word}`}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>

            {dictionary.suggested.length > 0 && (
              <div className="mt-5">
                <p className="eyebrow">Suggested from undo</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {dictionary.suggested.map((item) => (
                    <span key={item.word} className="inline-flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => dictionaryAction("add", item.word)}
                        className="rounded-md border border-dashed border-zinc-700 px-2 py-0.5 text-xs text-zinc-300 hover:border-zinc-500"
                        title={item.corrected_to ? `Was corrected to ${item.corrected_to}. Click to keep.` : "Click to keep."}
                      >
                        + {item.word}
                      </button>
                      <button
                        type="button"
                        onClick={() => dictionaryAction("dismiss", item.word)}
                        className="text-xs text-zinc-600 hover:text-zinc-300"
                        aria-label={`Dismiss ${item.word}`}
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}
