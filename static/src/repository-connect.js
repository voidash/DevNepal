const forms = document.querySelectorAll("[data-repository-connect]")

function resetPendingState(form) {
  const button = form.querySelector('button[type="submit"]')
  const label = form.querySelector("[data-connect-label]")
  const status = form.querySelector(".dn-connect-status")
  if (!button || !label || !status) return

  form.setAttribute("aria-busy", "false")
  button.disabled = false
  button.classList.remove("is-connecting")
  label.textContent = label.dataset.defaultLabel || label.textContent
  status.hidden = true
}

for (const form of forms) {
  const button = form.querySelector('button[type="submit"]')
  const label = form.querySelector("[data-connect-label]")
  const status = form.querySelector(".dn-connect-status")
  if (!button || !label || !status) continue

  label.dataset.defaultLabel = label.textContent
  form.addEventListener("submit", () => {
    form.setAttribute("aria-busy", "true")
    button.disabled = true
    button.classList.add("is-connecting")
    label.textContent = button.dataset.connectingLabel
    status.hidden = false
  })
}

window.addEventListener("pageshow", () => {
  for (const form of forms) resetPendingState(form)
})
