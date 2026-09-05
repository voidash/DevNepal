import { LitElement, html, nothing } from "lit"
import { customElement, state } from "lit/decorators.js"
import { unsafeStatic, html as staticHtml } from "lit/static-html.js"

import "./tokens/industry.css"
import "./tokens/industry-ext.css"
import "./app.css"

import "./components/dn-topnav"
import "./components/dn-sidebar"
import "./components/dn-footer"
import "./components/dn-page-header"
import "./components/dn-role-switch"
import "./components/dn-ref-screen"
import "./screens/live"

import { api, type Actor, type Session } from "./data"
import { live } from "./screens/live"
import { NAVIGATE, match, navigate, type Match } from "./router"

/**
 * The application root.
 *
 * Owns three things and nothing else: the current URL, the session, and the
 * shell around whatever screen the URL names. The screen is a Live component
 * when one has claimed the board, and the Reference board otherwise — same
 * URL, same shell, same data underneath.
 *
 * Light DOM throughout: the whole app is styled by one global stylesheet in
 * the canvas's own design system, and shadow roots would fence it off.
 */
const LANG_KEY = "devnepal-lang"

@customElement("dn-app")
export class DnApp extends LitElement {
  @state() private path = location.pathname
  @state() private session: Session | null = null
  @state() private unread = 0
  @state() private counts: Record<string, string | number> = {}
  /* Not `lang` — that is HTMLElement.lang, and setting it would stamp lang="ne"
     on the app root and give every Latin string Devanagari metrics. */
  @state() private uiLang: "en" | "ne" = "en"

  private unsubscribe?: () => void

  protected createRenderRoot() {
    return this
  }

  async connectedCallback() {
    super.connectedCallback()
    window.addEventListener("popstate", this.onNav)
    window.addEventListener(NAVIGATE, this.onNav)
    this.addEventListener("click", this.onClick)
    this.addEventListener("dn-signin", () => this.dialog?.open())
    this.addEventListener("dn-account", () => this.signOut())
    this.addEventListener("dn-lang", (e) => this.setLang((e as CustomEvent<"en" | "ne">).detail))
    this.addEventListener("dn-signed-in", (e) => this.onSignedIn((e as CustomEvent<Session>).detail))
    this.addEventListener("dn-notifications", () => navigate(this.home(this.session?.user.role ?? "public")))

    try {
      const stored = localStorage.getItem(LANG_KEY)
      if (stored === "ne" || stored === "en") this.uiLang = stored
    } catch { /* ignore */ }
    document.documentElement.lang = this.uiLang

    this.unsubscribe = api.onChange(() => void this.refresh())
    await this.refresh()
  }

  disconnectedCallback() {
    window.removeEventListener("popstate", this.onNav)
    window.removeEventListener(NAVIGATE, this.onNav)
    this.unsubscribe?.()
    super.disconnectedCallback()
  }

  private get dialog() {
    return this.querySelector("dn-role-switch")
  }

  private onNav = () => {
    this.path = location.pathname
    window.scrollTo({ top: 0 })
  }

  /* One listener for every in-app link, including those inside Reference
     boards: a same-origin path becomes a client-side navigation. */
  private onClick = (e: MouseEvent) => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    const a = (e.target as Element).closest?.("a[href]") as HTMLAnchorElement | null
    if (!a || a.target === "_blank" || a.hasAttribute("download")) return
    const href = a.getAttribute("href") ?? ""
    if (!href.startsWith("/")) return
    e.preventDefault()
    navigate(href)
  }

  private async refresh() {
    this.session = await api.me()
    const u = this.session?.user
    if (!u) {
      this.unread = 0
      this.counts = {}
      return
    }
    const notes = await api.notifications()
    this.unread = notes.filter((n) => !n.read).length
    if (u.role === "member") {
      const apps = await api.myApplications()
      const rec = await api.recognition(u.handle)
      this.counts = { applications: apps.length || "", verified: rec.length || "", notifications: this.unread || "", bookmarks: 5, community: 1, posts: 4 }
    } else if (u.role === "publisher" && u.ministry) {
      const apps = await api.applications({ ministry: u.ministry })
      const queue = await api.verificationQueue(u.ministry)
      const m = await api.ministry(u.ministry)
      this.counts = {
        projects: m?.projects ?? "",
        applications: apps.filter((a) => a.state === "applied").length || "",
        verification: queue.filter((q) => q.state === "candidate").length || "",
        officers: "view",
      }
    } else {
      this.counts = { review: 6, moderation: 4, anomalies: 3, sync: "1 failing" }
    }
  }

  private home(role: Actor) {
    return role === "member" ? "/me" : role === "publisher" ? "/ministry" : role === "admin" ? "/admin" : "/"
  }

  private async onSignedIn(session: Session) {
    this.session = session
    await this.refresh()
    /* Return to what they were doing if it makes sense for the role; else home. */
    const m = match(this.path)
    const stay = m && (m.route.actor === "public" || m.route.actor === session.user.role) && this.path !== "/sign-in"
    navigate(stay ? this.path : this.home(session.user.role))
  }

  private async signOut() {
    await api.signOut()
    await this.refresh()
    navigate("/")
  }

  private setLang(lang: "en" | "ne") {
    this.uiLang = lang
    document.documentElement.lang = lang
    try { localStorage.setItem(LANG_KEY, lang) } catch { /* ignore */ }
  }

  /* /sign-in is a place a link can point at, so it is a route — but the thing
     it names is the dialog, not a page. Arriving there opens it over whatever
     is underneath (the A2.3 board, which draws exactly this). */
  protected updated() {
    if (this.path === "/sign-in" && !this.session) {
      const d = this.dialog
      if (d && !d.querySelector("dialog[open]")) d.open()
    }
  }

  private screen(m: Match) {
    const tag = live[m.route.id]
    if (tag) {
      /* A Live screen. Params arrive as attributes; the component reads the
         store itself. */
      const t = unsafeStatic(tag)
      return staticHtml`<${t} .params=${m.params} .session=${this.session}></${t}>`
    }
    return html`<dn-ref-screen .screen=${m.route.id} .label=${m.route.code} .actor=${m.route.actor}></dn-ref-screen>`
  }

  render() {
    const m = match(this.path)
    /* The shell follows the SCREEN's actor, not the session: a signed-in
       member browsing the public catalog still sees the public frame, with
       their name in the top bar. */
    const actor: Actor = m?.route.actor ?? "public"
    const isPublic = actor === "public"

    return html`
      <div class="dn-frame ${isPublic ? "is-public" : "is-app"}">
        <dn-topnav
          .actor=${actor}
          .session=${this.session}
          .path=${this.path}
          .unread=${this.unread}
          .uiLang=${this.uiLang}
        ></dn-topnav>

        <div class="dn-body ${isPublic ? "" : "has-side"}">
          ${isPublic
            ? nothing
            : html`<dn-sidebar .actor=${actor} .session=${this.session} .current=${m?.route.id ?? ""} .counts=${this.counts}></dn-sidebar>`}
          <div class="dn-content">
            ${m
              ? this.screen(m)
              : html`
                  <div class="dn-notfound">
                    <div class="card-kicker">404</div>
                    <h1>There is no page at ${this.path}</h1>
                    <p class="text-muted">Nothing here yet. <a href="/">Back to DevNepal</a>.</p>
                  </div>
                `}
          </div>
        </div>

        ${isPublic ? html`<dn-footer></dn-footer>` : nothing}
        <dn-role-switch></dn-role-switch>
      </div>
    `
  }
}

declare global {
  interface HTMLElementTagNameMap {
    "dn-app": DnApp
  }
}
