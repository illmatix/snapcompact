#!/usr/bin/env python3
"""Claude Code hook glue for snapcompact.

PreCompact + SessionEnd(clear): snap_transcript.py snap    — render transcript tail to PNGs
SessionStart(compact|clear):    snap_transcript.py notify  — one-line savings note the
                                user sees in the message area
UserPromptSubmit:               snap_transcript.py announce — tell the post-compact
                                session the PNGs exist (once; runs after all
                                SessionStart output, so no hook race)

All modes read the hook JSON from stdin. PNGs land in ~/.claude/snaps/<session_id>/
(dirs 0700, files 0600). /clear starts a new session_id, so notify/announce fall back
to the newest snap dir whose meta.json cwd matches this project AND was snapped within
the last few minutes (an old stale snap must not resurface as this session's history).

PIL and the DejaVu font are imported lazily inside the snap branch only: notify/announce
stay stdlib-only (no per-prompt import cost), and a missing render dependency disables
snapping with a visible note instead of silently killing every hook.
"""
import json
import shutil
import sys
import time
from pathlib import Path

SNAP_DIR = Path.home() / ".claude" / "snaps"
MAX_CHARS = 72_000     # ~2 pages ≈ 6.5K image tokens; older history is dropped
MIN_CHARS = 2_000      # below this the compact summary already covers it; not worth a snap
FALLBACK_WINDOW = 600  # s: only bridge /clear→new-session with a snap this recent
RETENTION_DAYS = 7     # snaps hold full conversation prose — expire them


def _log(msg):
    """Append one line to ~/.claude/snaps/error.log — hooks.json swallows stderr, so
    this is the only forensic trace a failed snap leaves."""
    try:
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        with (SNAP_DIR / "error.log").open("a") as f:
            f.write(msg + "\n")
    except OSError:
        pass


def transcript_text(path):
    parts = []
    for line in Path(path).read_text(errors="replace").splitlines():
        try:
            msg = json.loads(line).get("message") or {}
        except json.JSONDecodeError:
            continue
        content = msg.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            parts.extend(b.get("text", "") for b in content if isinstance(b, dict))
    return "\n".join(p for p in parts if p)


def snap_dir_for(hook):
    """Snap dir for this session, else newest dir snapped from the same cwd within
    FALLBACK_WINDOW seconds (/clear hands the follow-up session a new session_id; the
    bridge is seconds, so a day-old snap for this repo must not match)."""
    if not SNAP_DIR.is_dir():
        return None
    outdir = SNAP_DIR / hook["session_id"]
    if list(outdir.glob("*.png")) and (outdir / "meta.json").exists():
        return outdir
    now = time.time()
    candidates = sorted((d for d in SNAP_DIR.iterdir() if d.is_dir()),
                        key=lambda d: d.stat().st_mtime, reverse=True)
    for d in candidates:
        try:
            meta = json.loads((d / "meta.json").read_text())
        except (OSError, ValueError):
            continue
        if (meta.get("cwd") == hook.get("cwd")
                and now - meta.get("snapped_at", 0) < FALLBACK_WINDOW
                and list(d.glob("*.png"))):
            return d
    return None


def savings_line(outdir):
    try:
        meta = json.loads((outdir / "meta.json").read_text())
        text_tokens = meta["chars"] // 4
        image_tokens = meta["image_tokens"]
        return (f"~{text_tokens:,} tokens of pre-compaction history for "
                f"~{image_tokens:,} image tokens ({text_tokens / image_tokens:.1f}x savings)")
    except (OSError, ValueError, KeyError, ZeroDivisionError):
        return ""


def main():
    hook = json.load(sys.stdin)

    if sys.argv[1] == "snap":
        # SessionEnd fires on every exit; only /clear warrants a snap
        if hook.get("hook_event_name") == "SessionEnd" and hook.get("reason") != "clear":
            return
        sys.path.insert(0, str(Path(__file__).parent))
        try:
            from snapcompact import ROWS, render, wrap_lines
        except Exception as e:  # Pillow or the DejaVu font is missing
            _log(f"render unavailable: {e!r}")
            print("snapcompact: snapshotting disabled — install Pillow + "
                  "DejaVu Sans Mono (see README)")
            return
        try:
            text = transcript_text(hook["transcript_path"])[-MAX_CHARS:]
            if len(text.strip()) < MIN_CHARS:
                return
            SNAP_DIR.mkdir(parents=True, exist_ok=True)
            SNAP_DIR.chmod(0o700)
            cutoff = time.time() - RETENTION_DAYS * 86400
            for d in SNAP_DIR.iterdir():  # opportunistic GC; also bounds the fallback scan
                if d.is_dir() and d.stat().st_mtime < cutoff:
                    shutil.rmtree(d, ignore_errors=True)
            outdir = SNAP_DIR / hook["session_id"]
            outdir.mkdir(parents=True, exist_ok=True)
            outdir.chmod(0o700)
            # drop the prior snap AND its meta.json first, so a crash mid-render degrades
            # to clean silence (snap_dir_for requires meta) instead of stale numbers +
            # torn PNGs served as truthful history
            for old in outdir.glob("*.png"):
                old.unlink()
            (outdir / "meta.json").unlink(missing_ok=True)
            (outdir / "announced").unlink(missing_ok=True)  # fresh snap → re-announce
            lines = wrap_lines(text)
            pages = [lines[i:i + ROWS] for i in range(0, len(lines), ROWS)]
            image_tokens = 0
            for n, page in enumerate(pages, 1):
                img = render(page)
                image_tokens += img.width * img.height // 750
                path = outdir / f"history-{n:03d}.png"
                img.save(path)
                path.chmod(0o600)
            tmp = outdir / "meta.json.tmp"
            tmp.write_text(json.dumps(
                {"chars": len(text), "image_tokens": image_tokens,
                 "cwd": hook.get("cwd", ""), "snapped_at": time.time()}))
            tmp.replace(outdir / "meta.json")  # atomic: readers never see a torn meta
            (outdir / "meta.json").chmod(0o600)
        except Exception as e:  # never break compaction; leave a trace instead of /dev/null
            _log(f"snap failed: {e!r}")

    elif sys.argv[1] == "notify":
        outdir = snap_dir_for(hook)
        if not outdir or (outdir / "announced").exists():
            return
        line = savings_line(outdir)
        if line:
            # additionalContext is the ONLY channel this build renders visibly
            # (as "SessionStart:compact says: ..."). systemMessage was silently
            # folded into the collapsed hook-success area AND still leaked into
            # model context — worst of both. The savings line is ~25 tokens;
            # showing it visibly beats hiding it to save nothing.
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": hook.get("hook_event_name", "SessionStart"),
                "additionalContext": f"snapcompact: snapped {line}",
            }}))

    elif sys.argv[1] == "announce":
        outdir = snap_dir_for(hook)
        if not outdir:
            return
        flag = outdir / "announced"
        if flag.exists():  # already announced → cheap exit, skip the glob
            return
        pngs = sorted(outdir.glob("*.png"))
        # additionalContext carries what the model needs (PNG paths). The savings
        # note is shown once at compact time by notify; repeating it via a second
        # channel here only leaks more tokens (systemMessage isn't out-of-context
        # on this build) — so announce stays PNG-only.
        print(json.dumps({"hookSpecificOutput": {
            # echo the event we were invoked from — hardcoding broke when stale
            # in-session hook wiring (SessionStart) ran a newer script version
            "hookEventName": hook.get("hook_event_name", "UserPromptSubmit"),
            "additionalContext": (
                "Pre-compaction conversation history (user and assistant messages) "
                  "was rendered to pixel-font PNG(s): "
                + ", ".join(str(p) for p in pngs)
                + ". Newlines appear as ¶. If you need detail the compact summary lost, "
                  "Read these images (each costs ~3.3K tokens). Long hex values appear "
                  "twice as `value [dup:value]` — trust them only when both copies match."
            ),
        }}))
        flag.write_text("")


if __name__ == "__main__":
    main()
