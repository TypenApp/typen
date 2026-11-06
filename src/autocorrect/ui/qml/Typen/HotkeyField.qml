import QtQuick
import QtQuick.Controls

// Key-capture field: click, press a chord, done. Writes "Ctrl+Alt+P" style strings.
Rectangle {
    id: hk
    property string key: ""
    property string value: key !== "" ? String(bridge.settings[key] || "") : ""
    property bool capturing: false
    signal captured(string chord)

    implicitWidth: 170
    implicitHeight: Theme.controlHeight
    radius: Theme.radiusSm
    color: capturing ? Theme.proofSoft : Theme.paper
    border.color: capturing ? Theme.proof : Theme.line
    border.width: 1

    Text {
        anchors.centerIn: parent
        text: hk.capturing ? "Press a shortcut…" : (hk.value || "Not set")
        color: hk.capturing ? Theme.proof : (hk.value ? Theme.ink : Theme.inkFaint)
        font.family: Theme.mono
        font.pixelSize: Theme.fsSmall
    }

    MouseArea {
        anchors.fill: parent
        cursorShape: Qt.PointingHandCursor
        onClicked: { hk.capturing = true; hk.forceActiveFocus() }
    }

    focus: true
    Keys.onPressed: function (event) {
        if (!hk.capturing) return
        event.accepted = true
        if (event.key === Qt.Key_Escape) { hk.capturing = false; return }
        var isMod = event.key === Qt.Key_Control || event.key === Qt.Key_Shift || event.key === Qt.Key_Alt || event.key === Qt.Key_Meta
        if (isMod) return
        var parts = []
        if (event.modifiers & Qt.ControlModifier) parts.push("Ctrl")
        if (event.modifiers & Qt.AltModifier) parts.push("Alt")
        if (event.modifiers & Qt.ShiftModifier) parts.push("Shift")
        if (event.modifiers & Qt.MetaModifier) parts.push(Qt.platform.os === "windows" ? "Win" : "Cmd")
        if (parts.length === 0) return   // a bare key is not a global hotkey
        var name = event.text && event.text.trim() !== "" && event.key < 0x01000000 ? event.text.toUpperCase() : keyName(event.key)
        if (name === "") return
        parts.push(name)
        var chord = parts.join("+")
        hk.capturing = false
        if (hk.key !== "") bridge.setSetting(hk.key, chord)
        hk.captured(chord)
    }
    onActiveFocusChanged: if (!activeFocus) capturing = false

    function keyName(k) {
        var names = {}
        names[Qt.Key_F1] = "F1"; names[Qt.Key_F2] = "F2"; names[Qt.Key_F3] = "F3"; names[Qt.Key_F4] = "F4"
        names[Qt.Key_F5] = "F5"; names[Qt.Key_F6] = "F6"; names[Qt.Key_F7] = "F7"; names[Qt.Key_F8] = "F8"
        names[Qt.Key_F9] = "F9"; names[Qt.Key_F10] = "F10"; names[Qt.Key_F11] = "F11"; names[Qt.Key_F12] = "F12"
        names[Qt.Key_Space] = "Space"; names[Qt.Key_Comma] = ","; names[Qt.Key_Period] = "."
        names[Qt.Key_Slash] = "/"; names[Qt.Key_Semicolon] = ";"; names[Qt.Key_Apostrophe] = "'"
        names[Qt.Key_BracketLeft] = "["; names[Qt.Key_BracketRight] = "]"; names[Qt.Key_Minus] = "-"
        names[Qt.Key_Equal] = "="; names[Qt.Key_QuoteLeft] = "`"; names[Qt.Key_Backslash] = "\\"
        return names[k] || ""
    }
}
