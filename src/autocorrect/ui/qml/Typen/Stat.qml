import QtQuick
import QtQuick.Layouts

// Big number + eyebrow, for the Overview counters.
ColumnLayout {
    property string label: ""
    property string value: "0"
    property bool highlight: false
    spacing: 2
    Text {
        text: value
        color: highlight ? Theme.proof : Theme.ink
        font.family: Theme.display
        font.pixelSize: Theme.fsHero
        font.weight: Font.Bold
        font.letterSpacing: -1
    }
    Eyebrow { label: parent.label }
}
