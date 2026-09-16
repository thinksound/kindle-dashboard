# Kindle Paperwhite Care Dashboard

E-ink dashboard for a jailbroken Kindle Paperwhite (11th gen, 1236×1648).
A GitHub Actions workflow renders the dashboard as a PNG every night;
the Kindle fetches it over Wi-Fi every 30 minutes and draws it to the
e-ink panel. The image persists with zero power, so the last valid
dashboard stays visible even if Wi-Fi drops. No home computer needed.

Layout mirrors the TNKSND web dashboard: today's date (large, left),
this month's calendar with today highlighted (right), and a daily
Henri Nouwen quote with a Bible verse (bottom). Pure black on white,
bold type — no color, no thin fonts, per e-ink constraints.

```
kindle-dashboard/            # local working copy (this folder)
├── render.py                # renderer (also has a --serve dev server)
├── fonts/                   # bundled OFL fonts (Noto Sans JP, Atkinson Hyperlegible)
├── kindle/
│   ├── dashboard.sh         # Kindle-side fetch-and-draw loop (POSIX sh)
│   ├── board-rotate.sh      # story rotation: 4 Board screens, 1/min, Wi-Fi synced (POSIX sh)
│   ├── board/               # story images served to board-rotate.sh over Wi-Fi
│   ├── board-version.txt    # board-rotate.sh version number (for self-update)
│   ├── test-image.sh        # one-shot draw test (same draw path)
│   ├── test-sh.sh           # sh_integration smoke test
│   └── diag.sh              # on-device diagnostic (writes diag-result.txt)
└── README.md
```

The live pipeline lives in the GitHub repo
[thinksound/kindle-dashboard](https://github.com/thinksound/kindle-dashboard):
`.github/workflows/dashboard.yml` renders `dashboard.png` nightly at
00:05 America/Los_Angeles and commits it. The Kindle downloads it from:

```
https://raw.githubusercontent.com/thinksound/kindle-dashboard/main/dashboard.png
```

## Kindle setup

1. Connect the Kindle over USB and copy `kindle/dashboard.sh` into the
   Kindle's `documents` folder.
2. On the Kindle, open the library and **tap `dashboard.sh` once**, then
   wait ~15 seconds. A full e-ink refresh is slow; the screen flashing is
   normal. (Requires the sh_integration scriptlet from KindleModding's
   "What's Next" guide; the SpiderCat jailbreak must already be installed.)
3. The dashboard appears and refreshes every 30 minutes.

To stop the loop, create an empty file `/tmp/stop-dashboard` on the
Kindle (e.g. `touch /tmp/stop-dashboard` in a KUAL terminal). The loop
checks for it every minute and exits cleanly.

## Board story rotation

`kindle/board-rotate.sh` turns the Kindle into the Board product story:
it cycles through full-screen images — orientation clock, care schedule,
family message, words of encouragement — one per minute. Images and
script updates are pulled from this repo over Wi-Fi, so no USB cable is
needed after the first install.

Setup (one time): copy `kindle/board-rotate.sh` into the Kindle's
`documents` folder over USB and tap it once in the library. It creates
`/mnt/us/board/`, downloads the images listed in `kindle/board/list.txt`,
and starts rotating. Every ~30 minutes it re-syncs images and checks
`kindle/board-version.txt` for a newer script version (self-update).

To change the story: replace/add PNGs under `kindle/board/`, update
`kindle/board/list.txt`, bump the number in `kindle/board-version.txt`
when the script itself changes, and push — Kindles pick it up
automatically within ~30 minutes.

Starting `board-rotate.sh` stops the `dashboard.sh` loop and vice versa;
only one of them ever owns the screen.

## Local preview / testing

```bash
cd ~/workspace/kindle-dashboard
pip install pillow        # only dependency
python3 render.py --out /tmp/test.png        # sanity check (1236x1648, mode L)
python3 render.py --out /tmp/d.png --date 2026-08-15   # test a 6-row month
python3 render.py --serve --port 8000        # dev server: /dashboard.png, /health
```

## Troubleshooting

- **Tap once and wait.** If a tap seems unresponsive, don't tap again —
  two concurrent draws tear the image. `dashboard.sh` refuses to run a
  second loop while one is active (`/tmp/dashboard.lock`).

- **fbink location.** On SpiderCat installs fbink lives at
  `/mnt/us/libkh/bin/fbink` — it is NOT on `PATH`. The scripts check
  there first, then `PATH`, then fall back to `eips`. Always pass
  `fbink -q` (quiet): without it, fbink prints status text onto the
  e-ink screen; `eips` prints debug text unconditionally.

- **Kindle can't download / image stale.** The footer shows
  `更新 M/D HH:MM` — the exact render time. If it stops advancing,
  check the Kindle's Wi-Fi and that
  `https://raw.githubusercontent.com/thinksound/kindle-dashboard/main/dashboard.png`
  loads in a normal browser. raw.githubusercontent.com caches ~5 min;
  daily content is unaffected.

- **Quotes.** Eight genuine published Henri Nouwen lines rotate daily
  (`day_of_year % 8`). To change the set, edit `QUOTES` in `render.py`
  (then copy it to the repo — the Action renders from the repo copy).

## Notes

- No credentials or secrets anywhere in this pipeline. The GitHub repo
  is public; the PNG is a static public file.
- The Kindle's OTA updates must stay blocked so a firmware update
  doesn't remove the jailbreak (SpiderCat blocks updates itself).
- The repo keeps a `kindle-dashboard-deploy` deploy key (read/write,
  currently unused — kept for possible future automation).
