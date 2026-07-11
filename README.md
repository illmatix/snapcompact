# SnapCompact PoC

Context compression for **cloud** Claude Code sessions: render text into a dense
pixel-font PNG that Claude reads back with its vision input at ~1/3 the token cost
(measured 2.6–2.8× on this repo's runs).
Based on [blog.can.ac/2026/06/10/snapcompact](https://blog.can.ac/2026/06/10/snapcompact/).

Does **not** apply to the local GLM-4.7-Flash stack — text-only model, no image input.

## Requirements

- **Pillow** (`pip install "Pillow>=8.0"`) — plugin install does not install Python
  packages, and every render path imports PIL.
- **DejaVu Sans Mono** — `apt install fonts-dejavu-core`, `dnf install dejavu-sans-mono-fonts`,
  or `brew install --cask font-dejavu`.

Linux/macOS only. If either is missing, snapshotting disables itself and prints a
one-line note on the next compact/clear (nothing else breaks).

## Install as plugin

The repo is a Claude Code plugin (and its own marketplace):

```bash
claude plugin marketplace add illmatix/snapcompact   # or a local clone path
claude plugin install snapcompact@snapcompact
```

Ships three hooks (PreCompact, SessionEnd, UserPromptSubmit) that
auto-snapshot conversation history, plus a `/snap <file>` command. If you previously
pasted the hooks into `~/.claude/settings.json` manually, remove them — the plugin
provides the same ones.

## omp (Oh My Pi)

[omp](https://omp.sh) has its **own** snapcompact — a native compaction strategy
(`compaction.strategy: snapcompact`, omp's default) shipped as the separate
`@oh-my-pi/snapcompact` package. It's an independent, more evolved take on the same
idea this PoC is built on (image discarded history into pixel-font PNG frames a vision
model reads back, no LLM summary) — **not** this repo's code: omp renders in native code
with provider-aware frame shapes and re-renders a bounded archive each compaction. So
nothing here runs under omp — not the Python renderer, not the `hooks/hooks.json` command
hooks above; omp loads JS/TS extension hooks and does its own imaging.

What this repo adds for omp is the status-line piece. `omp/statusline-savings.ts` is
an omp extension that reads the archive omp persists on each compaction and pins a
**cumulative** segment like `📸 ~208k saved` via `ctx.ui.setStatus`: the text-token cost
of all history snapcompact has archived this session — the live imaged frames plus
everything since evicted to stay under budget — minus what those frames still cost as
billed images. omp carries the tally forward on the archive itself, so it grows across
the session (resetting only on a fresh compaction chain). The image cost uses the
package's conservative flat per-frame estimate, so the figure is understated rather than
inflated (hence the `~`).

Install globally (every repo):

```bash
mkdir -p ~/.omp/agent/extensions
ln -s "$PWD/omp/statusline-savings.ts" ~/.omp/agent/extensions/snapcompact-savings.ts
```

Per-repo instead: symlink/copy into `<repo>/.omp/extensions/`, or add the path to the
`extensions:` array in `~/.omp/agent/config.yml`. The segment needs
`statusLine.showHookStatus` (default on); disable it with
`disabledExtensions: [extension-module:snapcompact-savings]`. Tests: `bun test omp/`.

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
- DejaVu Sans Mono 9pt (~5.4×12 px), ~37K chars/page — antialiased glyphs fixed
  6↔8 digit flips seen with PIL's 6×11 bitmap font at the same density
- Text flows as one continuous stream; newlines become `¶`
- Line colors cycle (article: helps small vision models lock on)

## Recipes

**Auto-snapshot before compaction or clear** — `snap_transcript.py` is hook
glue for Claude Code: PreCompact and SessionEnd (only on `/clear`) render the
transcript tail (last ~72K chars, usually ≤2 pages — hex duplication can add a
third) to `~/.claude/snaps/<session_id>/`; UserPromptSubmit
tells the post-compact session (once) to Read the PNGs if it needs lost detail, and
that exact values defer to the live transcript / structured memory (the snap is
approximate narrative). `/clear` starts a new
session_id, so lookups fall back to the newest snap dir whose recorded cwd matches
the project and was snapped in the last few minutes. The plugin registers all three
automatically. The savings note is not injected into model context — it surfaces
in the statusline instead (see below), so it costs no tokens and does not duplicate
claude-mem's own SessionStart summary. For a manual (non-plugin) setup, copy the three entries from
[`hooks/hooks.json`](hooks/hooks.json) into `~/.claude/settings.json`, replacing
`${CLAUDE_PLUGIN_ROOT}` with your clone path.

**Show savings in your statusline** — `snap_transcript.py statusline` reads the
statusLine JSON on stdin and prints `📸 <savings>` when a snap exists for the
session (nothing otherwise). It derives the session_id from `transcript_path`
(the payload omits it) and stays stdlib-only — no PIL — so it is cheap to run on
every render. It is not auto-wired (statusLine is a single user-owned command);
pipe the payload through it from your own statusLine, e.g. append its output
below your existing line:

```bash
snap=$(printf '%s' "$in" | python3 /path/to/snap_transcript.py statusline 2>/dev/null)
[ -n "$snap" ] && printf '%s\n%s' "$your_line" "$snap" || printf '%s' "$your_line"
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
- Latin/ASCII text only. Characters outside DejaVu Sans Mono's coverage (emoji,
  CJK) render as identical blank boxes — a heavily non-Latin transcript snaps
  "successfully" but reads back unrecoverable. Keep such history as text.
