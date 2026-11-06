import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Typen

Page {
    id: page
    readonly property var corr: bridge.corrections
    readonly property var rejected: corr.rejected_corrections || []
    readonly property var preferred: corr.preferred_variants || []
    readonly property var s: bridge.settings

    PageHeader {
        number: "04"
        title: "Corrections"
        lead: "Every stage of the engine is a switch. Turn off what gets in your way; the rest keeps working."
    }

    Card {
        SectionTitle { title: "Spelling" }
        ToggleRow { key: "enable_spelling"; label: "Fix misspelled words"; description: "Typos, transpositions and common misspellings from the lexicon." }
        SliderRow {
            key: "aggressiveness"; label: "Sensitivity"; from: 0.5; to: 1.5; step: 0.05
            enabled: s.enable_spelling === true
            description: "Lower only fixes near-certain typos. Higher also takes on rarer or longer-distance mistakes."
            formatter: function (v) { return v < 0.75 ? "Cautious" : (v < 1.0 ? "Careful" : (v <= 1.05 ? "Balanced" : (v < 1.3 ? "Confident" : "Eager"))) }
        }
        SliderRow {
            key: "min_correction_length"; label: "Shortest word to correct"; from: 2; to: 12; step: 1; suffix: " letters"
            enabled: s.enable_spelling === true
            description: "Short words are ambiguous; leaving them alone avoids wrong guesses."
        }
        ToggleRow { key: "correct_all_caps"; label: "Correct ALL-CAPS words"; description: "Off by default: acronyms and shouting are usually deliberate."; enabled: s.enable_spelling === true }
        ToggleRow { key: "correct_titlecase_midsentence"; label: "Correct Capitalised words mid-sentence"; description: "Off by default so names are never touched."; enabled: s.enable_spelling === true }
        ToggleRow { key: "enable_confusion_sets"; label: "Fix sound-alike words from context"; description: "their / there / they're, its / it's, affect / effect." }
        ToggleRow { key: "enable_grammar"; label: "Light grammar"; description: "a / an before vowels, doubled words, and the like." }
        ToggleRow { key: "enable_retroactive"; label: "Look back one word"; description: "Re-check the previous word once the next one gives it context." }
    }

    Card {
        SectionTitle { title: "Capitalisation" }
        ToggleRow { key: "enable_auto_capitalise"; label: "Capitalise automatically" }
        ToggleRow { key: "cap_sentence"; label: "First word of a sentence"; indent: true; enabled: s.enable_auto_capitalise === true }
        ToggleRow { key: "cap_after_newline"; label: "First word after a new line"; indent: true; enabled: s.enable_auto_capitalise === true }
        ToggleRow { key: "cap_pronoun_i"; label: "The pronoun I"; indent: true; enabled: s.enable_auto_capitalise === true }
        ToggleRow { key: "cap_brands"; label: "Brand and product names"; description: "iPhone, GitHub, PowerShell…"; indent: true; enabled: s.enable_auto_capitalise === true }
        ToggleRow { key: "cap_double_initial"; label: "TWo INitial capitals"; description: "Fix the classic sticky-Shift slip."; indent: true; enabled: s.enable_auto_capitalise === true }
    }

    Card {
        SectionTitle { title: "Punctuation & spacing" }
        ToggleRow { key: "enable_punctuation_assist"; label: "Punctuation assistance" }
        ToggleRow {
            key: "enable_auto_space_after_sentence"; label: "Space after . ! ?"; indent: true
            description: "Typing the next word straight after a full stop inserts the space for you; a Space you type anyway is swallowed."
            enabled: s.enable_punctuation_assist === true
        }
        ToggleRow { key: "enable_double_space_period"; label: "Double space ends a sentence"; indent: true; enabled: s.enable_punctuation_assist === true }
        SliderRow {
            key: "double_space_interval_ms"; label: "Double-space window"; from: 300; to: 3000; step: 100; suffix: " ms"; indent: true
            enabled: s.enable_punctuation_assist === true && s.enable_double_space_period === true
        }
        ToggleRow { key: "enable_space_before_punct"; label: "Remove space before , . ; : ! ?"; indent: true; enabled: s.enable_punctuation_assist === true }
        ToggleRow { key: "enable_missing_space"; label: "Split run-together words"; description: "helloworld → hello world when both halves are words."; indent: true; enabled: s.enable_punctuation_assist === true }
        ToggleRow { key: "enable_contractions"; label: "Apostrophes in contractions"; description: "dont → don't, im → I'm."; indent: true; enabled: s.enable_punctuation_assist === true }
        ToggleRow { key: "smart_quotes"; label: "Curly quotes"; description: "Off by default; code and shells want straight quotes."; indent: true; enabled: s.enable_punctuation_assist === true }
    }

    Card {
        SectionTitle { title: "Undo"; description: "Backspace straight after a correction puts your original word back." }
        ToggleRow { key: "undo_enabled"; label: "Backspace undoes the last correction" }
        SliderRow { key: "undo_window_ms"; label: "Within"; from: 500; to: 5000; step: 250; suffix: " ms"; indent: true; enabled: s.undo_enabled === true }
        ChoiceRow {
            key: "undo_remembers"; label: "After an undo, leave that word alone"; indent: true
            enabled: s.undo_enabled === true
            options: [{ value: "never", label: "Just once" }, { value: "session", label: "This session" }, { value: "always", label: "Always" }]
        }
    }

    Card {
        SectionTitle { title: "Never change these"; description: "Corrections you have rejected. Typen will not make them again." }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Field { id: rejOrig; Layout.fillWidth: true; placeholderText: "typed word" }
            Body { text: "→" }
            Field { id: rejCand; Layout.fillWidth: true; placeholderText: "correction to block" }
            SecondaryButton {
                text: "Block"
                enabled: rejOrig.text.trim() !== "" && rejCand.text.trim() !== ""
                onClicked: { bridge.call("add_rejected_correction", JSON.stringify({ original: rejOrig.text.trim(), candidate: rejCand.text.trim() })); rejOrig.text = ""; rejCand.text = "" }
            }
        }
        EmptyNote { visible: page.rejected.length === 0; text: "Nothing blocked yet. Undoing a correction twice adds it here automatically when 'Always' is chosen above." }
        Repeater {
            model: page.rejected
            ListRow {
                primary: modelData.original + "  →  " + modelData.candidate
                GhostButton { text: "Allow again"; onClicked: bridge.call("remove_rejected_correction", JSON.stringify({ original: modelData.original, candidate: modelData.candidate })) }
            }
        }
    }

    Card {
        SectionTitle { title: "Preferred variants"; description: "When a word has more than one accepted spelling, always use yours." }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Field { id: varSrc; Layout.fillWidth: true; placeholderText: "e.g. grey" }
            Body { text: "→" }
            Field { id: varPref; Layout.fillWidth: true; placeholderText: "e.g. gray" }
            SecondaryButton {
                text: "Prefer"
                enabled: varSrc.text.trim() !== "" && varPref.text.trim() !== ""
                onClicked: { bridge.call("set_preferred_variant", JSON.stringify({ source: varSrc.text.trim(), preferred: varPref.text.trim() })); varSrc.text = ""; varPref.text = "" }
            }
        }
        EmptyNote { visible: page.preferred.length === 0; text: "No preferred variants yet." }
        Repeater {
            model: page.preferred
            ListRow {
                primary: modelData.source + "  →  " + modelData.preferred
                GhostButton { text: "Remove"; onClicked: bridge.call("remove_preferred_variant", JSON.stringify({ source: modelData.source })) }
            }
        }
    }
}
