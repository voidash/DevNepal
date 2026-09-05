/**
 * Live screens claim boards here: board id → custom element tag.
 *
 * Anything not listed renders as its Reference board. Adding a line here is
 * how a screen moves from drawn to working; the URL does not change.
 *
 * Each screen module registers its element as a side effect of import, so the
 * import list below is the complete set of Live screens in the build.
 */
export const live: Record<string, string> = {}

export function registerLive(boardId: string, tag: string) {
  live[boardId] = tag
}
