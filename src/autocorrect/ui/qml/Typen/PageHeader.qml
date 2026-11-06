import QtQuick
import QtQuick.Layouts

// Numbered section header, like the site: "01 / General" eyebrow, Syne title, lead.
ColumnLayout {
    property string number: "01"
    property string title: ""
    property string lead: ""
    Layout.fillWidth: true
    spacing: 6

    Eyebrow { label: number + "  /  " + title }
    Text {
        text: title
        color: Theme.ink
        font.family: Theme.display
        font.pixelSize: Theme.fsTitle
        font.weight: Font.Bold
        font.letterSpacing: -0.5
    }
    Body {
        visible: lead !== ""
        text: lead
        font.pixelSize: Theme.fsLead
        Layout.maximumWidth: 640
    }
}
