import type { Session } from "../../data/api"
import type { href } from "../../router"

/**
 * A Live screen is a drawn board plus behaviour.
 *
 * The design is locked: every screen stays the canvas's own markup and CSS.
 * What makes a board live is an Enhancer registered against its id —
 *
 *   scope(ctx)        data for the board's own <sc-for> templates, read from
 *                     the store instead of the seed, so the catalog lists the
 *                     projects that exist and the inbox lists real applications
 *   mount(root, ctx)  after render: turn drawn fields into inputs, give the
 *                     drawn buttons their actions, point rows at their records
 *
 * Nothing is re-authored; the board that stakeholders approved is the board
 * that ships, working. A screen with no enhancer is Reference: same board,
 * drawn data, links only.
 */
export interface LiveCtx {
  boardId: string
  params: Record<string, string>
  session: Session | null
  navigate(path: string): void
  href: typeof href
  /** Open the sign-in dialog. */
  signIn(): void
  /** Re-run scope + render (after a filter changes, say). */
  reload(): void
}

export interface Enhancer {
  scope?(ctx: LiveCtx): Promise<Record<string, unknown>>
  mount?(root: HTMLElement, ctx: LiveCtx): void | Promise<void>
}

export const live: Record<string, Enhancer> = {}

export function registerLive(boardId: string, enhancer: Enhancer) {
  live[boardId] = enhancer
}
