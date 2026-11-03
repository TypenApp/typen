"use client";

import React, { useState } from "react";
import Link from "next/link";
import { Check, Dash, PageHeader, Section } from "@/components/Page";
import { PRICING_BY_CURRENCY, type CurrencyPricing } from "@/data/releases";

type Scenario = "NEW" | "RENEWAL" | "CROSSGRADE";

const SCENARIOS: Array<{ id: Scenario; label: string; note: string }> = [
  { id: "NEW", label: "New licence", note: "Perpetual licence with 12 months of updates." },
  {
    id: "RENEWAL",
    label: "Renew updates",
    note: "Another 12 months of updates at 30% off. Your existing licence keeps working either way.",
  },
  {
    id: "CROSSGRADE",
    label: "Standard → Pro",
    note: "Pay only the difference to move an existing Standard licence to Pro.",
  },
];

const STANDARD_FEATURES = [
  "Offline spelling, homophone, punctuation and capitalisation correction",
  "English variants: EN_GB, EN_US, EN_CA, EN_AU",
  "Custom dictionary, suggested words, CSV / JSON backup",
  "Backspace-to-undo on every correction",
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

const FAQ: Array<[string, string]> = [
  [
    "What does “perpetual” mean here?",
    "The version you buy keeps working forever, on the device it is bound to. Buying includes 12 months of updates; after that you can keep using what you have or renew at 30% off.",
  ],
  [
    "How is a licence delivered?",
    "As an offline Ed25519 certificate bound to a hash of your device. The app verifies it locally; there is no account and no activation server to go down.",
  ],
  [
    "Is the trial limited?",
    "No. Every download runs Pro for 14 days with nothing disabled. When the trial ends you drop to the free Standard preview until you add a licence.",
  ],
  [
    "Can I move it to a new computer?",
    "Yes — reissue it from your order. A licence is for one platform; Windows, macOS and Linux are separate purchases.",
  ],
];

function Toggle<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: Array<{ id: T; label: string }>;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="inline-flex rounded-lg border border-line p-0.5" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          role="radio"
          aria-checked={value === o.id}
          onClick={() => onChange(o.id)}
          className={`rounded px-3 py-1.5 text-sm transition ${
            value === o.id ? "bg-ink-3 text-paper" : "text-paper-muted hover:text-paper"
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export default function PricingPage() {
  const [currency, setCurrency] = useState<CurrencyPricing["code"]>("USD");
  const [scenario, setScenario] = useState<Scenario>("NEW");
  const p = PRICING_BY_CURRENCY[currency];

  const standardPrice = scenario === "RENEWAL" ? p.standardRenewal30PctOff : p.standardPrice;
  const proPrice =
    scenario === "RENEWAL" ? p.proRenewal30PctOff : scenario === "CROSSGRADE" ? p.crossGradeStandardToPro : p.proPrice;

  return (
    <div className="pb-8">
      <PageHeader
        eyebrow="Pricing"
        title="Pay once. Keep it."
        lede={
          <p>
            A perpetual licence for one platform with 12 months of updates. Every download starts with a free
            14-day trial of Pro — no account needed. Licences are offline certificates; nothing phones home.
          </p>
        }
      />

      <div className="container-site">
        <div className="flex flex-wrap items-center gap-3">
          <Toggle
            label="Currency"
            value={currency}
            onChange={setCurrency}
            options={(Object.keys(PRICING_BY_CURRENCY) as CurrencyPricing["code"][]).map((c) => ({ id: c, label: c }))}
          />
          <Toggle label="Scenario" value={scenario} onChange={setScenario} options={SCENARIOS} />
        </div>
        <p className="mt-3 text-sm text-paper-faint">{SCENARIOS.find((s) => s.id === scenario)?.note}</p>

        <div className="mt-8 grid gap-4 md:grid-cols-2">
          <div className="card p-7">
            <p className="eyebrow">Standard</p>
            <p className="display mt-4 text-4xl">
              {scenario === "CROSSGRADE" ? (
                <span className="text-xl text-paper-faint">Not applicable</span>
              ) : (
                <>
                  <span className="text-2xl text-paper-muted">{p.symbol}</span>
                  {standardPrice}
                </>
              )}
            </p>
            <p className="mt-1 font-mono text-xs text-paper-faint">one-time · {p.label}</p>
            <ul className="mt-7 space-y-2.5">
              {STANDARD_FEATURES.map((f) => (
                <Dash key={f}>{f}</Dash>
              ))}
            </ul>
          </div>

          <div className="card relative border-line-strong p-7">
            <span className="absolute right-5 top-5 rounded-full border border-proof/50 px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider text-proof">
              Trial edition
            </span>
            <p className="eyebrow">Pro</p>
            <p className="display mt-4 text-4xl">
              <span className="text-2xl text-paper-muted">{p.symbol}</span>
              {proPrice}
            </p>
            <p className="mt-1 font-mono text-xs text-paper-faint">one-time · {p.label}</p>
            <ul className="mt-7 space-y-2.5">
              {PRO_FEATURES.map((f) => (
                <Check key={f}>{f}</Check>
              ))}
            </ul>
          </div>
        </div>

        <div className="card mt-6 flex flex-col gap-4 p-6 sm:flex-row sm:items-center sm:justify-between">
          <p className="max-w-xl text-sm leading-relaxed text-paper-muted">
            Purchasing opens when the beta ends. Until then, download the beta and use every Pro feature free
            for 14 days.
          </p>
          <Link href="/download" className="btn-primary shrink-0">
            Download the beta
          </Link>
        </div>
      </div>

      <Section index="01" title="Questions">
        <dl className="grid gap-x-10 gap-y-8 md:grid-cols-2">
          {FAQ.map(([q, a]) => (
            <div key={q}>
              <dt className="font-display text-lg text-paper">{q}</dt>
              <dd className="mt-2 text-sm leading-relaxed text-paper-muted">{a}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-10 text-sm text-paper-faint">
          Technical detail on licences, device binding and payments is in the{" "}
          <Link href="/docs/licensing" className="link">
            licensing documentation
          </Link>
          .
        </p>
      </Section>
    </div>
  );
}
