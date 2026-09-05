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
