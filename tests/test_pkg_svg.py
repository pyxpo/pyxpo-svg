"""pyxpo-svg: path parsing, shapes, transforms, paint inheritance, the wire format and the web build."""
import json
import math
import shutil
import subprocess

import pytest

from pyxpo import LocalChannel, component, create_app
from pyxpo.build import web
from pyxpo.renderers.mock import MockRenderer
from pyxpo.renderers.web import page_js

import pyxpo_svg as S
from pyxpo_svg import C, L, M, Q, Z


def mount(root):
    ch = LocalChannel()
    r = MockRenderer(ch)
    app = create_app(root, ch)
    return app, r


def wire(*children, **props):
    @component
    def Root():
        return S.Svg(*children, **props)

    app, r = mount(Root)
    (node,) = r.find_all("PxSvg")
    return node.props


def close(a, b, eps=1e-3):
    return len(a) == len(b) and all(abs(x - y) <= eps for x, y in zip(a, b))


# parse_path

def test_lines_relative_and_implicit_lineto():
    assert S.parse_path("M10 10 h20 v20 H0 V5 z") == [M, 10, 10, L, 30, 10, L, 30, 30, L, 0, 30, L, 0, 5, Z]
    assert S.parse_path("m1 1 2 2 3 3") == [M, 1, 1, L, 3, 3, L, 6, 6]
    assert S.parse_path("M0,0L1-1l.5.5") == [M, 0, 0, L, 1, -1, L, 1.5, -0.5]


def test_z_returns_to_subpath_start():
    assert S.parse_path("M5 5 l10 0 z l1 1") == [M, 5, 5, L, 15, 5, Z, L, 6, 6]


def test_smooth_curves_reflect_control_points():
    d = S.parse_path("M0 0 C10 0 20 10 20 20 S30 40 40 40")
    assert d[:8] == [M, 0, 0, C, 10, 0, 20, 10] and d[10:15] == [C, 20, 30, 30, 40]
    q = S.parse_path("M0 0 Q10 10 20 0 T40 0")
    assert q == [M, 0, 0, Q, 10, 10, 20, 0, Q, 30, -10, 40, 0]
    # S after a non-curve uses the current point as its first control point
    assert S.parse_path("M0 0 L5 5 S10 10 15 5")[6:9] == [C, 5, 5]


def test_arc_becomes_cubics_ending_at_the_target():
    d = S.parse_path("M10 10 h20 v20 a10 10 0 01-10 10 z")
    assert d == [M, 10, 10, L, 30, 10, L, 30, 30, C, 30, 35.523, 25.523, 40, 20, 40, Z]
    full = S.parse_path("M0 50 A50 50 0 1 1 100 50 A50 50 0 1 1 0 50")
    assert full.count(C) == 4 and full[-2:] == [0, 50]
    # compact flags and a zero radius (a straight line)
    assert S.parse_path("M0 0a5 5 0 1010 0")[-2:] == [10, 0]
    assert S.parse_path("M0 0 A0 5 0 0 1 10 0") == [M, 0, 0, L, 10, 0]


def test_bad_path_data_raises():
    for bad in ("L10 10", "M0 0 X1", "M0 0 L1", "M0 0 A1 1 0 2 0 5 5"):
        with pytest.raises(ValueError):
            S.parse_path(bad)


# parse_transform

def test_transforms():
    assert S.parse_transform("translate(5 6)") == (1, 0, 0, 1, 5, 6)
    assert S.parse_transform("scale(2)") == (2, 0, 0, 2, 0, 0)
    a, b, c, d, e, f = S.parse_transform("rotate(-90 28 28)")
    assert close([a, b, c, d, e, f], [0, -1, 1, 0, 0, 56])
    m = S.parse_transform("translate(10,0) scale(2,3)")
    assert m == (2, 0, 0, 3, 10, 0)
    k = S.parse_transform("skewX(45)")
    assert close(k, [1, 0, 1, 1, 0, 0])
    assert S.parse_transform([1, 2, 3, 4, 5, 6]) == (1, 2, 3, 4, 5, 6)
    with pytest.raises(ValueError):
        S.parse_transform("spin(4)")


# shapes

def test_circle_and_rect_paths():
    c = S.Circle(50, 50, 10).attrs["d"]
    assert c[:3] == [M, 60, 50] and c.count(C) == 4 and c[-1] == Z
    assert S.Rect(0, 0, 10, 20).attrs["d"] == [M, 0, 0, L, 10, 0, L, 10, 20, L, 0, 20, Z]
    rounded = S.Rect(0, 0, 40, 20, rx=4).attrs["d"]
    assert rounded.count(C) == 4 and rounded[:3] == [M, 4, 0]
    # rx is clamped to half the side, ry defaults to rx
    assert S.Rect(0, 0, 10, 10, rx=50).attrs["d"][:3] == [M, 5, 0]
    assert S.Line(1, 2, 3, 4).attrs["d"] == [M, 1, 2, L, 3, 4]
    assert S.Polyline("0,0 10,5 20,0").attrs["d"] == [M, 0, 0, L, 10, 5, L, 20, 0]
    assert S.Polygon([(0, 0), (10, 0), (5, 5)]).attrs["d"][-1] == Z


def test_shape_errors():
    with pytest.raises(ValueError):
        S.Circle(0, 0, -1)
    with pytest.raises(ValueError):
        S.Polyline("0,0 1")
    with pytest.raises(TypeError):
        S.Path("M0 0", strok="#fff")


# wire format

def test_default_fill_is_black_and_no_stroke():
    p = wire(S.Rect(0, 0, 10, 10))
    assert p["ops"] == [{"d": [M, 0, 0, L, 10, 0, L, 10, 10, L, 0, 10, Z], "fill": 0xFF000000}]
    assert "box" not in p and "align" not in p and "slice" not in p


def test_stroke_options_and_opacity_fold_into_alpha():
    (op,) = wire(S.Line(0, 0, 10, 0, stroke="#ff0000", stroke_width=2.5, stroke_linecap="round",
                        stroke_linejoin="bevel", stroke_dasharray="4 2 1", stroke_dashoffset=3,
                        stroke_opacity=0.5))["ops"]
    assert "fill" in op   # a line still has the default fill, which draws nothing visible
    assert op["stroke"] == (128 << 24) | 0xFF0000 and op["width"] == 2.5
    assert op["cap"] == 1 and op["join"] == 2
    assert op["dash"] == [4, 2, 1, 4, 2, 1] and op["phase"] == 3


def test_none_paint_drops_the_op():
    assert wire(S.Path("M0 0 L1 1", fill="none"))["ops"] == []
    assert wire(S.Path("M0 0 L1 1", fill="none", stroke="#fff", stroke_width=0))["ops"] == []
    assert wire(S.Circle(1, 1, 1, opacity=0))["ops"] == []


def test_group_inherits_paint_and_composes_transform_and_opacity():
    ops = wire(S.G(S.Circle(0, 0, 1), S.Rect(0, 0, 1, 1, fill="#00ff00", transform="scale(2)"),
                   fill="#0000ff", opacity=0.5, transform="translate(10 20)"), color="#123456")["ops"]
    assert ops[0]["fill"] == (128 << 24) | 0x0000FF and ops[0]["m"] == [1, 0, 0, 1, 10, 20]
    assert ops[1]["fill"] == (128 << 24) | 0x00FF00 and ops[1]["m"] == [2, 0, 0, 2, 10, 20]


def test_current_color():
    (op,) = wire(S.Path("M0 0 L1 1", fill="none", stroke="currentColor"), color="#f0525e")["ops"]
    assert op["stroke"] == 0xFFF0525E


def test_text_op():
    (op,) = wire(S.Text("Today", 326, 120, font_size=11, font_weight="bold", text_anchor="end",
                        fill="#9a9ca1", font_family="Figtree"))["ops"]
    assert op == {"text": "Today", "x": 326, "y": 120, "size": 11, "weight": 700, "anchor": 2,
                  "family": "Figtree", "fill": 0xFF9A9CA1}
    (plain,) = wire(S.Text(42))["ops"]
    assert plain == {"text": "42", "x": 0, "y": 0, "size": 16, "fill": 0xFF000000}


def test_view_box_aspect_and_size():
    p = wire(S.Circle(5, 5, 5), width=56, height=56, view_box="0 0 10 10")
    assert p["box"] == [0, 0, 10, 10] and "align" not in p
    assert p["style"] == {"width": 56, "height": 56}
    p = wire(view_box=(0, 0, 4, 2), preserve_aspect_ratio="xMinYMax slice")
    assert p["align"] == "xMinYMax" and p["slice"] is True and p["ops"] == []
    p = wire(view_box=(0, 0, 4, 2), preserve_aspect_ratio="none", style={"flex": 1})
    assert p["align"] == "none" and "slice" not in p


def test_children_lists_and_none_are_flattened():
    pts = [S.Circle(i, 0, 1) for i in range(3)]
    assert len(wire(pts, None, False, [S.Rect(0, 0, 1, 1), [S.Line(0, 0, 1, 1, stroke="#000")]])["ops"]) == 5


def test_svg_errors():
    for kw in ({"view_box": "0 0 0 10"}, {"view_box": "0 0 10"}, {"view_box": (0, 0, 1, 1),
                                                                   "preserve_aspect_ratio": "middle"}):
        with pytest.raises(ValueError):
            S.Svg(**kw)
    with pytest.raises(TypeError):
        S.Svg("not an element")
    with pytest.raises(ValueError):
        wire(S.Rect(0, 0, 1, 1, fill_opacity=2))
    with pytest.raises(ValueError):
        wire(S.Text("x", font_weight="heavy"))
    with pytest.raises(ValueError):
        S.Line(0, math.inf, 1, 1)


def test_numbers_are_rounded_on_the_wire():
    (op,) = wire(S.Path("M0.123456 1.98765 L-0.0001 2"))["ops"]
    assert op["d"] == [M, 0.123, 1.988, L, 0, 2]
    assert all(isinstance(op["d"][i], int) for i in (0, 3))


# web

def test_page_js_and_web_build(tmp_path):
    assert set(page_js({"Svg": "pyxpo_svg"})) == {"Svg"}
    p = tmp_path / "proj"
    (p / "app").mkdir(parents=True)
    (p / "app" / "index.py").write_text("print('hi')\n")
    (p / "pyproject.toml").write_text('[project]\nname="x"\nversion="1.0.0"\n[tool.pyxpo]\nname = "Demo"\n'
                                      'bundle_id = "com.acme.demo"\nmodules = ["svg"]\n')
    out = web.build(p)
    html = (out / "index.html").read_text(encoding="utf-8")
    cfg = json.loads(html.split("window.PYXPO_CONFIG = ", 1)[1].split(";</script>", 1)[0])
    assert cfg["scripts"] == ["modules/Svg.js"]
    assert (out / "modules" / "Svg.js").read_text() == open(S.__path__[0] + "/web.js").read()


@pytest.mark.skipif(not shutil.which("node"), reason="needs node")
def test_web_js_parses():
    subprocess.run(["node", "--check", S.__path__[0] + "/web.js"], check=True)
