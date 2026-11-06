import QtQuick
import QtQuick.Controls

// .btn-primary: ink fill, paper text.
Button {
    id: btn
    property bool danger: false
    implicitHeight: Theme.controlHeight
    leftPadding: 14
    rightPadding: 14
    hoverEnabled: true
    opacity: enabled ? 1 : 0.5
    background: Rectangle {
        radius: Theme.radiusSm
        color: btn.danger ? (btn.hovered ? Theme.proofStrong : Theme.proof) : (btn.hovered ? Theme.ink3 : Theme.ink)
        Behavior on color { ColorAnimation { duration: 120 } }
    }
    contentItem: Text {
        text: btn.text
        color: btn.danger ? "#ffffff" : Theme.paper
        font.family: Theme.sans
        font.pixelSize: Theme.fsBody
        font.weight: Font.Medium
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
    }
}
