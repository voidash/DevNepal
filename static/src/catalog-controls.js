const controls = document.querySelectorAll("[data-auto-submit]");

for (const control of controls) {
  control.addEventListener("change", () => {
    const form = control.form;
    if (!(form instanceof HTMLFormElement)) {
      console.error("Catalog control is not associated with a form", control);
      return;
    }

    form.setAttribute("aria-busy", "true");
    form.requestSubmit();
  });
}

// The filter rail stands open beside the results on a desktop. On a narrow
// screen that same markup would bury the results under a full page of
// controls, so the disclosure starts closed there and the visitor opens it.
const filters = document.querySelector(".dn-catalog-filters");
const narrow = window.matchMedia("(max-width: 1000px)");

function matchFiltersToViewport(query) {
  if (!(filters instanceof HTMLDetailsElement)) {
    return;
  }
  if (query.matches && filters.dataset.visitorToggled !== "true") {
    filters.open = false;
  }
  if (!query.matches) {
    filters.open = true;
  }
}

if (filters instanceof HTMLDetailsElement) {
  filters.addEventListener("toggle", () => {
    if (narrow.matches) {
      filters.dataset.visitorToggled = "true";
    }
  });
  matchFiltersToViewport(narrow);
  narrow.addEventListener("change", matchFiltersToViewport);
}
