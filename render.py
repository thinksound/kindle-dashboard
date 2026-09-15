#!/usr/bin/env python3
"""
Kindle Paperwhite care-dashboard renderer.

Renders the TNKSND care dashboard as a 1236x1648 grayscale PNG optimized
for e-ink: pure black on pure white, high-contrast type, no color,
no thin lines, no alpha.

Layout (portrait 1236x1648):
  - Header: TNKSND wordmark
  - Left:  today's date, very large (month / day / weekday / year)
  - Right: this month's calendar, today inverted (white on black)
  - Bottom: daily Henri Nouwen quote (rotates) with Bible verse
  - Footer: render timestamp so staleness is visible on the e-ink panel

Usage:
    python3 render.py --out dashboard.png
    python3 render.py --date 2026-08-15 --out test.png   # preview another date
    python3 render.py --serve --port 8000                # HTTP server for the Kindle

Requires: Pillow  (`pip install pillow`)
Fonts are bundled under ./fonts/ (M PLUS Rounded 1c + Noto Sans JP variable
+ Atkinson Hyperlegible, all SIL OFL). System fallbacks are tried if missing.
"""

import argparse
import calendar
import datetime
import io
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1236, 1648
BLACK, WHITE = 0, 255
BASE = Path(__file__).resolve().parent

# Type scale (M PLUS Rounded 1c, all Regular — no bold anywhere):
#   380 day / 130 month / 104 weekday / 64 year & calendar title /
#   52 quote / 48 calendar cells / 40 attribution & verse / 34 footer
# Latin (Atkinson Hyperlegible Regular): 48 wordmark, 40 verse ref.

# ---------------------------------------------------------------- fonts ---

def _load_first(candidates, size):
    """Try (path, ttc_index) candidates in order; return first that loads."""
    for path, index in candidates:
        try:
            return ImageFont.truetype(str(path), size, index=index)
        except Exception:
            continue
    raise RuntimeError("no usable font found")


def jp_font(size, weight="Regular"):
    """Japanese-capable font, Regular throughout (no bold by design).

    M PLUS Rounded 1c (SIL OFL) — friendly rounded gothic, chosen by
    Tetsuro 2026-09-15. Static weights are bundled; SemiBold/Medium map
    to Bold and Light/Thin map to Regular (kept for API compatibility).
    """
    weight_files = {
        "Bold": "MPLUSRounded1c-Bold.ttf",
        "SemiBold": "MPLUSRounded1c-Bold.ttf",
        "Medium": "MPLUSRounded1c-Bold.ttf",
        "Regular": "MPLUSRounded1c-Regular.ttf",
        "Light": "MPLUSRounded1c-Regular.ttf",
        "Thin": "MPLUSRounded1c-Regular.ttf",
    }
    bundled = BASE / "fonts" / weight_files.get(weight, "MPLUSRounded1c-Bold.ttf")
    if bundled.exists():
        return ImageFont.truetype(str(bundled), size)
    # legacy fallback: Noto Sans JP variable (also bundled)
    legacy = BASE / "fonts" / "NotoSansJP-VF.ttf"
    if legacy.exists():
        f = ImageFont.truetype(str(legacy), size)
        try:
            f.set_variation_by_name(weight)
        except Exception:
            pass
        return f
    cands = [
        # macOS (M4 Mac Mini): Hiragino in the system font folder
        ("/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc", 0),
        ("/System/Library/Fonts/Hiragino Sans GB.ttc", 0),
        # Linux: Noto CJK (JP face is index 2 in the .ttc ordering used here)
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 2),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", 2),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
    ]
    return _load_first(cands, size)


def latin_font(size, bold=True):
    """Atkinson Hyperlegible (low-vision design) for Latin text."""
    name = "AtkinsonHyperlegible-Bold.otf" if bold else "AtkinsonHyperlegible-Regular.otf"
    bundled = BASE / "fonts" / name
    if bundled.exists():
        return ImageFont.truetype(str(bundled), size)
    cands = [
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
         else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 0),
        ("/System/Library/Fonts/Helvetica.ttc", 1 if bold else 0),
    ]
    return _load_first(cands, size)


# --------------------------------------------------------------- quotes ---
# Genuine, well-known published Henri Nouwen lines, translated simply into
# Japanese. (verse_jp, verse_en) give the accompanying Bible reference.
QUOTES = [
    ("喜びは向こうからやって来るものではありません。"
     "喜びを選び、毎日選び続けるのです。",
     "詩篇 118:24", "Psalm 118:24"),
    ("人生でいちばん大切な人は、助言や解決策をくれる人ではなく、"
     "私たちの痛みを共にし、傷に温かい手を添えてくれる人です。",
     "ローマ 12:15", "Romans 12:15"),
    ("もてなしとは、見知らぬ人が入り、敵ではなく友となるための、"
     "自由な場をつくることです。",
     "ヘブル 13:2", "Hebrews 13:2"),
    ("孤独は、変容のための炉です。",
     "マルコ 1:35", "Mark 1:35"),
    ("新しい生き方は、考えて見つけるものではありません。"
     "生きることで、考え方が新しくなるのです。",
     "ローマ 12:2", "Romans 12:2"),
    ("自己否定は、霊的な人生の最大の敵です。"
     "私たちは「愛されている者」と呼ばれているのですから。",
     "イザヤ 43:1", "Isaiah 43:1"),
    ("「愛されている者」であること。"
     "それが、私たちの存在の中心にある真理です。",
     "ヨハネの手紙一 3:1", "1 John 3:1"),
    ("赦しとは、不器用にしか愛せない人々のあいだで実践される、"
     "愛の別名です。",
     "コロサイ 3:13", "Colossians 3:13"),
]

WEEKDAYS_JP = ["日", "月", "火", "水", "木", "金", "土"]

MARGIN = 56


def wrap_ja(draw, text, font, max_w):
    """Greedy character wrap for Japanese (no spaces to break on)."""
    lines, cur = [], ""
    for ch in text:
        if font.getlength(cur + ch) <= max_w:
            cur += ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def render(target_date=None, now=None):
    today = target_date or datetime.date.today()
    now = now or datetime.datetime.now()
    year, month, day = today.year, today.month, today.day

    img = Image.new("L", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    # ---------------------------------------------------------- header ---
    d.text((MARGIN, 100), "TNKSND", font=latin_font(48, bold=False), fill=BLACK, anchor="lm")
    d.line([(MARGIN, 160), (W - MARGIN, 160)], fill=BLACK, width=4)

    # ------------------------------------------------- left: big date ---
    d.text((MARGIN, 250), f"{month}月", font=jp_font(130), fill=BLACK, anchor="lm")
    d.text((MARGIN, 560), f"{day}", font=jp_font(380), fill=BLACK, anchor="lm")
    wd = WEEKDAYS_JP[(datetime.date(year, month, day).weekday() + 1) % 7]  # Mon=0..Sun=6 -> Sun-first list
    d.text((MARGIN, 840), f"{wd}曜日", font=jp_font(104), fill=BLACK, anchor="lm")
    d.text((MARGIN, 965), f"{year}年", font=jp_font(64), fill=BLACK, anchor="lm")

    # vertical divider between date and calendar
    d.line([(648, 200), (648, 1050)], fill=BLACK, width=6)

    # ------------------------------------------------ right: calendar ---
    cx0, cx1 = 700, W - MARGIN          # 700..1180
    d.text(((cx0 + cx1) // 2, 250), f"{year}年 {month}月",
           font=jp_font(64), fill=BLACK, anchor="mm")

    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)
    cw, chh = 68, 100
    gx = cx0 + ((cx1 - cx0) - 7 * cw) // 2   # center the 7-col grid
    # weekday header row
    wdf = jp_font(48)
    for c, label in enumerate(WEEKDAYS_JP):
        x = gx + c * cw + cw // 2
        d.text((x, 340), label, font=wdf, fill=BLACK, anchor="mm")
    # day cells
    nf = jp_font(48)
    gy = 395
    for r, week in enumerate(weeks):
        for c, dnum in enumerate(week):
            if not dnum:
                continue
            x = gx + c * cw + cw // 2
            y = gy + r * chh + chh // 2
            if dnum == day:  # today: inverted for maximum contrast
                d.rounded_rectangle([gx + c * cw + 5, gy + r * chh + 8,
                                     gx + (c + 1) * cw - 5, gy + (r + 1) * chh - 8],
                                    radius=12, fill=BLACK)
                d.text((x, y), str(dnum), font=nf, fill=WHITE, anchor="mm")
            else:
                d.text((x, y), str(dnum), font=nf, fill=BLACK, anchor="mm")

    # ------------------------------------------------- divider + quote ---
    d.line([(MARGIN, 1085), (W - MARGIN, 1085)], fill=BLACK, width=6)

    quote, verse_jp, verse_en = QUOTES[today.timetuple().tm_yday % len(QUOTES)]
    # thick accent bar, pure black (no gray on e-ink)
    d.rectangle([MARGIN, 1130, MARGIN + 18, 1490], fill=BLACK)

    qfont = jp_font(52)
    lines = wrap_ja(d, quote, qfont, (W - MARGIN) - 120)
    y = 1155
    for line in lines[:4]:
        d.text((120, y), line, font=qfont, fill=BLACK, anchor="la")
        y += 76

    d.text((W - MARGIN, 1445), "— ヘンリー・ノーウェン",
           font=jp_font(40, weight="Regular"), fill=BLACK, anchor="ra")
    # verse: English (Atkinson) + Japanese, right-aligned as one block.
    # Drawn left-anchored from a computed start x to avoid anchor/measure drift.
    vjp, ven = jp_font(40, weight="Regular"), latin_font(40, bold=False)
    en_txt = f"({verse_en})"
    gap = 16
    total_w = ven.getlength(en_txt) + gap + vjp.getlength(verse_jp)
    vx = (W - MARGIN) - total_w
    d.text((vx, 1498), en_txt, font=ven, fill=BLACK, anchor="la")
    d.text((vx + ven.getlength(en_txt) + gap, 1498), verse_jp,
           font=vjp, fill=BLACK, anchor="la")

    # ------------------------------------------------------------ footer ---
    stamp = now.strftime("%-m/%-d %H:%M")
    d.text((MARGIN, 1575), "30分ごとに更新", font=jp_font(34, weight="Regular"),
           fill=BLACK, anchor="lm")
    d.text((W - MARGIN, 1575), f"更新 {stamp}", font=jp_font(34, weight="Regular"),
           fill=BLACK, anchor="rm")

    return img


# --------------------------------------------------------------- server ---

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/dashboard.png":
            img = render()  # fresh render on every request
            buf = io.BytesIO()
            img.save(buf, "PNG")
            data = buf.getvalue()
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)
        elif self.path == "/health":
            body = b"ok"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path in ("/", "/index.html"):
            body = (b"<html><body><h1>Kindle dashboard server</h1>"
                    b'<p><a href="/dashboard.png">/dashboard.png</a></p>'
                    b'<p><a href="/health">/health</a></p></body></html>')
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, fmt, *args):  # keep logs on one line
        print(f"[{datetime.datetime.now():%H:%M:%S}] {self.address_string()} {fmt % args}")


def serve(host="0.0.0.0", port=8000):
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"Serving dashboard PNG at http://{host}:{port}/dashboard.png")
    print("Kindle fetches this URL every 30 minutes. Ctrl-C to stop.")
    srv.serve_forever()


def main():
    ap = argparse.ArgumentParser(description="Kindle Paperwhite dashboard renderer")
    ap.add_argument("--out", help="write PNG to this path and exit")
    ap.add_argument("--date", help="render for YYYY-MM-DD instead of today (testing)")
    ap.add_argument("--serve", action="store_true", help="run HTTP server")
    ap.add_argument("--host", default="0.0.0.0", help="bind address (default: all interfaces)")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args()

    if a.serve:
        serve(a.host, a.port)
        return
    target = datetime.date.fromisoformat(a.date) if a.date else None
    img = render(target)
    out = a.out or str(BASE / "dashboard.png")
    img.save(out, "PNG")
    print(f"Wrote {out} ({img.size[0]}x{img.size[1]}, mode {img.mode})")


if __name__ == "__main__":
    main()
