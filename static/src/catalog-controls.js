const SCROLL_KEY = "dn-catalog-scroll";
const CATALOG_SELECTOR = ".dn-catalog";

function remember(offset) {
  try {
    sessionStorage.setItem(SCROLL_KEY, String(offset));
  } catch {
    return;
  }
}

function forget() {
  try {
    sessionStorage.removeItem(SCROLL_KEY);
  } catch {
    return;
  }
}

function restoreScroll() {
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
}

function bindAutoSubmit(root) {
  for (const control of root.querySelectorAll("[data-auto-submit]")) {
    control.addEventListener("change", () => {
      const form = control.form;
      if (!(form instanceof HTMLFormElement)) {
        console.error("Catalog control is not associated with a form", control);
        return;
      }
      remember(window.scrollY);
      form.requestSubmit();
    });
  }
}

function formUrl(form) {
  const url = new URL(form.getAttribute("action") || window.location.href, window.location.origin);
  url.search = new URLSearchParams(new FormData(form)).toString();
  return url;
}

function sameCatalogPage(url) {
  return url.origin === window.location.origin && url.pathname === window.location.pathname;
}

let incoming = null;

async function loadCatalog(url, { push = true } = {}) {
  const catalog = document.querySelector(CATALOG_SELECTOR);
  if (!(catalog instanceof HTMLElement)) {
    window.location.assign(url);
    return;
  }
  incoming?.abort();
  const controller = new AbortController();
  incoming = controller;
  catalog.setAttribute("aria-busy", "true");
  try {
    const response = await fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "text/html" },
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(String(response.status));
    }
    const doc = new DOMParser().parseFromString(await response.text(), "text/html");
    const next = doc.querySelector(CATALOG_SELECTOR);
    if (!(next instanceof HTMLElement)) {
      throw new Error("catalog missing");
    }
    const previousPage = new URL(window.location.href).searchParams.get("page");
    const active = document.activeElement;
    const focusName = active instanceof HTMLElement ? active.getAttribute("name") : null;
    const focusValue =
      active instanceof HTMLInputElement || active instanceof HTMLSelectElement ? active.value : "";
    const focusHref = active instanceof HTMLAnchorElement ? active.getAttribute("href") : null;
    catalog.replaceWith(next);
    forget();
    if (push) {
      history.pushState({}, "", url);
    }
    enhance(next);
    if (focusName) {
      const candidates = [...next.querySelectorAll(`[name="${CSS.escape(focusName)}"]`)];
      const match =
        candidates.find((element) => "value" in element && element.value === focusValue) ||
        candidates[0];
      if (match instanceof HTMLElement) {
        match.focus();
      }
    } else if (focusHref) {
      const match = [...next.querySelectorAll("a[href]")].find(
        (element) => element.getAttribute("href") === focusHref,
      );
      if (match instanceof HTMLElement) {
        match.focus();
      }
    }
    if (url.searchParams.get("page") !== previousPage) {
      next.querySelector("#projects-heading")?.scrollIntoView({ block: "start" });
    }
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      return;
    }
    window.location.assign(url);
  }
}

function bindSubmit(root) {
  const form = root.querySelector(".dn-catalog-form");
  if (!(form instanceof HTMLFormElement)) {
    return;
  }
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    loadCatalog(formUrl(form));
  });
}

function bindFilterLinks(root) {
  root.addEventListener("click", (event) => {
    if (!(event instanceof MouseEvent) || event.button !== 0) {
      return;
    }
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
      return;
    }
    const anchor = event.target instanceof Element ? event.target.closest("a[href]") : null;
    if (!(anchor instanceof HTMLAnchorElement) || !root.contains(anchor)) {
      return;
    }
    if (anchor.closest(".dn-catalog-results")) {
      return;
    }
    const url = new URL(anchor.href, window.location.href);
    if (!sameCatalogPage(url)) {
      return;
    }
    event.preventDefault();
    remember(window.scrollY);
    loadCatalog(url);
  });
}

const filtersQuery = window.matchMedia("(max-width: 1000px)");

function matchFiltersToViewport(query) {
  const filters = document.querySelector(".dn-catalog-filters");
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

function bindFilterDisclosure(root) {
  const filters = root.querySelector(".dn-catalog-filters");
  if (!(filters instanceof HTMLDetailsElement)) {
    return;
  }
  filters.addEventListener("toggle", () => {
    if (filtersQuery.matches) {
      filters.dataset.visitorToggled = "true";
    }
  });
  matchFiltersToViewport(filtersQuery);
}

function enhance(root) {
  bindAutoSubmit(root);
  bindSubmit(root);
  bindFilterLinks(root);
  bindFilterDisclosure(root);
}

restoreScroll();

const catalog = document.querySelector(CATALOG_SELECTOR);
if (catalog instanceof HTMLElement) {
  enhance(catalog);
}

filtersQuery.addEventListener("change", matchFiltersToViewport);

window.addEventListener("popstate", () => {
  if (!document.querySelector(CATALOG_SELECTOR)) {
    return;
  }
  loadCatalog(window.location.href, { push: false });
});
