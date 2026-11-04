"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";

/**
 * Live demo.
 *
 * Nothing here simulates autocorrect. Every keystroke goes to the real engine
 * (the same InputSessionManager + AutocorrectEngine the desktop daemon runs),
 * hosted as a Python function at /api/demo, and the engine's replacement plan
 * is applied to the textarea exactly as the OS injector would apply it.
 *
 * The function is serverless, so a request may land on an instance that has
 * never seen this session. Every `key`/`caret` request therefore carries the
 * text before the caret and the visitor's dictionary words; a fresh instance
 * primes a new session from them (without re-correcting anything) and answers
 * as if it had been there all along. `session_new: true` tells us that happened.
 */

type Mode = "connecting" | "live" | "offline";

interface LogEntry {
  id: number;
  kind: "FIXED" | "UNDO" | "DICT" | "INFO" | "ERROR";
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
  active_undo: string | null;
  word_count: number;
  session_new?: boolean;
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

const API = "/api/demo";
const SAMPLES: Array<{ label: string; text: string }> = [
  { label: "i recieved your mesage", text: "i recieved your mesage. its still not woking propaly. " },
  { label: "your welcome", text: "your welcome. raw eggs is best. " },
  { label: "dont forget teh milk", text: "dont forget teh milk ,and the bred. " },
  { label: ";sig", text: ";sig " },
];
const MAX_PASTE = 300;
const PRIME_TAIL = 600;

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
  const [attempt, setAttempt] = useState(0);

  const editorRef = useRef<HTMLTextAreaElement>(null);
  const sessionRef = useRef<string>("");
  const wordsRef = useRef<string[]>([]);
  const queueRef = useRef<Promise<void>>(Promise.resolve());

  const pushLog = useCallback((kind: LogEntry["kind"], message: string) => {
    setLogs((prev) => [{ id: Date.now() + Math.random(), kind, message }, ...prev.slice(0, 9)]);
  }, []);

  // --- transport ---------------------------------------------------------------
  const call = useCallback(async <T,>(route: string, body?: object): Promise<T> => {
    const res = await fetch(`${API}/${route}`, {
      method: body === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json", "X-Session-Id": sessionRef.current },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
    if (!res.ok) {
      const err = new Error(`engine ${res.status}`) as Error & { status?: number };
      err.status = res.status;
      throw err;
    }
    return (await res.json()) as T;
  }, []);

  /** Context a fresh serverless instance needs to rebuild this session. */
  const primingContext = () => {
    const ed = editorRef.current;
    const before = ed ? ed.value.slice(0, ed.selectionStart) : "";
    let text = before.length > PRIME_TAIL ? before.slice(-PRIME_TAIL) : before;
    if (text.length === PRIME_TAIL) {
      const cut = text.indexOf(" ");
      if (cut >= 0) text = text.slice(cut + 1);
    }
    return { text, words: wordsRef.current.slice(0, 64) };
  };

  const enqueue = useCallback(
    (task: () => Promise<void>) => {
      queueRef.current = queueRef.current.then(task).catch((err: unknown) => {
        const status = (err as { status?: number })?.status;
        if (status === undefined || status >= 500) {
          setMode("offline");
        } else {
          pushLog("ERROR", String((err as Error)?.message ?? err));
        }
      });
      return queueRef.current;
    },
    [pushLog],
  );

  const setDict = useCallback((d: Dictionary) => {
    wordsRef.current = d.words;
    setDictionary(d);
  }, []);

  const loadDictionary = useCallback(async () => {
    setDict(await call<Dictionary>("dictionary"));
  }, [call, setDict]);

  // --- connect -----------------------------------------------------------------
  useEffect(() => {
    sessionRef.current = newSessionId();
    let cancelled = false;
    setMode("connecting");
    (async () => {
      try {
        const h = await call<Health>("health");
        if (cancelled) return;
        setHealth(h);
        await call("reset", {});
        await loadDictionary();
        if (cancelled) return;
        setMode("live");
        pushLog("INFO", `Engine ${h.version} · lexicon ${h.lexicon_version} · ${h.word_count.toLocaleString()} words.`);
      } catch {
        if (!cancelled) setMode("offline");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [attempt, call, loadDictionary, pushLog]);

  // --- editor mutations (mirror of the OS injector) ------------------------------
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
    const data = await call<EngineResponse>("key", { key_name: keyName, char: ch, ...primingContext() });
    setLatency(data.latency_ms);
    if (data.action === "SUPPRESS_AND_INJECT" && data.plan) {
      applyPlan(data.plan);
      if (data.reverted_word) {
        pushLog("UNDO", `Kept "${data.reverted_word}" — added to suggestions.`);
        await loadDictionary();
      } else {
        const why = (data.reason ?? "auto").toLowerCase().replace(/_/g, " ");
        pushLog(
          "FIXED",
          `${data.plan.original_full.trim()} → ${data.plan.target_full.trim()}  (${why}, ${data.latency_ms.toFixed(1)} ms)`,
        );
      }
    } else {
      applyPassThrough(keyName, ch);
    }
  };

  const invalidateCaret = () =>
    enqueue(async () => {
      const ed = editorRef.current;
      if (ed && ed.value === "") await call("reset", {});
      else await call("caret", primingContext());
    });

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mode !== "live" || busy) {
      if (busy) e.preventDefault();
      return;
    }
    if (e.ctrlKey || e.altKey || e.metaKey) {
      invalidateCaret();
      return;
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
      return;
    }
    e.preventDefault();
    enqueue(() => processKey(keyName, ch));
  };

  const typeThroughEngine = async (text: string) => {
    const ed = editorRef.current;
    for (const ch of text) {
      if (ed) ed.setSelectionRange(ed.value.length, ed.value.length);
      await processKey(ch === " " ? "Space" : ch === "\n" ? "Return" : ch, ch);
    }
  };

  const onPaste = (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    if (mode !== "live") return;
    e.preventDefault();
    const text = e.clipboardData.getData("text").replace(/\r\n/g, "\n").slice(0, MAX_PASTE);
    if (!text) return;
    setBusy(true);
    enqueue(() => typeThroughEngine(text)).finally(() => setBusy(false));
  };

  const runSample = (sample: string) => {
    if (mode !== "live") return;
    setBusy(true);
    enqueue(async () => {
      const ed = editorRef.current;
      if (ed) ed.value = "";
      await call("reset", {});
      await typeThroughEngine(sample);
      ed?.focus();
    }).finally(() => setBusy(false));
  };

  const clear = () =>
    enqueue(async () => {
      const ed = editorRef.current;
      if (ed) ed.value = "";
      await call("reset", {});
      ed?.focus();
    });

  const dictionaryAction = (action: "add" | "delete" | "dismiss", word: string) =>
    enqueue(async () => {
      setDict(await call<Dictionary>(`dictionary/${action}`, { word, words: wordsRef.current }));
      if (action === "add") pushLog("DICT", `"${word}" added — accepted as typed from now on.`);
      if (action === "delete") pushLog("DICT", `"${word}" removed — corrected again.`);
    });

  const addWord = () => {
    const w = newWord.trim();
    if (!w || w.includes(" ")) return;
    setNewWord("");
    dictionaryAction("add", w);
  };

  // --- render ------------------------------------------------------------------
  const dot =
    mode === "live" ? "bg-emerald-400" : mode === "connecting" ? "animate-pulse bg-ink-faint" : "bg-proof";
  const statusText =
    mode === "live" && health
      ? `Live · engine ${health.version}${latency !== null ? ` · ${latency.toFixed(1)} ms` : ""}`
      : mode === "connecting"
        ? "Waking the engine…"
        : "Engine unreachable";

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3">
        <p className="text-sm text-ink-muted">
          Type below. Corrections land on <kbd className="kbd">Space</kbd> or punctuation; press{" "}
          <kbd className="kbd">Backspace</kbd> right after one to keep what you typed.
        </p>
        <span className="inline-flex items-center gap-2 font-mono text-[11px] text-ink-faint">
          <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden="true" />
          {statusText}
        </span>
      </div>

      {mode === "offline" ? (
        <div className="p-6">
          <p className="text-sm text-ink">The engine function did not answer.</p>
          <p className="mt-2 max-w-prose text-sm text-ink-muted">
            This demo runs the real engine as a serverless function, not a browser imitation, so when
            the function cannot be reached there is nothing honest to show in its place. A cold start
            can take a few seconds on the first visit; try once more.
          </p>
          <button type="button" className="btn-secondary mt-5" onClick={() => setAttempt((n) => n + 1)}>
            Retry
          </button>
        </div>
      ) : (
        <div className="grid gap-6 p-5 lg:grid-cols-[1fr_260px]">
          <div>
            <textarea
              ref={editorRef}
              defaultValue=""
              onKeyDown={onKeyDown}
              onPaste={onPaste}
              onMouseDown={() => mode === "live" && invalidateCaret()}
              rows={6}
              spellCheck={false}
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
              disabled={mode !== "live"}
              placeholder={mode === "live" ? "dont forget teh milk" : "Connecting…"}
              aria-label="Live demo editor"
              className="field min-h-[9.5rem] resize-none p-4 font-mono text-base leading-relaxed sm:text-lg"
            />
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span className="eyebrow mr-1">Try</span>
              {SAMPLES.map((s) => (
                <button
                  key={s.label}
                  type="button"
                  disabled={mode !== "live" || busy}
                  onClick={() => runSample(s.text)}
                  className="rounded border border-line px-2.5 py-1 font-mono text-xs text-ink-muted transition hover:border-ink-faint hover:text-ink disabled:opacity-50"
                >
                  {s.label}
                </button>
              ))}
              <button
                type="button"
                disabled={mode !== "live" || busy}
                onClick={clear}
                className="btn-ghost h-7 text-xs"
              >
                Clear
              </button>
            </div>

            <ol className="mt-4 max-h-32 space-y-1.5 overflow-y-auto font-mono text-xs text-ink-muted" aria-live="polite">
              {logs.length === 0 && <li className="text-ink-faint">Ready.</li>}
              {logs.map((log) => (
                <li key={log.id} className="flex gap-3">
                  <span
                    className={`w-10 shrink-0 ${
                      log.kind === "ERROR" ? "text-proof" : log.kind === "FIXED" ? "text-proof-strong" : "text-ink-faint"
                    }`}
                  >
                    {log.kind}
                  </span>
                  <span className={log.kind === "ERROR" ? "text-proof-strong" : undefined}>{log.message}</span>
                </li>
              ))}
            </ol>
          </div>

          <aside className="text-sm">
            <p className="eyebrow">Your words</p>
            <p className="mt-2 text-xs text-ink-faint">Anything here is never corrected. Lives only in this session.</p>
            <div className="mt-3 flex gap-2">
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
                aria-label="Add a word to your dictionary"
                className="field h-9 min-w-0 flex-1 text-xs"
              />
              <button type="button" disabled={mode !== "live"} onClick={addWord} className="btn-secondary h-9 px-3 text-xs">
                Add
              </button>
            </div>
            <div className="mt-3 flex flex-wrap gap-1.5">
              {dictionary.words.map((word) => (
                <span
                  key={word}
                  className="inline-flex items-center gap-1.5 rounded border border-line px-2 py-0.5 font-mono text-xs text-ink"
                >
                  {word}
                  <button
                    type="button"
                    onClick={() => dictionaryAction("delete", word)}
                    className="text-ink-faint hover:text-ink"
                    aria-label={`Remove ${word}`}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>

            {dictionary.suggested.length > 0 && (
              <div className="mt-6">
                <p className="eyebrow">Suggested from undo</p>
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {dictionary.suggested.map((item) => (
                    <span key={item.word} className="inline-flex items-center gap-1">
                      <button
                        type="button"
                        onClick={() => dictionaryAction("add", item.word)}
                        className="rounded border border-dashed border-line-strong px-2 py-0.5 font-mono text-xs text-ink-muted hover:border-ink-faint hover:text-ink"
                        title={item.corrected_to ? `Was corrected to ${item.corrected_to}. Click to keep.` : "Click to keep."}
                      >
                        + {item.word}
                      </button>
                      <button
                        type="button"
                        onClick={() => dictionaryAction("dismiss", item.word)}
                        className="text-xs text-ink-faint hover:text-ink"
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
