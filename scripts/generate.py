"""Render the profile graphics (timeline + ecosystem, dark + light) from data/profile.toml.

Usage:
    python3 scripts/generate.py            # render assets/*.svg
    python3 scripts/generate.py --fetch    # refresh data/stars.json from the GitHub API first

Standard library only (Python >= 3.11). The SVGs are zero-JS: CSS keyframes + SMIL, system
fonts, no external resources, so they survive GitHub's image sanitizing (rendered via <img>).
"""

from __future__ import annotations

import argparse
import datetime as dt
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
            "blue": "#60a5fa",
            "amber": "#fbbf24",
            "green": "#34d399",
            "violet": "#a78bfa",
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
            "blue": "#2563eb",
            "amber": "#b45309",
            "green": "#059669",
            "violet": "#7c3aed",
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
X0, X1 = 224, 968
PITCH = 60
ROW0 = 112


def month(s: str, now: dt.date) -> float:
    if s == "now":
        return now.year + (now.month - 0.5) / 12
    y, m = s.split("-")
    return int(y) + (int(m) - 0.5) / 12


def make_scale(points: list[list[float]]):
    years = [p[0] for p in points]
    weights = [p[1] for p in points]
    total = sum(w * (years[i + 1] - years[i]) for i, w in enumerate(weights[:-1]))
    k = (X1 - X0) / total

    def x(v: float) -> float:
        acc = X0
        for i in range(len(years) - 1):
            a, b = years[i], years[i + 1]
            if v <= b or i == len(years) - 2:
                return acc + (min(v, b) - a) * weights[i] * k
            acc += (b - a) * weights[i] * k
        return acc

    return x, [int(y) for y in range(int(years[0]), int(years[-1]))], weights, years, k


def render_timeline(cfg: dict, stars: dict[str, int], theme: dict, now: dt.date) -> str:
    c = theme["colors"]
    scale = [list(p) for p in cfg["scale"]]
    scale[-1][0] = max(scale[-1][0], now.year + 1)  # keep "now" inside the plot
    x, year_list, weights, years, k = make_scale(scale)
    tracks = [(lane, tr) for lane in cfg["lane"] for tr in lane["track"]]
    h = ROW0 + len(tracks) * PITCH + 18
    body: list[str] = []
    defs: list[str] = []

    body.append(t(32, 40, cfg["title"], "title"))
    body.append(t(32, 60, cfg["subtitle"], "sub"))

    # year grid: always label the years where the scale changes, the others where there is room
    labelled = [x(y) for y in years if y in year_list]
    for yr in year_list:
        gx = x(yr)
        if yr not in years and all(abs(gx - o) >= 40 for o in labelled):
            labelled.append(gx)
        body.append(
            f'<line x1="{gx:.1f}" y1="98" x2="{gx:.1f}" y2="{h - 14}" stroke="{theme["faint"]}"/>'
        )
        if any(abs(gx - o) < 0.01 for o in labelled):
            body.append(t(gx, 92, str(yr), "year mono", "middle"))

    # now marker
    nx = x(month("now", now))
    body.append(
        f'<line x1="{nx:.1f}" y1="98" x2="{nx:.1f}" y2="{h - 14}" stroke="{c["violet"]}" '
        'stroke-dasharray="2 4" opacity=".7"/>'
    )
    body.append(t(nx, 76, "now", "now", "middle"))
    body.append(f'<circle cx="{nx:.1f}" cy="98" r="3.5" fill="{c["violet"]}"/>')
    body.append(
        f'<circle class="ping" cx="{nx:.1f}" cy="98" r="3.5" fill="none" stroke="{c["violet"]}"/>'
    )

    clip_rects: list[str] = []
    row = 0
    for lane in cfg["lane"]:
        col = c[lane["color"]]
        n = len(lane["track"])
        top = ROW0 + row * PITCH
        # lane bracket (and a rotated lane label when the lane groups several tracks)
        body.append(
            f'<rect x="46" y="{top + 8}" width="3" height="{n * PITCH - 16}" rx="1.5" fill="{col}"/>'
        )
        if n > 1:
            cy = top + n * PITCH / 2
            body.append(
                f'<text x="38" y="{cy:g}" class="lane" text-anchor="middle" fill="{col}" '
                f'transform="rotate(-90 38 {cy:g})" style="fill:{col}">'
                f"{escape(lane['name'].upper())}</text>"
            )
        if row:
            body.append(
                f'<line x1="32" y1="{top:g}" x2="{T_W - 32}" y2="{top:g}" '
                f'stroke="{theme["faint"]}" stroke-dasharray="1 3"/>'
            )
        for tr in lane["track"]:
            by = ROW0 + row * PITCH + 30  # bar centre
            delay = 0.15 + row * 0.09
            body.append(t(58, by - 3, tr["name"], "tname"))
            body.append(t(58, by + 12, tr.get("sub", ""), "tsub"))
            hl = tr.get("highlight", False)
            bh = 10 if hl else 8
            for a, b in tr["spans"]:
                xa, xb = x(month(a, now)), x(month(b, now))
                gid = f"g{row}"
                if gid not in "".join(defs):
                    defs.append(
                        f'<linearGradient id="{gid}" x1="0" x2="1">'
                        f'<stop offset="0" stop-color="{col}" stop-opacity=".45"/>'
                        f'<stop offset="1" stop-color="{c["cyan"] if hl else col}"/>'
                        "</linearGradient>"
                    )
                rect = (
                    f'x="{xa:.1f}" y="{by - bh / 2:g}" width="{max(xb - xa, 4):.1f}" '
                    f'height="{bh}" rx="{bh / 2:g}"'
                )
                if hl:
                    body.append(
                        f'<rect {rect} fill="{col}" opacity=".25" class="glow bar" '
                        f'style="animation-delay:{delay:.2f}s"/>'
                    )
                body.append(
                    f'<rect {rect} fill="url(#{gid})" class="bar" style="animation-delay:{delay:.2f}s"/>'
                )
                clip_rects.append(f"<rect {rect}/>")
            # milestone labels: greedy placement into slots, no overlaps
            slots: dict[str, list[tuple[float, float]]] = {"above": [], "below": [], "below2": []}
            order = ["below", "above", "below2"]
            if note := tr.get("note"):
                xa = x(month(tr["spans"][0][0], now))
                body.append(t(xa, by - 10, note, "note"))
                slots["above"].append((xa, xa + text_width(note, 11)))
                order = ["below", "below2"]
            ys = {"above": by - 10, "below": by + 19, "below2": by + 32}
            for ms in sorted(tr["milestones"], key=lambda m: (m.get("minor", False), not m.get("strong"))):
                mx = x(month(ms["date"], now))
                minor = ms.get("minor", False)
                body.append(
                    f'<circle cx="{mx:.1f}" cy="{by}" r="{2.2 if minor else 4.2}" '
                    f'fill="{theme["bg1"] if not minor else col}" stroke="{col}" '
                    f'stroke-width="{0 if minor else 2.2}" class="ms" '
                    f'style="animation-delay:{delay + 0.6:.2f}s"/>'
                )
                if minor:
                    continue
                label = fill_stars(ms["label"], stars)
                w = text_width(label, 11.5)
                lx, anchor = mx - 3, "start"
                if lx + w > T_W - 24:
                    lx, anchor = mx + 3, "end"
                span = (lx, lx + w) if anchor == "start" else (lx - w, lx)
                for slot in order:
                    if all(span[1] + 8 < s0 or span[0] - 8 > s1 for s0, s1 in slots[slot]):
                        slots[slot].append(span)
                        body.append(
                            t(lx, ys[slot], label, "ml strong" if ms.get("strong") else "ml", anchor, f' style="animation-delay:{delay + 0.7:.2f}s"')
                        )
                        break
                else:
                    print(f"warning: no room for label {label!r} in track {tr['name']!r}")
            row += 1

    # light sweep through the bars: a moving gradient on a static, clipped rect
    sweep_op = 0.35 if theme is THEMES["dark"] else 0.7
    defs.append(f'<clipPath id="bars">{"".join(clip_rects)}</clipPath>')
    defs.append(
        f'<linearGradient id="sweep" gradientUnits="userSpaceOnUse" x1="{X0 - 140}" x2="{X0}">'
        '<stop offset="0" stop-color="#fff" stop-opacity="0"/>'
        f'<stop offset=".5" stop-color="#fff" stop-opacity="{sweep_op}"/>'
        '<stop offset="1" stop-color="#fff" stop-opacity="0"/>'
        f'<animateTransform attributeName="gradientTransform" type="translate" dur="8s" '
        f'begin="1.4s" repeatCount="indefinite" keyTimes="0;.7;1" '
        f'values="0 0;{X1 - X0 + 140} 0;{X1 - X0 + 140} 0"/>'
        "</linearGradient>"
    )
    body.append(
        f'<rect clip-path="url(#bars)" x="{X0}" y="{ROW0}" width="{X1 - X0}" '
        f'height="{h - ROW0}" fill="url(#sweep)"/>'
    )

    css = base_css(theme) + (
        f".year{{font-size:11px;fill:{theme['muted']}}}"
        f".now{{font-size:11px;font-weight:600;fill:{c['violet']}}}"
        f".lane{{font-size:10px;font-weight:700;letter-spacing:.12em}}"
        f".tname{{font-size:13px;font-weight:600}}"
        f".tsub{{font-size:11px;fill:{theme['muted']}}}"
        f".note{{font-size:11px;font-style:italic;fill:{theme['muted']};animation:fade 1s ease-out .3s both}}"
        f".ml{{font-size:11.5px;animation:fade .6s ease-out both}}"
        f".strong{{font-weight:700}}"
        ".bar{transform-box:fill-box;transform-origin:left center;"
        "animation:grow 1.1s cubic-bezier(.2,.7,.2,1) both}"
        ".ms{animation:fade .5s ease-out both}"
        ".glow{filter:blur(3px)}"
        ".ping{transform-box:fill-box;transform-origin:center;animation:ping 2s ease-out infinite}"
        "@keyframes grow{from{transform:scaleX(0)}}"
        "@keyframes fade{from{opacity:0}}"
        "@keyframes ping{0%{transform:scale(1);opacity:.9}100%{transform:scale(3.2);opacity:0}}"
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
    bottom = [g for g in cfg["group"] if g["row"] == "bottom"]
    foundation = next(g for g in bottom if len(g["packages"]) > 1)
    docs = next(g for g in bottom if g is not foundation)

    # row 1: clients <- hub <- docs toolchain
    r1y, r1h = 84, 96
    hx, hw = 340, 320
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

    # clients panel (left), packets flow out of the hub
    cx, cw = 32, 248
    body += panel(cx, r1y, cw, r1h, "Serves", c["neutral"], theme)
    colw = (cw - 28 - 8) / 2
    for i, name in enumerate(hub["clients"]):
        body.append(chip(cx + 14 + (i % 2) * (colw + 8), r1y + 32 + (i // 2) * 30, colw, name, c["cyan"], theme))
    wires.append((f"M{hx} {r1y + r1h / 2} H{cx + cw}", c["cyan"]))

    # docs toolchain panel (right)
    dx = 720
    dw = E_W - 32 - dx
    dcol = c[docs["color"]]
    body += panel(dx, r1y, dw, r1h, docs["name"], dcol, theme)
    for i, name in enumerate(docs["packages"]):
        body.append(chip(dx + 14, r1y + 32 + i * 30, 110, name, dcol, theme))
    if note := docs.get("note"):
        body.append(t(dx + 14, r1y + 78, note, "pnote"))
    wires.append((f"M{dx} {r1y + r1h / 2} H{hx + hw}", dcol))

    # row 2: three groups feeding the hub
    r2y = 226
    pw = (E_W - 64 - 2 * 20) / 3
    rows = max((len(g["packages"]) + 1) // 2 for g in top)
    ph = 34 + rows * 30 + 6
    colw = (pw - 28 - 8) / 2
    centers = []
    for gi, g in enumerate(top):
        px = 32 + gi * (pw + 20)
        col = c[g["color"]]
        body += panel(px, r2y, pw, ph, g["name"], col, theme)
        for i, name in enumerate(g["packages"]):
            body.append(chip(px + 14 + (i % 2) * (colw + 8), r2y + 32 + (i // 2) * 30, colw, name, col, theme))
        pcx = px + pw / 2
        centers.append(pcx)
        hbx = hx + hw / 2 + (gi - 1) * 90
        wires.append(
            (f"M{pcx:.1f} {r2y} C{pcx:.1f} {r2y - 26} {hbx:.1f} {r1y + r1h + 26} {hbx:.1f} {r1y + r1h}", col)
        )

    # row 3: foundation, feeding every group
    r3y = r2y + ph + 40
    fh = 34 + 30
    fcol = c[foundation["color"]]
    fw = E_W - 64
    body += panel(32, r3y, fw, fh, foundation["name"], fcol, theme)
    n = len(foundation["packages"])
    cwid = (fw - 28 - (n - 1) * 10) / n
    for i, name in enumerate(foundation["packages"]):
        body.append(chip(46 + i * (cwid + 10), r3y + 32, cwid, name, fcol, theme))
    for pcx in centers:
        wires.append((f"M{pcx:.1f} {r3y} V{r2y + ph}", fcol))

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
    now = dt.date.today()
    ASSETS.mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        outputs = {
            f"timeline-{name}.svg": render_timeline(cfg["timeline"], stars, theme, now),
            f"ecosystem-{name}.svg": render_ecosystem(cfg["ecosystem"], stars, theme),
        }
        for fn, svg in outputs.items():
            (ASSETS / fn).write_text(svg)
            print(f"{fn}: {len(svg.encode()) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
