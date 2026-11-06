import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Typen

Page {
    id: page
    readonly property var apps: bridge.apps
    readonly property var profiles: apps.profiles || []
    readonly property var excluded: apps.excluded_processes || []
    readonly property var codeApps: apps.code_processes || []
    readonly property var running: apps.running_apps || []
    readonly property var overridable: apps.schema || []
    readonly property var packs: (bridge.languages.domain_packs) || []

    // Editor state -----------------------------------------------------------
    property var editing: null          // profile dict being edited, or null
    property bool editorOpen: false

    function normalise(p) { return String(p || "").trim().toLowerCase() }
    function listWithout(list, item) { return list.filter(function (x) { return x !== item }) }

    function excludeProcess(proc) {
        proc = normalise(proc)
        if (proc === "" || excluded.indexOf(proc) >= 0) return
        bridge.setSetting("excluded_processes", excluded.concat([proc]))
    }
    function markCode(proc) {
        proc = normalise(proc)
        if (proc === "" || codeApps.indexOf(proc) >= 0) return
        bridge.setSetting("code_processes", codeApps.concat([proc]))
    }
    function newProfile(proc, title) {
        editing = {
            app_identifier: normalise(proc), display_name: title || proc, enabled: true,
            enable_punctuation_assist: true, enable_double_space_period: true, enable_auto_capitalise: true,
            enable_auto_space_after_sentence: true, aggressiveness: 1.0, active_domain_packs: [], region: "", overrides: {}
        }
        editorOpen = true
    }
    function editProfile(p) { editing = JSON.parse(JSON.stringify(p)); editorOpen = true }
    function saveProfile() {
        if (!editing || normalise(editing.app_identifier) === "") return
        var payload = JSON.parse(JSON.stringify(editing))
        payload.app_identifier = normalise(payload.app_identifier)
        if (!payload.display_name) payload.display_name = payload.app_identifier
        bridge.call("upsert_app_profile", JSON.stringify(payload))
        editorOpen = false; editing = null
    }
    function setOverride(key, value) {
        var e = JSON.parse(JSON.stringify(editing))
        if (["enable_punctuation_assist", "enable_double_space_period", "enable_auto_capitalise", "enable_auto_space_after_sentence", "aggressiveness"].indexOf(key) >= 0) e[key] = value
        else if (value === null || value === undefined) delete e.overrides[key]
        else e.overrides[key] = value
        editing = e
    }
    function overrideValue(key) {
        if (!editing) return undefined
        if (key in editing && key !== "overrides") return editing[key]
        return editing.overrides ? editing.overrides[key] : undefined
    }
    function prettyKey(k) { return k.replace(/^enable_|^cap_/, "").replace(/_/g, " ") }

    PageHeader {
        number: "06"
        title: "Apps"
        lead: "Where Typen should stay out of the way, which windows are code, and per-app behaviour."
    }

    // --- Running windows ------------------------------------------------------
    Card {
        RowLayout {
            Layout.fillWidth: true
            SectionTitle {
                title: "Open windows"
                description: bridge.ipcConnected ? "Pick a window to exclude it, treat it as code, or give it its own profile." : "Start Typen to see the windows that are open."
                Layout.fillWidth: true
            }
            GhostButton { text: "Refresh"; onClicked: bridge.refresh() }
        }
        EmptyNote { visible: page.running.length === 0; text: bridge.ipcConnected ? "No other windows right now." : "Not connected to the background service." }
        Repeater {
            model: page.running.slice(0, 14)
            ListRow {
                primary: modelData.title || modelData.process
                secondary: modelData.process + (page.excluded.indexOf(modelData.process) >= 0 ? "  ·  excluded" : "") + (page.codeApps.indexOf(modelData.process) >= 0 ? "  ·  code" : "")
                mono: false
                GhostButton { text: "Exclude"; visible: page.excluded.indexOf(modelData.process) < 0; onClicked: page.excludeProcess(modelData.process) }
                GhostButton { text: "Code"; visible: page.codeApps.indexOf(modelData.process) < 0; onClicked: page.markCode(modelData.process) }
                GhostButton { text: "Profile"; onClicked: page.newProfile(modelData.process, modelData.title) }
            }
        }
    }

    // --- Excluded ---------------------------------------------------------------
    Card {
        SectionTitle { title: "Excluded apps"; description: "Typen does nothing at all in these. Password managers, games and terminals are the usual candidates." }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Field { id: exclField; Layout.fillWidth: true; placeholderText: "process name, e.g. keepass.exe"; onAccepted: { page.excludeProcess(text); text = "" } }
            SecondaryButton { text: "Exclude"; enabled: exclField.text.trim() !== ""; onClicked: { page.excludeProcess(exclField.text); exclField.text = "" } }
        }
        EmptyNote { visible: page.excluded.length === 0; text: "Nothing excluded. Password fields are always skipped regardless." }
        Flow {
            Layout.fillWidth: true
            spacing: 6
            visible: page.excluded.length > 0
            Repeater {
                model: page.excluded
                Rectangle {
                    height: 28; width: exRow.implicitWidth + 16; radius: 14
                    color: Theme.paper1; border.color: Theme.line
                    RowLayout {
                        id: exRow; anchors.centerIn: parent; spacing: 6
                        Text { text: modelData; color: Theme.ink; font.family: Theme.mono; font.pixelSize: Theme.fsSmall }
                        Text { text: "×"; color: exDel.hovered ? Theme.proof : Theme.inkFaint; font.pixelSize: 14
                               HoverHandler { id: exDel }
                               TapHandler { onTapped: bridge.setSetting("excluded_processes", page.listWithout(page.excluded, modelData)) } }
                    }
                }
            }
        }
    }

    // --- Code apps -------------------------------------------------------------
    Card {
        SectionTitle { title: "Code and terminals"; description: "Treated like an editor: spelling off, no smart quotes, no sentence capitals. Common editors and shells are detected automatically." }
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Field { id: codeField; Layout.fillWidth: true; placeholderText: "process name, e.g. zed.exe"; onAccepted: { page.markCode(text); text = "" } }
            SecondaryButton { text: "Add"; enabled: codeField.text.trim() !== ""; onClicked: { page.markCode(codeField.text); codeField.text = "" } }
        }
        EmptyNote { visible: page.codeApps.length === 0; text: "No extra code apps. VS Code, Cursor, Windows Terminal, JetBrains IDEs and PowerShell are built in." }
        Flow {
            Layout.fillWidth: true
            spacing: 6
            visible: page.codeApps.length > 0
            Repeater {
                model: page.codeApps
                Rectangle {
                    height: 28; width: cdRow.implicitWidth + 16; radius: 14
                    color: Theme.paper1; border.color: Theme.line
                    RowLayout {
                        id: cdRow; anchors.centerIn: parent; spacing: 6
                        Text { text: modelData; color: Theme.ink; font.family: Theme.mono; font.pixelSize: Theme.fsSmall }
                        Text { text: "×"; color: cdDel.hovered ? Theme.proof : Theme.inkFaint; font.pixelSize: 14
                               HoverHandler { id: cdDel }
                               TapHandler { onTapped: bridge.setSetting("code_processes", page.listWithout(page.codeApps, modelData)) } }
                    }
                }
            }
        }
        ToggleRow { key: "browser_url_rules"; label: "Treat web editors as code"; description: "GitHub, GitLab, Codespaces, CodePen and similar tabs in Chrome, Edge and Firefox." }
    }

    // --- Profiles ----------------------------------------------------------------
    Card {
        RowLayout {
            Layout.fillWidth: true
            SectionTitle { title: "Per-app profiles"; description: "Different behaviour in different apps: a gentler Typen in chat, US spelling in one client, no capitals in another."; Layout.fillWidth: true }
            PrimaryButton { text: "New profile"; onClicked: page.newProfile("", "") }
        }
        EmptyNote { visible: page.profiles.length === 0 && !page.editorOpen; text: "No profiles yet. Global settings apply everywhere." }
        Repeater {
            model: page.profiles
            ListRow {
                primary: modelData.display_name || modelData.app_identifier
                secondary: modelData.app_identifier + (modelData.enabled ? "" : "  ·  disabled") + (modelData.region ? "  ·  " + String(modelData.region).replace("_", "-") : "")
                Toggle {
                    checked: modelData.enabled === true
                    onToggled: { var p = JSON.parse(JSON.stringify(modelData)); p.enabled = checked; bridge.call("upsert_app_profile", JSON.stringify(p)) }
                }
                GhostButton { text: "Edit"; onClicked: page.editProfile(modelData) }
                GhostButton { text: "Delete"; danger: true; onClicked: bridge.call("delete_app_profile", JSON.stringify({ app_identifier: modelData.app_identifier })) }
            }
        }

        // Inline editor
        Rectangle {
            visible: page.editorOpen && page.editing !== null
            Layout.fillWidth: true
            Layout.topMargin: 8
            implicitHeight: editorCol.implicitHeight + 32
            radius: Theme.radius
            color: Theme.paper1
            border.color: Theme.lineStrong
            ColumnLayout {
                id: editorCol
                anchors.fill: parent
                anchors.margins: 16
                spacing: 12
                Eyebrow { label: page.editing && page.profiles.some(function (p) { return p.app_identifier === page.normalise(page.editing.app_identifier) }) ? "Edit profile" : "New profile" }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Eyebrow { label: "Process" }
                        Field {
                            Layout.fillWidth: true
                            placeholderText: "slack.exe"
                            text: page.editing ? page.editing.app_identifier : ""
                            onTextEdited: { var e = page.editing; e.app_identifier = text; page.editing = e }
                        }
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 4
                        Eyebrow { label: "Name" }
                        Field {
                            Layout.fillWidth: true
                            placeholderText: "Slack"
                            text: page.editing ? page.editing.display_name : ""
                            onTextEdited: { var e = page.editing; e.display_name = text; page.editing = e }
                        }
                    }
                }
                Eyebrow { label: "Language in this app" }
                Choice {
                    options: [{ value: "", label: "Global" }, { value: "EN_GB", label: "UK" }, { value: "EN_US", label: "US" }, { value: "EN_CA", label: "CA" }, { value: "EN_AU", label: "AU" }, { value: "UNIVERSAL", label: "Universal" }]
                    value: page.editing ? page.editing.region : ""
                    onPicked: function (v) { var e = page.editing; e.region = v; page.editing = e }
                }
                Eyebrow { label: "Sensitivity" }
                RowLayout {
                    Layout.fillWidth: true
                    Slider {
                        id: aggr
                        Layout.fillWidth: true
                        from: 0.5; to: 1.5; stepSize: 0.05
                        value: page.editing ? Number(page.editing.aggressiveness) : 1.0
                        onMoved: page.setOverride("aggressiveness", Math.round(value * 100) / 100)
                    }
                    Text { text: aggr.value.toFixed(2); color: Theme.inkMuted; font.family: Theme.mono; font.pixelSize: Theme.fsSmall }
                }
                Eyebrow { label: "Behaviour in this app" }
                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    columnSpacing: 24
                    rowSpacing: 4
                    Repeater {
                        model: page.overridable.filter(function (spec) { return spec.type === "bool" })
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 8
                            readonly property var cur: page.overrideValue(modelData.key)
                            readonly property bool isSet: cur !== undefined && cur !== null
                            Text {
                                text: modelData.label || page.prettyKey(modelData.key)
                                color: isSet ? Theme.ink : Theme.inkMuted
                                font.family: Theme.sans; font.pixelSize: Theme.fsSmall
                                Layout.fillWidth: true
                                elide: Text.ElideRight
                            }
                            Choice {
                                options: [{ value: null, label: "Global" }, { value: true, label: "On" }, { value: false, label: "Off" }]
                                value: isSet ? cur : null
                                onPicked: function (v) { page.setOverride(modelData.key, v) }
                            }
                        }
                    }
                }
                Eyebrow { label: "Extra vocabulary in this app"; visible: page.packs.length > 0 }
                Flow {
                    Layout.fillWidth: true
                    spacing: 6
                    visible: page.packs.length > 0
                    Repeater {
                        model: page.packs
                        SecondaryButton {
                            readonly property bool on: page.editing && (page.editing.active_domain_packs || []).indexOf(modelData.id) >= 0
                            text: modelData.name
                            active: on
                            onClicked: {
                                var e = page.editing
                                var list = (e.active_domain_packs || []).filter(function (x) { return x !== modelData.id })
                                if (!on) list.push(modelData.id)
                                e.active_domain_packs = list
                                page.editing = e
                            }
                        }
                    }
                }
                RowLayout {
                    Layout.fillWidth: true
                    Item { Layout.fillWidth: true }
                    GhostButton { text: "Cancel"; onClicked: { page.editorOpen = false; page.editing = null } }
                    PrimaryButton { text: "Save profile"; enabled: page.editing && page.normalise(page.editing.app_identifier) !== ""; onClicked: page.saveProfile() }
                }
            }
        }
    }
}
