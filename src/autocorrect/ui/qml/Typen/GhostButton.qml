import QtQuick
import QtQuick.Controls

// .btn-ghost: text only, muted until hovered. `danger` turns it proof-red.
Button {
    id: btn
    property bool danger: false
    implicitHeight: Theme.controlHeight
    leftPadding: 8
    rightPadding: 8
    hoverEnabled: true
    opacity: enabled ? 1 : 0.5
    background: Rectangle {
        radius: Theme.radiusSm
        color: btn.hovered ? Theme.paper2 : "transparent"
    }
    contentItem: Text {
        text: btn.text
        color: btn.danger ? Theme.proof : (btn.hovered ? Theme.ink : Theme.inkMuted)
        font.family: Theme.sans
        font.pixelSize: Theme.fsBody
        font.weight: Font.Medium
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
}
