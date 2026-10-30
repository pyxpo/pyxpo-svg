# Changelog

## 0.1.0a1 (unreleased)

- First release: `Svg` with `Path`, `Line`, `Circle`, `Ellipse`, `Rect`, `Polyline`, `Polygon`, `G` and `Text`.
  Fill, stroke, opacity, line caps and joins, dashes, fill rules, transforms, `view_box` and
  `preserve_aspect_ratio`. Path data is parsed in Python (all SVG commands, arcs included) and drawn with
  Core Graphics on iOS, `Canvas` on Android and a real `<svg>` on the web and the desktop window.
