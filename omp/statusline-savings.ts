/**
 * snapcompact savings — omp (Oh My Pi) status line integration.
 *
 * omp's default compaction strategy (`compaction.strategy: snapcompact`) archives
 * discarded conversation history into dense pixel-font PNG frames a vision model reads
 * back far cheaper than the original text. This extension surfaces the **cumulative**
 * win in omp's status line: after each compaction it pins a `📸 ~208k saved` segment via
 * `ctx.ui.setStatus`.
 *
 * "Saved" = the text-token cost of all history snapcompact has archived over the current
 * compaction chain (the frames' live imaged middle + everything since evicted to stay under
 * budget) minus what those live frames still cost as billed images. omp keeps that tally on
 * the archive itself — `Archive.truncatedChars` carries forward across re-renders
 * (`truncatedChars = previousArchive.truncatedChars + newlyDropped`), so the number is read
 * straight off the latest compaction entry: already cumulative, growing across the session,
 * no per-event bookkeeping. It resets only when a fresh chain starts with no prior archive.
 *
 * The Claude Code half of this repo (hooks/hooks.json + snap_transcript.py) does the
 * equivalent for Claude Code's user-owned statusLine. omp never runs those command hooks
 * and ships its own snapcompact (`@oh-my-pi/snapcompact`), so this TS extension is the
 * omp-native counterpart: it reads the archive omp already persisted, it renders nothing.
 *
 * Install (global, every repo):
 *   mkdir -p ~/.omp/agent/extensions
 *   ln -s "$PWD/omp/statusline-savings.ts" ~/.omp/agent/extensions/snapcompact-savings.ts
 * Per-repo instead: symlink/copy into <repo>/.omp/extensions/, or add the path to the
 * `extensions:` array in ~/.omp/agent/config.yml. Display requires
 * `statusLine.showHookStatus` (default true). Disable with
 * `disabledExtensions: [extension-module:snapcompact-savings]`.
 */
import type { ExtensionAPI } from "@oh-my-pi/pi-coding-agent";

// Key under CompactionEntry.preserveData where @oh-my-pi/snapcompact stores its archive,
// plus the package's conservative per-frame billed-token estimate (high-res Anthropic
// frame, ~4,784 visual-token cap). Inlined because the extension loads from ~/.omp and
// cannot rely on resolving @oh-my-pi/snapcompact from there — source: that package's
// PRESERVE_KEY / FRAME_TOKEN_ESTIMATE (v16.4.2).
const PRESERVE_KEY = "snapcompact";
const FRAME_TOKEN_ESTIMATE = 5024;
const CHARS_PER_TOKEN = 4; // same text-token heuristic snapcompact.py uses (len // 4)
const STATUS_KEY = "snapcompact";

/** Subset of @oh-my-pi/snapcompact `Archive`/`Frame` this reads. */
interface ArchiveFrame {
	/** Characters actually printed onto this frame. */
	chars?: number;
}
interface SnapArchive {
	/** Rendered frames (the live imaged middle); empty when the whole archive fit in text. */
	frames?: ArchiveFrame[];
	/** Characters evicted so far to respect the archive budget — accumulates across the chain. */
	truncatedChars?: number;
}

export interface Savings {
	/** ~text tokens of all history archived so far (currently imaged + since evicted). */
	archivedTokens: number;
	/** ~billed image tokens the live frames still cost. */
	imageTokens: number;
	/** ~cumulative tokens no longer carried as live text (archivedTokens − imageTokens, ≥ 0). */
	savedTokens: number;
}

/**
 * Cumulative snapcompact savings read from one compaction's persisted archive, or null
 * when nothing was imaged (no snapcompact archive — e.g. a different strategy ran).
 *
 * The archive is itself cumulative — omp re-renders it from a growing bounded source and
 * carries `truncatedChars` forward across compactions — so this reads the latest entry
 * rather than summing events (no double counting, replay-safe). Imaged chars (current
 * frames) and evicted chars are disjoint by construction. imageTokens uses the conservative
 * flat per-frame estimate, so a partial last frame is over-priced and the saving understated.
 */
export function computeSavings(
	preserveData: Record<string, unknown> | undefined,
): Savings | null {
	const archive = preserveData?.[PRESERVE_KEY] as SnapArchive | undefined;
	const frames = archive?.frames;
	if (!Array.isArray(frames) || frames.length === 0) return null;
	let imagedChars = 0;
	for (const f of frames) {
		if (f && typeof f.chars === "number" && f.chars > 0) imagedChars += f.chars;
	}
	const evicted =
		typeof archive?.truncatedChars === "number" && archive.truncatedChars > 0
			? archive.truncatedChars
			: 0;
	const archivedChars = imagedChars + evicted;
	if (archivedChars <= 0) return null;
	const archivedTokens = archivedChars / CHARS_PER_TOKEN;
	const imageTokens = frames.length * FRAME_TOKEN_ESTIMATE;
	const savedTokens = Math.max(0, archivedTokens - imageTokens);
	return { archivedTokens, imageTokens, savedTokens };
}

function fmtK(n: number): string {
	const r = Math.round(n);
	if (r < 1000) return String(r);
	const k = r / 1000;
	return k < 10 ? `${k.toFixed(1)}k` : `${Math.round(k)}k`;
}

/** Render a status segment, e.g. "📸 ~208k saved". */
export function formatSavings(s: Savings): string {
	return `📸 ~${fmtK(s.savedTokens)} saved`;
}

export default function snapcompactStatusline(pi: ExtensionAPI): void {
	// session_compact fires after every persisted compaction (manual /compact and the
	// auto-maintenance paths). The value is recomputed from the entry's cumulative archive,
	// so re-fires are idempotent.
	pi.on("session_compact", (event, ctx) => {
		const s = computeSavings(event.compactionEntry.preserveData);
		if (s) ctx.ui.setStatus(STATUS_KEY, formatSavings(s));
	});

	// Safety net for any auto path that reports only here; guarded to the snapcompact
	// strategy. Recompute-not-accumulate keeps this idempotent with session_compact.
	pi.on("auto_compaction_end", (event, ctx) => {
		if (event.action !== "snapcompact" || !event.result) return;
		const s = computeSavings(event.result.preserveData);
		if (s) ctx.ui.setStatus(STATUS_KEY, formatSavings(s));
	});
}
