# SnapCompact PoC

Context compression for **cloud** Claude Code sessions: render text into a dense
pixel-font PNG that Claude reads back with its vision input at ~1/3 the token cost.
Based on [blog.can.ac/2026/06/10/snapcompact](https://blog.can.ac/2026/06/10/snapcompact/).

Does **not** apply to the local GLM-4.7-Flash stack — text-only model, no image input.

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

## How it packs

- 1568×1568 canvas (Anthropic's max tile, billed `1568²/750 ≈ 3,278` tokens)
- PIL built-in 6×11 bitmap font, ~36K chars/page
- Text flows as one continuous stream; newlines become `¶`
- Line colors cycle (article: helps small vision models lock on)

## Limits

- Recall is near-perfect, not guaranteed — article measured 0.86–0.96 F1.
  Use for conversation history / decisions / notes. **Not** for code you will
  re-edit verbatim — keep code as text.
- Reading a page costs Claude some extra thinking tokens (~5× the decoded
  output per the article); savings still dominate for repeated context.
- Requires a vision-capable model. Cloud Claude: yes. Local llama.cpp text
  models: no.
