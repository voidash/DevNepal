/**
 * Small DOM helpers for enhancers. Every enhancer works on a drawn board, so
 * these find things the way a person reading the drawing would: by the words
 * on them.
 */

export const norm = (s: string | null | undefined) =>
  (s ?? "").replace(/ /g, " ").replace(/\s+/g, " ").trim()

export function findByText<T extends Element = HTMLElement>(
  root: ParentNode,
  selector: string,
  text: string,
  mode: "includes" | "starts" | "equals" = "includes"
): T | null {
  const want = norm(text).toLowerCase()
  const matches = Array.from(root.querySelectorAll<T>(selector)).filter((el) => {
    const have = norm(el.textContent).toLowerCase()
    return (
      (mode === "includes" && have.includes(want)) ||
      (mode === "starts" && have.startsWith(want)) ||
      (mode === "equals" && have === want)
    )
  })
  /* Innermost, not first. querySelectorAll is document order, so an ancestor
     whose text merely BEGINS with the same words comes before the element
     that actually carries them — and setText on a section container erases
     the section. */
  return matches.find((m) => !matches.some((o) => o !== m && m.contains(o))) ?? null
}

export function allByText<T extends Element = HTMLElement>(root: ParentNode, selector: string, text: string): T[] {
  const want = norm(text).toLowerCase()
  return Array.from(root.querySelectorAll<T>(selector)).filter((el) => norm(el.textContent).toLowerCase().includes(want))
}

export function setText(el: Element | null | undefined, text: string) {
  if (el) el.textContent = text
}

/** The .field whose <label> starts with `label`. */
export function field(root: ParentNode, label: string): HTMLElement | null {
  for (const f of Array.from(root.querySelectorAll<HTMLElement>(".field"))) {
    const l = f.querySelector("label")
    if (l && norm(l.textContent).toLowerCase().startsWith(norm(label).toLowerCase())) return f
  }
  return null
}

/** Replace a drawn `.input` box with a real textarea carrying its text. */
export function toTextarea(box: Element, value?: string, rows = 3): HTMLTextAreaElement {
  const ta = document.createElement("textarea")
  ta.className = box.className
  ta.rows = rows
  ta.value = value ?? norm(box.textContent)
  ta.setAttribute("aria-label", value ? "" : norm(box.textContent))
  box.replaceWith(ta)
  return ta
}

export function toInput(box: Element, value: string, type = "text", placeholder = ""): HTMLInputElement {
  const input = document.createElement("input")
  input.className = box.className
  input.type = type
  input.value = value
  input.placeholder = placeholder
  box.replaceWith(input)
  return input
}

export function toSelect(box: Element, options: { value: string; label: string; disabled?: boolean }[], selected?: string): HTMLSelectElement {
  const sel = document.createElement("select")
  sel.className = box.className
  for (const o of options) {
    const opt = document.createElement("option")
    opt.value = o.value
    opt.textContent = o.label
    opt.disabled = !!o.disabled
    if (o.value === selected) opt.selected = true
    sel.appendChild(opt)
  }
  box.replaceWith(sel)
  return sel
}

/** Make a drawn .seg behave as a radiogroup. Returns the current value. */
export function segGroup(seg: Element | null, initial?: string, onChange?: (value: string) => void) {
  const opts = seg ? Array.from(seg.querySelectorAll<HTMLElement>(".seg-opt")) : []
  let value = initial ?? ""
  const paint = () => {
    for (const o of opts) {
      const on = norm(o.textContent) === value
      o.classList.toggle("is-on", on)
      o.style.background = ""
      o.style.color = ""
      o.setAttribute("aria-checked", String(on))
    }
  }
  if (seg) seg.setAttribute("role", "radiogroup")
  for (const o of opts) {
    o.setAttribute("role", "radio")
    o.tabIndex = 0
    const pick = () => {
      value = norm(o.textContent)
      paint()
      onChange?.(value)
    }
    o.addEventListener("click", pick)
    o.addEventListener("keydown", (e) => {
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault()
        pick()
      }
    })
  }
  if (!value && opts[0]) value = norm(opts[0].textContent)
  paint()
  return { get: () => value, set: (v: string) => { value = v; paint() } }
}

export function relTime(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return "just now"
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} min ago`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} hour${h === 1 ? "" : "s"} ago`
  const d = Math.floor(h / 24)
  return `${d} day${d === 1 ? "" : "s"} ago`
}

export function fmtDate(iso: string, withTime = true): string {
  const d = new Date(iso)
  const date = d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" })
  if (!withTime) return date
  return `${date} · ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`
}

export function plusWorkingDays(iso: string, days: number): string {
  const d = new Date(iso)
  let left = days
  while (left > 0) {
    d.setDate(d.getDate() + 1)
    if (d.getDay() !== 0 && d.getDay() !== 6) left--
  }
  return d.toLocaleDateString("en-GB", { weekday: "short", day: "numeric", month: "short" })
}

export const firstName = (name: string) => name.split(" ")[0]

/** Disable a button while an action runs; returns a restore function. */
export function busy(btn: HTMLButtonElement, label = "Sending…") {
  const was = btn.textContent
  btn.disabled = true
  btn.textContent = label
  return () => {
    btn.disabled = false
    btn.textContent = was
  }
}

/** A quiet confirmation, bottom-left, gone in 3.5 s. */
export function toast(text: string, kind: "ok" | "info" = "ok") {
  let host = document.querySelector<HTMLElement>(".dn-toasts")
  if (!host) {
    host = document.createElement("div")
    host.className = "dn-toasts"
    host.setAttribute("role", "status")
    host.setAttribute("aria-live", "polite")
    document.body.appendChild(host)
  }
  const t = document.createElement("div")
  t.className = `dn-toast is-${kind}`
  t.textContent = text
  host.appendChild(t)
  setTimeout(() => t.classList.add("is-out"), 3000)
  setTimeout(() => t.remove(), 3500)
}

/** Replace every text node containing `from` with `to`, keeping the markup. */
export function replaceText(root: Node, from: string, to: string) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const hits: Text[] = []
  for (let n = walker.nextNode(); n; n = walker.nextNode()) {
    if ((n as Text).data.includes(from)) hits.push(n as Text)
  }
  for (const t of hits) t.data = t.data.split(from).join(to)
}

export const STATE_LABEL: Record<string, { label: string; cls: string }> = {
  applied: { label: "Applied", cls: "tag-info" },
  accepted: { label: "Accepted", cls: "tag-success" },
  declined: { label: "Declined", cls: "tag-neutral" },
  opened: { label: "In progress", cls: "tag-info" },
  candidate: { label: "Evidence to verify", cls: "tag-warning" },
  verified: { label: "Verified", cls: "tag-success" },
  rejected: { label: "Not verified", cls: "tag-error" },
  recognised: { label: "Recognised", cls: "tag-success" },
}

export function stateTag(el: Element | null, state: string) {
  if (!el) return
  const s = STATE_LABEL[state] ?? { label: state, cls: "tag-neutral" }
  el.className = `tag ${s.cls}`
  el.textContent = s.label
}
