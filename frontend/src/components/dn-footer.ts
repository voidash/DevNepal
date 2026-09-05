import { LitElement, html } from "lit"
import { customElement } from "lit/decorators.js"

/**
 * Public-page footer. The canvas drew one on six boards; this is the one
 * version, in its register: brand line, four columns, the contacts a citizen
 * needs — security, support, code of conduct — as text links.
 */
@customElement("dn-footer")
export class DnFooter extends LitElement {
  protected createRenderRoot() {
    return this
  }

  render() {
    return html`
      <footer class="dn-footer">
        <div class="dn-footer-inner">
          <div class="dn-footer-brand">
            <span class="nav-brand dn-brand">DevNepal<span class="dn-brand-sub">Government of Nepal · PMO</span></span>
            <p class="text-muted">
              A trusted registry and collaboration layer, not a replacement for GitHub. Code, issues and
              reviews stay in approved repositories; DevNepal records who did what, and for which ministry.
            </p>
          </div>
          <div class="dn-footer-cols">
            <div>
              <h6>Projects</h6>
              <a href="/projects">Government projects</a>
              <a href="/community">Community projects</a>
              <a href="/how-to-contribute">How to contribute</a>
            </div>
            <div>
              <h6>People</h6>
              <a href="/members">Members</a>
              <a href="/recognition">Recognition</a>
              <a href="/recognition/badges">Badges and prestige tiers</a>
            </div>
            <div>
              <h6>Writing</h6>
              <a href="/blogs">Tech blogs</a>
              <a href="/how-to-contribute">Publishing policy</a>
            </div>
            <div>
              <h6>Contact</h6>
              <a href="/how-to-contribute">Security contact</a>
              <a href="/how-to-contribute">Support</a>
              <a href="/how-to-contribute">Code of conduct</a>
            </div>
          </div>
        </div>
        <div class="dn-footer-legal text-muted">
          <span>Office of the Prime Minister and Council of Ministers · Digital Collaboration Initiative</span>
          <span lang="ne">प्रधानमन्त्री तथा मन्त्रिपरिषद्को कार्यालय</span>
        </div>
      </footer>
    `
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "dn-footer": DnFooter
  }
}
