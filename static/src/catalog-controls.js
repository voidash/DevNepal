const controls = document.querySelectorAll("[data-auto-submit]");
const SCROLL_KEY = "dn-catalog-scroll";

function remember(offset) {
  try {
    sessionStorage.setItem(SCROLL_KEY, String(offset));
  } catch {
    // A private window with storage denied simply loses the scroll position.
  }
}

for (const control of controls) {
  control.addEventListener("change", () => {
    const form = control.form;
    if (!(form instanceof HTMLFormElement)) {
      console.error("Catalog control is not associated with a form", control);
      return;
    }

    remember(window.scrollY);
    form.setAttribute("aria-busy", "true");
    form.requestSubmit();
  });
}

// Choosing a filter is a full navigation, so the browser lands at the top of a
// freshly built page. That reads as the results having been thrown away rather
// than narrowed, so the page comes back where the visitor left it. The offset is
// re-applied after load because the document is still growing when the module
// first runs, and the browser would otherwise clamp the jump.
(() => {
  let stored = null;
  try {
    stored = sessionStorage.getItem(SCROLL_KEY);
    sessionStorage.removeItem(SCROLL_KEY);
  } catch {
    return;
  }
  if (stored === null) {
    return;
  }
  const offset = Number.parseInt(stored, 10);
  if (!Number.isFinite(offset) || offset <= 0) {
    return;
  }
  if ("scrollRestoration" in history) {
    history.scrollRestoration = "manual";
  }
  const settle = () => window.scrollTo(0, offset);
  settle();
  requestAnimationFrame(settle);
  window.addEventListener(
    "load",
    () => {
      settle();
      if ("scrollRestoration" in history) {
        history.scrollRestoration = "auto";
      }
    },
    { once: true },
  );
})();

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
