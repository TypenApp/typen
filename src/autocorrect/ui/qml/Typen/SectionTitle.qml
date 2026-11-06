import QtQuick
import QtQuick.Layouts

// A card's heading with an optional one-line description.
ColumnLayout {
    property string title: ""
    property string description: ""
    Layout.fillWidth: true
    spacing: 3
    Text {
        text: title
        color: Theme.ink
        font.family: Theme.display
        font.pixelSize: Theme.fsLead
        font.weight: Font.DemiBold
    }
    Body {
        visible: description !== ""
        text: description
        font.pixelSize: Theme.fsSmall
    }
}
