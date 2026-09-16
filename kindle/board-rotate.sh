#!/bin/sh
# Board story rotation for Kindle Paperwhite. (v2: Wi-Fi sync, no USB needed)
#
# What this does, step by step:
#   1. Syncs story images (PNG/JPG) from the kindle-dashboard GitHub repo
#      over Wi-Fi into /mnt/us/board/ -- no USB cable needed after the
#      first install. To change the story, just update the repo.
#   2. Draws each image full-screen for 60 seconds, then moves to the next,
#      looping forever: clock -> schedule -> family message -> encouragement.
#   3. Re-syncs every ~30 minutes, so new images appear on their own.
#   4. Checks the repo for a newer version of itself and self-updates.
#
# How to run it (one time): copy this file into the Kindle's "documents"
# folder over USB, then tap it once in the Kindle library (sh_integration
# on a SpiderCat-jailbroken Kindle). After that, everything -- images and
# script updates -- arrives over Wi-Fi automatically.
# Tap ONCE; a second tap while one loop runs is ignored.
#
# Mutual exclusion: starting this script stops the dashboard.sh loop, and
# starting dashboard.sh stops this script -- they never fight over the
# screen.
#
# How to stop it: restart the Kindle, or create an empty file called
# /tmp/stop-board-rotate. The loop checks for it every few seconds.

SCRIPT_VERSION=2                # bump with every script change (repo file
                                # kindle/board-version.txt must match)
IMGDIR="/mnt/us/board"          # story images live here (USB-visible)
INTERVAL=60                     # seconds shown per image
RESCAN_EVERY=30                 # re-sync + re-scan every N images (~30 min)
LOCK="/tmp/board-rotate.lock"   # single-instance guard
STOPFILE="/tmp/stop-board-rotate"

# GitHub repo mirrors (first success wins)
REPO_RAW="https://raw.githubusercontent.com/thinksound/kindle-dashboard/main/kindle"
REPO_CDN="https://cdn.jsdelivr.net/gh/thinksound/kindle-dashboard@main/kindle"
VERSION_FILE="board-version.txt"   # remote: plain version number
LIST_FILE="board/list.txt"         # remote: image filenames, one per line

# Our own path, for self-update (only absolute paths are trusted)
SELF="$0"
case "$SELF" in /*.sh) ;; *) SELF="";; esac

log() {
    echo "board-rotate: $*"
}

# --- single instance: an older rotation loop is stopped, then we proceed ---
if [ -f "$LOCK" ]; then
    if command -v pgrep >/dev/null 2>&1; then
        ME=$$
        for p in $(pgrep -f 'board-rotate\.sh'); do
            [ "$p" != "$ME" ] || continue
            kill "$p" 2>/dev/null
        done
        sleep 2
        rm -f "$LOCK"
    else
        log "another rotation seems to be running; restart the Kindle and tap again"
        exit 0
    fi
fi
touch "$LOCK"
trap 'rm -f "$LOCK"' EXIT INT TERM

# --- mutual exclusion with the dashboard loop ---
touch /tmp/stop-dashboard        # dashboard.sh exits on its stop file
[ -f "$STOPFILE" ] && rm -f "$STOPFILE"   # clear our own stale stop file

# Keep the Kindle from covering the story with its screensaver
# (on ad-supported Kindles the screensaver shows ads). Re-applied on reboot.
lipc-set-prop com.lab126.powerd preventScreenSaver 1 2>/dev/null

# --- drawing helpers (fbink preferred, eips fallback) ---
draw_file() {
    # $1 = image path; draws it full-screen with a full e-ink refresh
    if [ -x /mnt/us/libkh/bin/fbink ]; then
        /mnt/us/libkh/bin/fbink -q -f -g "file=$1"
    elif command -v fbink >/dev/null 2>&1; then
        fbink -q -f -g "file=$1"
    elif command -v eips >/dev/null 2>&1; then
        eips -g "$1"
    else
        log "ERROR: neither fbink nor eips found on this Kindle"
        return 1
    fi
}

show_text() {
    # $1 = short status message, centered on screen via fbink built-in font
    if [ -x /mnt/us/libkh/bin/fbink ]; then
        /mnt/us/libkh/bin/fbink -q -c -m -M "$1"
    elif command -v fbink >/dev/null 2>&1; then
        fbink -q -c -m -M "$1"
    fi
}

# --- Wi-Fi sync from the GitHub repo ---
fetch_url() {
    # $1 = path inside kindle/ in the repo, $2 = destination file.
    # Downloads to a temp file first; the destination is only replaced
    # after a successful download. Tries both mirrors.
    _rel="$1"; _dest="$2"; _tmp="$_dest.tmp"
    for _base in "$REPO_RAW" "$REPO_CDN"; do
        if curl -sfSL -m 60 -o "$_tmp" "$_base/$_rel" 2>/dev/null; then
            mv "$_tmp" "$_dest"
            return 0
        fi
        rm -f "$_tmp"
    done
    return 1
}

valid_image() {
    # $1 = path; true if it looks like a real PNG or JPEG
    [ -f "$1" ] || return 1
    [ -s "$1" ] || return 1
    command -v od >/dev/null 2>&1 || return 0
    case "$1" in
        *.png|*.PNG)
            _m=$(head -c 8 "$1" 2>/dev/null | od -An -tx1 | tr -d ' \n')
            [ "$_m" = "89504e470d0a1a0a" ] ;;
        *)
            _m=$(head -c 2 "$1" 2>/dev/null | od -An -tx1 | tr -d ' \n')
            [ "$_m" = "ffd8" ] ;;
    esac
}

sync_images() {
    # Downloads every image named in the repo's board/list.txt.
    # A failed download keeps the previous file; only validated
    # images replace what's on screen.
    mkdir -p "$IMGDIR"
    _list="/tmp/board-list.txt"
    fetch_url "$LIST_FILE" "$_list" || {
        log "image list fetch failed, keeping local images"
        return 1
    }
    while IFS= read -r _name || [ -n "$_name" ]; do
        [ -f "$STOPFILE" ] && return 1
        case "$_name" in ""|\#*) continue ;; esac
        _name=$(basename "$_name")          # no subdirectories, ever
        _tmp="$IMGDIR/$_name.tmp"
        if fetch_url "board/$_name" "$_tmp"; then
            if valid_image "$_tmp"; then
                mv "$_tmp" "$IMGDIR/$_name"
                log "synced image $_name"
            else
                log "downloaded $_name failed validation, kept old file"
                rm -f "$_tmp"
            fi
        else
            log "could not fetch image $_name, kept old file"
        fi
    done < "$_list"
    return 0
}

self_update() {
    # If the repo carries a newer script version, download it, validate
    # it, install it over ourselves, and restart into it.
    if [ -z "$SELF" ]; then
        log "self-update skipped (unknown script path)"
        return 1
    fi
    _ver="/tmp/board-version.txt"
    fetch_url "$VERSION_FILE" "$_ver" || {
        log "version check failed (offline?), skipping update"
        return 1
    }
    _remote=$(tr -cd '0-9' < "$_ver" 2>/dev/null | head -c 8)
    if [ -n "$_remote" ] && [ "$_remote" -gt "$SCRIPT_VERSION" ] 2>/dev/null; then
        log "updating script v$SCRIPT_VERSION -> v$_remote"
        _new="$SELF.new"
        if fetch_url "board-rotate.sh" "$_new" \
           && [ "$(head -c 9 "$_new" 2>/dev/null)" = "#!/bin/sh" ] \
           && sh -n "$_new" 2>/dev/null; then
            mv "$_new" "$SELF"
            chmod +x "$SELF"
            log "update installed, restarting into new version"
            exec "$SELF"
            # not reached
        else
            log "downloaded script failed validation, keeping v$SCRIPT_VERSION"
            rm -f "$_new"
        fi
    fi
    return 0
}

# --- image listing ---
list_images() {
    # prints valid images in $IMGDIR, one per line, sorted by filename
    for f in "$IMGDIR"/*.png "$IMGDIR"/*.PNG \
             "$IMGDIR"/*.jpg "$IMGDIR"/*.JPG "$IMGDIR"/*.jpeg; do
        valid_image "$f" && echo "$f"
    done | sort
}

wait_for_images() {
    # blocks until at least one image exists (or we're told to stop)
    while [ ! -f "$STOPFILE" ]; do
        IMAGES=$(list_images)
        if [ -n "$IMAGES" ]; then
            return 0
        fi
        show_text "Syncing story images over Wi-Fi..."
        log "waiting for images in $IMGDIR"
        n=0
        while [ "$n" -lt 120 ] && [ ! -f "$STOPFILE" ]; do
            sleep 10
            n=$((n + 10))
        done
        sync_images
    done
    return 1
}

log "starting v$SCRIPT_VERSION, images from $IMGDIR"
sync_images          # best effort; rotation continues on failure
self_update          # may restart into a newer version (never returns then)
wait_for_images || { log "stop file found, exiting"; exit 0; }

# --- rotation loop ---
idx=0
shown=0
while [ ! -f "$STOPFILE" ]; do
    if [ "$shown" -ge "$RESCAN_EVERY" ]; then
        sync_images
        self_update      # may exec into newer version
        IMAGES=$(list_images)
        shown=0
    fi
    if [ -z "$IMAGES" ]; then
        IMAGES=$(list_images)
        shown=0
    fi
    if [ -z "$IMAGES" ]; then
        show_text "Syncing story images over Wi-Fi..."
        log "image folder empty, retrying sync"
        sync_images
        sleep 60
        continue
    fi

    count=$(echo "$IMAGES" | wc -l)
    idx=$((idx % count))
    img=$(echo "$IMAGES" | sed -n "$((idx + 1))p")
    idx=$((idx + 1))
    shown=$((shown + 1))

    if [ -f "$img" ]; then
        log "showing $idx/$count: $img"
        draw_file "$img"
    else
        log "image vanished before draw: $img"
    fi

    n=0
    while [ "$n" -lt "$INTERVAL" ] && [ ! -f "$STOPFILE" ]; do
        sleep 5
        n=$((n + 5))
    done
done

log "stop file found, exiting"
