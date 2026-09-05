import type {
  AppState,
  Application,
  DevNepalAPI,
  Evidence,
  Ministry,
  Notification,
  Person,
  Project,
  ProjectFilters,
  PublicProfile,
  RecognitionRecord,
  Session,
  TimelineEvent,
  Workstream,
} from "./api"
import { members, ministries, projects as seedProjects } from "./seed"

/**
 * The store behind the demo: localStorage, seeded, shared across tabs.
 *
 * Two browser windows — a member in one, a ministry publisher in the other —
 * see each other's writes without a reload, because every mutation persists
 * and the `storage` event re-emits to the other tab. That is the whole
 * "in sync" story for tomorrow, and it costs nothing.
 *
 * Reads are synchronous underneath; the API is async so that DjangoAdapter
 * can replace this class method by method without a screen noticing.
 */

const KEY = "devnepal-store-v1"

/* The people who can sign in. Members come from the seed; officers are added
   here because they are accounts, not directory entries. */
export const accounts: Person[] = [
  { handle: "@sabina", name: "Sabina Rai",      nameNe: "सबिना राई",     initials: "SR", role: "member",    roleLabel: "Member" },
  { handle: "@rajan",  name: "Rajan Koirala",   nameNe: "राजन कोइराला",  initials: "RK", role: "publisher", roleLabel: "Ministry Publisher · DoIT",     ministry: "DoIT",    designation: "Director, IT Section" },
  { handle: "@sarita", name: "Sarita Gautam",   nameNe: "सरिता गौतम",    initials: "SG", role: "publisher", roleLabel: "Ministry Publisher · MoLMCPA",  ministry: "MoLMCPA", designation: "Under Secretary, IT Section" },
  { handle: "@bikash", name: "Bikash Neupane",  nameNe: "विकास न्यौपाने", initials: "BN", role: "admin",     roleLabel: "Super Admin · PMO",             designation: "Under Secretary" },
]

/* Workstreams are derived from the seed projects. The Sewa Portal ones match
   the canvas board B2.3 word for word; the rest follow the project's types. */
const DEFAULT_QUESTIONS = [
  "What relevant work have you done before? A link is enough.",
  "Hours per week you can commit",
]
const SEWA_QUESTIONS = [
  "Which assistive technologies have you tested with?",
  "Hours per week you can commit",
]

function buildWorkstreams(): Workstream[] {
  const out: Workstream[] = []
  for (const p of seedProjects) {
    if (p.slug === "sewa-portal-accessibility") {
      out.push(
        { id: `${p.slug}/screen-reader`, projectSlug: p.slug, title: "Screen-reader labelling (Nepali)", places: 4, filled: 2, questions: SEWA_QUESTIONS },
        { id: `${p.slug}/contrast`,      projectSlug: p.slug, title: "Contrast and focus states",        places: 2, filled: 1, questions: SEWA_QUESTIONS },
        { id: `${p.slug}/keyboard-qa`,   projectSlug: p.slug, title: "Keyboard paths · QA",              places: 2, filled: 2, questions: SEWA_QUESTIONS },
      )
      continue
    }
    p.types.forEach((t, i) => {
      out.push({
        id: `${p.slug}/${t.toLowerCase().replace(/[^a-z]+/g, "-")}`,
        projectSlug: p.slug,
        title: `${t} · ${p.title}`,
        places: 2 + (i % 2),
        filled: i === 0 ? 1 : 0,
        questions: DEFAULT_QUESTIONS,
      })
    })
  }
  return out
}

interface State {
  session: Session | null
  applications: Application[]
  evidence: Evidence[]
  recognition: RecognitionRecord[]
  timeline: TimelineEvent[]
  notifications: Notification[]
  seq: number
}

const empty = (): State => ({
  session: null,
  applications: [],
  evidence: [],
  recognition: [],
  timeline: [],
  notifications: [],
  seq: 1,
})

const now = () => new Date().toISOString()

export class MockAdapter implements DevNepalAPI {
  private state: State
  private listeners = new Set<() => void>()
  private readonly workstreamList = buildWorkstreams()

  constructor() {
    this.state = this.read()
    window.addEventListener("storage", (e) => {
      if (e.key !== KEY) return
      this.state = this.read()
      this.emit()
    })
  }

  // ── persistence ─────────────────────────────────────────────────────────
  private read(): State {
    try {
      const raw = localStorage.getItem(KEY)
      return raw ? { ...empty(), ...(JSON.parse(raw) as Partial<State>) } : empty()
    } catch {
      return empty()
    }
  }
  private write() {
    try {
      localStorage.setItem(KEY, JSON.stringify(this.state))
    } catch {
      /* private mode — the demo still works within this tab */
    }
    this.emit()
  }
  private emit() {
    for (const l of this.listeners) l()
  }
  private id(prefix: string) {
    return `${prefix}-${String(this.state.seq++).padStart(3, "0")}`
  }
  private log(applicationId: string, kind: TimelineEvent["kind"], by: string, text: string) {
    this.state.timeline.push({ id: this.id("ev"), applicationId, at: now(), kind, by, text })
  }
  private notify(forHandle: string, text: string, href?: string, kind: Notification["kind"] = "info") {
    this.state.notifications.unshift({ id: this.id("n"), forHandle, at: now(), text, kind, read: false, href })
  }
  private requireUser(): Person {
    const u = this.state.session?.user
    if (!u) throw new Error("Not signed in")
    return u
  }

  onChange(cb: () => void) {
    this.listeners.add(cb)
    return () => this.listeners.delete(cb)
  }

  // ── session ─────────────────────────────────────────────────────────────
  async me() {
    return this.state.session
  }
  async accounts() {
    return accounts
  }
  async signIn(handle: string) {
    const user = accounts.find((a) => a.handle === handle)
    if (!user) throw new Error(`No account ${handle}`)
    this.state.session = { user, signedInAt: now() }
    this.write()
    return this.state.session
  }
  async signOut() {
    this.state.session = null
    this.write()
  }

  // ── discovery ───────────────────────────────────────────────────────────
  async projects(f: ProjectFilters = {}) {
    const q = f.q?.trim().toLowerCase()
    return (seedProjects as readonly Project[]).filter((p) => {
      if (f.ministry && p.ministry !== f.ministry) return false
      if (f.type && !p.types.includes(f.type)) return false
      if (f.difficulty && p.difficulty !== f.difficulty) return false
      if (q) {
        const hay = `${p.title} ${p.ne} ${p.ministry} ${p.stack} ${p.summary} ${p.types.join(" ")}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }
  async project(slug: string) {
    return (seedProjects as readonly Project[]).find((p) => p.slug === slug)
  }
  async workstreams(slug: string) {
    return this.workstreamList.filter((w) => w.projectSlug === slug)
  }
  async ministry(code: string) {
    const m = (ministries as readonly Ministry[]).find((x) => x.code === code)
    if (!m) return undefined
    const projectsCount = seedProjects.filter((p) => p.ministry === code).length
    return { ...m, projects: projectsCount }
  }
  async member(handle: string) {
    return (members as readonly PublicProfile[]).find((m) => m.handle === handle)
  }

  // ── applications ────────────────────────────────────────────────────────
  async apply(workstreamId: string, answers: string[]) {
    const user = this.requireUser()
    const ws = this.workstreamList.find((w) => w.id === workstreamId)
    if (!ws) throw new Error("Unknown workstream")
    const existing = this.state.applications.find(
      (a) => a.workstreamId === workstreamId && a.memberHandle === user.handle && a.state !== "declined"
    )
    if (existing) return existing
    const project = await this.project(ws.projectSlug)
    const app: Application = {
      id: this.id("app"),
      workstreamId,
      projectSlug: ws.projectSlug,
      memberHandle: user.handle,
      answers,
      state: "applied",
      createdAt: now(),
    }
    this.state.applications.push(app)
    this.log(app.id, "applied", user.handle, `Applied to ${ws.title}`)
    const officers = accounts.filter((a) => a.role === "publisher" && a.ministry === project?.ministry)
    for (const o of officers) {
      this.notify(o.handle, `${user.name} applied to ${ws.title}`, `/ministry/applications/${app.id}`)
    }
    this.write()
    return app
  }
  async application(id: string) {
    return this.state.applications.find((a) => a.id === id)
  }
  async myApplications() {
    const user = this.state.session?.user
    if (!user) return []
    return this.state.applications.filter((a) => a.memberHandle === user.handle)
  }
  async applications(q: { ministry: string; state?: AppState }) {
    const slugs = new Set<string>(seedProjects.filter((p) => p.ministry === q.ministry).map((p) => p.slug))
    return this.state.applications.filter(
      (a) => slugs.has(a.projectSlug) && (!q.state || a.state === q.state)
    )
  }
  async decide(appId: string, decision: "accepted" | "declined", note: string) {
    const officer = this.requireUser()
    const app = this.state.applications.find((a) => a.id === appId)
    if (!app) throw new Error("Unknown application")
    app.state = decision
    app.decidedBy = officer.handle
    app.decidedAt = now()
    app.note = note
    const ws = this.workstreamList.find((w) => w.id === app.workstreamId)
    if (decision === "accepted" && ws) ws.filled = Math.min(ws.places, ws.filled + 1)
    this.log(appId, decision, officer.handle, decision === "accepted" ? `Accepted by ${officer.name}` : `Declined by ${officer.name}`)
    this.notify(
      app.memberHandle,
      decision === "accepted"
        ? `${officer.name} accepted your application — here is where to begin`
        : `Your application was not taken forward this time`,
      decision === "accepted" ? `/me/applications/${appId}/accepted` : `/me/applications/${appId}`
    )
    this.write()
    return app
  }

  // ── contribution and recognition ────────────────────────────────────────
  async submitEvidence(appId: string, e: { kind: "link" | "file"; url: string; note: string }) {
    const user = this.requireUser()
    const app = this.state.applications.find((a) => a.id === appId)
    if (!app) throw new Error("Unknown application")
    if (app.state !== "accepted" && app.state !== "opened") throw new Error("Application is not open for evidence")
    const ev: Evidence = { id: this.id("evd"), applicationId: appId, ...e, state: "candidate", createdAt: now() }
    this.state.evidence.push(ev)
    app.state = "candidate"
    this.log(appId, "evidence", user.handle, `Evidence submitted: ${e.note || e.url}`)
    const project = await this.project(app.projectSlug)
    for (const o of accounts.filter((a) => a.role === "publisher" && a.ministry === project?.ministry)) {
      this.notify(o.handle, `${user.name} submitted evidence to verify`, `/ministry/verification/${ev.id}`)
    }
    this.write()
    return ev
  }
  async evidenceFor(appId: string) {
    return this.state.evidence.filter((e) => e.applicationId === appId)
  }
  async verificationQueue(ministry: string) {
    const slugs = new Set<string>(seedProjects.filter((p) => p.ministry === ministry).map((p) => p.slug))
    const appIds = new Set(this.state.applications.filter((a) => slugs.has(a.projectSlug)).map((a) => a.id))
    return this.state.evidence.filter((e) => appIds.has(e.applicationId))
  }
  async verify(evidenceId: string, decision: "accepted" | "rejected", note?: string) {
    const officer = this.requireUser()
    const ev = this.state.evidence.find((e) => e.id === evidenceId)
    if (!ev) throw new Error("Unknown evidence")
    const app = this.state.applications.find((a) => a.id === ev.applicationId)!
    ev.state = decision === "accepted" ? "verified" : "rejected"
    ev.verifiedBy = officer.handle
    ev.verifiedAt = now()
    ev.verifierNote = note
    if (decision === "accepted") {
      app.state = "recognised"
      const first = !this.state.recognition.some((r) => r.memberHandle === app.memberHandle)
      const record: RecognitionRecord = {
        id: this.id("rec"),
        memberHandle: app.memberHandle,
        applicationId: app.id,
        projectSlug: app.projectSlug,
        acceptedBy: officer.handle,
        via: "evidence",
        score: 38,
        badge: first ? "First accepted" : undefined,
        at: now(),
      }
      this.state.recognition.push(record)
      this.log(app.id, "verified", officer.handle, `Verified by ${officer.name}`)
      this.log(app.id, "recognised", "system", first ? "Recognised · First-accepted badge · 38 points" : "Recognised · 38 points")
      this.notify(app.memberHandle, `${officer.name} verified your work — it now counts`, `/me/applications/${app.id}/recognised`)
    } else {
      app.state = "rejected"
      this.log(app.id, "rejected", officer.handle, `Not verified: ${note ?? "no reason given"}`)
      this.notify(app.memberHandle, `Your evidence was not verified — see the reason`, `/me/applications/${app.id}`)
    }
    this.write()
    return ev
  }
  async recognition(handle: string) {
    return this.state.recognition.filter((r) => r.memberHandle === handle)
  }
  async timeline(appId: string) {
    return this.state.timeline.filter((t) => t.applicationId === appId)
  }
  async notifications() {
    const user = this.state.session?.user
    if (!user) return []
    return this.state.notifications.filter((n) => n.forHandle === user.handle)
  }
}
