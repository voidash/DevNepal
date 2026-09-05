import { LitElement, html, nothing } from "lit"
import { customElement, property } from "lit/decorators.js"

import type { Actor, Session } from "../data/api"
import { ministries } from "../data/seed"
import { href } from "../router"

/**
 * The rail beside a signed-in screen — 109 hand-drawn asides collapsed to one
 * component with three menus. Anatomy is the canvas's: optional organisation
 * block, uppercase section labels, rows with a right-aligned count, the active
 * row tinted with a 2px accent rule on its left edge.
 *
 * Every row points at a real route. Rows whose screen is still a Reference
 * board still navigate — the board is there, drawn, reachable.
 */
interface Item {
  label: string
  /** Board id the row opens. */
  board: string
  params?: Record<string, string>
  /** Key into `counts` for the right-aligned figure. */
  count?: string
}
interface Group {
  label?: string
  items: Item[]
}

const MENUS: Record<Exclude<Actor, "public">, Group[]> = {
  member: [
    {
      label: "Dashboard",
      items: [
        { label: "Overview", board: "b5-5" },
        { label: "Applications", board: "b6-5", params: { id: "demo" }, count: "applications" },
        { label: "Bookmarks", board: "b2-1", count: "bookmarks" },
        { label: "Verified contributions", board: "b2-8", params: { id: "demo" }, count: "verified" },
        { label: "My community projects", board: "b3-7", count: "community" },
        { label: "My blog posts", board: "b4-7", count: "posts" },
        { label: "Notifications", board: "b5-5", count: "notifications" },
      ],
    },
    {
      label: "Account",
      items: [
        { label: "Profile & visibility", board: "b5-1" },
        { label: "Connections", board: "b5-2" },
        { label: "Email preferences", board: "b5-3" },
        { label: "Recognition settings", board: "b5-4" },
      ],
    },
  ],
  publisher: [
    {
      items: [
        { label: "Overview", board: "c3-1" },
        { label: "Projects", board: "c2-11", count: "projects" },
        { label: "Applications", board: "c3-3", count: "applications" },
        { label: "Verification queue", board: "c4-1", count: "verification" },
        { label: "Progress updates", board: "c5-1" },
        { label: "Officers", board: "c1-5", count: "officers" },
        { label: "Analytics", board: "c5-4" },
        { label: "Audit log · my actions", board: "c6-2" },
      ],
    },
  ],
  admin: [
    {
      items: [
        { label: "Review queue", board: "d2-1", count: "review" },
        { label: "Reports & moderation", board: "d3-2", count: "moderation" },
        { label: "Recognition · anomalies", board: "d4-2", count: "anomalies" },
        { label: "Ministry organizations", board: "d1-2" },
        { label: "Taxonomy · skills, tags, licences", board: "d5-5" },
        { label: "Badges & scoring policy", board: "d5-6" },
        { label: "Operational dashboards", board: "d5-1" },
        { label: "Sync health", board: "d5-3", count: "sync" },
        { label: "Privileged access", board: "d5-8" },
        { label: "Audit log", board: "d1-5" },
      ],
    },
  ],
}

@customElement("dn-sidebar")
export class DnSidebar extends LitElement {
  @property({ type: String }) actor: Exclude<Actor, "public"> = "member"
  @property({ attribute: false }) session: Session | null = null
  /** Current board id, for the active row. */
  @property({ type: String }) current = ""
  @property({ attribute: false }) counts: Record<string, string | number> = {}

  protected createRenderRoot() {
    return this
  }

  private orgBlock() {
    const u = this.session?.user
    if (this.actor === "publisher") {
      const m = ministries.find((x) => x.code === u?.ministry) as
        | { name: string; parent?: string; officers: number; mfa: string }
        | undefined
      return html`
        <div class="dn-side-org">
          <div class="dn-side-org-kicker">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M3 21h18M5 21V7l7-4 7 4v14M9 21v-6h6v6"/></svg>
            Ministry organization
          </div>
          <div class="dn-side-org-name">${m?.name ?? "Ministry"}</div>
          <div class="dn-side-org-meta">${m?.parent ? `${m.parent} · ` : ""}${m?.officers ?? 0} named officers · MFA ${m?.mfa?.toLowerCase() ?? "enforced"}</div>
        </div>
      `
    }
    if (this.actor === "admin") {
      return html`
        <div class="dn-side-org">
          <div class="dn-side-org-kicker">Platform administration</div>
          <div class="dn-side-org-name">PMO · DevNepal operations</div>
          <div class="dn-side-org-meta">Session expires in 27 min · MFA verified</div>
        </div>
      `
    }
    return nothing
  }

  render() {
    const groups = MENUS[this.actor]
    return html`
      <aside class="dn-side" aria-label="Section navigation">
        ${this.orgBlock()}
        ${groups.map(
          (g) => html`
            ${g.label ? html`<div class="dn-side-label">${g.label}</div>` : nothing}
            ${g.items.map((it) => {
              const active = it.board === this.current
              const count = it.count ? this.counts[it.count] : undefined
              return html`
                <a href=${href(it.board, it.params)} aria-current=${active ? "page" : nothing}>
                  <span>${it.label}</span>
                  ${count !== undefined && count !== "" ? html`<span class="dn-side-count">${count}</span>` : nothing}
                </a>
              `
            })}
          `
        )}
      </aside>
    `
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "dn-sidebar": DnSidebar
  }
}
