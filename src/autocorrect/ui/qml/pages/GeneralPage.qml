import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Typen

Page {
    id: page
    readonly property var gen: bridge.general

    PageHeader {
        number: "02"
        title: "General"
        lead: "How Typen behaves as an app: startup, shortcuts, the Esc switch, notifications and privacy."
    }

    Card {
        SectionTitle { title: "Startup" }
        ToggleRow { key: "launch_at_login"; label: "Launch at login"; description: "Start Typen when you sign in to Windows." }
        ToggleRow { key: "start_paused"; label: "Start paused"; description: "Come up listening but not correcting until you resume." }
        ToggleRow { key: "show_tray_icon"; label: "Show the tray icon"; description: "The icon blinks red on each correction and is the quickest way to pause." }
    }

    Card {
        SectionTitle { title: "Shortcuts"; description: "Click a field, then press the new combination. Esc cancels." }
        SettingRow { label: "Pause or resume"; HotkeyField { key: "pause_hotkey" } }
        SettingRow { label: "Open Typen"; HotkeyField { key: "settings_hotkey" } }
    }

    Card {
        SectionTitle {
            title: "Esc switch"
            description: "Holding Esc is the panic button that always works, even when a shortcut is taken by another app."
        }
        ToggleRow { key: "panic_hotkey_enabled"; label: "Hold Esc to pause"; enabled: gen.panic_hotkey_supported !== false }
        SliderRow {
            key: "panic_hold_seconds"; label: "Hold for"; from: 5; to: 60; step: 1; suffix: " s"
            enabled: bridge.settings.panic_hotkey_enabled === true
            description: "Long enough that a few quick Escs in a game or editor never trip it."
        }
        ToggleRow {
            key: "panic_toggles_resume"; label: "Holding Esc also resumes"; indent: true
            enabled: bridge.settings.panic_hotkey_enabled === true
        }
        Body {
            visible: gen.panic_hotkey_supported === false
            text: "The Esc switch is not available on this platform."
            color: Theme.proof
        }
    }

    Card {
        SectionTitle { title: "Notifications"; description: "Each one can be turned off on its own." }
        ToggleRow { key: "tray_pulse_on_correction"; label: "Blink the tray icon on each correction" }
        ToggleRow { key: "notify_first_correction"; label: "Confirm the very first correction with a toast" }
        ToggleRow { key: "notify_pause_resume"; label: "Toast when paused or resumed" }
        ToggleRow { key: "notify_suggested_word"; label: "Toast when a word becomes a dictionary suggestion" }
    }

    Card {
        SectionTitle { title: "Appearance" }
        ChoiceRow {
            key: "ui_theme"; label: "Theme"
            options: [{ value: "system", label: "Follow system" }, { value: "light", label: "Light" }, { value: "dark", label: "Dark" }]
        }
    }

    Card {
        SectionTitle { title: "Privacy"; description: "Typen works entirely on this computer. Nothing you type is stored or sent anywhere." }
        ToggleRow { key: "insights_enabled"; label: "Keep typing insights"; description: "Aggregate counters only: corrections made, keystrokes saved." }
        ChoiceRow {
            key: "insights_retention_days"; label: "Keep insights for"; indent: true
            enabled: bridge.settings.insights_enabled === true
            options: [{ value: "0", label: "This session" }, { value: "7", label: "7 days" }, { value: "30", label: "30 days" }]
        }
        ChoiceRow {
            key: "log_level"; label: "Log level"
            description: "Verbose logs help with bug reports; they still never contain typed text."
            options: [{ value: "off", label: "Off" }, { value: "errors", label: "Errors" }, { value: "verbose", label: "Verbose" }]
        }
        Divider {}
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            SecondaryButton { text: "Open data folder"; onClicked: bridge.openDataFolder() }
            Item { Layout.fillWidth: true }
            PrimaryButton {
                danger: true
                text: wipeConfirm.visible ? "Yes, erase everything" : "Erase all local data"
                onClicked: {
                    if (wipeConfirm.visible) { bridge.call("privacy_wipe", "{}"); wipeConfirm.visible = false }
                    else wipeConfirm.visible = true
                }
            }
            GhostButton { id: wipeConfirm; visible: false; text: "Cancel"; onClicked: visible = false }
        }
        Body {
            visible: wipeConfirm.visible
            text: "This removes your custom dictionary, suggestions, profiles, snippets, insights and every setting. It cannot be undone."
            color: Theme.proof
        }
    }

    Card {
        SectionTitle { title: "Updates" }
        ToggleRow { key: "updates_check_on_launch"; label: "Check for updates on launch" }
        ToggleRow { key: "updates_auto_language_data"; label: "Download language data automatically"; description: "Word lists and typo tables, signed and verified before use." }
        ChoiceRow {
            key: "update_channel"; label: "Channel"
            options: [{ value: "stable", label: "Stable" }, { value: "beta", label: "Beta" }]
        }
    }
}
