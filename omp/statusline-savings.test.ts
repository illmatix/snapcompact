import { expect, test } from "bun:test";
import factory, { computeSavings, formatSavings } from "./statusline-savings.ts";

// Minimal structural stand-ins for the omp surfaces the extension touches. The default
// export is typed (pi: ExtensionAPI) => void; ExtensionAPI is not resolvable in this
// standalone test, so bridge to these locals once, with a reason, at the call boundary.
type EventHandler = (event: unknown, ctx: unknown) => void;
interface CapturedPi {
	on(event: string, handler: EventHandler): void;
}
interface CapturedCtx {
	ui: { setStatus(key: string, text: string | undefined): void };
}

// ExtensionAPI ⇄ CapturedPi: structurally compatible for `.on`, but the real type is
// unresolvable here — reinterpret the factory's parameter once instead of importing it.
const runFactory = factory as unknown as (pi: CapturedPi) => void;

function mockPi(): { pi: CapturedPi; handlers: Map<string, EventHandler> } {
	const handlers = new Map<string, EventHandler>();
	return {
		pi: {
			on(event, handler) {
				handlers.set(event, handler);
			},
		},
		handlers,
	};
}

function mockCtx(): { ctx: CapturedCtx; statuses: Map<string, string | undefined> } {
	const statuses = new Map<string, string | undefined>();
	return {
		ctx: {
			ui: {
				setStatus(key, text) {
					statuses.set(key, text);
				},
			},
		},
		statuses,
	};
}

/** Build a preserveData blob shaped like @oh-my-pi/snapcompact's persisted archive. */
function preserve(frameChars: number[], truncatedChars = 0): Record<string, unknown> {
	return { snapcompact: { frames: frameChars.map((chars) => ({ chars })), truncatedChars } };
}

test("computeSavings totals imaged history and subtracts current image cost", () => {
	const s = computeSavings(preserve([48000, 48000, 24000]));
	// 120000 chars / 4 = 30000 archived text tokens; 3 frames * 5024 = 15072 image tokens
	expect(s?.archivedTokens).toBe(30000);
	expect(s?.imageTokens).toBe(15072);
	expect(s?.savedTokens).toBe(30000 - 15072);
});

test("computeSavings counts evicted history so the tally stays cumulative", () => {
	// 48k still imaged + 200k evicted so far = 248k chars archived over the chain.
	const s = computeSavings(preserve([48000], 200000));
	expect(s?.archivedTokens).toBe(62000);
	expect(s?.imageTokens).toBe(5024);
	expect(s?.savedTokens).toBe(62000 - 5024);
});

test("computeSavings returns null without a snapcompact archive", () => {
	expect(computeSavings(undefined)).toBeNull();
	expect(computeSavings({})).toBeNull();
	expect(computeSavings({ other: 1 })).toBeNull(); // e.g. a context-full compaction
});

test("computeSavings returns null when nothing was archived", () => {
	expect(computeSavings(preserve([]))).toBeNull(); // archive fit in verbatim text
	expect(computeSavings(preserve([0, 0]))).toBeNull();
});

test("computeSavings clamps to zero when image cost exceeds a tiny archive", () => {
	const s = computeSavings(preserve([16000])); // 4000 text tokens vs one 5024-token frame
	expect(s?.savedTokens).toBe(0);
});

test("formatSavings renders compact cumulative k-notation", () => {
	const s = (savedTokens: number): Parameters<typeof formatSavings>[0] => ({
		archivedTokens: 0,
		imageTokens: 0,
		savedTokens,
	});
	expect(formatSavings(s(208000))).toBe("📸 ~208k saved");
	expect(formatSavings(s(56976))).toBe("📸 ~57k saved");
	expect(formatSavings(s(4976))).toBe("📸 ~5.0k saved");
	expect(formatSavings(s(800))).toBe("📸 ~800 saved");
});

test("factory registers the compaction handlers", () => {
	const { pi, handlers } = mockPi();
	runFactory(pi);
	expect(handlers.has("session_compact")).toBe(true);
	expect(handlers.has("auto_compaction_end")).toBe(true);
});

test("session_compact pins the cumulative savings status", () => {
	const { pi, handlers } = mockPi();
	runFactory(pi);
	const { ctx, statuses } = mockCtx();
	// 48k imaged + 300k evicted = 348k chars → 87000 tokens − 5024 image = 81976 → "82k".
	handlers.get("session_compact")?.(
		{
			type: "session_compact",
			compactionEntry: { preserveData: preserve([48000], 300000) },
			fromExtension: false,
		},
		ctx,
	);
	expect(statuses.get("snapcompact")).toBe("📸 ~82k saved");
});

test("session_compact leaves status unset for a non-snapcompact compaction", () => {
	const { pi, handlers } = mockPi();
	runFactory(pi);
	const { ctx, statuses } = mockCtx();
	handlers.get("session_compact")?.(
		{ type: "session_compact", compactionEntry: { preserveData: {} }, fromExtension: false },
		ctx,
	);
	expect(statuses.has("snapcompact")).toBe(false);
});

test("auto_compaction_end reacts only to the snapcompact strategy with a result", () => {
	const { pi, handlers } = mockPi();
	runFactory(pi);
	const h = handlers.get("auto_compaction_end");

	const other = mockCtx();
	h?.({ type: "auto_compaction_end", action: "context-full", result: { preserveData: preserve([40000]) } }, other.ctx);
	expect(other.statuses.has("snapcompact")).toBe(false);

	const aborted = mockCtx();
	h?.({ type: "auto_compaction_end", action: "snapcompact", result: undefined }, aborted.ctx);
	expect(aborted.statuses.has("snapcompact")).toBe(false);

	const ok = mockCtx();
	// 40000 chars → 10000 tokens − 5024 image = 4976 → "5.0k".
	h?.({ type: "auto_compaction_end", action: "snapcompact", result: { preserveData: preserve([40000]) } }, ok.ctx);
	expect(ok.statuses.get("snapcompact")).toBe("📸 ~5.0k saved");
});
