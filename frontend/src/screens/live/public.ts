import { api, type Project, type ProjectFilters, type Workstream } from "../../data"
import { registerLive, type LiveCtx } from "./registry"
import { allByText, findByText, norm, replaceText, setText, toInput, toast } from "./util"

/* ── A2.1 · Government projects catalog ────────────────────────────────────
   The board's card list is already a template over `catalog`; scope points it
   at the store. mount turns the drawn search box into an input and the drawn
   filter chips into filters, and makes each card open its project. */

const filters: ProjectFilters = {}

const MINISTRY_ROWS: [string, string][] = [
  ["MoCIT / DoIT", "DoIT"],
  ["Health & Population", "MoHP"],
  ["Federal Affairs (MoFAGA)", "MoFAGA"],
  ["Education (MoEST)", "MoEST"],
  ["Hydrology & Meteorology", "DHM"],
  ["Agriculture (MoALD)", "MoALD"],
]

const TYPES = ["Engineering", "UI/UX", "QA", "Security", "Data", "Documentation", "Localization", "Research", "Community"]

let catalogCache: Project[] = []
let catalogTotal = 0

registerLive("a2-1", {
  async scope() {
    catalogCache = await api.projects(filters)
    catalogTotal = (await api.projects()).length
    return { catalog: catalogCache }
  },
  mount(root, ctx) {
    // search
    const box = findByText(root, ".input", "Search title")
    if (box) {
      const input = toInput(box, filters.q ?? "", "search", "Search title, ministry, technology or skill — नेपालीमा पनि खोज्नुहोस्")
      input.setAttribute("aria-label", "Search projects")
      let t: number | undefined
      input.addEventListener("input", () => {
        clearTimeout(t)
        t = window.setTimeout(() => {
          filters.q = input.value
          ctx.reload()
        }, 180)
      })
      // keep focus across the reload
      queueMicrotask(() => {
        if (filters.q) {
          input.focus()
          input.setSelectionRange(input.value.length, input.value.length)
        }
      })
    }

    // contribution-type chips
    for (const name of TYPES) {
      const chip = findByText(root, ".seg-opt, .tag", name, "equals")
      if (!chip) continue
      chip.setAttribute("role", "button")
      chip.tabIndex = 0
      const on = filters.type === name
      chip.classList.toggle("is-on", on)
      chip.setAttribute("aria-pressed", String(on))
      chip.style.cursor = "pointer"
      const toggle = () => {
        filters.type = filters.type === name ? undefined : name
        ctx.reload()
      }
      chip.addEventListener("click", toggle)
      chip.addEventListener("keydown", (e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault()
          toggle()
        }
      })
    }

    // ministry rows
    for (const [label, code] of MINISTRY_ROWS) {
      const row = findByText(root, "aside div, aside label, aside span", label, "starts")
      const clickable = row?.closest("label") ?? row?.parentElement ?? row
      if (!clickable) continue
      clickable.style.cursor = "pointer"
      clickable.setAttribute("role", "button")
      clickable.setAttribute("aria-pressed", String(filters.ministry === code))
      if (filters.ministry === code) clickable.classList.add("is-on")
      clickable.addEventListener("click", () => {
        filters.ministry = filters.ministry === code ? undefined : code
        ctx.reload()
      })
    }

    // clear all
    const clear = findByText(root, "a", "Clear all", "equals")
    if (clear) {
      clear.setAttribute("href", "javascript:void 0")
      clear.removeAttribute("data-ref-link")
      clear.addEventListener("click", (e) => {
        e.preventDefault()
        delete filters.q
        delete filters.type
        delete filters.ministry
        ctx.reload()
      })
    }

    // count line
    const count = findByText(root, "span", "Showing", "starts")
    if (count) {
      const active = [filters.type, filters.ministry, filters.q ? `“${filters.q}”` : ""].filter(Boolean).join(", ")
      setText(count, `Showing ${catalogCache.length} of ${catalogTotal} open projects${active ? ` · ${active}` : ""}`)
    }

    // cards open their project
    for (const card of Array.from(root.querySelectorAll<HTMLElement>(".card"))) {
      const title = card.querySelector(".card-title")
      const p = catalogCache.find((x) => norm(title?.textContent) === x.title)
      if (!p) continue
      card.dataset.goto = `/projects/${p.slug}`
      card.setAttribute("role", "link")
      card.tabIndex = 0
      card.addEventListener("keydown", (e) => {
        if (e.key === "Enter") ctx.navigate(`/projects/${p.slug}`)
      })
      const bookmark = card.querySelector<HTMLButtonElement>('button[aria-label="Bookmark"]')
      bookmark?.addEventListener("click", (e) => {
        e.stopPropagation()
        toast(`Bookmarked ${p.title}`)
      })
    }
    // pagination is drawn; the six projects fit one page
    for (const b of allByText<HTMLButtonElement>(root, "button", "Previous").concat(allByText<HTMLButtonElement>(root, "button", "Next"))) b.disabled = true
  },
})

/* ── A2.2 / A2.3 · Project detail ──────────────────────────────────────────
   Title, ministry and summary come from the store; the workstreams table is
   rebuilt from real capacity; "Sign in to apply" is a gate — a member goes to
   the apply form, anyone else gets the sign-in dialog and comes back here. */

const SEWA_TITLE = "Sewa Portal Accessibility Remediation"

async function mountProject(root: HTMLElement, ctx: LiveCtx) {
  const slug = ctx.params.slug ?? "sewa-portal-accessibility"
  const p = (await api.project(slug)) ?? (await api.project("sewa-portal-accessibility"))!
  const ws = await api.workstreams(p.slug)

  if (p.title !== SEWA_TITLE) {
    replaceText(root, SEWA_TITLE, p.title)
    replaceText(root, "सेवा पोर्टल पहुँचयोग्यता सुधार", p.ne)
    replaceText(root, "Department of Information Technology", p.ministry)
    const problem = findByText(root, "div", "Problem", "equals")?.nextElementSibling
    if (problem) setText(problem, p.summary)
    for (const el of allByText(root, "span, div", "· DoIT")) {
      if (norm(el.textContent).length < 60) el.textContent = norm(el.textContent).replace("DoIT", p.ministry)
    }
  }

  // workstreams table
  const table = findByText(root, "table", "Capacity")
  const tbody = table?.querySelector("tbody")
  const tmpl = tbody?.querySelector("tr")
  if (tbody && tmpl) {
    tbody.innerHTML = ""
    for (const w of ws) {
      const tr = tmpl.cloneNode(true) as HTMLTableRowElement
      const cells = tr.querySelectorAll("td")
      const open = w.filled < w.places
      setText(cells[0], w.title)
      setText(cells[1], p.types.join(" · "))
      setText(cells[2], p.stack)
      setText(cells[3], String(p.tasks))
      setText(cells[4], `${w.filled} of ${w.places} places`)
      const tag = cells[5]?.querySelector(".tag")
      if (tag) {
        tag.className = `tag ${open ? "tag-accent" : "tag-neutral"}`
        tag.textContent = open ? "Accepting" : "Full"
      }
      if (open) {
        tr.dataset.goto = `/projects/${p.slug}/apply?ws=${encodeURIComponent(w.id)}`
        tr.style.cursor = "pointer"
      }
      tbody.appendChild(tr)
    }
    const count = findByText(root, "span", "Workstreams ·", "starts")
    if (count) setText(count, `Workstreams · ${ws.length}`)
  }

  // the gate
  const member = ctx.session?.user.role === "member"
  for (const btn of allByText<HTMLButtonElement>(root, "button", "Sign in to apply")) {
    btn.removeAttribute("data-goto")
    if (member) {
      btn.textContent = "Apply to a workstream"
      btn.addEventListener("click", () => ctx.navigate(`/projects/${p.slug}/apply`))
    } else {
      btn.addEventListener("click", () => ctx.signIn())
    }
  }
  for (const b of allByText<HTMLButtonElement>(root, "button", "Bookmark", )) b.addEventListener("click", () => toast(`Bookmarked ${p.title}`))
  for (const b of allByText<HTMLButtonElement>(root, "button", "Repository")) b.addEventListener("click", () => toast("Repository opens on GitHub", "info"))
}

registerLive("a2-2", { mount: mountProject })
registerLive("a2-3", { mount: mountProject })

export type { Workstream }
