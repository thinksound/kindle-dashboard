#!/bin/sh
# Kindle Paperwhite dashboard refresh loop.
#
# What this does, step by step:
#   1. Downloads the latest dashboard PNG from GitHub over Wi-Fi
#      (tries two mirrors, keeps the first valid PNG).
#   2. Draws it full-screen on the e-ink panel (fbink preferred, eips fallback).
#      If the download fails, the last good image is redrawn anyway, so the
#      screen heals itself instead of staying stuck on the Kindle's own UI.
#   3. Sleeps 30 minutes, then repeats forever.
#
# How to run it: copy this file to the Kindle's "documents" folder over USB,
# then tap it in the Kindle library (works via the sh_integration scriptlet
# from KindleModding's "What's Next" guide on a SpiderCat-jailbroken Kindle).
# Tap ONCE and wait ~15 seconds; a second tap while one loop runs is ignored.
#
# How to stop it: restart the Kindle, or create an empty file called
# /tmp/stop-dashboard (e.g. from a KUAL terminal: touch /tmp/stop-dashboard).
# The loop checks for it every minute and exits cleanly.

# --- configuration: dashboard PNG mirrors (first valid PNG wins) ---
# Rendered nightly by GitHub Actions, served over HTTPS.
URLS="https://raw.githubusercontent.com/thinksound/kindle-dashboard/main/dashboard.png
https://cdn.jsdelivr.net/gh/thinksound/kindle-dashboard@main/dashboard.png"

PNG="/tmp/dashboard.png"          # validated current image (scratch)
NEWPNG="/tmp/dashboard-new.png"   # download scratch: a failed fetch never clobbers PNG
GOOD="/mnt/us/dashboard-current.png"  # last known-good image; survives reboot, USB-visible
STOPFILE="/tmp/stop-dashboard"    # create this file to stop the loop
INTERVAL=1800                     # refresh every 30 minutes (seconds)
LOCK="/tmp/dashboard.lock"        # single-instance guard (see below)

log() {
    # simple timestamped log line (visible in KUAL terminal / usbnet ssh)
    echo "dashboard: $*"
}

# Only one refresh loop may run at a time. If this script is tapped while
# an older copy of the loop is still running (e.g. right after updating
# this file over USB), stop the old copy so the two never draw over each
# other and tear the image.
if [ -f "$LOCK" ]; then
    if command -v pgrep >/dev/null 2>&1; then
        ME=$$
        for p in $(pgrep -f 'dashboard\.sh'); do
            [ "$p" != "$ME" ] || continue
            kill "$p" 2>/dev/null
        done
        sleep 2
        rm -f "$LOCK"
    else
        log "another loop seems to be running; restart the Kindle and tap again"
        exit 0
    fi
fi
touch "$LOCK"
trap 'rm -f "$LOCK"' EXIT INT TERM

# Keep the Kindle from covering the dashboard with its screensaver
# (on ad-supported Kindles the screensaver shows ads). This resets on
# every reboot, so it's re-applied each time the loop starts.
lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null

# Download $1 to $PNG. Succeeds only if curl reports success AND the
# result is really a PNG (checked via magic bytes when `od` exists).
# This guards against saving an HTML error page and trying to draw it.
fetch_png() {
    _url="$1"
    _info=$(curl -sfSL -m 90 -o "$NEWPNG" -w "%{http_code} %{size_download}" "$_url" 2>&1)
    _rc=$?
    _code=${_info%% *}
    _size=${_info##* }
    if [ "$_rc" -ne 0 ]; then
        log "fetch failed: $1 (curl rc=$_rc)"
        return 1
    fi
    if command -v od >/dev/null 2>&1; then
        _magic=$(head -c 8 "$NEWPNG" 2>/dev/null | od -An -tx1 | tr -d ' \n')
        if [ "$_magic" != "89504e470d0a1a0a" ]; then
            log "fetch failed: $1 not a PNG (http=$_code size=$_size)"
            return 1
        fi
    fi
    log "fetched $_size bytes (http $_code)"
    return 0
}

# Draw $PNG full-screen (fbink preferred, eips fallback).
draw_image() {
    if [ -x /mnt/us/libkh/bin/fbink ]; then
        /mnt/us/libkh/bin/fbink -q -f -g "file=$PNG"
    elif command -v fbink >/dev/null 2>&1; then
        fbink -q -f -g "file=$PNG"
    elif command -v eips >/dev/null 2>&1; then
        eips -g "$PNG"
    else
        log "ERROR: neither fbink nor eips found on this Kindle"
        return 1
    fi
}

# remove a stale stop file from a previous run, if any
[ -f "$STOPFILE" ] && rm -f "$STOPFILE"

# If the board story rotation is running, stop it (one screen owner at a time).
touch /tmp/stop-board-rotate

log "starting"

while :; do
    # --- stop check (top of every loop) ---
    if [ -f "$STOPFILE" ]; then
        rm -f "$STOPFILE"
        log "stop file found, exiting"
        exit 0
    fi

    # --- fetch the freshly rendered PNG (first valid mirror wins) ---
    OK=0
    for URL in $URLS; do
        log "fetching from $(echo "$URL" | cut -d/ -f3)"
        if fetch_png "$URL"; then
            mv "$NEWPNG" "$PNG"
            cp "$PNG" "$GOOD" 2>/dev/null
            OK=1
            break
        fi
        sleep 5
    done

    if [ "$OK" = "1" ]; then
        draw_image
    elif [ -f "$PNG" ]; then
        # Download failed but we still have this session's image:
        # redraw it so the screen heals itself instead of staying wrong.
        log "fetch failed, redrawing last image from this session"
        draw_image
    elif [ -f "$GOOD" ]; then
        # Nothing from this session (e.g. just rebooted): restore the
        # last known-good image kept on USB-visible storage.
        log "fetch failed, restoring last known-good image"
        cp "$GOOD" "$PNG"
        draw_image
    else
        log "fetch failed and no previous image exists; screen unchanged"
    fi

    # --- sleep in 60-second chunks so the stop file is honored promptly ---
    n=0
    while [ "$n" -lt "$INTERVAL" ] && [ ! -f "$STOPFILE" ]; do
        sleep 60
        n=$((n + 60))
    done
done
