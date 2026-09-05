import { LitElement, html, nothing } from "lit"
import { customElement, property, state } from "lit/decorators.js"
import { unsafeHTML } from "lit/directives/unsafe-html.js"

import { referenceScope } from "../data/seed"

/**
 * A Reference screen: one board of the design canvas, extracted by
 * scripts/extract-canvas.py, mounted as-is.
 *
 * Reference is the honest tier. The board looks right — it is the approved
 * drawing — and does nothing: no data binding to the store, no forms that
 * submit, links that only navigate. A screen leaves this tier when a Live
 * component claims its route.
 *
 * Renders into the light DOM on purpose. The board's markup is styled by
 * industry.css through global class names (.btn, .card, .tag …); a shadow
 * root would cut it off from every one of them.
 *
 * The canvas runtime is not loaded, so its two template constructs are
 * resolved here against the shared seed instead:
 *
 *   <sc-for list="{{ catalog }}" as="p">…{{ p.title }}…</sc-for>
 *   <sc-if value="{{ story }}">…</sc-if>
 *
 * Without this, the boards show "{{ p.title }}" — which is what they did.
 * Expanding from seed.ts rather than from placeholder text means a Reference
 * board and the Live screen beside it show the same ministries, the same
 * people and the same projects.
 */
const boards = import.meta.glob<string>("../screens/ref/*.html", {
  query: "?raw",
  import: "default",
})

type Scope = Record<string, unknown>

const EXPR = /\{\{\s*([\w.]+)\s*\}\}/g

function resolve(path: string, scope: Scope): unknown {
  return path.split(".").reduce<unknown>((acc, key) => {
    if (acc === null || acc === undefined) return undefined
    return (acc as Record<string, unknown>)[key]
  }, scope)
}

function substitute(text: string, scope: Scope): string {
  return text.replace(EXPR, (_, path: string) => {
    const v = resolve(path, scope)
    return v === undefined || v === null ? "" : String(v)
  })
}

function substituteNode(root: Node, scope: Scope) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT)
  const texts: Text[] = []
  const elements: Element[] = []
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if (n.nodeType === Node.TEXT_NODE) {
      if ((n as Text).data.includes("{{")) texts.push(n as Text)
    } else {
      elements.push(n as Element)
    }
  }
  for (const t of texts) t.data = substitute(t.data, scope)
  for (const el of elements) {
    for (const attr of Array.from(el.attributes)) {
      if (attr.value.includes("{{")) el.setAttribute(attr.name, substitute(attr.value, scope))
    }
  }
}

/** Expand the canvas's template elements in place, depth-first. */
function expand(root: ParentNode, scope: Scope) {
  // Loops first: their bodies may contain conditionals and nested loops.
  let loop: Element | null
  while ((loop = root.querySelector("sc-for"))) {
    // Only take a loop with no loop ancestor still unexpanded.
    if (loop.parentElement?.closest("sc-for")) {
      loop = loop.parentElement.closest("sc-for")!
    }
    const listPath = (loop.getAttribute("list") ?? "").replace(EXPR, "$1").trim()
    const alias = loop.getAttribute("as") ?? "item"
    const list = resolve(listPath, scope)
    const items = Array.isArray(list) ? list : []
    const frag = document.createDocumentFragment()
    for (const item of items) {
      const clone = document.createElement("div")
      clone.innerHTML = loop.innerHTML
      const inner: Scope = { ...scope, [alias]: item }
      expand(clone, inner)
      substituteNode(clone, inner)
      while (clone.firstChild) frag.appendChild(clone.firstChild)
    }
    loop.replaceWith(frag)
  }

  // Conditionals: keep the children or drop the block.
  let cond: Element | null
  while ((cond = root.querySelector("sc-if"))) {
    const path = (cond.getAttribute("value") ?? "").replace(EXPR, "$1").trim()
    const v = resolve(path, scope)
    const truthy = Array.isArray(v) ? v.length > 0 : Boolean(v)
    if (truthy) {
      const frag = document.createDocumentFragment()
      while (cond.firstChild) frag.appendChild(cond.firstChild)
      cond.replaceWith(frag)
    } else {
      cond.remove()
    }
  }
}

export function renderBoard(raw: string, scope: Scope = referenceScope): string {
  const tpl = document.createElement("template")
  tpl.innerHTML = raw
  expand(tpl.content, scope)
  substituteNode(tpl.content, scope)

  /* Every link on the canvas is href="#". Left alone, each one scrolls to the
     top and rewrites the URL hash — which is the router's. Neutralise them;
     the Live tier gives links real targets. */
  for (const a of Array.from(tpl.content.querySelectorAll('a[href="#"]'))) {
    a.setAttribute("href", "javascript:void 0")
    a.setAttribute("data-ref-link", "")
  }
  const holder = document.createElement("div")
  holder.appendChild(tpl.content)
  return holder.innerHTML
}

@customElement("dn-ref-screen")
export class DnRefScreen extends LitElement {
  /** Canvas board id, e.g. "b2-3". */
  @property({ type: String }) screen = ""
  /** Shown in the chip; the board's code from routes.json. */
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
    this.markup = renderBoard(raw)
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
