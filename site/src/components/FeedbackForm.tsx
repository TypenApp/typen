"use client";

import React, { useState } from "react";
import { GITHUB_REPO_URL } from "@/data/releases";

type Kind = "suggestion" | "bug";

interface FormState {
  kind: Kind;
  alias: string;
  email: string;
  note: string;
  steps: string;
  appVersion: string;
  os: string;
  website: string; // honeypot
}

const INITIAL: FormState = {
  kind: "suggestion",
  alias: "",
  email: "",
  note: "",
  steps: "",
  appVersion: "",
  os: "",
  website: "",
};

const COPY: Record<Kind, { title: string; help: string; notePlaceholder: string; button: string; lands: string }> = {
  suggestion: {
    title: "Suggestion",
    help: "An idea, a word the engine should know, a setting you wish existed.",
    notePlaceholder: "It would be great if Typen could…",
    button: "Send suggestion",
    lands: "Suggestions open a GitHub Discussion so other people can add to them and vote.",
  },
  bug: {
    title: "Report a bug",
    help: "Something corrected that should not have been, or missed when it should have fired.",
    notePlaceholder: "Typen capitalised the word after a comma in Slack…",
    button: "Report bug",
    lands: "Bug reports open a GitHub Issue tagged bug so they can be tracked to a fix.",
  },
};

export function FeedbackForm({ initialKind = "suggestion" }: { initialKind?: Kind }) {
  const [form, setForm] = useState<FormState>({ ...INITIAL, kind: initialKind });
  const [status, setStatus] = useState<"idle" | "sending" | "done" | "error">("idle");
  const [message, setMessage] = useState("");
  const [resultUrl, setResultUrl] = useState("");

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }));
  const copy = COPY[form.kind];
  const canSend = status !== "sending" && form.alias.trim().length > 0 && form.note.trim().length >= 10;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSend) return;
    setStatus("sending");
    setMessage("");
    setResultUrl("");
    const diagnostics: Record<string, string> = {};
    if (form.kind === "bug") {
      if (form.appVersion.trim()) diagnostics.app_version = form.appVersion.trim();
      if (form.os.trim()) diagnostics.os = form.os.trim();
    }
    try {
      const res = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          kind: form.kind,
          alias: form.alias,
          email: form.email,
          note: form.note,
          steps: form.kind === "bug" ? form.steps : "",
          source: "site",
          app_version: form.appVersion,
          diagnostics: Object.keys(diagnostics).length ? diagnostics : undefined,
          website: form.website,
        }),
      });
      const data = (await res.json().catch(() => ({}))) as { ok?: boolean; url?: string; error?: string };
      if (res.ok && data.ok) {
        setStatus("done");
        setResultUrl(data.url ?? "");
        setMessage(form.kind === "bug" ? "Thanks — your bug report is in." : "Thanks — your suggestion is in.");
        setForm((f) => ({ ...f, note: "", steps: "" }));
      } else {
        setStatus("error");
        setMessage(data.error ?? `Something went wrong (HTTP ${res.status}).`);
      }
    } catch {
      setStatus("error");
      setMessage("Could not reach the server. Check your connection and try again.");
    }
  }

  return (
    <form onSubmit={submit} className="card p-6 sm:p-8" noValidate>
      {/* Kind switch */}
      <div className="inline-flex rounded border border-line p-0.5" role="tablist" aria-label="Feedback type">
        {(Object.keys(COPY) as Kind[]).map((k) => {
          const active = form.kind === k;
          return (
            <button
              key={k}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => {
                set("kind", k);
                setStatus("idle");
                setMessage("");
                setResultUrl("");
              }}
              className={`rounded px-3.5 py-1.5 text-sm transition-colors ${
                active ? "bg-ink text-paper" : "text-ink-muted hover:text-ink"
              }`}
            >
              {COPY[k].title}
            </button>
          );
        })}
      </div>
      <p className="mt-3 text-sm text-ink-muted">{copy.help}</p>

      <div className="mt-6 grid gap-5 sm:grid-cols-2">
        <label className="block">
          <span className="eyebrow">Alias</span>
          <input
            className="field mt-2"
            value={form.alias}
            onChange={(e) => set("alias", e.target.value)}
            placeholder="How should we credit you?"
            maxLength={60}
            required
            autoComplete="nickname"
          />
        </label>
        <label className="block">
          <span className="eyebrow">Email (optional)</span>
          <input
            className="field mt-2"
            type="email"
            value={form.email}
            onChange={(e) => set("email", e.target.value)}
            placeholder="Only if you want a reply"
            autoComplete="email"
          />
        </label>
      </div>

      <label className="mt-5 block">
        <span className="eyebrow">{form.kind === "bug" ? "What happened?" : "Your idea"}</span>
        <textarea
          className="field mt-2 min-h-[140px] resize-y"
          value={form.note}
          onChange={(e) => set("note", e.target.value)}
          placeholder={copy.notePlaceholder}
          maxLength={4000}
          required
        />
        <span className="mt-1 block text-right font-mono text-[11px] text-ink-faint">{form.note.length} / 4000</span>
      </label>

      {form.kind === "bug" && (
        <>
          <label className="mt-2 block">
            <span className="eyebrow">Steps to reproduce (optional)</span>
            <textarea
              className="field mt-2 min-h-[96px] resize-y"
              value={form.steps}
              onChange={(e) => set("steps", e.target.value)}
              placeholder={"1. Open Slack\n2. Type 'hello, world'\n3. …"}
              maxLength={2000}
            />
          </label>
          <div className="mt-5 grid gap-5 sm:grid-cols-2">
            <label className="block">
              <span className="eyebrow">Typen version (optional)</span>
              <input
                className="field mt-2"
                value={form.appVersion}
                onChange={(e) => set("appVersion", e.target.value)}
                placeholder="Settings › About, e.g. 1.3.0"
                maxLength={40}
              />
            </label>
            <label className="block">
              <span className="eyebrow">Operating system (optional)</span>
              <input
                className="field mt-2"
                value={form.os}
                onChange={(e) => set("os", e.target.value)}
                placeholder="Windows 11 24H2"
                maxLength={80}
              />
            </label>
          </div>
        </>
      )}

      {/* Honeypot: invisible to people, irresistible to bots. */}
      <div className="absolute -left-[9999px] top-auto h-px w-px overflow-hidden" aria-hidden="true">
        <label>
          Website
          <input tabIndex={-1} autoComplete="off" value={form.website} onChange={(e) => set("website", e.target.value)} />
        </label>
      </div>

      <div className="mt-6 flex flex-wrap items-center justify-between gap-4">
        <p className="max-w-md text-xs leading-relaxed text-ink-faint">
          {copy.lands} Your alias and note appear publicly on GitHub; your email does not have to.
        </p>
        <button type="submit" className="btn-primary" disabled={!canSend}>
          {status === "sending" ? "Sending…" : copy.button}
        </button>
      </div>

      {message && (
        <div
          role="status"
          className={`mt-5 rounded border px-4 py-3 text-sm ${
            status === "error" ? "border-proof/40 text-proof" : "border-line text-ink"
          }`}
        >
          {message}{" "}
          {resultUrl && (
            <a href={resultUrl} target="_blank" rel="noopener noreferrer" className="link">
              Open it on GitHub ↗
            </a>
          )}
          {status === "error" && (
            <>
              {" "}
              You can also post directly:{" "}
              <a
                href={form.kind === "bug" ? `${GITHUB_REPO_URL}/issues/new` : `${GITHUB_REPO_URL}/discussions/new?category=ideas`}
                target="_blank"
                rel="noopener noreferrer"
                className="link"
              >
                {form.kind === "bug" ? "new issue" : "new discussion"} ↗
              </a>
              .
            </>
          )}
        </div>
      )}
    </form>
  );
}
