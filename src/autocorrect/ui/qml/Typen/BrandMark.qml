import QtQuick
import QtQuick.Shapes

// Outlined Syne Bold, the same paths as packaging/typen-mark.svg. A live Text
// measurement puts the cursor in the middle of the tile, because Qt does not
// apply the variable font's Bold axis. These coordinates are the tile space
// (88x64); the square SVG letterboxes that tile by 12px.
Item {
    id: mark
    property int tileHeight: 32
    property bool accent: false
    property bool paused: false

    readonly property real s: tileHeight / 64
    readonly property color glyph: (paused || accent) ? "#ffffff" : Theme.paper
    readonly property string letterPath: "M24.022 32.616V29.952H34.294V32.616ZM20.158 36 27.454 20.472H30.91L38.278 36H34.798L28.414 22.008H29.95L23.614 36ZM44.934 36.264Q43.158 36.264 41.706 35.484Q40.254 34.704 39.402 33.3Q38.55 31.896 38.55 30.048Q38.55 28.152 39.414 26.76Q40.278 25.368 41.754 24.588Q43.23 23.808 45.102 23.808Q47.166 23.808 48.426 24.636Q49.686 25.464 50.262 26.88Q50.838 28.296 50.838 30.048Q50.838 31.104 50.502 32.196Q50.166 33.288 49.47 34.212Q48.774 35.136 47.646 35.7Q46.518 36.264 44.934 36.264ZM45.942 33.864Q47.358 33.864 48.39 33.384Q49.422 32.904 49.974 32.04Q50.526 31.176 50.526 30.048Q50.526 28.824 49.962 27.972Q49.398 27.12 48.378 26.676Q47.358 26.232 45.942 26.232Q43.95 26.232 42.846 27.276Q41.742 28.32 41.742 30.048Q41.742 31.2 42.27 32.052Q42.798 32.904 43.746 33.384Q44.694 33.864 45.942 33.864ZM50.526 24.072H53.646V36H50.742Q50.742 36 50.682 35.532Q50.622 35.064 50.574 34.344Q50.526 33.624 50.526 32.928Z"

    width: Math.round(88 * s)
    height: tileHeight

    Rectangle {
        anchors.fill: parent
        radius: 14 * mark.s
        color: mark.paused ? "#6b7280" : (mark.accent ? Theme.proof : Theme.ink)
        antialiasing: true
    }

    Item {
        width: 88
        height: 64
        scale: mark.s
        transformOrigin: Item.TopLeft

        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                fillColor: mark.glyph
                strokeColor: "transparent"
                PathSvg { path: mark.letterPath }
            }
        }

        // Cursor bar from the outlined Bold drawing: flush after "Aa", ending at x=68.
        Rectangle {
            x: 54.038
            y: 33
            width: 13.962
            height: 3
            radius: 1
            color: mark.glyph
        }

        Squiggle {
            x: 20
            y: 41
            width: 48
            height: 10
            strokeWidth: 3.2
            color: mark.accent ? "#ffffff" : (Theme.dark ? "#ff5a3c" : "#e5341a")
        }
    }
}
