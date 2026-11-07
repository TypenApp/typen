# Core Typing Engine, Suffix-Diff Replacement & Undo Mechanics

> **Core Architecture** · 6 min read  
> Deep dive into InputSessionManager, SuffixDiffPlanner, retroactive two-word homophone repair, sentence capitalisation, and deliberate double-Backspace undo.

## Contents

1. [Word Boundary Evaluation & Caret Invalidation](#word-boundary-evaluation)
2. [Flicker-Free Suffix-Diff Replacement (SuffixDiffPlanner)](#suffix-diff-planner)
3. [Retroactive Two-Word Homophone & Subject-Verb Repair](#retroactive-homophones-and-grammar)
4. [Deliberate Double-Backspace Undo & Suggested Dictionary Words](#double-backspace-undo)

---

<a id="word-boundary-evaluation"></a>
## Word Boundary Evaluation & Caret Invalidation

Unlike intrusive browser extensions that parse entire DOM trees on every keystroke, InputSessionManager maintains a tiny ephemeral ActiveWordBuffer and a 5-token ContextRingBuffer.

Whenever you click the mouse, press an arrow/navigation key (Left, Right, Home, End), or use any Ctrl/Alt/Cmd shortcut, the word buffer immediately transitions to BufferState.TAINTED. A tainted buffer never backspaces or mutates surrounding text until a clean word boundary restarts.

<a id="suffix-diff-planner"></a>
## Flicker-Free Suffix-Diff Replacement (SuffixDiffPlanner)

When replacing a misspelled token such as 'recieved ' with 'received ', SuffixDiffPlanner computes the longest common prefix ('rec', length 3) and only backspaces the diverging suffix ('ieved', 5 backspaces) before injecting 'eived ' in a single atomic OS input packet.

This eliminates visual caret jitter and prevents race conditions in fast electron, terminal, or rich-text editors.

**SuffixDiffPlanner Example (src/autocorrect/input/diff_planner.py)**

```python
plan = SuffixDiffPlanner.plan(
    original_full="recieved ",
    target_full="received ",
    delimiter_was_suppressed=True,
)
# plan.common_prefix_len == 3 ("rec")
# plan.backspaces_to_send == 5 ("ieved")
# plan.text_to_inject == "eived "
```

<a id="retroactive-homophones-and-grammar"></a>
## Retroactive Two-Word Homophone & Subject-Verb Repair

Some confusions cannot be resolved until the following word is completed. When you type 'your ' followed by 'welcome ', the engine evaluates the two-word bigram at the second word boundary and atomically transforms 'your welcome ' into 'you're welcome ' (preserving initial capitalisation).

Contextual grammar also repairs subject-verb agreement and plural determiners in real time: 'Raw eggs is best.' -> 'Raw eggs are best.', 'The dogs was barking.' -> 'The dogs were barking.', and 'I should of went home.' -> 'I should have gone home.' while guarding against false positives like 'One of the raw eggs is cracked.' or 'Physics is hard'.

<a id="double-backspace-undo"></a>
## Deliberate Double-Backspace Undo & Suggested Dictionary Words

A fast typist often presses a single Backspace subconsciously to delete a trailing space. Therefore, the first Backspace after an autocorrection is always a normal edit (deleting only the delimiter).

Pressing Backspace a second consecutive time triggers TransactionLedger.consume_for_reversal(), restoring your exact original token ('received' -> 'recieved') and arming a one-shot suppression for that token instance.

Crucially, reverting a word does NOT silently pollute your permanent dictionary. Instead, the reverted word is quietly noted in the 'Suggested Add to Dictionary Words' queue inside the Dictionary settings screen, so you can promote or dismiss it whenever convenient.

---

*Part of the [Typen Documentation](https://github.com/TypenApp/docs) · [Read on the web](https://typen.org/docs/core-engine) · [TypenApp on GitHub](https://github.com/TypenApp)*
