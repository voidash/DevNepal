import routesJson from "./routes.json"
import type { Actor } from "./data/api"

/**
 * Path routing over the screen inventory.
 *
 * Every board in routes.json is a route. A Live screen claims a board by
 * registering its tag name against the board id in screens/live; everything
 * unclaimed renders as a Reference board. Same URL either way, so a screen
 * going live changes nothing for a link that points at it.
 *
 * History-API paths, not hashes: the demo is shared as URLs, and
 * /projects/sewa-portal-accessibility reads like a product. The static host
 * needs one rewrite rule to index.html (GitHub Pages: a 404.html copy).
 */

export interface Route {
  id: string
  code: string
  label: string
  actor: Actor
  job: string
  path: string
  hasMain: boolean
  story: string
}

export const routes = routesJson as Route[]

const byId = new Map(routes.map((r) => [r.id, r]))

interface Compiled {
  route: Route
  keys: string[]
  re: RegExp
  weight: number
}

const compiled: Compiled[] = routes
  .map((route) => {
    const keys: string[] = []
    const pattern = route.path
      .split("/")
      .map((seg) => {
        if (seg.startsWith(":")) {
          keys.push(seg.slice(1))
          return "([^/]+)"
        }
        return seg.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
      })
      .join("/")
    /* Static segments outrank params so /projects/public-example beats
       /projects/:slug. */
    const weight = route.path.split("/").filter((s) => s && !s.startsWith(":")).length * 10 - keys.length
    return { route, keys, re: new RegExp(`^${pattern}/?$`), weight }
  })
  .sort((a, b) => b.weight - a.weight)

export interface Match {
  route: Route
  params: Record<string, string>
}

export function match(pathname: string): Match | null {
  const path = pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname
  for (const c of compiled) {
    const m = c.re.exec(path)
    if (!m) continue
    const params: Record<string, string> = {}
    c.keys.forEach((k, i) => (params[k] = decodeURIComponent(m[i + 1])))
    return { route: c.route, params }
  }
  return null
}

/** Build a path for a board, filling params: href("a2-2", { slug }) */
export function href(id: string, params: Record<string, string | number> = {}): string {
  const r = byId.get(id)
  if (!r) return `/${id}`
  return r.path.replace(/:(\w+)/g, (_, k: string) => encodeURIComponent(String(params[k] ?? "demo")))
}

export function route(id: string): Route | undefined {
  return byId.get(id)
}

export const NAVIGATE = "dn:navigate"

export function navigate(path: string, replace = false) {
  if (path === location.pathname + location.search) return
  if (replace) history.replaceState({}, "", path)
  else history.pushState({}, "", path)
  window.dispatchEvent(new CustomEvent(NAVIGATE, { detail: { path } }))
}

/* ── canvas link text → app path ────────────────────────────────────────────
   The boards' links are all href="#". Their TEXT says where they meant to go.
   Anything not mapped stays inert (the ref viewer marks it). Overview differs
   by actor, so the lookup takes one. */
const COMMON: Record<string, string> = {
  home: "/",
  devnepal: "/",
  "government projects": "/projects",
  "browse government projects": "/projects",
  "browse projects": "/projects",
  "all projects": "/projects",
  "community projects": "/community",
  members: "/members",
  "members directory": "/members",
  "tech blogs": "/blogs",
  blogs: "/blogs",
  recognition: "/recognition",
  leaderboard: "/recognition",
  badges: "/recognition/badges",
  "badges and prestige tiers": "/recognition/badges",
  "how to contribute": "/how-to-contribute",
  "how it works": "/how-to-contribute",
  "sign in": "/sign-in",
  "sign in to apply": "/sign-in",
  "create account": href("b1-2"),
  apply: `/projects/sewa-portal-accessibility/apply`,
  "apply to a workstream": `/projects/sewa-portal-accessibility/apply`,
  "view project": "/projects/sewa-portal-accessibility",
  "open project": "/projects/sewa-portal-accessibility",
  "my applications": href("b6-5", { id: "demo" }),
  notifications: "/me",
  dashboard: "/me",
  "profile & visibility": href("b5-1"),
  "profile and visibility": href("b5-1"),
  connections: href("b5-2"),
  "connections & data": href("b5-2"),
  "email preferences": href("b5-3"),
  "recognition settings": href("b5-4"),
  "my community projects": href("b3-7"),
  "my blog posts": href("b4-7"),
  "new post": href("b4-1"),
  "list a community project": href("b3-1"),
  "verification queue": "/ministry/verification",
  applications: "/ministry",
  officers: href("c1-5"),
  analytics: href("c5-4"),
  "audit log": href("c6-2"),
  "audit log · my actions": href("c6-2"),
  "progress updates": href("c5-1"),
  projects: "/projects",
  "review queue": href("d2-1"),
  "reports & moderation": href("d3-2"),
  "recognition · anomalies": href("d4-2"),
  "ministry organizations": href("d1-2"),
  "operational dashboards": "/admin",
  "sync health": href("d5-3"),
  "privileged access": href("d5-8"),
}

const OVERVIEW: Record<Actor, string> = {
  public: "/",
  member: "/me",
  publisher: "/ministry",
  admin: "/admin",
}

/* Second pass for the canvas's "All 1,930 members →" and "Browse government
   projects" phrasings: strip counts and verbs, then match on the noun. Order
   matters — "community projects" must win over "projects". */
const FUZZY: [RegExp, string][] = [
  [/community project/, "/community"],
  [/government project|open project|browse project|\bprojects?\b/, "/projects"],
  [/leaderboard|badge|recognition/, "/recognition"],
  [/\bmembers?\b|directory/, "/members"],
  [/\bposts?\b|\bblogs?\b|writing/, "/blogs"],
  [/how listing works|nominate|publisher|how to contribute|contribute/, "/how-to-contribute"],
  [/join with github|sign in|create account/, "/sign-in"],
]

export function pathFor(linkText: string, actor: Actor = "public"): string | null {
  const key = linkText.replace(/\s+/g, " ").replace(/[→←›»]/g, "").trim().toLowerCase()
  if (!key) return null
  if (key === "overview") return OVERVIEW[actor]
  const exact = COMMON[key]
  if (exact) return exact
  const loose = key.replace(/^(all|browse|see|view|open|explore)\s+/, "").replace(/[\d,]+\s*/g, "")
  for (const [re, path] of FUZZY) if (re.test(loose)) return path
  return null
}
