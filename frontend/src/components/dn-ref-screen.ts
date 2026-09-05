import { LitElement, html, nothing } from "lit"
import { customElement, property, state } from "lit/decorators.js"
import { unsafeHTML } from "lit/directives/unsafe-html.js"

import type { Actor } from "../data/api"
import { referenceScope } from "../data/seed"
import { pathFor } from "../router"

/**
 * A Reference screen: one board of the design canvas, extracted by
 * scripts/extract-canvas.py, mounted inside the real shell.
 *
 * Reference is the honest tier. The board looks right — it is the approved
 * drawing — and does not write anything: no store, no forms that submit. Its
 * links DO navigate, because their text says where they meant to go and the
 * router knows those places. A screen leaves this tier when a Live component
 * claims its route; the URL never changes.
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
 * Expanding from seed.ts rather than placeholder text means a Reference board
 * and the Live screen beside it show the same ministries, people and projects.
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

/** Expand the canvas's template elements in place, outermost loop first. */
function expand(root: ParentNode, scope: Scope) {
  let loop: Element | null
  while ((loop = root.querySelector("sc-for"))) {
    const outer = loop.parentElement?.closest("sc-for")
    if (outer) loop = outer
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

/* The canvas serialises tables as <sc-raw-table>, <sc-raw-tr>, <sc-raw-td> …
   so the HTML parser leaves their structure alone. A browser renders unknown
   elements inline, which turns every table into one run-on line of text —
   42 tables across the boards. Rename them back to what they are. */
const RAW_TAGS: Record<string, string> = {
  "sc-raw-table": "table",
  "sc-raw-thead": "thead",
  "sc-raw-tbody": "tbody",
  "sc-raw-tfoot": "tfoot",
  "sc-raw-tr": "tr",
  "sc-raw-th": "th",
  "sc-raw-td": "td",
  "sc-raw-caption": "caption",
}

function restoreTables(root: ParentNode) {
  for (const from of Object.keys(RAW_TAGS)) {
    for (const el of Array.from(root.querySelectorAll(from))) {
      const to = document.createElement(RAW_TAGS[from])
      for (const attr of Array.from(el.attributes)) to.setAttribute(attr.name, attr.value)
      if (!to.classList.contains("table") && to.tagName === "TABLE") to.classList.add("table")
      while (el.firstChild) to.appendChild(el.firstChild)
      el.replaceWith(to)
    }
  }
}

export function renderBoard(raw: string, actor: Actor, scope: Scope = referenceScope): string {
  const tpl = document.createElement("template")
  tpl.innerHTML = raw
  expand(tpl.content, scope)
  substituteNode(tpl.content, scope)
  restoreTables(tpl.content)

  /* Every link on the canvas is href="#". Its text says where it meant to go;
     the router knows most of those places. Wired links become real
     navigation; the rest are made inert rather than left to scroll to the top
     and clobber the URL. */
  for (const a of Array.from(tpl.content.querySelectorAll('a[href="#"]'))) {
    const to = pathFor(a.textContent ?? "", actor)
    if (to) {
      a.setAttribute("href", to)
    } else {
      a.setAttribute("href", "javascript:void 0")
      a.setAttribute("data-ref-link", "")
      a.setAttribute("aria-disabled", "true")
    }
  }
  /* Buttons that read as navigation on the drawing. */
  for (const b of Array.from(tpl.content.querySelectorAll("button"))) {
    const to = pathFor(b.textContent ?? "", actor)
    if (to) b.setAttribute("data-goto", to)
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
  /** Whose screen this is — Overview means a different place per actor. */
  @property({ type: String }) actor: Actor = "public"

  @state() private markup: string | null = null
  @state() private missing = false

  protected createRenderRoot() {
    return this
  }

  connectedCallback() {
    super.connectedCallback()
    this.addEventListener("click", this.onClick)
  }

  private onClick = (e: MouseEvent) => {
    const b = (e.target as Element).closest?.("button[data-goto]") as HTMLElement | null
    if (!b) return
    e.preventDefault()
    this.dispatchEvent(new CustomEvent("dn-goto", { detail: b.dataset.goto, bubbles: true, composed: true }))
    history.pushState({}, "", b.dataset.goto!)
    window.dispatchEvent(new CustomEvent("dn:navigate"))
  }

  protected willUpdate(changed: Map<string, unknown>) {
    if (changed.has("screen") || changed.has("actor")) void this.load()
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
    this.markup = renderBoard(raw, this.actor)
  }

  render() {
    if (this.missing) {
      return html`<p class="text-muted" style="padding:32px">
        No reference board for <code>${this.screen}</code>.
      </p>`
    }
    return html`
      <div class="dn-ref" data-screen=${this.screen}>
        ${this.markup ? unsafeHTML(this.markup) : nothing}
        <span class="dn-ref-chip" title="Drawn, not wired yet. Navigation works; forms do not.">
          Reference · ${this.label || this.screen}
        </span>
      </div>
    `
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "dn-ref-screen": DnRefScreen
  }
}
