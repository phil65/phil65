# /// script
# requires-python = ">=3.13"
# dependencies = ["mknodes>=4.1"]
# ///
"""Build the profile README and its graphics from data/profile.toml.

Usage:
    uv run scripts/generate.py            # README.md, assets/*.svg, assets/ecosystem.mmd
    uv run scripts/generate.py --fetch    # refresh data/stars.json from the GitHub API first

- timeline-{dark,light}.svg: drawn here (zero-JS: CSS keyframes + SMIL, system fonts).
- ecosystem.mmd: a Mermaid block-beta diagram written here, rendered to
  ecosystem-{dark,light}.svg by mmd-viz (needs Node / npx).
- README.md: built with mknodes (GitHub flavour).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import subprocess
import tomllib
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape

import mknodes as mk

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data" / "profile.toml"
STARS = ROOT / "data" / "stars.json"
ASSETS = ROOT / "assets"
USER = "phil65"

SANS = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI','Noto Sans',Helvetica,Arial,sans-serif"
)
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


def t(
    x: float, y: float, s: str, cls: str, anchor: str = "start", extra: str = ""
) -> str:
    a = "" if anchor == "start" else f' text-anchor="{anchor}"'
    return f'<text x="{x:g}" y="{y:g}" class="{cls}"{a}{extra}>{escape(s)}</text>'


def fill_stars(label: str, stars: dict[str, int]) -> str:
    return re.sub(r"\{stars:([^}]+)\}", lambda m: str(stars.get(m.group(1), 0)), label)


def svg_doc(
    w: int, h: int, label: str, style: str, body: list[str], theme: dict
) -> str:
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

    body: list[str] = [
        t(32, 40, cfg["title"], "title"),
        t(32, 60, cfg["subtitle"], "sub"),
    ]
    defs: list[str] = []
    centers = [x + cw / 2 for x in cols]

    # axis through all period nodes, with a gradient across the period colours
    stops = "".join(
        f'<stop offset="{i / (n - 1):.3f}" stop-color="{c[p["color"]]}"/>'
        for i, p in enumerate(periods)
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
        body.append(
            t(
                cx,
                axis_y - 14,
                p["years"],
                "years",
                "middle",
                f' style="fill:{col};{d}"',
            )
        )
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
            (
                f'<rect x="{x:.1f}" y="{card_y}" width="{cw:.1f}" height="{card_h}" rx="10" '
                f'fill="{theme["panel"]}" stroke="{col if last else theme["panel_border"]}" '
                f'stroke-opacity="{0.6 if last else 1}"/>'
            ),
            f'<rect x="{x + 14:.1f}" y="{card_y}" width="28" height="2" rx="1" fill="{col}"/>',
            t(x + 14, card_y + 26, p["name"], "era"),
        ]
        y = card_y + 50
        for lines in wrapped[i]:
            g.append(f'<circle cx="{x + 17:.1f}" cy="{y - 4}" r="2.5" fill="{col}"/>')
            for j, line in enumerate(lines):
                g.append(t(x + 26, y + j * 15, line, "topic"))
            y += len(lines) * 15 + 7
        body.append(
            f'<g class="card" style="animation-delay:{0.3 + i * 0.12:.2f}s">{"".join(g)}</g>'
        )

    # UI / UX rail: the thread that runs through every period
    body.append(
        f'<rect x="32" y="{rail_top}" width="{T_W - 64}" height="{band_bottom - rail_top:.0f}" rx="10" '
        f'fill="{ui_col}" fill-opacity="{theme["chip_alpha"] * 0.6:.3f}" stroke="{ui_col}" stroke-opacity=".3"/>'
    )
    body.append(
        t(
            46,
            rail_top + 21,
            cfg["ui_label"].upper(),
            "ptitle",
            extra=f' style="fill:{ui_col}"',
        )
    )
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
                t(
                    cx,
                    rail_y + 24 + j * 15,
                    line,
                    "ui",
                    "middle",
                    f' style="animation-delay:{0.7 + i * 0.12:.2f}s"',
                )
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


# --- ecosystem (Mermaid -> mmd-viz) ------------------------------------------------------


def node_id(name: str) -> str:
    return re.sub(r"\W", "_", name.split("<")[0])


def ecosystem_mermaid(cfg: dict, stars: dict[str, int]) -> str:
    """The ecosystem as a Mermaid block-beta diagram (panels via `class <block> <accent>`)."""
    lines = ["block-beta", f"  columns {cfg['columns']}"]
    classes = []
    for b in cfg["block"]:
        if b.get("hub"):
            label = "<br/>".join(fill_stars(x, stars) for x in b["label"])
            lines.append(f'  {b["id"]}["{label}"]')
            classes.append(f"  class {b['id']} hub")
            continue
        span = b.get("span", 1)
        lines.append(f'  block:{b["id"]}["{b["name"]}"]:{span}')
        lines.append(f"    columns {b.get('columns', 2)}")
        nodes = [
            p if re.fullmatch(r"[A-Za-z_]\w*", p) else f'{node_id(p)}["{p}"]'
            for p in b["packages"]
        ]
        lines.append("    " + " ".join(nodes))
        lines.append("  end")
        classes.append(f"  class {b['id']} {b['color']}")
    lines += [f"  {a} --> {b}" for a, b in cfg["edges"]]
    return "\n".join([*lines, *classes]) + "\n"


def render_mermaid(src: Path, out: Path, theme: str, cfg: dict) -> None:
    cmd = [
        "npx", "-y", f"mmd-viz@{cfg['mmd_viz']}", str(src), "--theme", theme,
        "--title", cfg["title"], "--footer", cfg["footer"], "-o", str(out),
    ]  # fmt: skip
    subprocess.run(cmd, check=True)


# --- README (mknodes, GitHub flavour) ----------------------------------------------------


def picture(name: str, alt: str) -> str:
    return (
        "<picture>\n"
        f'  <source media="(prefers-color-scheme: dark)" srcset="assets/{name}-dark.svg">\n'
        f'  <source media="(prefers-color-scheme: light)" srcset="assets/{name}-light.svg">\n'
        f'  <img alt="{escape(alt)}" src="assets/{name}-light.svg" width="100%">\n'
        "</picture>"
    )


def build_readme(cfg: dict, mermaid: str) -> str:
    rd = cfg["readme"]
    page = mk.MkPage()
    page += mk.MkHeader(rd["greeting"], level=3)
    page += mk.MkText(rd["intro"].strip())
    # raw HTML via MkText: MkHtmlBlock drops its wrapper element in the GitHub flavour
    page += mk.MkText(picture("timeline", rd["timeline_alt"]))
    page += mk.MkText(picture("ecosystem", cfg["ecosystem"]["alt"]))
    # ```mmd: GitHub highlights it as Mermaid but does not render it as a diagram
    page += mk.MkDetailsBlock(
        mk.MkCode(mermaid.rstrip(), language="mmd"), title="Mermaid source"
    )
    page += mk.MkHeader("Featured", level=4)
    rows = [
        {
            "Project": " · ".join(f"[{n}]({u})" for n, u in f["links"]),
            "What it is": f["what"],
        }
        for f in rd["featured"]
    ]
    page += mk.MkTable(rows)
    page += mk.MkDetailsBlock("![Metrics](/github-metrics.svg)", title="GitHub metrics")
    page += mk.MkText(
        "<sub>" + "<br>\n".join(rd["footnote"].strip().splitlines()) + "</sub>"
    )
    md = asyncio.run(page.to_markdown(flavor="github"))
    return re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"


# --- main --------------------------------------------------------------------------------


def fetch_stars() -> dict[str, int]:
    """All public source repos of USER with their star counts (GITHUB_TOKEN optional)."""
    out: dict[str, int] = {}
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "profile-generator",
    }
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
    ap.add_argument(
        "--fetch", action="store_true", help="refresh data/stars.json first"
    )
    args = ap.parse_args()
    if args.fetch:
        STARS.write_text(json.dumps(fetch_stars(), indent=2) + "\n")
    stars = json.loads(STARS.read_text())
    cfg = tomllib.loads(DATA.read_text())
    ASSETS.mkdir(exist_ok=True)
    for name, theme in THEMES.items():
        svg = render_timeline(cfg["timeline"], theme)
        (ASSETS / f"timeline-{name}.svg").write_text(svg)
        print(f"timeline-{name}.svg: {len(svg.encode()) / 1024:.1f} KB")
    mermaid = ecosystem_mermaid(cfg["ecosystem"], stars)
    src = ASSETS / "ecosystem.mmd"
    src.write_text(mermaid)
    for name in THEMES:
        out = ASSETS / f"ecosystem-{name}.svg"
        render_mermaid(src, out, name, cfg["ecosystem"])
        print(f"{out.name}: {out.stat().st_size / 1024:.1f} KB")
    (ROOT / "README.md").write_text(build_readme(cfg, mermaid))
    print("README.md")


if __name__ == "__main__":
    main()
