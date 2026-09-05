import { api, type Application, type Evidence } from "../../data"
import { registerLive, type LiveCtx } from "./registry"
import {
  allByText,
  busy,
  field,
  findByText,
  firstName,
  fmtDate,
  norm,
  plusWorkingDays,
  relTime,
  replaceText,
  segGroup,
  setText,
  STATE_LABEL,
  toTextarea,
  toast,
} from "./util"

/** Enhancers for the ministry publisher: inbox → decide → verify. */

async function requirePublisher(ctx: LiveCtx) {
  const u = ctx.session?.user
  if (u?.role === "publisher" && u.ministry) return u
  ctx.signIn()
  return null
}

/* Rows rendered by scope, in order; mount maps row index → record. */
let inboxIds: string[] = []
let inboxEvidence: Record<string, string> = {}

/* ── C3.1 · Ministry overview ─────────────────────────────────────────────── */
registerLive("c3-1", {
  async scope(ctx) {
    const u = ctx.session?.user
    if (u?.role !== "publisher" || !u.ministry) return {}
    const code = u.ministry
    const projects = await api.projects({ ministry: code })
    const apps = await api.applications({ ministry: code })
    const queue = await api.verificationQueue(code)
    inboxEvidence = {}
    for (const e of queue) if (e.state === "candidate") inboxEvidence[e.applicationId] = e.id

    const pubProjects = await Promise.all(
      projects.map(async (p) => {
        const mine = apps.filter((a) => a.projectSlug === p.slug)
        const fresh = mine.filter((a) => a.state === "applied").length
        const cands = mine.filter((a) => a.state === "candidate").length
        const state = p.status === "Open" ? "Live" : p.status
        const stateClass = p.status === "Open" ? "tag-success" : p.status === "Paused" ? "tag-warning" : "tag-neutral"
        return {
          title: p.title,
          state,
          stateClass,
          apps: fresh ? `${fresh} new` : "—",
          cands: cands ? `${cands} to verify` : "—",
          response: p.status === "Open" ? p.response : "—",
          action: fresh ? "Respond" : cands ? "Verify" : "View",
        }
      })
    )

    const ordered = [...apps].sort((a, b) => b.createdAt.localeCompare(a.createdAt))
    inboxIds = ordered.map((a) => a.id)
    const rows = await Promise.all(
      ordered.map(async (a) => {
        const m = await api.member(a.memberHandle)
        const ws = (await api.workstreams(a.projectSlug)).find((w) => w.id === a.workstreamId)
        const s = STATE_LABEL[a.state] ?? { label: a.state, cls: "tag-neutral" }
        return { who: m?.name ?? a.memberHandle, handle: a.memberHandle, ws: ws?.title ?? "", when: relTime(a.createdAt), state: s.label, stateClass: s.cls }
      })
    )
    return { pubProjects, apps: rows }
  },

  async mount(root, ctx) {
    const u = await requirePublisher(ctx)
    if (!u) return
    const m = await api.ministry(u.ministry!)
    const apps = await api.applications({ ministry: u.ministry! })
    const applied = apps.filter((a) => a.state === "applied")
    const cands = apps.filter((a) => a.state === "candidate")
    const projects = await api.projects({ ministry: u.ministry! })

    const sub = root.querySelector("h1")?.nextElementSibling
    if (sub) setText(sub, `${m?.name ?? u.ministry} · ${new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}`)

    // the four tiles: label, number, footnote
    const tile = (label: string) => findByText(root, "span", label, "starts")?.parentElement
    const set = (label: string, n: string, foot: string) => {
      const t = tile(label)
      if (!t) return
      const spans = t.querySelectorAll(":scope > span")
      setText(spans[1], n)
      if (spans[2]) spans[2].innerHTML = foot
    }
    const open = projects.filter((p) => p.status === "Open").length
    set("Open for contribution", String(open), `${projects.filter((p) => p.status === "Draft").length} draft · ${projects.filter((p) => p.status === "Paused").length} paused`)
    set("Applications awaiting response", String(applied.length), applied.length ? `oldest ${relTime(applied[0].createdAt)}` : "none waiting")
    set("Candidate contributions to verify", String(cands.length), cands.length ? `${cands.length} evidence submission${cands.length === 1 ? "" : "s"}` : "nothing to verify")

    // SLA banner only when something is actually late (nothing is, tonight)
    /* The banner is a direct child of <main>; its parent is the whole board.
       Hide the banner itself — nothing is past SLA in a store created tonight. */
    const banner = findByText(root, "b", "have waited longer")?.closest("div")
    if (banner) (banner as HTMLElement).style.display = "none"

    // inbox rows
    const inbox = findByText(root, "table", "Applicant")
    const trs = inbox ? Array.from(inbox.querySelectorAll("tbody tr")) : []
    trs.forEach((tr, i) => {
      const id = inboxIds[i]
      const a = apps.find((x) => x.id === id)
      if (!a) return
      const cellActions = tr.querySelector("td:last-child")
      const nameCell = tr.querySelector("td")
      if (nameCell) {
        nameCell.style.cursor = "pointer"
        nameCell.addEventListener("click", () => ctx.navigate(`/ministry/applications/${a.id}`))
      }
      if (!cellActions) return
      const buttons = Array.from(cellActions.querySelectorAll<HTMLButtonElement>("button"))
      if (a.state === "applied") {
        for (const b of buttons) {
          const label = norm(b.textContent)
          b.addEventListener("click", async () => {
            if (label === "Accept" || label === "Decline") {
              const restore = busy(b, "…")
              try {
                await api.decide(a.id, label === "Accept" ? "accepted" : "declined", label === "Accept" ? "Welcome — see the starter task on your dashboard." : "Thank you for applying; the workstream is full for now.")
                toast(label === "Accept" ? `Accepted · ${a.memberHandle} has been told` : `Declined · ${a.memberHandle} has been told`)
              } catch (err) {
                restore()
                toast((err as Error).message, "info")
              }
            } else {
              ctx.navigate(`/ministry/applications/${a.id}`)
            }
          })
        }
      } else {
        cellActions.innerHTML = ""
        const link = document.createElement("a")
        if (a.state === "candidate" && inboxEvidence[a.id]) {
          link.href = `/ministry/verification/${inboxEvidence[a.id]}`
          link.textContent = "Verify →"
        } else {
          link.href = `/ministry/applications/${a.id}`
          link.textContent = "View"
        }
        cellActions.appendChild(link)
      }
    })
    if (!trs.length && inbox) {
      const tbody = inbox.querySelector("tbody")
      if (tbody) tbody.innerHTML = `<tr><td colspan="5" class="text-muted" style="padding:18px 12px">No applications yet. When a member applies to one of your workstreams it appears here, and you are notified.</td></tr>`
    }
    const inboxTitle = findByText(root, "div", "Applications inbox ·", "starts")
    if (inboxTitle) setText(inboxTitle, `Applications inbox · ${projects.map((p) => p.title).slice(0, 1).join("")}${projects.length > 1 ? ` and ${projects.length - 1} more` : ""}`)

    // project table action links
    const projTable = findByText(root, "table", "Lifecycle state")
    projTable?.querySelectorAll("tbody tr").forEach((tr, i) => {
      const p = projects[i]
      const a = tr.querySelector("td:last-child a")
      if (!p || !a) return
      a.setAttribute("href", `/projects/${p.slug}`)
      a.removeAttribute("data-ref-link")
    })
    const projTitle = findByText(root, "div", "Projects ·", "starts")
    if (projTitle) setText(projTitle, `Projects · ${projects.length}`)

    const newDraft = findByText<HTMLButtonElement>(root, "button", "New project draft")
    newDraft?.addEventListener("click", () => ctx.navigate(ctx.href("c2-1")))
    for (const a of allByText<HTMLAnchorElement>(root, "a", "Respond now")) {
      a.setAttribute("href", applied[0] ? `/ministry/applications/${applied[0].id}` : "/ministry")
      a.removeAttribute("data-ref-link")
    }
  },
})

/* ── C3.2 · Application detail ────────────────────────────────────────────── */
registerLive("c3-2", {
  async mount(root, ctx) {
    const u = await requirePublisher(ctx)
    if (!u) return
    const a: Application | undefined = await api.application(ctx.params.id)
    if (!a) return ctx.navigate("/ministry")
    const m = await api.member(a.memberHandle)
    const p = await api.project(a.projectSlug)
    const ws = (await api.workstreams(a.projectSlug)).find((w) => w.id === a.workstreamId)
    const name = m?.name ?? a.memberHandle
    const first = firstName(name)

    replaceText(root, "Kritika Poudel", name)
    replaceText(root, "@kritika", a.memberHandle)
    replaceText(root, "Kritika’s", `${first}’s`)
    replaceText(root, "Kritika", first)
    replaceText(root, "Screen-reader labelling (Nepali)", ws?.title ?? "")
    replaceText(root, "applied 2 days ago", `applied ${relTime(a.createdAt)}`)
    replaceText(root, "Her answers", "Answers")
    const avatar = root.querySelector("span")
    if (avatar && norm(avatar.textContent).length <= 3) setText(avatar, name.split(" ").map((s) => s[0]).join("").slice(0, 2).toUpperCase())
    const respondBy = findByText(root, "b", "Fri 5 Sep")
    if (respondBy) setText(respondBy, plusWorkingDays(a.createdAt, 3))

    const profile = findByText(root, "div", "Public profile", "equals")?.parentElement
    if (profile && m) {
      const tags = profile.querySelector("div:nth-child(2)")
      if (tags) tags.innerHTML = m.skills.map((s) => `<span class="tag tag-neutral">${s}</span>`).join("")
      const meta = profile.querySelector("div:nth-child(3)")
      if (meta) setText(meta, `${m.tier} · ${m.verified} verified contribution${m.verified === 1 ? "" : "s"} · ${m.head}`)
    }
    const answers = findByText(root, "div", "Answers", "equals")?.parentElement
    if (answers && ws) {
      answers.innerHTML = `<div>Answers</div>` + ws.questions.map((q, i) => `<b>${q}</b><br>${a.answers[i] ?? "—"}${i < ws.questions.length - 1 ? "<br><br>" : ""}`).join("")
    }

    const decision = segGroup(field(root, "Decision")?.querySelector(".seg") ?? null, "Accept")
    const msgBox = field(root, "Message")?.querySelector(".input")
    const message = msgBox
      ? toTextarea(
          msgBox,
          `Namaste ${first} — welcome to the ${ws?.title ?? "workstream"} workstream on ${p?.title ?? "the project"}. Start with the starter task on your dashboard; we review within ${p?.response.toLowerCase() ?? "three working days"}.`,
          4
        )
      : null
    const send = findByText<HTMLButtonElement>(root, "button", "Send ·")
    const relabel = () => {
      if (send) send.textContent = `Send · ${decision.get()}`
    }
    relabel()
    field(root, "Decision")?.addEventListener("click", relabel)

    if (a.state !== "applied" && send) {
      send.disabled = true
      send.textContent = `Already ${STATE_LABEL[a.state]?.label.toLowerCase() ?? a.state}`
    }
    send?.addEventListener("click", async () => {
      const d = decision.get()
      if (d !== "Accept" && d !== "Decline") return toast(`“${d}” is not in this prototype — accept or decline`, "info")
      const restore = busy(send)
      try {
        await api.decide(a.id, d === "Accept" ? "accepted" : "declined", message?.value ?? "")
        toast(`${d === "Accept" ? "Accepted" : "Declined"} · recorded under your name · ${first} has been told`)
        ctx.navigate("/ministry")
      } catch (err) {
        restore()
        toast((err as Error).message, "info")
      }
    })
  },
})

/* ── C4.2 · Evidence review ───────────────────────────────────────────────── */
registerLive("c4-2", {
  async mount(root, ctx) {
    const u = await requirePublisher(ctx)
    if (!u) return
    const queue = await api.verificationQueue(u.ministry!)
    const ev: Evidence | undefined = queue.find((e) => e.id === ctx.params.id)
    if (!ev) return ctx.navigate(ctx.href("c4-1"))
    const a = (await api.application(ev.applicationId))!
    const m = await api.member(a.memberHandle)
    const ws = (await api.workstreams(a.projectSlug)).find((w) => w.id === a.workstreamId)
    const name = m?.name ?? a.memberHandle
    const first = firstName(name)
    const [kind, ...rest] = ev.note.split(" — ")
    const what = rest.join(" — ") || ev.note

    const h1 = root.querySelector("h1")
    if (h1) setText(h1, `${ws?.title ?? "Contribution"} · ${kind || "evidence"}`)
    const submitted = findByText(root, "span", "Submitted", "starts")
    if (submitted) setText(submitted, `Submitted ${fmtDate(ev.createdAt)} by ${name} (${a.memberHandle}) · workstream: ${ws?.title ?? ""}`)
    replaceText(root, "keyboard-audit-passport-renewal.pdf", ev.url.replace(/^https?:\/\//, ""))
    replaceText(root, "1.1 MB · scanned clean · EN", ev.kind === "link" ? "Link · reachable · checked" : "File · scanned clean")
    replaceText(root, "PDF preview", ev.kind === "link" ? "Link" : "File")
    const whatEl = findByText(root, "b", "What she did")?.parentElement
    if (whatEl) whatEl.innerHTML = `<b>What ${first} did:</b> ${what}`
    for (const link of allByText<HTMLAnchorElement>(root, "a", "Open file")) {
      link.href = ev.url
      link.target = "_blank"
      link.rel = "noopener"
      link.textContent = ev.kind === "link" ? "Open link ↗" : "Open file"
      link.removeAttribute("data-ref-link")
    }
    for (const link of allByText<HTMLAnchorElement>(root, "a", "Issues filed")) (link as HTMLElement).style.display = "none"
    replaceText(root, "Anjali", first)

    const decision = segGroup(field(root, "Decision")?.querySelector(".seg") ?? null, "Accept")
    const noteBox = field(root, "Note to")?.querySelector(".input")
    const note = noteBox ? toTextarea(noteBox, "Thorough and reproducible. Counted as one accepted contribution.", 3) : null
    const accept = findByText<HTMLButtonElement>(root, "button", "Accept contribution")
    const relabel = () => {
      if (accept) accept.textContent = decision.get() === "Reject" ? "Reject · with reason" : decision.get() === "Accept" ? "Accept contribution" : "Request clarification"
    }
    field(root, "Decision")?.addEventListener("click", relabel)
    if (ev.state !== "candidate" && accept) {
      accept.disabled = true
      accept.textContent = ev.state === "verified" ? "Already verified" : "Already rejected"
    }
    accept?.addEventListener("click", async () => {
      const d = decision.get()
      if (d === "Request clarification") return toast("Clarification requests are not in this prototype", "info")
      const restore = busy(accept)
      try {
        await api.verify(ev.id, d === "Accept" ? "accepted" : "rejected", note?.value)
        toast(d === "Accept" ? `Verified · recorded under your name · ${first} has been told` : `Not verified · ${first} has been told why`)
        ctx.navigate("/ministry")
      } catch (err) {
        restore()
        toast((err as Error).message, "info")
      }
    })

    const q = findByText(root, ".card-kicker", "Queue ·", "starts")
    if (q) setText(q, `Queue · ${queue.filter((e) => e.state === "candidate").length}`)
  },
})
