// pyxpo-svg in the browser and the desktop window: a real <svg> element built from the operations Python flattened.
// The page loads this file after app.js (see pyxpoPage in app.js).
(function () {
  "use strict";

  const NS = "http://www.w3.org/2000/svg";
  const CAPS = ["butt", "round", "square"];
  const JOINS = ["miter", "round", "bevel"];
  const ANCHORS = ["start", "middle", "end"];

  function rgb(argb) {
    return "rgb(" + ((argb >>> 16) & 255) + "," + ((argb >>> 8) & 255) + "," + (argb & 255) + ")";
  }

  function alpha(argb) {
    return ((argb >>> 24) & 255) / 255;
  }

  // Path steps are absolute: 0 M x y, 1 L x y, 2 C x1 y1 x2 y2 x y, 3 Q x1 y1 x y, 4 Z.
  function pathData(d) {
    const out = [];
    let i = 0;
    while (i < d.length) {
      switch (d[i]) {
        case 0: out.push("M" + d[i + 1] + " " + d[i + 2]); i += 3; break;
        case 1: out.push("L" + d[i + 1] + " " + d[i + 2]); i += 3; break;
        case 2: out.push("C" + d.slice(i + 1, i + 7).join(" ")); i += 7; break;
        case 3: out.push("Q" + d.slice(i + 1, i + 5).join(" ")); i += 5; break;
        case 4: out.push("Z"); i += 1; break;
        default: i = d.length;
      }
    }
    return out.join("");
  }

  function paint(node, key, argb) {
    if (!argb) { node.setAttribute(key, "none"); return; }
    node.setAttribute(key, rgb(argb));
    const a = alpha(argb);
    if (a < 1) node.setAttribute(key + "-opacity", String(a));
  }

  function element(op) {
    let node;
    if (typeof op.text === "string") {
      node = document.createElementNS(NS, "text");
      node.textContent = op.text;
      node.setAttribute("x", op.x || 0);
      node.setAttribute("y", op.y || 0);
      node.setAttribute("font-size", op.size || 16);
      if (op.weight) node.setAttribute("font-weight", op.weight);
      if (op.family) node.setAttribute("font-family", op.family);
      node.setAttribute("text-anchor", ANCHORS[op.anchor || 0] || "start");
      paint(node, "fill", op.fill || 0);
    } else {
      node = document.createElementNS(NS, "path");
      node.setAttribute("d", pathData(op.d || []));
      paint(node, "fill", op.fill || 0);
      if (op.evenodd) node.setAttribute("fill-rule", "evenodd");
      paint(node, "stroke", op.stroke || 0);
      if (op.stroke) {
        node.setAttribute("stroke-width", op.width == null ? 1 : op.width);
        if (op.cap) node.setAttribute("stroke-linecap", CAPS[op.cap] || "butt");
        if (op.join) node.setAttribute("stroke-linejoin", JOINS[op.join] || "miter");
        if (op.miter != null) node.setAttribute("stroke-miterlimit", op.miter);
        if (op.dash) node.setAttribute("stroke-dasharray", op.dash.join(" "));
        if (op.phase) node.setAttribute("stroke-dashoffset", op.phase);
      }
    }
    if (op.m) node.setAttribute("transform", "matrix(" + op.m.join(" ") + ")");
    return node;
  }

  function makeSvg(el) {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("width", "100%");
    svg.setAttribute("height", "100%");
    svg.style.display = "block";
    svg.style.overflow = "hidden";
    svg.setAttribute("aria-hidden", "true");
    el.appendChild(svg);
    const props = { ops: [], box: null, align: "xMidYMid", slice: false };

    function render() {
      if (props.box) svg.setAttribute("viewBox", props.box.join(" "));
      else svg.removeAttribute("viewBox");
      const a = props.align || "xMidYMid";
      svg.setAttribute("preserveAspectRatio", a === "none" ? "none" : a + (props.slice ? " slice" : " meet"));
      svg.replaceChildren(...(props.ops || []).map(element));
    }

    return {
      update(p, removed) {
        Object.assign(props, p);
        for (const k of removed || []) {
          if (k === "ops") props.ops = [];
          else if (k === "box") props.box = null;
          else if (k === "align") props.align = "xMidYMid";
          else if (k === "slice") props.slice = false;
        }
        render();
      },
      dispose() { svg.remove(); },
    };
  }

  pyxpoPage.defineView("PxSvg", makeSvg);
})();
