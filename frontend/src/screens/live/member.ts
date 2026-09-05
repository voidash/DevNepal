import { api, type Application } from "../../data"
import { registerLive, type LiveCtx } from "./registry"
import {
  allByText,
  busy,
  field,
  findByText,
  firstName,
  fmtDate,
  norm,
  relTime,
  replaceText,
  segGroup,
  setText,
  stateTag,
  toInput,
  toSelect,
  toTextarea,
  toast,
} from "./util"

/** Enhancers for the member's journey: apply → accepted → evidence → recognised. */

async function requireMember(ctx: LiveCtx) {
  if (ctx.session?.user.role === "member") return ctx.session.user
  ctx.signIn()
  return null
}

async function officerName(handle?: string) {
  if (!handle) return "the ministry"
  const a = (await api.accounts()).find((x) => x.handle === handle)
  return a ? `${a.name}, ${a.ministry ?? "PMO"}` : handle
}

function appPath(a: Application) {
  if (a.state === "accepted" || a.state === "opened") return `/me/applications/${a.id}/accepted`
  if (a.state === "recognised") return `/me/applications/${a.id}/recognised`
  return `/me/applications/${a.id}`
}

/* ── B2.3 · Apply to a workstream ─────────────────────────────────────────── */
registerLive("b2-3", {
  async mount(root, ctx) {
    if (!(await requireMember(ctx))) return
    const slug = ctx.params.slug ?? "sewa-portal-accessibility"
    const p = (await api.project(slug))!
    const all = await api.workstreams(slug)
    const open = all.filter((w) => w.filled < w.places)
    const wanted = new URLSearchParams(location.search).get("ws")

    replaceText(root, "Sewa Portal Accessibility Remediation", p.title)
    replaceText(root, "· DoIT", `· ${p.ministry}`)
    replaceText(root, "asked by DoIT", `asked by ${p.ministry}`)
    replaceText(root, "DoIT will see", `${p.ministry} will see`)

    const wsField = field(root, "Workstream")?.querySelector(".input")
    const select = wsField
      ? toSelect(
          wsField,
          open.map((w) => ({ value: w.id, label: `${w.title} · ${w.filled} of ${w.places} places` })),
          wanted && open.some((w) => w.id === wanted) ? wanted : open[0]?.id
        )
      : null

    const q1Field = field(root, "Which assistive") ?? root.querySelectorAll(".field")[1]
    const q1Box = q1Field?.querySelector(".input")
    const q1 = q1Box ? toTextarea(q1Box, undefined, 3) : null
    const q1Label = q1Field?.querySelector("label")
    const chosen = () => open.find((w) => w.id === select?.value) ?? open[0]
    const relabel = () => {
      const w = chosen()
      if (q1Label && w) q1Label.innerHTML = `${w.questions[0]} <span class="text-muted">· asked by ${p.ministry}</span>`
    }
    relabel()
    select?.addEventListener("change", relabel)

    const hours = segGroup(field(root, "Hours")?.querySelector(".seg") ?? null, "4–8")

    allByText<HTMLButtonElement>(root, "button", "Cancel").forEach((b) =>
      b.addEventListener("click", () => ctx.navigate(`/projects/${p.slug}`))
    )
    const submit = findByText<HTMLButtonElement>(root, "button", "Submit application")
    if (!open.length && submit) {
      submit.disabled = true
      submit.textContent = "No open places"
    }
    submit?.addEventListener("click", async () => {
      const w = chosen()
      if (!w) return
      const restore = busy(submit)
      try {
        await api.apply(w.id, [q1?.value ?? "", `${hours.get()} hours per week`])
        toast(`Application sent to ${p.ministry} · they respond ${p.response.toLowerCase()}`)
        ctx.navigate("/me")
      } catch (err) {
        restore()
        toast((err as Error).message, "info")
      }
    })
  },
})

/* ── B5.5 · Dashboard ─────────────────────────────────────────────────────── */
registerLive("b5-5", {
  async mount(root, ctx) {
    const me = await requireMember(ctx)
    if (!me) return
    const apps = await api.myApplications()
    const h1 = root.querySelector("h1")
    if (h1) setText(h1, `Namaste, ${firstName(me.name)}`)
    replaceText(root, "@aarati", me.handle)
    replaceText(root, "Aarati", firstName(me.name))

    const kicker = findByText(root, ".card-kicker", "Applications ·", "starts")
    const card = kicker?.closest(".card")
    const list = card?.querySelector(".card-kicker")?.parentElement?.nextElementSibling
    const tmpl = list?.firstElementChild
    if (kicker) setText(kicker, `Applications · ${apps.length}`)
    if (list && tmpl) {
      list.innerHTML = ""
      if (!apps.length) {
        const row = tmpl.cloneNode(true) as HTMLElement
        const [title, tag] = row.querySelectorAll("span")
        setText(title, "No applications yet")
        if (tag) {
          tag.className = "tag tag-outline"
          tag.textContent = "Start here"
        }
        const meta = row.lastElementChild
        if (meta && meta !== row.firstElementChild) setText(meta, "Browse the government projects and apply to a workstream that fits.")
        row.dataset.goto = "/projects"
        row.style.cursor = "pointer"
        list.appendChild(row)
      }
      for (const a of [...apps].reverse()) {
        const p = await api.project(a.projectSlug)
        const w = (await api.workstreams(a.projectSlug)).find((x) => x.id === a.workstreamId)
        const row = tmpl.cloneNode(true) as HTMLElement
        const [title, tag] = row.querySelectorAll("span")
        setText(title, p?.title ?? a.projectSlug)
        stateTag(tag, a.state)
        const meta = row.lastElementChild
        if (meta && meta !== row.firstElementChild) {
          const when = a.decidedAt ? `${a.state === "declined" ? "Declined" : "Accepted"} ${relTime(a.decidedAt)} by ${await officerName(a.decidedBy)}` : `Applied ${relTime(a.createdAt)}`
          setText(meta, `${p?.ministry ?? ""} · ${w?.title ?? ""} · ${when}`)
        }
        row.dataset.goto = appPath(a)
        row.style.cursor = "pointer"
        list.appendChild(row)
      }
      const all = card?.querySelector("a")
      if (all && apps[0]) all.setAttribute("href", appPath(apps[apps.length - 1]))
    }
    allByText<HTMLButtonElement>(root, "button", "Sync now").forEach((b) => b.addEventListener("click", () => toast("GitHub synchronised · nothing new")))
    allByText<HTMLButtonElement>(root, "button", "Disconnect GitHub").forEach((b) => b.addEventListener("click", () => toast("Not in this prototype", "info")))
  },
})

/* ── B2.4 · Accepted — where to begin ─────────────────────────────────────── */
registerLive("b2-4", {
  async mount(root, ctx) {
    const me = await requireMember(ctx)
    if (!me) return
    const a = await api.application(ctx.params.id)
    if (!a) return ctx.navigate("/me")
    const p = await api.project(a.projectSlug)
    const w = (await api.workstreams(a.projectSlug)).find((x) => x.id === a.workstreamId)
    const by = await officerName(a.decidedBy)

    const lead = findByText(root, "b", "Your application was accepted")
    const line = lead?.parentElement
    if (lead && line) {
      const quote = line.querySelector("div")
      line.textContent = ""
      line.appendChild(lead)
      line.append(` — ${by} · ${fmtDate(a.decidedAt ?? a.createdAt)}`)
      if (quote) {
        quote.textContent = a.note ? `“${a.note}”` : ""
        line.appendChild(quote)
      }
    }
    replaceText(root, "Kritika", firstName(me.name))
    replaceText(root, "@kritika", me.handle)
    replaceText(root, "Nepali labelling workstream", w?.title ?? "your workstream")
    replaceText(root, "DoIT verifies", `${p?.ministry ?? "the ministry"} verifies`)

    const gh = findByText<HTMLButtonElement>(root, "button", "Open issue")
    gh?.addEventListener("click", () => toast("Opens the issue on GitHub — external", "info"))
    if (gh) {
      const evidence = gh.cloneNode(false) as HTMLButtonElement
      evidence.className = "btn btn-secondary blueprint"
      evidence.textContent = "Submit non-code evidence instead"
      evidence.style.marginLeft = "8px"
      evidence.addEventListener("click", () => ctx.navigate(`/me/applications/${a.id}/evidence`))
      gh.after(evidence)
    }
    const tl = findByText<HTMLAnchorElement>(root, "a", "Applied")
    if (tl) {
      tl.setAttribute("href", `/me/applications/${a.id}`)
      tl.removeAttribute("data-ref-link")
      tl.textContent = `Applied ${fmtDate(a.createdAt, false)} · Accepted ${fmtDate(a.decidedAt ?? a.createdAt, false)} →`
    }
  },
})

/* ── B2.6 · Submit evidence ───────────────────────────────────────────────── */
registerLive("b2-6", {
  async mount(root, ctx) {
    if (!(await requireMember(ctx))) return
    const a = await api.application(ctx.params.id)
    if (!a) return ctx.navigate("/me")
    const p = await api.project(a.projectSlug)
    const w = (await api.workstreams(a.projectSlug)).find((x) => x.id === a.workstreamId)

    replaceText(root, "Keyboard operation audit", w?.title ?? "Your workstream")
    replaceText(root, "Goes to DoIT", `Goes to ${p?.ministry ?? "the ministry"}`)
    const typeBox = field(root, "Contribution type")?.querySelector(".input")
    const type = typeBox ? toSelect(typeBox, ["QA · test report", "Design · review", "Documentation", "Localisation · reviewed strings", "Research"].map((v) => ({ value: v, label: v })), "QA · test report") : null
    const evBox = field(root, "Evidence")?.querySelector(".input")
    const url = evBox ? toInput(evBox, "https://github.com/doit-np/sewa-portal/issues/144", "url", "Link to the file, PR, document or issue") : null
    const whatBox = field(root, "What you did")?.querySelector(".input")
    const what = whatBox ? toTextarea(whatBox, undefined, 3) : null

    const submit = findByText<HTMLButtonElement>(root, "button", "Submit for verification")
    if (a.state !== "accepted" && a.state !== "opened" && submit) {
      submit.disabled = true
      submit.textContent = a.state === "candidate" ? "Already submitted · awaiting verification" : "Application not open"
    }
    submit?.addEventListener("click", async () => {
      const restore = busy(submit)
      try {
        await api.submitEvidence(a.id, { kind: "link", url: url?.value ?? "", note: `${type?.value ?? ""} — ${what?.value ?? ""}` })
        toast(`Sent to ${p?.ministry ?? "the ministry"} as a candidate record`)
        ctx.navigate(`/me/applications/${a.id}`)
      } catch (err) {
        restore()
        toast((err as Error).message, "info")
      }
    })
  },
})

/* ── B2.8 · Recognised ────────────────────────────────────────────────────── */
registerLive("b2-8", {
  async mount(root, ctx) {
    const me = await requireMember(ctx)
    if (!me) return
    const a = await api.application(ctx.params.id)
    if (!a) return ctx.navigate("/me")
    const p = await api.project(a.projectSlug)
    const recs = await api.recognition(me.handle)
    const rec = recs.find((r) => r.applicationId === a.id)
    const ev = (await api.evidenceFor(a.id)).find((e) => e.state === "verified")
    const by = await officerName(rec?.acceptedBy)

    const lead = findByText(root, "b", "accepted your contribution")
    if (lead) setText(lead, `${by} accepted your contribution`)
    const leadLine = lead?.parentElement
    if (leadLine && rec) {
      const parts = leadLine.childNodes
      for (const n of Array.from(parts)) {
        if (n.nodeType === Node.TEXT_NODE && n.textContent?.includes("“")) n.textContent = ev?.verifierNote ? ` “${ev.verifierNote}”` : ""
        if (n.nodeType === Node.TEXT_NODE && n.textContent?.includes("15:10")) n.textContent = ` · ${fmtDate(rec.at)}`
      }
    }
    const count = findByText(root, "div", "Verified contributions ·", "starts")
    if (count) setText(count, `Verified contributions · ${recs.length}`)

    const row = root.querySelector("table tbody tr")
    if (row && rec) {
      const cells = row.querySelectorAll("td")
      const first = cells[0]?.querySelector("div")
      if (first) {
        const sub = first.querySelector("span")
        first.textContent = ""
        first.append(ev ? `Evidence · ${norm(ev.note).slice(0, 48)}` : "Merged pull request")
        if (sub) {
          sub.textContent = `${p?.title ?? ""} · ${fmtDate(rec.at, false)}`
          first.appendChild(document.createElement("br"))
          first.appendChild(sub)
        }
      }
      setText(cells[1], by)
      const tag = cells[2]?.querySelector(".tag")
      if (tag) tag.textContent = rec.via === "evidence" ? "Ministry attestation" : "GitHub webhook"
    }
    const badge = findByText(root, ".card-kicker", "New badge", "equals")?.closest(".card")
    if (badge) {
      if (rec?.badge) {
        replaceText(badge, "First accepted contribution", rec.badge)
        replaceText(badge, "18 Aug 2026 · evidence: PR #142", `${fmtDate(rec.at, false)} · evidence: this record`)
      } else {
        (badge as HTMLElement).style.display = "none"
      }
    }
    const score = findByText(root, ".card-kicker", "Recognition", "equals")?.nextElementSibling
    if (score) setText(score, String(recs.reduce((s, r) => s + r.score, 0)))
    replaceText(root, "18 Aug 2026", fmtDate(rec?.at ?? a.createdAt, false))
    const next = findByText(root, "b", "Next")?.parentElement
    if (next) next.innerHTML = `<b>Next</b> · more places are open on ${p?.title ?? "this project"}`
  },
})

/* ── B6.5 · Application timeline ──────────────────────────────────────────── */
registerLive("b6-5", {
  async mount(root, ctx) {
    const me = await requireMember(ctx)
    if (!me) return
    const a = await api.application(ctx.params.id)
    if (!a) {
      const mine = await api.myApplications()
      return ctx.navigate(mine.length ? `/me/applications/${mine[mine.length - 1].id}` : "/me")
    }
    const p = await api.project(a.projectSlug)
    const w = (await api.workstreams(a.projectSlug)).find((x) => x.id === a.workstreamId)
    const events = [...(await api.timeline(a.id))].reverse()

    replaceText(root, "Sewa Portal Accessibility Remediation", p?.title ?? "")
    replaceText(root, "MoCIT · DoIT", p?.ministry ?? "")
    replaceText(root, "Screen-reader labelling (Nepali)", w?.title ?? "")
    replaceText(root, "DoIT’s named officers", `${p?.ministry ?? "the ministry"}’s named officers`)
    const tags = root.querySelectorAll(".tag")
    stateTag(tags[1] ?? null, a.state)

    const items = Array.from(root.querySelectorAll<HTMLElement>("div > span:empty + div"))
    const list = items[0]?.parentElement?.parentElement
    const tmpl = items[0]?.parentElement
    if (list && tmpl) {
      list.innerHTML = ""
      for (const e of events) {
        const li = tmpl.cloneNode(true) as HTMLElement
        const [title, meta] = li.querySelectorAll("div")
        setText(title, e.text)
        setText(meta, `${fmtDate(e.at)} · ${e.by === "system" ? "automatic" : e.by}`)
        list.appendChild(li)
      }
    }
    const withdraw = findByText<HTMLAnchorElement>(root, "a", "Withdraw")
    if (withdraw && (a.state === "accepted" || a.state === "opened")) {
      const ev = document.createElement("a")
      ev.href = `/me/applications/${a.id}/evidence`
      ev.textContent = "Submit evidence →"
      ev.style.marginRight = "16px"
      withdraw.before(ev)
    }
    withdraw?.addEventListener("click", (e) => {
      e.preventDefault()
      toast("Withdrawal is not in this prototype", "info")
    })
  },
})
