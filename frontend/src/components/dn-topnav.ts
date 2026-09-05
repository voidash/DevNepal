import { LitElement, html, nothing } from "lit"
import { customElement, property } from "lit/decorators.js"

import type { Actor, Session } from "../data/api"

/**
 * The top bar, as the canvas drew it on all 115 boards (35 variants collapsed
 * to one component): brand block, the five public sections, the language
 * segment, then either "Sign in" (public) or the bell and the person.
 *
 * Light DOM so industry.css's .nav / .nav-brand / .seg / .btn apply.
 */
const SECTIONS: { label: string; path: string }[] = [
  { label: "Government projects", path: "/projects" },
  { label: "Community projects", path: "/community" },
  { label: "Members", path: "/members" },
  { label: "Tech blogs", path: "/blogs" },
  { label: "Recognition", path: "/recognition" },
]

@customElement("dn-topnav")
export class DnTopnav extends LitElement {
  @property({ type: String }) actor: Actor = "public"
  @property({ attribute: false }) session: Session | null = null
  @property({ type: String }) path = "/"
  @property({ type: Number }) unread = 0
  @property({ type: String, attribute: "ui-lang" }) uiLang: "en" | "ne" = "en"

  protected createRenderRoot() {
    return this
  }

  private isCurrent(p: string) {
    return p === "/" ? this.path === "/" : this.path.startsWith(p)
  }

  private fire(name: string, detail?: unknown) {
    this.dispatchEvent(new CustomEvent(name, { detail, bubbles: true, composed: true }))
  }

  render() {
    const signedIn = !!this.session
    const u = this.session?.user
    return html`
      <nav class="nav dn-topnav" aria-label="Primary">
        <a href="/" class="nav-brand dn-brand" aria-label="DevNepal home">
          DevNepal
          <span class="dn-brand-sub">Government of Nepal · PMO</span>
        </a>

        <div class="dn-topnav-links">
          ${this.actor === "public"
            ? html`<a href="/" aria-current=${this.isCurrent("/") ? "page" : nothing}>Home</a>`
            : nothing}
          ${SECTIONS.map(
            (s) => html`<a href=${s.path} aria-current=${this.isCurrent(s.path) ? "page" : nothing}>${s.label}</a>`
          )}
          ${this.actor === "public"
            ? html`<a href="/how-to-contribute" aria-current=${this.isCurrent("/how-to-contribute") ? "page" : nothing}>How to contribute</a>`
            : nothing}
        </div>

        <div class="dn-topnav-tools">
          <div class="seg dn-lang" role="radiogroup" aria-label="Language · भाषा">
            <button
              type="button"
              class="seg-opt"
              role="radio"
              aria-checked=${this.uiLang === "en"}
              @click=${() => this.fire("dn-lang", "en")}
            >EN</button>
            <button
              type="button"
              class="seg-opt"
              role="radio"
              lang="ne"
              aria-checked=${this.uiLang === "ne"}
              @click=${() => this.fire("dn-lang", "ne")}
            >ने</button>
          </div>

          ${signedIn && u
            ? html`
                <button
                  type="button"
                  class="btn btn-ghost btn-icon dn-bell"
                  aria-label=${this.unread ? `Notifications, ${this.unread} unread` : "Notifications"}
                  @click=${() => this.fire("dn-notifications")}
                >
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                    <path d="M10.268 21a2 2 0 0 0 3.464 0"></path>
                    <path d="M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326"></path>
                  </svg>
                  ${this.unread ? html`<span class="dn-bell-dot" aria-hidden="true"></span>` : nothing}
                </button>
                <button type="button" class="dn-person" @click=${() => this.fire("dn-account")} title="Account · sign out">
                  <span class="dn-avatar" aria-hidden="true">${u.initials}</span>
                  <span class="dn-person-text">
                    <span class="dn-person-name">${u.name}</span>
                    <span class="dn-person-role">${u.roleLabel}</span>
                  </span>
                </button>
              `
            : html`
                <button type="button" class="btn btn-primary blueprint dn-signin" @click=${() => this.fire("dn-signin")}>
                  <i class="corner tl"></i><i class="corner tr"></i><i class="corner bl"></i><i class="corner br"></i>
                  Sign in
                </button>
              `}
        </div>
      </nav>
    `
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "dn-topnav": DnTopnav
  }
}
