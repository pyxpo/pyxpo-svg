"""SVG shapes, paths and text drawn natively: charts, rings, sparklines and icons.

    import pyxpo_svg as S

    S.Svg(
        S.Path(d="M0 100 L60 40 L120 70 L180 20", fill="none", stroke="#f0525e", stroke_width=2.5,
               stroke_linecap="round", stroke_linejoin="round"),
        S.Circle(cx=180, cy=20, r=4, fill="#f0525e"),
        S.Text("Today", x=180, y=118, font_size=11, fill="#9a9ca1", text_anchor="end"),
        width="100%", height=130, view_box="0 0 180 130", preserve_aspect_ratio="none",
    )

The tree is flattened in Python into a list of draw operations: path data is parsed here (every SVG command,
arcs included) into absolute move, line, cubic, quadratic and close steps, shapes become paths, `G` attributes
are inherited and transforms are composed. iOS draws the list with Core Graphics, Android with `Canvas`, the web
and the desktop window with a real `<svg>` element. `view_box` maps user units to the view's size on every
platform; without it one user unit is one pt/dp.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from pyxpo.module_api import native_view
from pyxpo.style import parse_color

__version__ = "0.1.0a1"

__all__ = ["Svg", "Path", "Line", "Circle", "Ellipse", "Rect", "Polyline", "Polygon", "G", "Text", "Node",
           "parse_path", "parse_transform"]

_View = native_view("PxSvg")

# Path step codes on the wire: M x y, L x y, C x1 y1 x2 y2 x y, Q x1 y1 x y, Z.
M, L, C, Q, Z = 0, 1, 2, 3, 4

Matrix = Tuple[float, float, float, float, float, float]   # a b c d e f: x' = a x + c y + e, y' = b x + d y + f
_IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

_PAINT = ("fill", "fill_opacity", "fill_rule", "stroke", "stroke_width", "stroke_opacity", "stroke_linecap",
          "stroke_linejoin", "stroke_miterlimit", "stroke_dasharray", "stroke_dashoffset", "font_size",
          "font_weight", "font_family", "text_anchor", "color")
_OWN = ("opacity", "transform")   # not inherited: a group multiplies opacity and composes transforms
_CAPS = ("butt", "round", "square")
_JOINS = ("miter", "round", "bevel")
_ANCHORS = ("start", "middle", "end")
_RULES = ("nonzero", "evenodd")
_ALIGNS = ("none", "xMinYMin", "xMidYMin", "xMaxYMin", "xMinYMid", "xMidYMid", "xMaxYMid", "xMinYMax", "xMidYMax",
           "xMaxYMax")
_WEIGHTS = {"normal": 400, "bold": 700, "lighter": 300, "bolder": 700}
_DEFAULTS: Dict[str, Any] = {
    "fill": "#000000", "fill_opacity": 1.0, "fill_rule": "nonzero", "stroke": None, "stroke_width": 1.0,
    "stroke_opacity": 1.0, "stroke_linecap": "butt", "stroke_linejoin": "miter", "stroke_miterlimit": 4.0,
    "stroke_dasharray": None, "stroke_dashoffset": 0.0, "font_size": 16.0, "font_weight": 400, "font_family": None,
    "text_anchor": "start", "color": "#000000",
}


class Node:
    """One element of an `Svg` tree. Build it with `Path`, `Circle`, `G` and the other functions."""
    __slots__ = ("kind", "attrs", "children")

    def __init__(self, kind: str, attrs: Dict[str, Any], children: Sequence["Node"] = ()):
        self.kind = kind
        self.attrs = attrs
        self.children = tuple(children)

    def __eq__(self, other: Any) -> bool:
        return isinstance(other, Node) and (self.kind, self.attrs, self.children) == (other.kind, other.attrs,
                                                                                      other.children)

    def __repr__(self) -> str:
        return "%s(%s)" % (self.kind, ", ".join("%s=%r" % kv for kv in self.attrs.items()))


def _paint(kind: str, attrs: Dict[str, Any], paint: Dict[str, Any]) -> Dict[str, Any]:
    for k in paint:
        if k not in _PAINT and k not in _OWN:
            raise TypeError("%s() got an unexpected keyword argument %r" % (kind, k))
    attrs.update(paint)
    return attrs


def Path(d: str, **paint: Any) -> Node:
    """A path from SVG path data, e.g. `"M0 10 L20 0 Z"`. All commands are supported, relative ones and arcs too."""
    return Node("Path", _paint("Path", {"d": parse_path(d)}, paint))


def Line(x1: float = 0, y1: float = 0, x2: float = 0, y2: float = 0, **paint: Any) -> Node:
    """A straight line. Give it a `stroke`: a line has no fill."""
    return Node("Path", _paint("Line", {"d": [M, _n(x1), _n(y1), L, _n(x2), _n(y2)]}, paint))


def Circle(cx: float = 0, cy: float = 0, r: float = 0, **paint: Any) -> Node:
    """A circle. The outline starts at 3 o'clock and runs clockwise, so a dash starts there too."""
    return Node("Path", _paint("Circle", {"d": _ellipse(_n(cx), _n(cy), _pos("r", r), _pos("r", r))}, paint))


def Ellipse(cx: float = 0, cy: float = 0, rx: float = 0, ry: float = 0, **paint: Any) -> Node:
    """An ellipse with radii `rx` and `ry`."""
    return Node("Path", _paint("Ellipse", {"d": _ellipse(_n(cx), _n(cy), _pos("rx", rx), _pos("ry", ry))}, paint))


def Rect(x: float = 0, y: float = 0, width: float = 0, height: float = 0, rx: Optional[float] = None,
         ry: Optional[float] = None, **paint: Any) -> Node:
    """A rectangle, with rounded corners when `rx` or `ry` is set (one of them sets both, as in SVG)."""
    w, h = _pos("width", width), _pos("height", height)
    rx_ = _pos("rx", rx) if rx is not None else None
    ry_ = _pos("ry", ry) if ry is not None else None
    if rx_ is None:
        rx_ = ry_ or 0.0
    if ry_ is None:
        ry_ = rx_
    return Node("Path", _paint("Rect", {"d": _rect(_n(x), _n(y), w, h, min(rx_, w / 2), min(ry_, h / 2))}, paint))


def Polyline(points: Any, **paint: Any) -> Node:
    """An open line through `points`: `"0,10 20,5 40,8"`, `[(0, 10), (20, 5)]` or a flat `[0, 10, 20, 5]`."""
    return Node("Path", _paint("Polyline", {"d": _poly(points, False)}, paint))


def Polygon(points: Any, **paint: Any) -> Node:
    """A closed shape through `points` (same forms as `Polyline`)."""
    return Node("Path", _paint("Polygon", {"d": _poly(points, True)}, paint))


def G(*children: Any, **paint: Any) -> Node:
    """A group. Its paint attributes are inherited by the children, `transform` applies to all of them and
    `opacity` multiplies theirs (each child is faded on its own, not composited as one layer)."""
    return Node("G", _paint("G", {}, paint), _children(children))


def Text(text: Any, x: float = 0, y: float = 0, **paint: Any) -> Node:
    """One line of text. `y` is the baseline; `text_anchor` is "start", "middle" or "end". Text is filled only."""
    return Node("Text", _paint("Text", {"text": str(text), "x": _n(x), "y": _n(y)}, paint))


def Svg(*children: Any, width: Any = None, height: Any = None, view_box: Any = None,
        preserve_aspect_ratio: str = "xMidYMid meet", color: Any = "#000000", style: Any = None, **props: Any):
    """A vector drawing. `width` and `height` size the view like style width and height (numbers or "100%");
    `style` wins over them. `view_box` ("x y w h" or a 4-tuple) maps user units onto the view, scaled as
    `preserve_aspect_ratio` says ("none", or an alignment such as "xMidYMid" plus "meet" or "slice").
    `color` is what `"currentColor"` means in fills and strokes."""
    wire: Dict[str, Any] = {"ops": _flatten(_children(children), color)}
    if view_box is not None:
        vb = _numbers("view_box", view_box)
        if len(vb) != 4 or vb[2] <= 0 or vb[3] <= 0:
            raise ValueError("view_box needs x, y and a positive width and height, got %r" % (view_box,))
        wire["box"] = vb   # "view_box" would be renamed to "viewbox" by the core key aliases
        align, slice_ = _aspect(preserve_aspect_ratio)
        if align != "xMidYMid":
            wire["align"] = align
        if slice_:
            wire["slice"] = True
    size = {k: v for k, v in (("width", width), ("height", height)) if v is not None}
    if size:
        style = [size, style] if style is not None else size
    return _View(style=style, **wire, **props)


# flattening

def _children(items: Iterable[Any]) -> List[Node]:
    out: List[Node] = []
    for c in items:
        if c is None or c is False or c is True:
            continue
        if isinstance(c, (list, tuple)):
            out.extend(_children(c))
        elif isinstance(c, Node):
            out.append(c)
        else:
            raise TypeError("Svg children must be Path, Circle, G and the other pyxpo_svg elements, got %r" % (c,))
    return out


def _flatten(nodes: List[Node], color: Any) -> List[Dict[str, Any]]:
    ops: List[Dict[str, Any]] = []
    state = dict(_DEFAULTS, color=color)
    for n in nodes:
        _walk(n, state, _IDENTITY, 1.0, ops)
    return ops


def _walk(node: Node, parent: Dict[str, Any], m: Matrix, opacity: float, ops: List[Dict[str, Any]]) -> None:
    a = node.attrs
    state = dict(parent)
    for k in _PAINT:
        if k in a:
            state[k] = a[k]
    if a.get("transform") is not None:
        m = _mul(m, parse_transform(a["transform"]))
    if a.get("opacity") is not None:
        opacity *= _unit("opacity", a["opacity"])
    if node.kind == "G":
        for c in node.children:
            _walk(c, state, m, opacity, ops)
        return
    op: Dict[str, Any] = {}
    if node.kind == "Text":
        op["text"], op["x"], op["y"] = a["text"], a["x"], a["y"]
        op["size"] = _pos("font_size", state["font_size"])
        weight = _weight(state["font_weight"])
        if weight != 400:
            op["weight"] = weight
        anchor = _choice("text_anchor", state["text_anchor"], _ANCHORS)
        if anchor:
            op["anchor"] = anchor
        if state["font_family"]:
            op["family"] = str(state["font_family"])
        fill = _color(state["fill"], state, _unit("fill_opacity", state["fill_opacity"]) * opacity)
        if not fill:
            return
        op["fill"] = fill
    else:
        op["d"] = a["d"]
        fill = _color(state["fill"], state, _unit("fill_opacity", state["fill_opacity"]) * opacity)
        stroke = _color(state["stroke"], state, _unit("stroke_opacity", state["stroke_opacity"]) * opacity)
        width = _pos("stroke_width", state["stroke_width"])
        if stroke and width == 0:
            stroke = 0
        if not fill and not stroke:
            return
        if fill:
            op["fill"] = fill
            if _choice("fill_rule", state["fill_rule"], _RULES):
                op["evenodd"] = True
        if stroke:
            op["stroke"] = stroke
            if width != 1:
                op["width"] = width
            cap = _choice("stroke_linecap", state["stroke_linecap"], _CAPS)
            join = _choice("stroke_linejoin", state["stroke_linejoin"], _JOINS)
            if cap:
                op["cap"] = cap
            if join:
                op["join"] = join
            miter = _pos("stroke_miterlimit", state["stroke_miterlimit"])
            if miter != 4:
                op["miter"] = max(miter, 1.0)
            dash = _dash(state["stroke_dasharray"])
            if dash:
                op["dash"] = dash
                phase = _n(state["stroke_dashoffset"])
                if phase:
                    op["phase"] = phase
    if m != _IDENTITY:
        op["m"] = [_r(v) for v in m]
    ops.append(op)


def _color(value: Any, state: Dict[str, Any], alpha: float) -> int:
    """0 (draw nothing) for None, "none", "transparent" and colors with no alpha left after the opacities."""
    if value is None:
        return 0
    if isinstance(value, str):
        v = value.strip()
        if v in ("none", "transparent", ""):
            return 0
        if v == "currentColor":
            value = state["color"]
            if isinstance(value, str) and value.strip() == "currentColor":
                raise ValueError("color cannot be currentColor")
            return _color(value, state, alpha)
    c = parse_color(value)
    a = int(round(((c >> 24) & 255) * alpha))
    return (a << 24) | (c & 0xFFFFFF) if a > 0 else 0


def _aspect(value: str) -> Tuple[str, bool]:
    parts = str(value).split()
    if not parts or len(parts) > 2 or parts[0] not in _ALIGNS or (len(parts) == 2 and parts[1] not in ("meet", "slice")):
        raise ValueError('preserve_aspect_ratio must be "none" or an alignment such as "xMidYMid meet", got %r'
                         % (value,))
    return parts[0], len(parts) == 2 and parts[1] == "slice" and parts[0] != "none"


def _dash(value: Any) -> Optional[List[float]]:
    if value is None or (isinstance(value, str) and value.strip() in ("none", "")):
        return None
    d = [_pos("stroke_dasharray", v) for v in (_numbers("stroke_dasharray", value))]
    if not d or not any(d):
        return None
    return d + d if len(d) % 2 else d   # an odd list repeats, as in SVG


def _weight(value: Any) -> int:
    if isinstance(value, str):
        v = value.strip()
        if v in _WEIGHTS:
            return _WEIGHTS[v]
        value = v
    try:
        w = int(float(value))
    except (TypeError, ValueError):
        raise ValueError("font_weight must be 100 to 900, \"normal\" or \"bold\", got %r" % (value,)) from None
    if not 1 <= w <= 1000:
        raise ValueError("font_weight must be 100 to 900, got %r" % (value,))
    return w


def _choice(name: str, value: Any, options: Tuple[str, ...]) -> int:
    """Index of `value` in `options`; 0 is the default and is left off the wire."""
    if value not in options:
        raise ValueError("%s must be one of %s, got %r" % (name, ", ".join(options), value))
    return options.index(value)


# numbers

def _n(v: Any) -> float:
    if isinstance(v, bool):
        raise ValueError("expected a number, got %r" % (v,))
    try:
        f = float(v)
    except (TypeError, ValueError):
        raise ValueError("expected a number, got %r" % (v,)) from None
    if not math.isfinite(f):
        raise ValueError("expected a finite number, got %r" % (v,))
    return _r(f)


def _r(f: float) -> float:
    f = round(f, 3)
    return 0.0 if f == 0 else f   # no -0.0 on the wire


def _pos(name: str, v: Any) -> float:
    f = _n(v)
    if f < 0:
        raise ValueError("%s must not be negative, got %r" % (name, v))
    return f


def _unit(name: str, v: Any) -> float:
    f = _n(v)
    if not 0 <= f <= 1:
        raise ValueError("%s must be 0 to 1, got %r" % (name, v))
    return f


_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _numbers(name: str, value: Any) -> List[float]:
    if isinstance(value, str):
        items: List[Any] = _NUM.findall(value)
        if re.sub(r"[\s,]+", "", _NUM.sub("", value)):
            raise ValueError("%s has a bad number list: %r" % (name, value))
        return [_n(v) for v in items]
    out: List[float] = []
    for v in value:
        if isinstance(v, (list, tuple)):
            out.extend(_n(x) for x in v)
        else:
            out.append(_n(v))
    return out


# shapes

_K = 0.5522847498307936   # cubic control distance for a quarter circle of radius 1


def _ellipse(cx: float, cy: float, rx: float, ry: float) -> List[float]:
    if rx == 0 or ry == 0:
        return []
    kx, ky = rx * _K, ry * _K
    return [M, _r(cx + rx), cy,
            C, _r(cx + rx), _r(cy + ky), _r(cx + kx), _r(cy + ry), cx, _r(cy + ry),
            C, _r(cx - kx), _r(cy + ry), _r(cx - rx), _r(cy + ky), _r(cx - rx), cy,
            C, _r(cx - rx), _r(cy - ky), _r(cx - kx), _r(cy - ry), cx, _r(cy - ry),
            C, _r(cx + kx), _r(cy - ry), _r(cx + rx), _r(cy - ky), _r(cx + rx), cy, Z]


def _rect(x: float, y: float, w: float, h: float, rx: float, ry: float) -> List[float]:
    if w == 0 or h == 0:
        return []
    if rx == 0 or ry == 0:
        return [M, x, y, L, _r(x + w), y, L, _r(x + w), _r(y + h), L, x, _r(y + h), Z]
    kx, ky = rx * (1 - _K), ry * (1 - _K)
    r, b = x + w, y + h
    pts = [M, x + rx, y, L, r - rx, y, C, r - kx, y, r, y + ky, r, y + ry,
           L, r, b - ry, C, r, b - ky, r - kx, b, r - rx, b,
           L, x + rx, b, C, x + kx, b, x, b - ky, x, b - ry,
           L, x, y + ry, C, x, y + ky, x + kx, y, x + rx, y, Z]
    return _round(pts)


def _round(d: List[float]) -> List[float]:
    """Round the coordinates of wire steps and keep the step codes as ints."""
    codes = _codes(d)
    return [v if i in codes else _r(v) for i, v in enumerate(d)]


def _codes(d: List[float]) -> set:
    idx, i = set(), 0
    sizes = {M: 2, L: 2, C: 6, Q: 4, Z: 0}
    while i < len(d):
        idx.add(i)
        i += 1 + sizes[int(d[i])]
    return idx


def _poly(points: Any, close: bool) -> List[float]:
    nums = _numbers("points", points)
    if len(nums) % 2:
        raise ValueError("points needs x, y pairs, got %d numbers" % len(nums))
    if not nums:
        return []
    d: List[float] = [M, nums[0], nums[1]]
    for i in range(2, len(nums), 2):
        d += [L, nums[i], nums[i + 1]]
    if close:
        d.append(Z)
    return d


# path data

_CMD_ARGS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}
_PATH_TOKEN = re.compile(r"\s*,?\s*([MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)")


def _path_tokens(d: str) -> List[Union[str, float]]:
    out: List[Union[str, float]] = []
    i, n = 0, len(d)
    arc_pos = -1   # position inside an arc's 7 arguments; the two flags may be written without separators
    while i < n:
        if d[i] in " \t\r\n,":
            i += 1
            continue
        if arc_pos in (3, 4) and d[i] in "01":
            out.append(float(d[i]))
            i += 1
            arc_pos += 1
            continue
        m = _PATH_TOKEN.match(d, i)
        if not m:
            raise ValueError("bad path data at %d: %r" % (i, d[i:i + 12]))
        t = m.group(1)
        i = m.end()
        if t.isalpha():
            out.append(t)
            arc_pos = 0 if t in "Aa" else -1
        else:
            out.append(float(t))
            if arc_pos >= 0:
                arc_pos = (arc_pos + 1) % 7
    return out


def parse_path(d: str) -> List[float]:
    """SVG path data to the wire steps: absolute M, L, C, Q and Z only. H, V, S, T and arcs are converted."""
    if not isinstance(d, str):
        raise TypeError("path data must be a string, got %r" % (d,))
    toks = _path_tokens(d)
    out: List[float] = []
    x = y = sx = sy = 0.0
    last_c: Optional[Tuple[float, float]] = None   # second control point of the previous C or S
    last_q: Optional[Tuple[float, float]] = None   # control point of the previous Q or T
    i, cmd = 0, ""
    while i < len(toks):
        t = toks[i]
        if isinstance(t, str):
            cmd = t
            i += 1
        elif not cmd:
            raise ValueError("path data must start with a command, got %r" % (d[:12],))
        elif cmd in "Zz":
            raise ValueError("path data has a number after Z: %r" % (d,))
        up = cmd.upper()
        rel = cmd != up
        if not out and up != "M":
            raise ValueError("path data must start with M, got %r" % (d[:12],))
        k = _CMD_ARGS[up]
        if up == "Z":
            out.append(Z)
            x, y = sx, sy
            last_c = last_q = None
            continue
        args = toks[i:i + k]
        if len(args) < k or any(isinstance(a, str) for a in args):
            raise ValueError("path command %s needs %d numbers: %r" % (cmd, k, d))
        i += k
        a = [float(v) for v in args]
        ox, oy = (x, y) if rel else (0.0, 0.0)
        nc: Optional[Tuple[float, float]] = None
        nq: Optional[Tuple[float, float]] = None
        if up == "M":
            x, y = a[0] + ox, a[1] + oy
            sx, sy = x, y
            out += [M, x, y]
            cmd = "l" if rel else "L"   # more pairs after a move are lines
        elif up == "L":
            x, y = a[0] + ox, a[1] + oy
            out += [L, x, y]
        elif up == "H":
            x = a[0] + ox
            out += [L, x, y]
        elif up == "V":
            y = a[0] + (y if rel else 0.0)
            out += [L, x, y]
        elif up == "C":
            x1, y1, x2, y2 = a[0] + ox, a[1] + oy, a[2] + ox, a[3] + oy
            x, y = a[4] + ox, a[5] + oy
            out += [C, x1, y1, x2, y2, x, y]
            nc = (x2, y2)
        elif up == "S":
            x1, y1 = (2 * x - last_c[0], 2 * y - last_c[1]) if last_c else (x, y)
            x2, y2 = a[0] + ox, a[1] + oy
            x, y = a[2] + ox, a[3] + oy
            out += [C, x1, y1, x2, y2, x, y]
            nc = (x2, y2)
        elif up == "Q":
            x1, y1 = a[0] + ox, a[1] + oy
            x, y = a[2] + ox, a[3] + oy
            out += [Q, x1, y1, x, y]
            nq = (x1, y1)
        elif up == "T":
            x1, y1 = (2 * x - last_q[0], 2 * y - last_q[1]) if last_q else (x, y)
            x, y = a[0] + ox, a[1] + oy
            out += [Q, x1, y1, x, y]
            nq = (x1, y1)
        else:   # A
            if a[3] not in (0, 1) or a[4] not in (0, 1):
                raise ValueError("arc flags must be 0 or 1: %r" % (d,))
            ex, ey = a[5] + ox, a[6] + oy
            out += _arc(x, y, a[0], a[1], a[2], a[3] != 0, a[4] != 0, ex, ey)
            x, y = ex, ey
        last_c, last_q = nc, nq
    return _round(out)


def _arc(x1: float, y1: float, rx: float, ry: float, angle: float, large: bool, sweep: bool, x2: float,
         y2: float) -> List[float]:
    """An elliptical arc as cubic steps (SVG 1.1 implementation notes F.6.5 and F.6.6)."""
    if x1 == x2 and y1 == y2:
        return []
    rx, ry = abs(rx), abs(ry)
    if rx == 0 or ry == 0:
        return [L, x2, y2]
    phi = math.radians(angle % 360)
    cp, sp = math.cos(phi), math.sin(phi)
    dx, dy = (x1 - x2) / 2, (y1 - y2) / 2
    x1p, y1p = cp * dx + sp * dy, -sp * dx + cp * dy
    lam = (x1p / rx) ** 2 + (y1p / ry) ** 2
    if lam > 1:
        s = math.sqrt(lam)
        rx, ry = rx * s, ry * s
    num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
    den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    co = math.sqrt(max(0.0, num / den)) if den else 0.0
    if large == sweep:
        co = -co
    cxp, cyp = co * rx * y1p / ry, -co * ry * x1p / rx
    cx = cp * cxp - sp * cyp + (x1 + x2) / 2
    cy = sp * cxp + cp * cyp + (y1 + y2) / 2

    def ang(ux: float, uy: float, vx: float, vy: float) -> float:
        return math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)

    t1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry)
    dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    segs = max(1, int(math.ceil(abs(dt) / (math.pi / 2) - 1e-9)))
    step = dt / segs
    k = 4 / 3 * math.tan(step / 4)
    out: List[float] = []

    def pt(t: float) -> Tuple[float, float]:
        ex, ey = rx * math.cos(t), ry * math.sin(t)
        return cp * ex - sp * ey + cx, sp * ex + cp * ey + cy

    def dpt(t: float) -> Tuple[float, float]:
        ex, ey = -rx * math.sin(t), ry * math.cos(t)
        return cp * ex - sp * ey, sp * ex + cp * ey

    t = t1
    px, py = x1, y1
    for s in range(segs):
        t2 = t + step
        qx, qy = pt(t2) if s < segs - 1 else (x2, y2)
        d1, d2 = dpt(t), dpt(t2)
        out += [C, px + k * d1[0], py + k * d1[1], qx - k * d2[0], qy - k * d2[1], qx, qy]
        t, px, py = t2, qx, qy
    return out


# transforms

_TRANSFORM = re.compile(r"\s*(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)\s*,?")


def _mul(m1: Matrix, m2: Matrix) -> Matrix:
    a1, b1, c1, d1, e1, f1 = m1
    a2, b2, c2, d2, e2, f2 = m2
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2, a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def parse_transform(value: Any) -> Matrix:
    """An SVG transform list ("translate(10 0) rotate(-90 28 28)") or a 6-number matrix to (a, b, c, d, e, f)."""
    if not isinstance(value, str):
        m = _numbers("transform", value)
        if len(m) != 6:
            raise ValueError("a transform matrix needs 6 numbers, got %r" % (value,))
        return tuple(m)  # type: ignore[return-value]
    out, pos, s = _IDENTITY, 0, value.strip()
    while pos < len(s):
        hit = _TRANSFORM.match(s, pos)
        if not hit:
            raise ValueError("bad transform %r" % (value,))
        pos = hit.end()
        name, a = hit.group(1), _numbers("transform", hit.group(2))
        if name == "matrix" and len(a) == 6:
            m: Matrix = tuple(a)  # type: ignore[assignment]
        elif name == "translate" and len(a) in (1, 2):
            m = (1, 0, 0, 1, a[0], a[1] if len(a) == 2 else 0)
        elif name == "scale" and len(a) in (1, 2):
            m = (a[0], 0, 0, a[1] if len(a) == 2 else a[0], 0, 0)
        elif name == "rotate" and len(a) in (1, 3):
            r = math.radians(a[0])
            m = (math.cos(r), math.sin(r), -math.sin(r), math.cos(r), 0, 0)
            if len(a) == 3:
                m = _mul(_mul((1, 0, 0, 1, a[1], a[2]), m), (1, 0, 0, 1, -a[1], -a[2]))
        elif name in ("skewX", "skewY") and len(a) == 1:
            t = math.tan(math.radians(a[0]))
            m = (1, 0, t, 1, 0, 0) if name == "skewX" else (1, t, 0, 1, 0, 0)
        else:
            raise ValueError("bad transform %s(%s)" % (name, hit.group(2).strip()))
        out = _mul(out, m)
    return out
