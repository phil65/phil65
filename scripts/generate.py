"""Render the profile graphics (timeline + ecosystem, dark + light) from data/profile.toml.

Usage:
    python3 scripts/generate.py            # render assets/*.svg
    python3 scripts/generate.py --fetch    # refresh data/stars.json from the GitHub API first

Standard library only (Python >= 3.11). The SVGs are zero-JS: CSS keyframes + SMIL, system
fonts, no external resources, so they survive GitHub's image sanitizing (rendered via <img>).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import tomllib
import urllib.request
from xml.sax.saxutils import escape


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "profile.toml"
STARS = ROOT / "data" / "stars.json"
ASSETS = ROOT / "assets"
USER = "phil65"

SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,SFMono-Regular,'SF Mono',Menlo,Consolas,monospace"

THEMES = {
    "dark": {
        "bg1": "#0d1117",
        "bg2": "#131a2a",
        "border": "#30363d",
        "panel": "#161b22",
        "panel_border": "#262c36",
        "text": "#e6edf3",
        "muted": "#8b949e",
        "faint": "#21262d",
        "chip_alpha": 0.12,
        "colors": {
            "pink": "#f472b6",
            "orange": "#fb923c",
            "blue": "#60a5fa",
            "amber": "#fbbf24",
            "green": "#34d399",
            "violet": "#a78bfa",
            "indigo": "#818cf8",
            "cyan": "#22d3ee",
            "neutral": "#8b949e",
        },
    },
    "light": {
        "bg1": "#ffffff",
        "bg2": "#f3f5fa",
        "border": "#d0d7de",
        "panel": "#f6f8fa",
        "panel_border": "#d8dee4",
        "text": "#1f2328",
        "muted": "#59636e",
        "faint": "#e6e9ee",
        "chip_alpha": 0.10,
        "colors": {
            "pink": "#db2777",
            "orange": "#c2410c",
            "blue": "#2563eb",
            "amber": "#a16207",
            "green": "#059669",
            "violet": "#7c3aed",
            "indigo": "#4f46e5",
            "cyan": "#0891b2",
            "neutral": "#59636e",
        },
    },
}


# --- helpers -----------------------------------------------------------------------------


def text_width(s: str, size: float) -> float:
    """Rough width of a system sans-serif string (wide enough for Segoe UI / Helvetica)."""
    wide = sum(1 for c in s if c.isupper() or c in "mwMW★")
    narrow = sum(1 for c in s if c in "ilj.,·:;'| ")
    return size * (0.56 * len(s) + 0.14 * wide - 0.24 * narrow)


def t(x: float, y: float, s: str, cls: str, anchor: str = "start", extra: str = "") -> str:
    a = "" if anchor == "start" else f' text-anchor="{anchor}"'
    return f'<text x="{x:g}" y="{y:g}" class="{cls}"{a}{extra}>{escape(s)}</text>'


def fill_stars(label: str, stars: dict[str, int]) -> str:
    return re.sub(r"\{stars:([^}]+)\}", lambda m: str(stars.get(m.group(1), 0)), label)


def svg_doc(w: int, h: int, label: str, style: str, body: list[str], theme: dict) -> str:
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" '
        f'height="{h}" role="img" aria-label="{escape(label)}">'
        f"<title>{escape(label)}</title>"
        f"<style>{style}</style>"
        "<defs>"
        f'<linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{theme["bg1"]}"/>'
        f'<stop offset="1" stop-color="{theme["bg2"]}"/></linearGradient>'
        "</defs>"
        f'<rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="14" fill="url(#bg)" '
        f'stroke="{theme["border"]}"/>' + "".join(body) + "</svg>\n"
    )


def base_css(theme: dict) -> str:
    return (
        f"text{{font-family:{SANS};fill:{theme['text']}}}"
        f".title{{font-size:18px;font-weight:700}}"
        f".sub{{font-size:12.5px;fill:{theme['muted']}}}"
        f".muted{{fill:{theme['muted']}}}"
        f".mono{{font-family:{MONO}}}"
        "@media (prefers-reduced-motion:reduce){*{animation:none!important}}"
    )


# --- timeline ----------------------------------------------------------------------------

T_W = 1000
GAP = 12


def wrap(s: str, size: float, width: float) -> list[str]:
    lines: list[str] = []
    for word in s.split():
        if lines and text_width(f"{lines[-1]} {word}", size) <= width:
            lines[-1] += f" {word}"
        else:
            lines.append(word)
    return lines


def render_timeline(cfg: dict, theme: dict) -> str:
    """Periods as columns of topics, joined by an axis, with a UI / UX rail underneath."""
    c = theme["colors"]
    ui_col = c["pink"]
    periods = cfg["period"]
    n = len(periods)
    cw = (T_W - 64 - (n - 1) * GAP) / n
    cols = [32 + i * (cw + GAP) for i in range(n)]
    inner = cw - 30

    axis_y, card_y = 104, 126
    wrapped = [[wrap(tp, 12, inner) for tp in p["topics"]] for p in periods]
    card_h = 46 + max(sum(len(w) * 15 + 7 for w in ws) for ws in wrapped) + 4
    rail_top = card_y + card_h + 20
    ui_wrapped = [wrap(p["ui"], 12, cw - 12) for p in periods]
    rail_y = rail_top + 42
    band_bottom = rail_y + 26 + max(len(w) for w in ui_wrapped) * 15 + 6
    note = cfg.get("footnote")
    h = int(band_bottom + (40 if note else 32))

    body: list[str] = [t(32, 40, cfg["title"], "title"), t(32, 60, cfg["subtitle"], "sub")]
    defs: list[str] = []
    centers = [x + cw / 2 for x in cols]

    # axis through all period nodes, with a gradient across the period colours
    stops = "".join(
        f'<stop offset="{i / (n - 1):.3f}" stop-color="{c[p["color"]]}"/>' for i, p in enumerate(periods)
    )
    # userSpaceOnUse: a bounding-box gradient on a zero-height line would not render at all
    defs.append(
        f'<linearGradient id="axis" gradientUnits="userSpaceOnUse" x1="{centers[0]:.1f}" '
        f'x2="{centers[-1]:.1f}" y1="0" y2="0">{stops}</linearGradient>'
    )
    defs.append(f'<path id="ax" d="M{centers[0]:.1f} {axis_y} H{centers[-1]:.1f}"/>')
    body.append(
        f'<path d="M{centers[0]:.1f} {axis_y} H{centers[-1]:.1f}" stroke="url(#axis)" '
        'stroke-width="2" fill="none" pathLength="1" class="draw"/>'
    )
    body.append(
        f'<circle r="3" fill="{theme["text"]}" opacity=".8"><animateMotion dur="6s" repeatCount="indefinite" '
        'begin="-1s"><mpath href="#ax"/></animateMotion></circle>'
    )

    for i, (p, x, cx) in enumerate(zip(periods, cols, centers)):
        col = c[p["color"]]
        last = i == n - 1
        d = f"animation-delay:{0.15 + i * 0.12:.2f}s"
        # period node + years
        body.append(t(cx, axis_y - 14, p["years"], "years", "middle", f' style="fill:{col};{d}"'))
        body.append(
            f'<circle cx="{cx:.1f}" cy="{axis_y}" r="6" fill="{theme["bg1"]}" stroke="{col}" '
            f'stroke-width="2.5" class="pop" style="{d}"/>'
        )
        if last:
            body.append(f'<circle cx="{cx:.1f}" cy="{axis_y}" r="2.5" fill="{col}"/>')
            body.append(
                f'<circle class="ping" cx="{cx:.1f}" cy="{axis_y}" r="6" fill="none" stroke="{col}"/>'
            )
        body.append(
            f'<line x1="{cx:.1f}" y1="{axis_y + 6}" x2="{cx:.1f}" y2="{card_y}" stroke="{col}" '
            'stroke-opacity=".5" stroke-dasharray="2 3"/>'
        )
        # card
        g = [
            f'<rect x="{x:.1f}" y="{card_y}" width="{cw:.1f}" height="{card_h}" rx="10" '
            f'fill="{theme["panel"]}" stroke="{col if last else theme["panel_border"]}" '
            f'stroke-opacity="{0.6 if last else 1}"/>',
            f'<rect x="{x + 14:.1f}" y="{card_y}" width="28" height="2" rx="1" fill="{col}"/>',
            t(x + 14, card_y + 26, p["name"], "era"),
        ]
        y = card_y + 50
        for lines in wrapped[i]:
            g.append(f'<circle cx="{x + 17:.1f}" cy="{y - 4}" r="2.5" fill="{col}"/>')
            for j, line in enumerate(lines):
                g.append(t(x + 26, y + j * 15, line, "topic"))
            y += len(lines) * 15 + 7
        body.append(f'<g class="card" style="animation-delay:{0.3 + i * 0.12:.2f}s">{"".join(g)}</g>')

    # UI / UX rail: the thread that runs through every period
    body.append(
        f'<rect x="32" y="{rail_top}" width="{T_W - 64}" height="{band_bottom - rail_top:.0f}" rx="10" '
        f'fill="{ui_col}" fill-opacity="{theme["chip_alpha"] * 0.6:.3f}" stroke="{ui_col}" stroke-opacity=".3"/>'
    )
    body.append(t(46, rail_top + 21, cfg["ui_label"].upper(), "ptitle", extra=f' style="fill:{ui_col}"'))
    rail = f"M{centers[0]:.1f} {rail_y} H{centers[-1]:.1f}"
    defs.append(f'<path id="rl" d="{rail}"/>')
    body.append(
        f'<path d="{rail}" stroke="{ui_col}" stroke-width="2" stroke-opacity=".7" fill="none" '
        'stroke-dasharray="4 4" class="flow"/>'
    )
    for i, cx in enumerate(centers):
        body.append(
            f'<circle cx="{cx:.1f}" cy="{rail_y}" r="5" fill="{theme["bg1"]}" stroke="{ui_col}" '
            f'stroke-width="2" class="pop" style="animation-delay:{0.6 + i * 0.12:.2f}s"/>'
        )
        for j, line in enumerate(ui_wrapped[i]):
            body.append(
                t(cx, rail_y + 24 + j * 15, line, "ui", "middle", f' style="animation-delay:{0.7 + i * 0.12:.2f}s"')
            )
    body.append(
        f'<circle r="3.5" fill="{ui_col}"><animateMotion dur="6s" repeatCount="indefinite" '
        'begin="-3s"><mpath href="#rl"/></animateMotion></circle>'
    )

    if note:
        body.append(t(T_W - 32, h - 16, note, "foot", "end"))

    css = base_css(theme) + (
        f".foot{{font-size:11px;font-style:italic;fill:{theme['muted']}}}"
        ".years{font-size:13px;font-weight:700;animation:fade .6s ease-out both}"
        ".era{font-size:14px;font-weight:700}"
        ".topic{font-size:12px}"
        f".ptitle{{font-size:10.5px;font-weight:700;letter-spacing:.1em}}"
        ".ui{font-size:12px;animation:fade .6s ease-out both}"
        ".card{animation:fade .7s ease-out both}"
        ".pop{transform-box:fill-box;transform-origin:center;animation:pop .5s cubic-bezier(.3,1.6,.5,1) both}"
        ".draw{stroke-dasharray:1;animation:draw 1.2s ease-out both}"
        ".flow{animation:flow 6s linear infinite}"
        ".ping{transform-box:fill-box;transform-origin:center;animation:ping 2s ease-out infinite}"
        "@keyframes fade{from{opacity:0}}"
        "@keyframes pop{from{transform:scale(0)}}"
        "@keyframes draw{from{stroke-dashoffset:1}}"
        "@keyframes flow{to{stroke-dashoffset:-48}}"
        "@keyframes ping{0%{transform:scale(1);opacity:.9}100%{transform:scale(2.6);opacity:0}}"
    )
    body.insert(0, f"<defs>{''.join(defs)}</defs>")
    return svg_doc(T_W, h, f"{USER}: {cfg['subtitle']}", css, body, theme)


# --- ecosystem ---------------------------------------------------------------------------

E_W = 1000


def chip(x: float, y: float, w: float, name: str, col: str, theme: dict) -> str:
    return (
        f'<g><rect x="{x:g}" y="{y:g}" width="{w:g}" height="24" rx="6" fill="{col}" '
        f'fill-opacity="{theme["chip_alpha"]}" stroke="{col}" stroke-opacity=".35"/>'
        f'<circle cx="{x + 11:g}" cy="{y + 12:g}" r="3" fill="{col}"/>'
        + t(x + 21, y + 16.5, name, "chip")
        + "</g>"
    )


def panel(x: float, y: float, w: float, h: float, title: str, col: str, theme: dict) -> list[str]:
    return [
        f'<rect x="{x:g}" y="{y:g}" width="{w:g}" height="{h:g}" rx="10" fill="{theme["panel"]}" '
        f'stroke="{theme["panel_border"]}"/>',
        f'<rect x="{x + 14:g}" y="{y:g}" width="28" height="2" rx="1" fill="{col}"/>',
        t(x + 14, y + 21, title.upper(), "ptitle", extra=f' style="fill:{col}"'),
    ]


def render_ecosystem(cfg: dict, stars: dict[str, int], theme: dict) -> str:
    c = theme["colors"]
    body: list[str] = []
    wires: list[tuple[str, str]] = []  # (path d, colour)
    body.append(t(32, 40, cfg["title"], "title"))
    body.append(t(32, 60, cfg["subtitle"], "sub"))

    hub = cfg["hub"]
    top = [g for g in cfg["group"] if g["row"] == "top"]
    side = next(g for g in cfg["group"] if g["row"] == "side")
    bottom = [g for g in cfg["group"] if g["row"] == "bottom"]
    foundation = next(g for g in bottom if len(g["packages"]) > 1)
    docs = next(g for g in bottom if g is not foundation)

    # row 1: clients <- hub <- side group (Rust bindings)
    r1y, r1h = 84, 96
    sw_ = 274  # width of the two side panels
    hx = 32 + sw_ + 54
    hw = E_W - 2 * hx
    body.append(
        f'<rect class="halo" x="{hx - 6}" y="{r1y - 6}" width="{hw + 12}" height="{r1h + 12}" rx="20" '
        f'fill="none" stroke="url(#hubg)" stroke-width="2"/>'
    )
    body.append(
        f'<rect x="{hx}" y="{r1y}" width="{hw}" height="{r1h}" rx="14" fill="{theme["panel"]}" '
        f'stroke="url(#hubg)" stroke-width="1.6"/>'
    )
    star_label = f"★ {stars.get(hub['repo'], 0)}"
    nw = text_width(hub["name"], 24) * 1.08  # bold
    sw = text_width(star_label, 12) + 18
    gx = hx + hw / 2 - (nw + 10 + sw) / 2
    body.append(t(gx, r1y + 36, hub["name"], "hub"))
    body.append(
        f'<rect x="{gx + nw + 10:.1f}" y="{r1y + 19}" width="{sw:.1f}" height="22" rx="11" '
        f'fill="{c["amber"]}" fill-opacity=".14" stroke="{c["amber"]}" stroke-opacity=".5"/>'
    )
    body.append(t(gx + nw + 10 + sw / 2, r1y + 34.5, star_label, "star", "middle"))
    for i, line in enumerate(hub["tagline"]):
        body.append(t(hx + hw / 2, r1y + 60 + i * 16, line, "tag", "middle"))

    def grid(px: float, py: float, pw: float, names: list[str], col: str, ncols: int = 2) -> None:
        colw = (pw - 28 - (ncols - 1) * 8) / ncols
        for i, name in enumerate(names):
            x_ = px + 14 + (i % ncols) * (colw + 8)
            body.append(chip(x_, py + 32 + (i // ncols) * 30, colw, name, col, theme))

    # clients panel (left), packets flow out of the hub
    body += panel(32, r1y, sw_, r1h, "Serves", c["neutral"], theme)
    grid(32, r1y, sw_, hub["clients"], c["cyan"])
    wires.append((f"M{hx} {r1y + r1h / 2} H{32 + sw_}", c["cyan"]))

    # side panel (right), feeding the hub
    sx = E_W - 32 - sw_
    scol = c[side["color"]]
    body += panel(sx, r1y, sw_, r1h, side["name"], scol, theme)
    grid(sx, r1y, sw_, side["packages"], scol)
    wires.append((f"M{sx} {r1y + r1h / 2} H{hx + hw}", scol))

    # row 2: three groups feeding the hub
    r2y = 226
    pw = (E_W - 64 - 2 * 20) / 3
    rows = max((len(g["packages"]) + 1) // 2 for g in top)
    ph = 34 + rows * 30 + 6
    centers = []
    for gi, g in enumerate(top):
        px = 32 + gi * (pw + 20)
        col = c[g["color"]]
        body += panel(px, r2y, pw, ph, g["name"], col, theme)
        grid(px, r2y, pw, g["packages"], col)
        pcx = px + pw / 2
        centers.append(pcx)
        hbx = hx + hw / 2 + (gi - 1) * 80
        wires.append(
            (f"M{pcx:.1f} {r2y} C{pcx:.1f} {r2y - 26} {hbx:.1f} {r1y + r1h + 26} {hbx:.1f} {r1y + r1h}", col)
        )

    # row 3: foundation (feeding every group) and the docs toolchain under the last column
    r3y = r2y + ph + 40
    fh = 34 + 30
    fcol = c[foundation["color"]]
    dx = 32 + 2 * (pw + 20)
    fw = dx - 20 - 32
    body += panel(32, r3y, fw, fh, foundation["name"], fcol, theme)
    grid(32, r3y, fw, foundation["packages"], fcol, len(foundation["packages"]))
    for pcx in centers[:-1]:
        wires.append((f"M{pcx:.1f} {r3y} V{r2y + ph}", fcol))
    fx, px3 = 32 + fw - 40, centers[-1] - 100
    wires.append((f"M{fx:.1f} {r3y} C{fx:.1f} {r3y - 22} {px3:.1f} {r2y + ph + 22} {px3:.1f} {r2y + ph}", fcol))
    dcol = c[docs["color"]]
    body += panel(dx, r3y, pw, fh, docs["name"], dcol, theme)
    body.append(chip(dx + 14, r3y + 32, 110, docs["packages"][0], dcol, theme))
    if note := docs.get("note"):
        body.append(t(dx + 136, r3y + 48.5, note, "pnote"))
    wires.append((f"M{32 + fw} {r3y + fh / 2 + 10} H{dx}", fcol))

    h = int(r3y + fh + 32)
    count = sum(len(g["packages"]) for g in cfg["group"])
    body.append(t(E_W - 32, 40, f"{count} packages", "count", "end"))
    body.append(t(E_W - 32, 60, f"github.com/{USER}", "sub mono", "end"))

    # wires + packets (all loops share one 4 s period, so the cycle is seamless)
    wire_svg, packet_svg = [], []
    for i, (d, col) in enumerate(wires):
        wire_svg.append(
            f'<path id="w{i}" d="{d}" fill="none" stroke="{col}" stroke-opacity=".45" '
            'stroke-width="1.5" stroke-dasharray="3 5" class="flow"/>'
        )
        for j in range(2):
            begin = -(i * 0.7 + j * 2) % 4
            packet_svg.append(
                f'<circle r="3" fill="{col}"><animateMotion dur="4s" repeatCount="indefinite" '
                f'begin="-{begin:.1f}s"><mpath href="#w{i}"/></animateMotion></circle>'
            )
    defs = (
        "<defs>"
        '<linearGradient id="hubg" x1="0" x2="1">'
        f'<stop offset="0" stop-color="{c["violet"]}"/><stop offset="1" stop-color="{c["cyan"]}"/>'
        "</linearGradient></defs>"
    )
    css = base_css(theme) + (
        f".hub{{font-size:24px;font-weight:700}}"
        f".star{{font-size:12px;font-weight:600;fill:{c['amber']}}}"
        f".tag{{font-size:12px;fill:{theme['muted']}}}"
        f".count{{font-size:13px;font-weight:600;fill:{theme['muted']}}}"
        f".ptitle{{font-size:10.5px;font-weight:700;letter-spacing:.1em}}"
        f".pnote{{font-size:11px;font-style:italic;fill:{theme['muted']}}}"
        f".chip{{font-size:12.5px}}"
        ".flow{animation:flow 4s linear infinite}"
        "@keyframes flow{to{stroke-dashoffset:-48}}"
        ".halo{opacity:.35;animation:halo 4s ease-in-out infinite}"
        "@keyframes halo{50%{opacity:.85}}"
    )
    return svg_doc(
        E_W, h, f"{USER}: {cfg['title']}", css, [defs, *wire_svg, *body, *packet_svg], theme
    )


# --- main --------------------------------------------------------------------------------


def fetch_stars() -> dict[str, int]:
    """All public source repos of USER with their star counts (GITHUB_TOKEN optional)."""
    out: dict[str, int] = {}
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "profile-generator"}
    if token := os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {token}"
    page = 1
    while True:
        url = f"https://api.github.com/users/{USER}/repos?type=owner&per_page=100&page={page}"
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers)) as r:
            batch = json.load(r)
        if not batch:
            break
        out.update({r["name"]: r["stargazers_count"] for r in batch if not r["fork"]})
        page += 1
    return {k: v for k, v in sorted(out.items()) if v > 0}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fetch", action="store_true", help="refresh data/stars.json first")
    args = ap.parse_args()
    if args.fetch:
        STARS.write_text(json.dumps(fetch_stars(), indent=2) + "\n")
    stars = json.loads(STARS.read_text())
    cfg = tomllib.loads(DATA.read_text())
    ASSETS.mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        outputs = {
            f"timeline-{name}.svg": render_timeline(cfg["timeline"], theme),
            f"ecosystem-{name}.svg": render_ecosystem(cfg["ecosystem"], stars, theme),
        }
        for fn, svg in outputs.items():
            (ASSETS / fn).write_text(svg)
            print(f"{fn}: {len(svg.encode()) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
