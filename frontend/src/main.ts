import { LitElement, html } from "lit"
import { customElement, state } from "lit/decorators.js"
import { repeat } from "lit/directives/repeat.js"

import "./tokens/industry.css"
import "./app.css"
import "./components/dn-ref-screen"
import routes from "./routes.json"

/**
 * Block 1 shell: a rail of all 115 canvas boards and the one you picked.
 *
 * This is the extraction made visible, nothing more. The real app shell
 * (dn-shell, sidebar, page header) and the path router arrive in blocks 3
 * and 4; both replace this file rather than extend it.
 *
 * Routing is by hash on the board id — #/b2-3 — because that survives a
 * static host with no rewrite rules, which is where tomorrow's build lives.
 */
type Route = (typeof routes)[number]

const ACTORS: Record<Route["actor"], string> = {
  public: "A · Public visitor",
  member: "B · Member",
  publisher: "C · Ministry Publisher",
  admin: "D · Super Admin",
}

function currentId(): string {
  const id = location.hash.replace(/^#\/?/, "")
  return routes.some((r) => r.id === id) ? id : routes[0].id
}

@customElement("dn-app")
export class DnApp extends LitElement {
  /* Not `id` — that is HTMLElement.id, and a private field with the same
     name makes the class un-assignable to HTMLElement. */
  @state() private screenId = currentId()

  protected createRenderRoot() {
    return this
  }

  connectedCallback() {
    super.connectedCallback()
    window.addEventListener("hashchange", this.onHash)
    if (!location.hash) location.hash = `#/${this.screenId}`
  }

  disconnectedCallback() {
    window.removeEventListener("hashchange", this.onHash)
    super.disconnectedCallback()
  }

  private onHash = () => {
    this.screenId = currentId()
    this.querySelector(".dn-stage")?.scrollTo({ top: 0 })
  }

  render() {
    const current = routes.find((r) => r.id === this.screenId) ?? routes[0]
    const groups = (Object.keys(ACTORS) as Route["actor"][]).map((actor) => ({
      actor,
      items: routes.filter((r) => r.actor === actor),
    }))

    return html`
      <div class="dn-canvas">
        <nav class="dn-rail" aria-label="Screens">
          <div class="dn-rail-head">
            <strong>DevNepal</strong>
            <span class="text-muted">${routes.length} screens · reference tier</span>
          </div>
          ${groups.map(
            (g) => html`
              <div class="dn-rail-group">
                <h6>${ACTORS[g.actor]} <span class="text-muted">${g.items.length}</span></h6>
                <ol>
                  ${repeat(
                    g.items,
                    (r) => r.id,
                    (r) => html`
                      <li>
                        <a
                          href=${`#/${r.id}`}
                          aria-current=${r.id === current.id ? "page" : "false"}
                        >
                          <span class="dn-code">${r.code}</span>
                          <span>${r.label}</span>
                        </a>
                      </li>
                    `
                  )}
                </ol>
              </div>
            `
          )}
        </nav>

        <div class="dn-stage">
          <header class="dn-stage-head">
            <span class="dn-code">${current.code}</span>
            <h4>${current.label}</h4>
            ${current.story ? html`<p class="text-muted">${current.story}</p>` : ""}
          </header>
          <dn-ref-screen .screen=${current.id} .label=${current.code}></dn-ref-screen>
        </div>
      </div>
    `
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "dn-app": DnApp
  }
}
