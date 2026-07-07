---
description: Render a text file to pixel-font PNG(s) for cheap vision re-reading
argument-hint: <file> [output-dir]
---

Run `python3 ${CLAUDE_PLUGIN_ROOT}/snapcompact.py $ARGUMENTS` (second argument,
if given, becomes `-o <output-dir>`). Report the printed token-cost summary and
the PNG path(s) to the user. Do not Read the PNGs back unless asked — the point
is to spend the tokens later, not now.
