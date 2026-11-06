# Productivity: Snippets, Domain Packs & App Profiles

> **Features** · 5 min read  
> Expand text snippets with dynamic date/time macros, enable the 6 specialized domain vocabulary packs, and tailor typing behaviour per application.

## Contents

1. [Text Expansion Snippets & Dynamic Macros](#snippet-engine)
2. [6 Bundled Domain Vocabulary Packs](#domain-vocabulary-packs)
3. [Per-Application Typing Profiles](#app-profiles)

---

<a id="snippet-engine"></a>
## Text Expansion Snippets & Dynamic Macros

SnippetEngine (src/autocorrect/productivity/snippet_engine.py) matches prefix-triggered or word-boundary shortcuts in O(1) time before standard lexical evaluation.

Triggers can begin with prefix symbols such as ';' or '@' (e.g. ';sig', ';addr', '@@email') and support automatic UTC/local template interpolation via {{date}} and {{time}}.

**Example Snippet Definitions**

```json
[
  {
    "trigger": ";sig",
    "expansion": "Best regards,
the Typen team",
    "description": "Standard email sign-off"
  },
  {
    "trigger": ";stamp",
    "expansion": "Reviewed on {{date}} at {{time}} UTC",
    "description": "Audit timestamp macro"
  }
]
```

<a id="domain-vocabulary-packs"></a>
## 6 Bundled Domain Vocabulary Packs

Domain packs overlay specialized terminology and domain-specific direct typo tables onto the active ResourceBundle without bloating baseline memory:

- programming.pack.json: Kubernetes, PostgreSQL, idempotency, kubectl, GraphQL, PySide6.
- medicine.pack.json: arrhythmia, pharmacokinetics, ophthalmology, cholecystectomy.
- finance.pack.json: reconciliation, amortisation, EBITDA, fiduciary, derivatives.
- law.pack.json: jurisprudence, indemnification, affidavit, estoppel, habeas.
- business.pack.json: deliverables, stakeholder, procurement, omni-channel.
- academic.pack.json: epistemology, historiography, econometrics, longitudinal.

<a id="app-profiles"></a>
## Per-Application Typing Profiles

ApplicationProfileManager automatically adapts correction behaviour when you switch windows. For example, in Visual Studio Code (code.exe), punctuation assistance, double-space periods, and auto-capitalisation are disabled while the 'programming' domain pack is active. In Microsoft Word (winword.exe), full prose assistance and the 'business' + 'academic' packs are enabled.

---

*Part of the [Typen Documentation](https://github.com/TypenApp/docs) · [Read on the web](https://autocorrect-desktop-six.vercel.app/docs/productivity) · [TypenApp on GitHub](https://github.com/TypenApp)*
