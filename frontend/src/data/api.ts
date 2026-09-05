/**
 * The contract between the screens and whatever stores the data.
 *
 * Two implementations, zero screen changes between them:
 *   MockAdapter   — localStorage, seeded, tonight
 *   DjangoAdapter — fetch("/api/…") against DRF, when the backend lands
 *
 * This file IS the backend spec. Change it first, in a PR both sides approve;
 * then the mock; then Django. Never the other way round.
 */

export type Actor = "public" | "member" | "publisher" | "admin"

export interface Person {
  handle: string
  name: string
  nameNe: string
  initials: string
  role: Exclude<Actor, "public">
  /** Shown under the name in the top bar: "Member", "Ministry Publisher · DoIT". */
  roleLabel: string
  /** Ministry code for publishers. */
  ministry?: string
  designation?: string
}

export interface Session {
  user: Person
  signedInAt: string
}

export type AppState =
  | "applied"
  | "accepted"
  | "declined"
  | "opened"
  | "candidate"
  | "verified"
  | "rejected"
  | "recognised"

export interface Workstream {
  id: string
  projectSlug: string
  title: string
  places: number
  filled: number
  /** Ministry-configured questions asked at apply time. */
  questions: string[]
}

export interface Project {
  slug: string
  title: string
  ne: string
  ministry: string
  short: string
  summary: string
  status: string
  statusClass: string
  stack: string
  types: readonly string[]
  mode: string
  difficulty: string
  effort: string
  response: string
  tasks: number
  contributors: number
  updated: string
  repo?: string
  licence?: string
  deadline?: string
}

export interface Ministry {
  code: string
  name: string
  nameNe: string
  parent?: string
  domain: string
  officers: number
  projects: number
  status: string
  statusClass: string
  mfa: string
  last: string
}

export interface PublicProfile {
  handle: string
  name: string
  nameNe: string
  head: string
  loc: string
  tier: string
  skills: readonly string[]
  open: string
  verified: number
}

export interface Application {
  id: string
  workstreamId: string
  projectSlug: string
  memberHandle: string
  answers: string[]
  state: AppState
  createdAt: string
  decidedBy?: string
  decidedAt?: string
  note?: string
}

export interface Evidence {
  id: string
  applicationId: string
  kind: "link" | "file"
  url: string
  note: string
  state: "candidate" | "verified" | "rejected"
  createdAt: string
  verifiedBy?: string
  verifiedAt?: string
  verifierNote?: string
}

export interface RecognitionRecord {
  id: string
  memberHandle: string
  applicationId: string
  projectSlug: string
  acceptedBy: string
  via: "evidence" | "merge"
  score: number
  badge?: string
  at: string
}

export interface TimelineEvent {
  id: string
  applicationId: string
  at: string
  kind: AppState | "evidence"
  by: string
  text: string
}

export interface Notification {
  id: string
  forHandle: string
  at: string
  text: string
  kind: "info" | "security"
  read: boolean
  href?: string
}

export interface ProjectFilters {
  q?: string
  ministry?: string
  type?: string
  difficulty?: string
}

export interface DevNepalAPI {
  // session
  me(): Promise<Session | null>
  /** Demo: sign in as a seeded account by handle. Django: provider OAuth. */
  signIn(handle: string): Promise<Session>
  signOut(): Promise<void>
  /** Accounts available to the demo sign-in dialog. */
  accounts(): Promise<Person[]>

  // discovery (public)
  projects(f?: ProjectFilters): Promise<Project[]>
  project(slug: string): Promise<Project | undefined>
  workstreams(slug: string): Promise<Workstream[]>
  ministry(code: string): Promise<Ministry | undefined>
  member(handle: string): Promise<PublicProfile | undefined>

  // applications (member writes, publisher decides)
  apply(workstreamId: string, answers: string[]): Promise<Application>
  application(id: string): Promise<Application | undefined>
  myApplications(): Promise<Application[]>
  applications(q: { ministry: string; state?: AppState }): Promise<Application[]>
  decide(appId: string, decision: "accepted" | "declined", note: string): Promise<Application>

  // contribution and recognition
  submitEvidence(appId: string, e: { kind: "link" | "file"; url: string; note: string }): Promise<Evidence>
  evidenceFor(appId: string): Promise<Evidence[]>
  verificationQueue(ministry: string): Promise<Evidence[]>
  verify(evidenceId: string, decision: "accepted" | "rejected", note?: string): Promise<Evidence>
  recognition(handle: string): Promise<RecognitionRecord[]>
  timeline(appId: string): Promise<TimelineEvent[]>

  notifications(): Promise<Notification[]>
  /** Fires after any write, in this tab or another. Returns an unsubscribe. */
  onChange(cb: () => void): () => void
}
