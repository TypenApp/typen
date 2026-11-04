# AI: Layer 2 Local Models & Layer 3 BYOK Cloud AI

> **Features** · 6 min read  
> Hardware-aware local ONNX/GGUF sentence analysis (400ms Pause Pill & Ctrl+Shift+R hotkey) and consent-gated BYOK Cloud AI with hard USD spending limits.

## Contents

1. [The 3-Layer Intelligence Hierarchy](#three-layer-intelligence)
2. [Layer 2 Hardware Detection & Idle Unloading](#layer2-hardware-selection)
3. [Layer 3 BYOK Consent, OS Keyring & Spending Circuit Breakers](#layer3-byok-guardrails)

---

<a id="three-layer-intelligence"></a>
## The 3-Layer Intelligence Hierarchy

Typen strictly separates real-time keystroke correction from heavy neural inference so typing latency never degrades:

- Layer 1 (Always-On, < 0.4ms): Deterministic mmap Lexicon + SymSpell + Trigram Context Model + Confusion Sets.
- Layer 2 (Local AI, On-Device): Hardware-aware quantized ONNX/GGUF sentence grammar engine triggered ONLY after a >= 400ms pause at a sentence boundary (non-focus-stealing Pause Pill) or via explicit Ctrl+Shift+R hotkey.
- Layer 3 (BYOK Cloud AI, Explicit Invocation Only): Direct HTTPS calls to OpenAI, Anthropic, Gemini, or custom OpenAI-compatible endpoints using your own API key stored in OS Keyring.

<a id="layer2-hardware-selection"></a>
## Layer 2 Hardware Detection & Idle Unloading

LocalModelManager.detect_hardware_profile() inspects CPU cores, system RAM, and platform accelerators (DirectML on Windows, CoreML on macOS, CPU-AVX2 on Linux) to recommend 'rewrite-gguf-q4-360m' (>= 16 GB RAM, 8+ cores) or 'grammar-onnx-int8-small' (>= 4 GB RAM).

To preserve system memory, if no sentence evaluation occurs for 300 seconds (MODEL_IDLE_UNLOAD_SECONDS), the local model automatically unloads from RAM until needed again.

<a id="layer3-byok-guardrails"></a>
## Layer 3 BYOK Consent, OS Keyring & Spending Circuit Breakers

Cloud AI is never invoked during ordinary background typing. Even when explicitly invoked, BYOKProviderManager enforces four mandatory guardrails:

- 1. OS Keyring Storage: API keys are stored in Windows Credential Locker or macOS Keychain via keyring and scrubbed from all logs by SecretRedactingFilter.
- 2. Explicit Transmission Disclosure & Consent: Requires user_consented=True or global consent opt-in before a single byte leaves the machine.
- 3. Local-Only Lockdown Switch: A master circuit breaker in SpendingController that blocks all outbound AI network calls with LocalOnlyLockdownError.
- 4. Hard Daily & Monthly USD Spend Caps: UsageTracker logs token counts (never prompt text) in ai_usage.sqlite3 and halts requests once daily ($2.00 default) or monthly ($15.00 default) limits are reached.

---

*Part of the [Typen Documentation](https://github.com/TypenApp/docs) · [Read on the web](https://autocorrect-desktop.vercel.app/docs/ai-intelligence) · [TypenApp on GitHub](https://github.com/TypenApp)*
