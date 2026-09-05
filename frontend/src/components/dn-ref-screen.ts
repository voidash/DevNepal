import { LitElement, html, nothing } from "lit"
import { customElement, property, state } from "lit/decorators.js"
import { unsafeHTML } from "lit/directives/unsafe-html.js"

import { api, type Actor, type Session } from "../data"
import { referenceScope } from "../data/seed"
import { href, navigate, pathFor } from "../router"
import { live, type LiveCtx } from "../screens/live/registry"

/**
 * One board of the design canvas, extracted by scripts/extract-canvas.py,
 * mounted inside the real shell — and, when an Enhancer is registered for it,
 * made to work.
 *
 * The design is locked: this element never re-authors a board. It renders the
 * drawn markup, resolves the canvas's own templates against data (seed for a
 * Reference board, the store for a Live one), and hands the result to the
 * board's enhancer to wire up. Same markup either way; the "Reference" chip is
 * the only visible difference, and it goes when the enhancer arrives.
 *
 * Light DOM on purpose: the board is styled by industry.css through global
 * class names, and a shadow root would fence it off from every one of them.
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

/** Expand the canvas's <sc-for> / <sc-if> in place, outermost loop first. */
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
      if (to.tagName === "TABLE") to.classList.add("table")
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
     the router knows most of those places. The rest are made inert rather
     than left to scroll to the top and clobber the URL. */
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
  /** The board's code from routes.json, for the chip. */
  @property({ type: String }) label = ""
  /** Whose screen this is — Overview means a different place per actor. */
  @property({ type: String }) actor: Actor = "public"
  @property({ attribute: false }) params: Record<string, string> = {}
  @property({ attribute: false }) session: Session | null = null

  @state() private markup: string | null = null
  @state() private missing = false

  private loadToken = 0
  private lastKey = ""
  private needsMount = false
  private unsubscribe?: () => void

  protected createRenderRoot() {
    return this
  }

  connectedCallback() {
    super.connectedCallback()
    this.addEventListener("click", this.onClick)
    this.unsubscribe = api.onChange(() => {
      if (live[this.screen]) void this.load()
    })
  }

  disconnectedCallback() {
    this.unsubscribe?.()
    super.disconnectedCallback()
  }

  private onClick = (e: MouseEvent) => {
    const goto = (e.target as Element).closest?.("[data-goto]") as HTMLElement | null
    if (!goto || (e.target as Element).closest("a[href], button:not([data-goto]), input, textarea, select")) return
    e.preventDefault()
    navigate(goto.dataset.goto!)
  }

  private get ctx(): LiveCtx {
    return {
      boardId: this.screen,
      params: this.params,
      session: this.session,
      navigate,
      href,
      signIn: () => this.dispatchEvent(new CustomEvent("dn-signin", { bubbles: true, composed: true })),
      reload: () => void this.load(),
    }
  }

  protected willUpdate() {
    const key = `${this.screen}|${this.actor}|${JSON.stringify(this.params)}|${this.session?.user.handle ?? ""}`
    if (key !== this.lastKey) {
      this.lastKey = key
      void this.load()
    }
  }

  private async load() {
    const token = ++this.loadToken
    const loader = boards[`../screens/ref/${this.screen}.html`]
    if (!loader) {
      this.missing = true
      this.markup = null
      return
    }
    const raw = await loader()
    const enhancer = live[this.screen]
    let scope: Scope = referenceScope
    if (enhancer?.scope) {
      try {
        scope = { ...referenceScope, ...(await enhancer.scope(this.ctx)) }
      } catch (err) {
        console.error(`[dn-ref-screen] scope failed for ${this.screen}`, err)
      }
    }
    if (token !== this.loadToken) return
    this.missing = false
    const next = renderBoard(raw, this.actor, scope)
    /* A board with no scope renders the same string every time, and Lit sees
       an unchanged @state as no change at all — no render, no updated(), no
       mount. But the reason we reloaded (a sign-in, a store write) means the
       enhancer must run again over fresh DOM. Clear first, then set. */
    if (next === this.markup) {
      this.markup = null
      await this.updateComplete
      if (token !== this.loadToken) return
    }
    this.markup = next
    this.needsMount = !!enhancer?.mount
  }

  protected async updated() {
    if (!this.needsMount || !this.markup) return
    this.needsMount = false
    const root = this.querySelector<HTMLElement>(".dn-ref")
    if (!root) return
    try {
      await live[this.screen]?.mount?.(root, this.ctx)
    } catch (err) {
      console.error(`[dn-ref-screen] mount failed for ${this.screen}`, err)
    }
  }

  render() {
    if (this.missing) {
      return html`<p class="text-muted" style="padding:32px">
        No reference board for <code>${this.screen}</code>.
      </p>`
    }
    const isLive = !!live[this.screen]
    return html`
      <div class="dn-ref ${isLive ? "is-live" : "is-reference"}" data-screen=${this.screen}>
        ${this.markup ? unsafeHTML(this.markup) : nothing}
        ${isLive
          ? nothing
          : html`<span class="dn-ref-chip" title="Drawn, not wired yet. Navigation works; forms do not.">
              Reference · ${this.label || this.screen}
            </span>`}
      </div>
    `
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "dn-ref-screen": DnRefScreen
  }
}
