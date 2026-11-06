import QtQuick
import QtQuick.Layouts

// .card: a bordered paper panel. Children go into the inner column.
Rectangle {
    id: card
    default property alias content: inner.data
    property int padding: 18
    property alias spacing: inner.spacing

    Layout.fillWidth: true
    implicitHeight: inner.implicitHeight + padding * 2
    radius: Theme.radius
    color: Theme.paper
    border.color: Theme.line
    border.width: 1

    ColumnLayout {
        id: inner
        anchors.fill: parent
        anchors.margins: card.padding
        spacing: Theme.gap
    }
}
