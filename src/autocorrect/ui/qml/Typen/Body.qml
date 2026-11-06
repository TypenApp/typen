import QtQuick
import QtQuick.Layouts

// Body copy: wraps, muted by default.
Text {
    property bool muted: true
    Layout.fillWidth: true
    wrapMode: Text.WordWrap
    color: muted ? Theme.inkMuted : Theme.ink
    font.family: Theme.sans
    font.pixelSize: Theme.fsBody
    lineHeight: 1.35
}
