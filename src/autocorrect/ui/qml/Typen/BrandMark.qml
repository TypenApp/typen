import QtQuick

// The Typen mark, drawn from the same 88x64 geometry as autocorrect.branding.draw_mark:
// an ink tile with "Aa", a short bar, and the proofreader's red squiggle.
Item {
    id: mark
    property int tileHeight: 32
    property bool accent: false
    property bool paused: false

    readonly property real s: tileHeight / 64
    width: Math.round(88 * s)
    height: tileHeight

    Rectangle {
        anchors.fill: parent
        radius: 14 * mark.s
        color: mark.paused ? "#6b7280" : (mark.accent ? Theme.proof : Theme.ink)
        antialiasing: true
    }

    Text {
        x: 19.75 * mark.s
        y: 36 * mark.s - font.pixelSize * 0.78
        text: "Aa"
        color: mark.paused || mark.accent ? "#ffffff" : Theme.paper
        font.family: Theme.display
        font.weight: Font.Bold
        font.pixelSize: 24 * mark.s
        font.letterSpacing: -1 * mark.s
    }

    Rectangle {
        x: 54.25 * mark.s
        y: 33 * mark.s
        width: 13.75 * mark.s
        height: 3 * mark.s
        radius: 1 * mark.s
        color: mark.paused || mark.accent ? "#ffffff" : Theme.paper
    }

    Squiggle {
        x: 20 * mark.s
        y: 41 * mark.s
        width: 48 * mark.s
        height: 10 * mark.s
        strokeWidth: 3.2 * mark.s
        color: mark.accent ? "#ffffff" : (Theme.dark ? "#ff5a3c" : "#e5341a")
    }
}
