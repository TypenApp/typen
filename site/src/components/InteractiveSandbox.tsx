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
 *
 * Requests are batched: keys typed while a request is in flight are sent
 * together in the next one, and a paste or sample is a single request. The
 * engine answers with one result per key. This keeps the demo quick at a few
 * hundred milliseconds of round trip, and it keeps a fast typist from looking
 * like a flood to Vercel's automatic DDoS mitigation, which otherwise answers
 * `fetch` with a JavaScript challenge page (HTTP 403, `X-Vercel-Mitigated:
 * challenge`) that only a full page load can pass. When that happens anyway we
 * keep what was typed, say so, and offer a reload that restores the draft.
 */

type Mode = "connecting" | "live" | "offline" | "checkpoint";

interface PendingKey {
  key_name: string;
  char: string;
  /** performance.now() when the key was pressed: lets the engine time the double-Backspace gesture. */
  t: number;
}

class CheckpointError extends Error {
  constructor() {
    super("security checkpoint");
  }
}

const DRAFT_KEY = "typen-demo-draft";

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

interface BatchResponse extends EngineResponse {
  results?: EngineResponse[];
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
  { label: "dont forget teh milk", text: "dont forget teh milk ,and the braed. " },
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
  const pendingRef = useRef<PendingKey[]>([]);
  const flushQueuedRef = useRef(false);
  const draftRef = useRef("");
  /** `t` of the last key sent to the engine: a fresh instance needs it to time a double Space across batches. */
  const lastKeyTRef = useRef<number | null>(null);

  const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

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
    const mitigated = res.headers.get("x-vercel-mitigated");
    const isJson = (res.headers.get("content-type") ?? "").includes("json");
    if (mitigated || (res.status === 403 && !isJson)) throw new CheckpointError();
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
    return { text, words: wordsRef.current.slice(0, 64), prev_t: lastKeyTRef.current ?? undefined };
  };

  const enqueue = useCallback(
    (task: () => Promise<void>) => {
      queueRef.current = queueRef.current.then(task).catch((err: unknown) => {
        if (err instanceof CheckpointError) {
          pendingRef.current = [];
          flushQueuedRef.current = false;
          draftRef.current = editorRef.current?.value ?? ""; // the panel replaces the field
          setMode("checkpoint");
          return;
        }
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
        // A draft saved before a checkpoint reload: put it back and let the
        // engine prime from it, so the visitor continues where they were.
        let draft = "";
        try {
          draft = sessionStorage.getItem(DRAFT_KEY) ?? "";
          sessionStorage.removeItem(DRAFT_KEY);
        } catch {
          /* storage unavailable */
        }
        if (draft && editorRef.current) {
          editorRef.current.value = draft;
          editorRef.current.setSelectionRange(draft.length, draft.length);
          await call("caret", { text: draft.slice(-PRIME_TAIL), words: [] });
        }
        await loadDictionary();
        if (cancelled) return;
        setMode("live");
        pushLog("INFO", `Engine ${h.version} · lexicon ${h.lexicon_version} · ${h.word_count.toLocaleString()} words.`);
        if (draft) pushLog("INFO", "Draft restored.");
      } catch (err) {
        if (!cancelled) setMode(err instanceof CheckpointError ? "checkpoint" : "offline");
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

  /** Mirror one engine result on the field, exactly as the OS injector would. */
  const applyResult = (key: PendingKey, data: EngineResponse): boolean => {
    if (data.action === "SUPPRESS_AND_INJECT" && data.plan) {
      applyPlan(data.plan);
      if (data.reverted_word) {
        pushLog("UNDO", `Kept "${data.reverted_word}" — added to suggestions.`);
        return true;
      }
      const why = (data.reason ?? "auto").toLowerCase().replace(/_/g, " ");
      // Punctuation fixes are mostly spaces; show them rather than trimming them away.
      const show = (s: string) => s.trim() || s.replace(/ /g, "␣");
      pushLog(
        "FIXED",
        `${show(data.plan.original_full)} → ${show(data.plan.target_full)}  (${why}, ${data.latency_ms.toFixed(1)} ms)`,
      );
      return false;
    }
    applyPassThrough(key.key_name, key.char);
    return false;
  };

  /**
   * Send a batch of keys in one request and apply the results in order.
   *
   * Manual typing is applied the moment the answer arrives, so the field never
   * lags the keyboard. Samples and pastes are also evaluated in one request,
   * but `animate` replays the answer at a typewriter cadence so the visitor
   * sees each typo typed and then repaired, instead of a block of text landing.
   */
  const sendKeys = async (keys: PendingKey[], opts?: { animate?: boolean }) => {
    if (keys.length === 0) return;
    let data: BatchResponse;
    try {
      data = await call<BatchResponse>("key", { keys, ...primingContext() });
    } catch (err) {
      // Whatever went wrong, the visitor's keystrokes must not vanish.
      for (const k of keys) applyPassThrough(k.key_name, k.char);
      throw err;
    } finally {
      lastKeyTRef.current = keys[keys.length - 1].t;
    }
    const results = data.results ?? [data];
    let reverted = false;
    if (opts?.animate) {
      const ed = editorRef.current;
      // The playback owns the caret: a stray click must not scatter the text.
      let caret = ed ? ed.selectionStart : 0;
      for (let i = 0; i < keys.length; i++) {
        const r = results[i];
        const ch = keys[i].char;
        const correcting = r !== undefined && r.action === "SUPPRESS_AND_INJECT" && r.plan !== null;
        // A beat before a correction so the typo is seen before it snaps right.
        if (correcting) await sleep(85);
        ed?.setSelectionRange(caret, caret);
        if (r === undefined) applyPassThrough(keys[i].key_name, ch);
        else {
          if (applyResult(keys[i], r)) reverted = true;
          setLatency(r.latency_ms);
        }
        caret = ed ? ed.selectionStart : caret;
        const jitter = ((i * 17) % 13) - 6; // -6..+6 ms, a human cadence rather than a metronome
        await sleep(Math.max(18, (correcting ? 55 : ch === "." || ch === "," ? 70 : ch === " " ? 45 : 34) + jitter));
      }
    } else {
      results.forEach((r, i) => {
        if (i < keys.length && applyResult(keys[i], r)) reverted = true;
      });
      setLatency(results.reduce((max, r) => Math.max(max, r.latency_ms), 0));
    }
    if (reverted) await loadDictionary();
  };

  /** Everything queued since the last request goes out as one batch, applied at once. */
  const flushKeys = async () => {
    flushQueuedRef.current = false;
    const keys = pendingRef.current;
    pendingRef.current = [];
    await sendKeys(keys);
  };

  const queueKey = (keyName: string, ch: string) => {
    pendingRef.current.push({ key_name: keyName, char: ch, t: performance.now() });
    if (!flushQueuedRef.current) {
      flushQueuedRef.current = true;
      enqueue(flushKeys);
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
    queueKey(keyName, ch);
  };

  /** Type a whole text through the engine as one batch, then play back with a typewriter cadence. */
  const typeThroughEngine = async (text: string) => {
    const ed = editorRef.current;
    if (ed) {
      ed.focus();
      ed.setSelectionRange(ed.value.length, ed.value.length);
    }
    const now = performance.now();
    const chars = Array.from(text);
    const keys: PendingKey[] = chars.map((ch, i) => ({
      key_name: ch === " " ? "Space" : ch === "\n" ? "Return" : ch,
      char: ch,
      // A steady 25 keys/s ending now, so timing-based gestures behave as if typed.
      t: now - (chars.length - 1 - i) * 40,
    }));
    await sendKeys(keys, { animate: true });
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
      lastKeyTRef.current = null;
      await call("reset", {});
      await typeThroughEngine(sample);
      ed?.focus();
    }).finally(() => setBusy(false));
  };

  const clear = () =>
    enqueue(async () => {
      const ed = editorRef.current;
      if (ed) ed.value = "";
      lastKeyTRef.current = null;
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
        : mode === "checkpoint"
          ? "Paused by a security checkpoint"
          : "Engine unreachable";

  const reloadKeepingDraft = () => {
    try {
      const text = draftRef.current || (editorRef.current?.value ?? "");
      if (text) sessionStorage.setItem(DRAFT_KEY, text);
    } catch {
      /* storage unavailable */
    }
    window.location.reload();
  };

  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-3">
        <p className="text-sm text-ink-muted">
          Type below. Corrections land on <kbd className="kbd">Space</kbd> or punctuation; a second{" "}
          <kbd className="kbd">Space</kbd> ends the sentence with a full stop; press{" "}
          <kbd className="kbd">Backspace</kbd> twice right after a correction to keep what you typed.
        </p>
        <span className="inline-flex items-center gap-2 font-mono text-[11px] text-ink-faint">
          <span className={`h-1.5 w-1.5 rounded-full ${dot}`} aria-hidden="true" />
          {statusText}
        </span>
      </div>

      {mode === "checkpoint" ? (
        <div className="p-6">
          <p className="text-sm text-ink">The host paused the demo for a security check.</p>
          <p className="mt-2 max-w-prose text-sm text-ink-muted">
            Vercel, which runs the engine function, briefly mistook this typing session for automated
            traffic and is asking for a browser check that only a page load can pass. Nothing you typed
            is lost: reload, and the text comes back with the engine primed from it.
          </p>
          <button type="button" className="btn-primary mt-5" onClick={reloadKeepingDraft}>
            Reload and continue
          </button>
        </div>
      ) : mode === "offline" ? (
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
