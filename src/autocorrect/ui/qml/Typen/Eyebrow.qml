import QtQuick

// .eyebrow: mono, uppercase, letter-spaced label.
Text {
    property string label: ""
    text: label.toUpperCase()
    color: Theme.inkFaint
    font.family: Theme.mono
    font.pixelSize: Theme.fsEyebrow
    font.letterSpacing: 2
    font.weight: Font.Medium
}
