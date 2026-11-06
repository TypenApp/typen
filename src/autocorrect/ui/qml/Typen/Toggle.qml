import QtQuick
import QtQuick.Controls

// A switch in the house style: ink track when on, paper knob.
Switch {
    id: sw
    implicitWidth: 40
    implicitHeight: 22
    hoverEnabled: true
    opacity: enabled ? 1 : 0.45
    indicator: Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: sw.checked ? Theme.ink : Theme.paper3
        border.color: sw.checked ? Theme.ink : Theme.lineStrong
        Behavior on color { ColorAnimation { duration: 120 } }
        Rectangle {
            x: sw.checked ? parent.width - width - 3 : 3
            y: 3
            width: parent.height - 6
            height: width
            radius: width / 2
            color: sw.checked ? Theme.paper : Theme.inkFaint
            Behavior on x { NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
        }
    }
    contentItem: Item {}
}
