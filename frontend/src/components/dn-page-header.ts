import { LitElement, html, nothing, type TemplateResult } from "lit"
import { customElement, property } from "lit/decorators.js"

/**
 * The band at the top of a Live screen: kicker, title, one line of context,
 * and the page's primary action on the right. The canvas draws this on every
 * board with small variations; Live screens get one version.
 *
 * `action` is a template, not a slot — light-DOM elements cannot slot.
 */
@customElement("dn-page-header")
export class DnPageHeader extends LitElement {
  @property({ type: String }) kicker = ""
  @property({ type: String }) heading = ""
  @property({ type: String }) description = ""
  @property({ attribute: false }) action: TemplateResult | typeof nothing = nothing

  protected createRenderRoot() {
    return this
  }

  render() {
    return html`
      <header class="dn-page-header ${this.description ? "has-desc" : ""}">
        <div class="dn-page-header-text">
          ${this.kicker ? html`<div class="card-kicker">${this.kicker}</div>` : nothing}
          <h1>${this.heading}</h1>
          ${this.description ? html`<p class="text-muted">${this.description}</p>` : nothing}
        </div>
        ${this.action !== nothing ? html`<div class="dn-page-header-action">${this.action}</div>` : nothing}
      </header>
    `
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "dn-page-header": DnPageHeader
  }
}
