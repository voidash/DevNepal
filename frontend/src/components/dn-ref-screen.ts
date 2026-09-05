import { LitElement, html, nothing } from "lit"
import { customElement, property, state } from "lit/decorators.js"
import { unsafeHTML } from "lit/directives/unsafe-html.js"

/**
 * A Reference screen: one board of the design canvas, extracted by
 * scripts/extract-canvas.py, mounted as-is.
 *
 * Reference is the honest tier. The board looks right — it is the approved
 * drawing — and does nothing: no data, no forms, every link a placeholder.
 * A screen leaves this tier when a Live component claims its route. Until
 * then the chip in the corner says so, on the screen, so nobody in a demo
 * mistakes a drawing for a feature.
 *
 * Renders into the light DOM on purpose. The board's markup is styled by
 * industry.css through global class names (.btn, .card, .tag …); a shadow
 * root would cut it off from every one of them.
 */
const boards = import.meta.glob<string>("../screens/ref/*.html", {
  query: "?raw",
  import: "default",
})

@customElement("dn-ref-screen")
export class DnRefScreen extends LitElement {
  /** Canvas board id, e.g. "b2-3". */
  @property({ type: String }) screen = ""
  /** Shown in the chip; the board's label from routes.json. */
  @property({ type: String }) label = ""

  @state() private markup: string | null = null
  @state() private missing = false

  protected createRenderRoot() {
    return this
  }

  protected willUpdate(changed: Map<string, unknown>) {
    if (changed.has("screen")) void this.load()
  }

  private async load() {
    this.markup = null
    this.missing = false
    const loader = boards[`../screens/ref/${this.screen}.html`]
    if (!loader) {
      this.missing = true
      return
    }
    const raw = await loader()
    /* Every link on the canvas is href="#". Left alone, each one scrolls to
       the top and rewrites the URL hash — which is the router's. Neutralise
       them here rather than in 115 files; the Live tier gives links real
       targets. */
    this.markup = raw.replaceAll('href="#"', 'href="javascript:void 0" data-ref-link')
  }

  render() {
    if (this.missing) {
      return html`<p class="text-muted" style="padding:32px">
        No reference board for <code>${this.screen}</code>.
      </p>`
    }
    return html`
      <div class="dn-ref" data-screen=${this.screen}>
        <span class="dn-ref-chip" title="Drawn, not wired. Becomes live when its component lands.">
          Reference · ${this.label || this.screen}
        </span>
        ${this.markup ? unsafeHTML(this.markup) : nothing}
      </div>
    `
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "dn-ref-screen": DnRefScreen
  }
}
