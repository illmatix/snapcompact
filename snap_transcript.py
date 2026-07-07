#!/usr/bin/env python3
"""Claude Code hook glue for snapcompact.

PreCompact:   snap_transcript.py snap      — render the transcript tail to PNGs
SessionStart: snap_transcript.py announce  — tell the post-compact session they exist

Both modes read the hook JSON from stdin. PNGs land in ~/.claude/snaps/<session_id>/.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from snapcompact import ROWS, render, wrap_lines

SNAP_DIR = Path.home() / ".claude" / "snaps"
MAX_CHARS = 72_000  # ~2 pages ≈ 6.5K image tokens; older history is dropped


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


def main():
    hook = json.load(sys.stdin)
    outdir = SNAP_DIR / hook["session_id"]

    if sys.argv[1] == "snap":
        text = transcript_text(hook["transcript_path"])[-MAX_CHARS:]
        if not text.strip():
            return
        outdir.mkdir(parents=True, exist_ok=True)
        for old in outdir.glob("*.png"):
            old.unlink()
        lines = wrap_lines(text)
        for n, page in enumerate([lines[i:i + ROWS] for i in range(0, len(lines), ROWS)], 1):
            render(page).save(outdir / f"history-{n:03d}.png")

    elif sys.argv[1] == "announce":
        pngs = sorted(outdir.glob("*.png"))
        if not pngs:
            return
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": (
                "Pre-compaction conversation history was rendered to pixel-font PNG(s): "
                + ", ".join(str(p) for p in pngs)
                + ". Newlines appear as ¶. If you need detail the compact summary lost, "
                  "Read these images (each costs ~3.3K tokens). Long hex values appear "
                  "twice as `value [dup:value]` — trust them only when both copies match."
            ),
        }}))


if __name__ == "__main__":
    main()
