# Bundled fonts

Both fonts below are free under the **SIL Open Font License 1.1** and are
bundled so the dashboard renders identically on any machine.

- **NotoSansJP-VF.ttf** — Noto Sans JP (variable, weights Thin–Black).
  Japanese text. Source: https://github.com/google/fonts (ofl/notosansjp)
- **AtkinsonHyperlegible-Regular.otf / -Bold.otf** — Atkinson Hyperlegible
  by the Braille Institute, designed for low-vision legibility. Latin text
  (wordmark, English verse references).
  Source: https://github.com/googlefonts/atkinson-hyperlegible

If these files are deleted, `render.py` falls back to system fonts
(macOS Hiragino, Linux Noto CJK, then DejaVu).
