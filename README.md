# SnapCompact PoC

Context compression for **cloud** Claude Code sessions: render text into a dense
pixel-font PNG that Claude reads back with its vision input at ~1/3 the token cost.
Based on [blog.can.ac/2026/06/10/snapcompact](https://blog.can.ac/2026/06/10/snapcompact/).

Does **not** apply to the local GLM-4.7-Flash stack — text-only model, no image input.

## Install as plugin

The repo is a Claude Code plugin (and its own marketplace):

```bash
claude marketplace add illmatix/snapcompact   # or a local clone path
claude plugin install snapcompact@snapcompact
```

Ships the PreCompact/UserPromptSubmit auto-snapshot hooks and a `/snap <file>`
command. If you previously pasted the hooks into `~/.claude/settings.json`
manually, remove them — the plugin provides the same ones.

## Usage

```bash
python3 snapcompact.py SESSION-NOTES.txt          # writes SESSION-NOTES.snap-001.png ...
python3 snapcompact.py notes.txt -o ~/snaps/      # choose output dir
```

Then in a later Claude Code session: ask Claude to `Read` the PNG(s). Claude
transcribes the pixel text internally and works from it.

## Measured (2026-07-06, this repo's PoC run)

- 33,893 chars (~8.5K text tokens) → 1 page → ~3,278 image tokens = **2.6× compression**
- Recall test: 7 planted facts (exact numbers, a commit hash, a full ssh command)
  buried in 400 lines of log noise — **all 7 recovered exactly** by Claude Fable 5
  reading the PNG.
- Follow-up runs with the old PIL bitmap font scored 5/7 (a 6↔8 digit flip and a
  hex-pair transposition); DejaVu Sans Mono 9pt at equal density scored 7/7 and
  6/7 across two fresh-fact runs — the miss was 3 wrong chars inside a 40-char
  hex hash (short facts stayed exact). Better glyphs help; long hex is still
  the weak spot.
- 8pt tested worse: 5/7 with a dropped char and e↔a flips, no compression gain
  until input exceeds ~37K chars/page. 9pt stays the default.
- All-black (no color cycling) tested 6/7 with a miss in a 5-digit port — the
  only short-fact miss in any run. Color cycling stays.
- Long hex tokens (≥16 chars) now render twice (`value [dup:value]`): when the
  copies read back identical, trust them; when they differ, treat the value as
  unreliable. Measured: agreement confirmed a 24-char token, disagreement
  correctly flagged a hash the reader had garbled — detection, not correction.

## How it packs

- 1568×1568 canvas (Anthropic's max tile, billed `1568²/750 ≈ 3,278` tokens)
- DejaVu Sans Mono 9pt (~5.4×14 px), ~37K chars/page — antialiased glyphs fixed
  6↔8 digit flips seen with PIL's 6×11 bitmap font at the same density
- Text flows as one continuous stream; newlines become `¶`
- Line colors cycle (article: helps small vision models lock on)

## Recipes

**Auto-snapshot before compaction** — `snap_transcript.py` is hook glue for
Claude Code: PreCompact renders the transcript tail (last ~72K chars, ≤2 pages)
to `~/.claude/snaps/<session_id>/`; UserPromptSubmit tells the post-compact
session (once) to Read them if it needs lost detail. The plugin registers both
automatically; manual equivalent in `~/.claude/settings.json`:

```json
"hooks": {
  "PreCompact": [{"hooks": [{"type": "command", "timeout": 30,
    "command": "python3 /path/to/snapcompact/snap_transcript.py snap 2>/dev/null || true"}]}],
  "UserPromptSubmit": [{"hooks": [{"type": "command", "timeout": 15,
    "command": "python3 /path/to/snapcompact/snap_transcript.py announce 2>/dev/null || true"}]}]
}
```

**Compress saved sessions** — ecc's `/save-session` writes to
`~/.claude/session-data/`; snap the file and point the resuming session at the
PNGs instead of the raw text (~1/3 the tokens):

```bash
python3 snapcompact.py ~/.claude/session-data/<file> -o ~/.claude/snaps/sessions/
```

**Log archaeology** — pack a day of logs into context for one page's cost, then
ask Claude to work from the image:

```bash
python3 snapcompact.py /var/log/app/today.log -o /tmp/logsnap/
```

## Limits

- Recall is near-perfect, not guaranteed — article measured 0.86–0.96 F1.
  Use for conversation history / decisions / notes. **Not** for code you will
  re-edit verbatim — keep code as text.
- Reading a page costs Claude some extra thinking tokens (~5× the decoded
  output per the article); savings still dominate for repeated context.
- Requires a vision-capable model. Cloud Claude: yes. Local llama.cpp text
  models: no.
