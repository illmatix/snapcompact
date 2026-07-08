#!/usr/bin/env python3
"""Claude Code hook glue for snapcompact.

PreCompact + SessionEnd(clear): snap_transcript.py snap    — render transcript tail to PNGs
SessionStart(compact|clear):    snap_transcript.py notify  — one-line savings note the
                                user sees in the message area
UserPromptSubmit:               snap_transcript.py announce — tell the post-compact
                                session the PNGs exist (once; runs after all
                                SessionStart output, so no hook race)

All modes read the hook JSON from stdin. PNGs land in ~/.claude/snaps/<session_id>/.
/clear starts a new session_id, so notify/announce fall back to the newest snap dir
whose meta.json cwd matches this project.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from snapcompact import ROWS, render, wrap_lines

SNAP_DIR = Path.home() / ".claude" / "snaps"
MAX_CHARS = 72_000  # ~2 pages ≈ 6.5K image tokens; older history is dropped
MIN_CHARS = 2_000   # below this the compact summary already covers it; not worth a snap


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
    """Snap dir for this session, else newest dir snapped from the same cwd
    (/clear hands the follow-up session a new session_id)."""
    outdir = SNAP_DIR / hook["session_id"]
    if list(outdir.glob("*.png")):
        return outdir
    candidates = sorted((d for d in SNAP_DIR.iterdir() if d.is_dir()),
                        key=lambda d: d.stat().st_mtime, reverse=True)
    for d in candidates:
        try:
            meta = json.loads((d / "meta.json").read_text())
        except (OSError, ValueError):
            continue
        if meta.get("cwd") == hook.get("cwd") and list(d.glob("*.png")):
            return d
    return None


def savings_line(outdir):
    try:
        meta = json.loads((outdir / "meta.json").read_text())
        text_tokens = meta["chars"] // 4
        image_tokens = meta.get("image_tokens") or meta["pages"] * 3278
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
        outdir = SNAP_DIR / hook["session_id"]
        text = transcript_text(hook["transcript_path"])[-MAX_CHARS:]
        if len(text.strip()) < MIN_CHARS:
            return
        outdir.mkdir(parents=True, exist_ok=True)
        for old in outdir.glob("*.png"):
            old.unlink()
        (outdir / "announced").unlink(missing_ok=True)  # fresh snap → re-announce
        lines = wrap_lines(text)
        pages = [lines[i:i + ROWS] for i in range(0, len(lines), ROWS)]
        image_tokens = 0
        for n, page in enumerate(pages, 1):
            img = render(page)
            image_tokens += img.width * img.height // 750
            img.save(outdir / f"history-{n:03d}.png")
        (outdir / "meta.json").write_text(json.dumps(
            {"chars": len(text), "pages": len(pages),
             "image_tokens": image_tokens, "cwd": hook.get("cwd", "")}))

    elif sys.argv[1] == "notify":
        outdir = snap_dir_for(hook)
        if not outdir or (outdir / "announced").exists():
            return
        line = savings_line(outdir)
        if line:
            # plain stdout on SessionStart → visible in the message area
            print(f"snapcompact: snapped {line}")

    elif sys.argv[1] == "announce":
        outdir = snap_dir_for(hook)
        if not outdir:
            return
        flag = outdir / "announced"
        pngs = sorted(outdir.glob("*.png"))
        if flag.exists():
            return
        line = savings_line(outdir)
        savings = f"Access {line}. " if line else ""
        print(json.dumps({"hookSpecificOutput": {
            # echo the event we were invoked from — hardcoding broke when stale
            # in-session hook wiring (SessionStart) ran a newer script version
            "hookEventName": hook.get("hook_event_name", "UserPromptSubmit"),
            "additionalContext": (
                savings
                + "Pre-compaction conversation history was rendered to pixel-font PNG(s): "
                + ", ".join(str(p) for p in pngs)
                + ". Newlines appear as ¶. If you need detail the compact summary lost, "
                  "Read these images (each costs ~3.3K tokens). Long hex values appear "
                  "twice as `value [dup:value]` — trust them only when both copies match."
            ),
        }}))
        flag.write_text("")


if __name__ == "__main__":
    main()
