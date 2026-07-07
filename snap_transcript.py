#!/usr/bin/env python3
"""Claude Code hook glue for snapcompact.

PreCompact:       snap_transcript.py snap      — render the transcript tail to PNGs
UserPromptSubmit: snap_transcript.py announce  — tell the post-compact session they
                  exist (once; runs after all SessionStart output, so no hook race)

Both modes read the hook JSON from stdin. PNGs land in ~/.claude/snaps/<session_id>/.
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


def main():
    hook = json.load(sys.stdin)
    outdir = SNAP_DIR / hook["session_id"]

    if sys.argv[1] == "snap":
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
            {"chars": len(text), "pages": len(pages), "image_tokens": image_tokens}))

    elif sys.argv[1] == "announce":
        flag = outdir / "announced"
        pngs = sorted(outdir.glob("*.png"))
        if not pngs or flag.exists():
            return
        try:
            meta = json.loads((outdir / "meta.json").read_text())
            text_tokens = meta["chars"] // 4
            image_tokens = meta.get("image_tokens") or meta["pages"] * 3278
            savings = (f"Access ~{text_tokens:,} tokens of pre-compaction history for "
                       f"~{image_tokens:,} image tokens ({text_tokens / image_tokens:.1f}x savings). ")
        except (OSError, ValueError, KeyError):
            savings = ""
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
