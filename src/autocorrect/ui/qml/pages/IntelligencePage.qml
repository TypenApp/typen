import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Typen

Page {
    id: page
    readonly property var ai: bridge.ai
    readonly property var local: ai.local_ai || {}
    readonly property var byok: ai.byok || {}
    readonly property var providers: byok.providers || {}
    readonly property var usage: byok.usage_30d || {}
    readonly property var providerList: [
        { id: "openai", name: "OpenAI", models: ["gpt-4o-mini", "gpt-4o"] },
        { id: "anthropic", name: "Anthropic", models: ["claude-3-5-haiku-latest", "claude-3-5-sonnet-latest"] },
        { id: "gemini", name: "Gemini", models: ["gemini-2.0-flash", "gemini-1.5-pro"] },
        { id: "custom_openai", name: "OpenAI-compatible", models: ["default"] }
    ]

    function updateAi(obj) { bridge.call("update_ai_settings", JSON.stringify(obj)) }

    PageHeader {
        number: "08"
        title: "Intelligence"
        lead: "Everything on the other pages runs locally with no model at all. These are the optional extras."
    }

    Card {
        SectionTitle { title: "On-device model"; description: "A small language model for context-aware rewrites. It runs entirely on this computer." }
        RowLayout {
            Layout.fillWidth: true
            spacing: 28
            Repeater {
                model: [
                    { k: "CPU cores", v: String(local.cpu_cores || "—") },
                    { k: "Memory", v: local.total_ram_mb ? Math.round(local.total_ram_mb / 1024) + " GB" : "—" },
                    { k: "Accelerator", v: String(local.accelerator || "cpu") },
                    { k: "Recommended", v: String(local.recommended_model_id || "—") }
                ]
                ColumnLayout {
                    spacing: 2
                    Eyebrow { label: modelData.k }
                    Text { text: modelData.v; color: Theme.ink; font.family: Theme.mono; font.pixelSize: Theme.fsSmall }
                }
            }
            Item { Layout.fillWidth: true }
            Pill { label: local.model_loaded ? "loaded" : "not loaded"; tone: local.model_loaded ? "ok" : "muted" }
        }
        RowLayout {
            Layout.fillWidth: true
            SettingRow { label: "Rewrite shortcut"; description: "Select text and press it to rewrite with the model."; Layout.fillWidth: true; HotkeyField { key: "rewrite_hotkey" } }
        }
        RowLayout {
            Layout.fillWidth: true
            Item { Layout.fillWidth: true }
            SecondaryButton { visible: !local.model_loaded; text: "Load model"; onClicked: page.updateAi({ load_local_model: true }) }
            GhostButton { visible: local.model_loaded === true; text: "Unload"; onClicked: page.updateAi({ unload_local_model: true }) }
        }
        SettingRow {
            label: "Pause pill"
            description: "A small floating pill while the model is thinking so you know why text is changing."
            Toggle { checked: local.pause_pill_enabled === true; onToggled: page.updateAi({ pause_pill_enabled: checked }) }
        }
    }

    Card {
        SectionTitle { title: "Cloud models (bring your own key)"; description: "Off unless you turn it on. Keys stay in the Windows credential store; only the selected text is ever sent." }
        SettingRow {
            label: "Local only"
            description: "Hard block: nothing leaves this computer, even if a key is set."
            Toggle { checked: byok.local_only_mode === true; onToggled: page.updateAi({ local_only_mode: checked }) }
        }
        SettingRow {
            label: "Allow cloud requests"
            enabled: byok.local_only_mode !== true
            Toggle { checked: byok.global_cloud_consent === true; enabled: byok.local_only_mode !== true; onToggled: page.updateAi({ global_cloud_consent: checked }) }
        }
        Divider {}
        Eyebrow { label: "Provider" }
        Choice {
            options: page.providerList.map(function (p) { return { value: p.id, label: p.name + (page.providers[p.id] && page.providers[p.id].has_key ? " ✓" : "") } })
            value: byok.active_provider || "openai"
            onPicked: function (v) {
                var p = page.providerList.filter(function (x) { return x.id === v })[0]
                page.updateAi({ active_provider: v, active_model: p ? p.models[0] : undefined })
            }
        }
        Eyebrow { label: "Model" }
        Choice {
            readonly property var cur: page.providerList.filter(function (x) { return x.id === (byok.active_provider || "openai") })[0]
            options: cur ? cur.models : []
            value: byok.active_model || ""
            onPicked: function (v) { page.updateAi({ active_model: v }) }
        }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Field {
                id: keyField
                Layout.fillWidth: true
                echoMode: TextInput.Password
                placeholderText: page.providers[byok.active_provider] && page.providers[byok.active_provider].has_key ? "Key saved — paste a new one to replace it" : "Paste API key"
            }
            PrimaryButton {
                text: "Save key"
                enabled: keyField.text.trim() !== ""
                onClicked: { bridge.call("set_byok_api_key", JSON.stringify({ provider: byok.active_provider || "openai", api_key: keyField.text.trim() })); keyField.text = "" }
            }
            GhostButton {
                text: "Remove"
                visible: page.providers[byok.active_provider] && page.providers[byok.active_provider].has_key
                onClicked: bridge.call("set_byok_api_key", JSON.stringify({ provider: byok.active_provider || "openai", api_key: "" }))
            }
        }
        Divider {}
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            ColumnLayout {
                spacing: 4
                Eyebrow { label: "Daily limit (USD)" }
                Field { id: daily; implicitWidth: 120; text: String(byok.daily_limit_usd || "2.00"); onEditingFinished: if (text !== String(byok.daily_limit_usd)) page.updateAi({ daily_limit_usd: text }) }
            }
            ColumnLayout {
                spacing: 4
                Eyebrow { label: "Monthly limit (USD)" }
                Field { id: monthly; implicitWidth: 120; text: String(byok.monthly_limit_usd || "15.00"); onEditingFinished: if (text !== String(byok.monthly_limit_usd)) page.updateAi({ monthly_limit_usd: text }) }
            }
            Item { Layout.fillWidth: true }
            ColumnLayout {
                spacing: 2
                Eyebrow { label: "Last 30 days" }
                Text {
                    text: (usage.requests || 0) + " requests  ·  $" + Number(usage.estimated_cost_usd || 0).toFixed(2)
                    color: Theme.ink; font.family: Theme.mono; font.pixelSize: Theme.fsSmall
                }
            }
        }
    }
}
