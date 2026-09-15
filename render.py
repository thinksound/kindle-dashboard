#!/usr/bin/env python3
"""Kindle Paperwhite care-dashboard renderer (simple design).

Renders the dashboard as a 1236x1648 grayscale PNG optimized for e-ink:
pure black on pure white, high-contrast type, no color, no thin lines.

Type scale (2 sizes, all Regular — no bold anywhere):
  M=44 : date block (all parts the same size), quote, verse text
  S=36 : TNKSND wordmark, calendar, author, verse reference, footer

Layout (portrait 1236x1648, all English):
  - Header: TNKSND wordmark
  - Left:  today's date, centered (year / month day / weekday)
  - Right: this month's calendar, today inverted (white on black)
  - Bottom: daily great-person quote (rotates) + related Bible verse
  - Footer: render timestamp so staleness is visible on the e-ink panel

Usage:
    python3 render.py --out dashboard.png
    python3 render.py --date 2026-08-15 --out test.png   # preview another date
    python3 render.py --serve --port 8000                # HTTP server for the Kindle

Requires: Pillow  (`pip install pillow`)
Fonts are bundled under ./fonts/ (Atkinson Hyperlegible, SIL OFL).
System fallbacks are tried if missing.
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




# (quote_en, author_en, verse_text_en, verse_ref_en) — daily rotation
QUOTES = [
    ("Not all of us can do great things, but we can do small things with great love.",
     "Mother Teresa", "Let all that you do be done in love.",
     "1 Corinthians 16:14"),
    ("Darkness cannot drive out darkness; only light can do that. Hate cannot drive out hate; only love can do that.",
     "Martin Luther King Jr.", "Do not be overcome by evil, but overcome evil with good.",
     "Romans 12:21"),
    ("Live as if you were to die tomorrow. Learn as if you were to live forever.",
     "Mahatma Gandhi", "Teach us to number our days, that we may gain a heart of wisdom.",
     "Psalm 90:12"),
    ("Imagination is more important than knowledge.",
     "Albert Einstein", "Now to him who is able to do far more abundantly than all that we ask or think.",
     "Ephesians 3:20"),
    ("The best and most beautiful things in the world cannot be seen or even touched \u2014 they must be felt with the heart.",
     "Helen Keller", "We look not to the things that are seen but to the things that are unseen.",
     "2 Corinthians 4:18"),
    ("Humility is not thinking less of yourself, but thinking of yourself less.",
     "C. S. Lewis", "In humility count others more significant than yourselves.",
     "Philippians 2:3"),
    ("Everyone thinks of changing the world, but no one thinks of changing himself.",
     "Leo Tolstoy", "Be transformed by the renewal of your mind.",
     "Romans 12:2"),
    ("Life is a tragedy when seen in close-up, but a comedy in long-shot.",
     "Charlie Chaplin", "A time to weep, and a time to laugh.",
     "Ecclesiastes 3:4"),
    ("No one can be truly happy until the whole world is happy.",
     "Kenji Miyazawa", "Let each of you look not only to his own interests, but also to the interests of others.",
     "Philippians 2:4"),
    ("Patience is bitter, but its fruit is sweet.",
     "Hideyo Noguchi", "Blessed is the man who remains steadfast under trial.",
     "James 1:12"),
    ("Success is not the key to happiness. Happiness is the key to success.",
     "Albert Schweitzer", "I have learned in whatever situation I am to be content.",
     "Philippians 4:11"),
    ("I learned that courage was not the absence of fear, but the triumph over it.",
     "Nelson Mandela", "God gave us a spirit not of fear but of power and love and self-control.",
     "2 Timothy 1:7"),
    ("Love gives without holding back.",
     "Toyohiko Kagawa", "It is more blessed to give than to receive.",
     "Acts 20:35"),
    ("Yesterday is gone. Tomorrow has not yet come. We have only today. Let us begin.",
     "Mother Teresa", "Sufficient for the day is its own trouble.",
     "Matthew 6:34"),
    ("You have made us for yourself, and our hearts are restless until they rest in you.",
     "Augustine", "Come to me, all who labor and are heavy laden, and I will give you rest.",
     "Matthew 11:28"),
    ("Even if I knew that tomorrow the world would go to pieces, I would still plant my apple tree.",
     "Martin Luther", "In the morning sow your seed, and at evening withhold not your hand.",
     "Ecclesiastes 11:6"),
    ("I know that I know nothing.",
     "Socrates", "If anyone imagines that he knows something, he does not yet know as he ought to know.",
     "1 Corinthians 8:2"),
    ("Do not do to others what you do not want done to yourself.",
     "Confucius", "Whatever you wish that others would do to you, do also to them.",
     "Matthew 7:12"),
    ("Genius is one percent inspiration and ninety-nine percent perspiration.",
     "Thomas Edison", "In all toil there is profit.",
     "Proverbs 14:23"),
    ("Nothing in life is to be feared; it is only to be understood.",
     "Marie Curie", "Fear not, for I am with you.",
     "Isaiah 41:10"),
    ("Do I not destroy my enemies when I make them my friends?",
     "Abraham Lincoln", "Love your enemies and pray for those who persecute you.",
     "Matthew 5:44"),
    ("Success is stumbling from failure to failure with no loss of enthusiasm.",
     "Winston Churchill", "When I fall, I shall rise.",
     "Micah 7:8"),
    ("Love does not consist in gazing at each other, but in looking outward together in the same direction.",
     "Antoine de Saint-Exup\u00e9ry", "Do two walk together, unless they have agreed to meet?",
     "Amos 3:3"),
    ("Preach the gospel at all times. Use words if necessary.",
     "Francis of Assisi", "Let your light shine before others.",
     "Matthew 5:16"),
]

MONTHS_EN = ["January", "February", "March", "April", "May", "June",
             "July", "August", "September", "October", "November", "December"]
WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
               "Saturday", "Sunday"]
WEEKDAYS_EN_SHORT = ["S", "M", "T", "W", "T", "F", "S"]


def wrap_en(draw, text, font, max_w):
    """Word-based wrapping for English text."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if draw.textlength(t, font=font) <= max_w:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines

MARGIN = 56

L, M, S = 84, 44, 36


def render(target_date=None, now=None):
    today = target_date or datetime.date.today()
    now = now or datetime.datetime.now()
    year, month, day = today.year, today.month, today.day

    img = Image.new("L", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    # header
    d.text((MARGIN, 100), "TNKSND", font=latin_font(S, bold=False), fill=BLACK, anchor="lm")

    # date block: centered in the left column, generous line spacing
    dcx = (MARGIN + 440) // 2
    lf = latin_font(M, bold=False)
    wd = WEEKDAYS_EN[datetime.date(year, month, day).weekday()]
    d.text((dcx, 506), str(year), font=lf, fill=BLACK, anchor="mm")
    d.text((dcx, 590), f"{MONTHS_EN[month - 1]} {day}", font=lf, fill=BLACK, anchor="mm")
    d.text((dcx, 674), wd, font=lf, fill=BLACK, anchor="mm")

    d.line([(440, 200), (440, 980)], fill=BLACK, width=2)

    # calendar (right): everything S
    cx0, cx1 = 490, W - MARGIN
    d.text(((cx0 + cx1) // 2, 290), f"{MONTHS_EN[month - 1]} {year}",
           font=latin_font(S, bold=False), fill=BLACK, anchor="mm")
    weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)
    cw, chh = 88, 88
    gx = cx0 + ((cx1 - cx0) - 7 * cw) // 2
    wf = latin_font(S, bold=False)
    for c, label in enumerate(WEEKDAYS_EN_SHORT):
        d.text((gx + c * cw + cw // 2, 375), label, font=wf, fill=BLACK, anchor="mm")
    gy = 425
    for r, week in enumerate(weeks):
        for c, dnum in enumerate(week):
            if not dnum:
                continue
            x = gx + c * cw + cw // 2
            y = gy + r * chh + chh // 2
            if dnum == day:
                d.rounded_rectangle([gx + c * cw + 5, gy + r * chh + 8,
                                     gx + (c + 1) * cw - 5, gy + (r + 1) * chh - 8],
                                    radius=12, fill=BLACK)
                d.text((x, y), str(dnum), font=wf, fill=WHITE, anchor="mm")
            else:
                d.text((x, y), str(dnum), font=wf, fill=BLACK, anchor="mm")

    # verse first, then quote — both at M, attributions at S
    quote, author, verse_text, verse_ref = QUOTES[today.timetuple().tm_yday % len(QUOTES)]
    qf = latin_font(M, bold=False)
    mf = latin_font(S, bold=False)
    y = 1020
    for line in wrap_en(d, f"“{verse_text}”", qf, (W - MARGIN) - 120)[:3]:
        d.text((W - MARGIN, y), line, font=qf, fill=BLACK, anchor="ra")
        y += 58
    y += 20
    d.text((W - MARGIN, y), f"— {verse_ref}", font=mf, fill=BLACK, anchor="ra")
    # airy gap plus one extra line before the quote
    y += 100 + 62
    for line in wrap_en(d, quote, qf, (W - MARGIN) - 120)[:4]:
        d.text((W - MARGIN, y), line, font=qf, fill=BLACK, anchor="ra")
        y += 62
    y += 20
    d.text((W - MARGIN, y), f"— {author}", font=mf, fill=BLACK, anchor="ra")

    # footer
    stamp = now.strftime("%-m/%-d %H:%M")
    d.text((MARGIN, 1575), "Updates every 30 minutes", font=latin_font(S, bold=False), fill=BLACK, anchor="lm")
    d.text((W - MARGIN, 1575), f"Updated {stamp}", font=latin_font(S, bold=False), fill=BLACK, anchor="rm")

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
