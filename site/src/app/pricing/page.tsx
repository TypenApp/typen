"use client";

import React, { useState } from "react";
import Link from "next/link";
import { PRICING_BY_CURRENCY, type CurrencyPricing } from "@/data/releases";

type Scenario = "NEW" | "RENEWAL" | "CROSSGRADE";

const SCENARIOS: Array<{ id: Scenario; label: string; note: string }> = [
  { id: "NEW", label: "New licence", note: "Perpetual licence with 12 months of updates." },
  { id: "RENEWAL", label: "Renew updates", note: "Another 12 months of updates at 30% off. Your existing licence keeps working either way." },
  { id: "CROSSGRADE", label: "Standard → Pro", note: "Pay only the difference to move an existing Standard licence to Pro." },
];

const STANDARD_FEATURES = [
  "Offline spelling, homophone, punctuation and capitalisation correction",
  "English variants: EN_GB, EN_US, EN_CA, EN_AU",
  "Custom dictionary, suggested words, CSV / JSON backup",
  "Double-Backspace undo",
  "12 months of app and lexicon updates",
];

const PRO_FEATURES = [
  "Everything in Standard",
  "Domain vocabulary packs",
  "Per-application profiles",
  "Text-expansion snippets with date / time macros",
  "Local AI and bring-your-own-key cloud AI (when published)",
  "Local typing insights",
];

export default function PricingPage() {
  const [currency, setCurrency] = useState<CurrencyPricing["code"]>("USD");
  const [scenario, setScenario] = useState<Scenario>("NEW");
  const p = PRICING_BY_CURRENCY[currency];

  const standardPrice = scenario === "RENEWAL" ? p.standardRenewal30PctOff : p.standardPrice;
  const proPrice =
    scenario === "RENEWAL" ? p.proRenewal30PctOff : scenario === "CROSSGRADE" ? p.crossGradeStandardToPro : p.proPrice;

  return (
    <div className="container-narrow pb-24 pt-16">
      <p className="eyebrow">Pricing</p>
      <h1 className="mt-3 text-3xl font-semibold tracking-tight text-zinc-50 sm:text-4xl">
        Pay once. Keep it.
      </h1>
      <p className="mt-3 max-w-2xl text-zinc-400">
        A perpetual licence for one platform with 12 months of updates. Every
        download starts with a free 14-day trial of Pro — no account needed.
        Licences are offline certificates; nothing phones home.
      </p>

      {/* Controls */}
      <div className="mt-8 flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-lg border border-zinc-800 p-0.5">
          {(Object.keys(PRICING_BY_CURRENCY) as CurrencyPricing["code"][]).map((code) => (
            <button
              key={code}
              type="button"
              onClick={() => setCurrency(code)}
              className={`rounded-md px-3 py-1.5 text-sm transition ${
                currency === code ? "bg-zinc-800 text-zinc-100" : "text-zinc-400 hover:text-zinc-100"
              }`}
            >
              {code}
            </button>
          ))}
        </div>
        <div className="inline-flex rounded-lg border border-zinc-800 p-0.5">
          {SCENARIOS.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => setScenario(s.id)}
              className={`rounded-md px-3 py-1.5 text-sm transition ${
                scenario === s.id ? "bg-zinc-800 text-zinc-100" : "text-zinc-400 hover:text-zinc-100"
              }`}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>
      <p className="mt-2 text-sm text-zinc-500">{SCENARIOS.find((s) => s.id === scenario)?.note}</p>

      {/* Plans */}
      <div className="mt-8 grid gap-4 sm:grid-cols-2">
        <div className="card p-6">
          <h2 className="font-medium text-zinc-100">Standard</h2>
          <p className="mt-4 text-3xl font-semibold text-zinc-50">
            {scenario === "CROSSGRADE" ? (
              <span className="text-lg text-zinc-500">n/a</span>
            ) : (
              <>
                {p.symbol}
                {standardPrice}
              </>
            )}
          </p>
          <p className="mt-1 text-sm text-zinc-500">one-time · {p.label}</p>
          <ul className="mt-6 space-y-2 text-sm text-zinc-300">
            {STANDARD_FEATURES.map((f) => (
              <li key={f} className="flex gap-2">
                <span className="text-zinc-600">—</span>
                <span>{f}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="card border-zinc-700 p-6">
          <div className="flex items-center justify-between">
            <h2 className="font-medium text-zinc-100">Pro</h2>
            <span className="text-xs text-zinc-500">Trial edition</span>
          </div>
          <p className="mt-4 text-3xl font-semibold text-zinc-50">
            {p.symbol}
            {proPrice}
          </p>
          <p className="mt-1 text-sm text-zinc-500">one-time · {p.label}</p>
          <ul className="mt-6 space-y-2 text-sm text-zinc-300">
            {PRO_FEATURES.map((f) => (
              <li key={f} className="flex gap-2">
                <span className="text-zinc-600">—</span>
                <span>{f}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="mt-10 flex flex-col gap-4 border-t border-zinc-800 pt-8 sm:flex-row sm:items-center sm:justify-between">
        <p className="max-w-xl text-sm text-zinc-400">
          Purchasing opens when the beta ends. Until then, download the beta and
          use every Pro feature free for 14 days.
        </p>
        <Link href="/download" className="btn-primary">
          Download the beta
        </Link>
      </div>
    </div>
  );
}
