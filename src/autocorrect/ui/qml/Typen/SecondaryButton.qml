import QtQuick
import QtQuick.Controls

// .btn-secondary: ink outline on paper.
Button {
    id: btn
    property bool active: false
    implicitHeight: Theme.controlHeight
    leftPadding: 14
    rightPadding: 14
    hoverEnabled: true
    opacity: enabled ? 1 : 0.5
    background: Rectangle {
        radius: Theme.radiusSm
        color: btn.active ? Theme.ink : (btn.hovered ? Theme.paper2 : "transparent")
        border.color: btn.active ? Theme.ink : Theme.lineStrong
        border.width: 1
        Behavior on color { ColorAnimation { duration: 120 } }
    }
    contentItem: Text {
        text: btn.text
        color: btn.active ? Theme.paper : Theme.ink
        font.family: Theme.sans
        font.pixelSize: Theme.fsBody
        font.weight: Font.Medium
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
}
