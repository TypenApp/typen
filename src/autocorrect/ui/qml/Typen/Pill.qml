import QtQuick

// Small status chip. `tone`: "ink" | "proof" | "ok" | "muted".
Rectangle {
    property string label: ""
    property string tone: "muted"
    readonly property color fg: tone === "proof" ? Theme.proof : (tone === "ok" ? Theme.ok : (tone === "ink" ? Theme.paper : Theme.inkMuted))
    implicitWidth: pillText.implicitWidth + 16
    implicitHeight: 20
    radius: 10
    color: tone === "ink" ? Theme.ink : (tone === "proof" ? Theme.proofSoft : Theme.paper2)
    border.color: tone === "ink" ? Theme.ink : Theme.line
    Text {
        id: pillText
        anchors.centerIn: parent
        text: label
        color: parent.fg
        font.family: Theme.mono
        font.pixelSize: 10
        font.letterSpacing: 1
    }
}
