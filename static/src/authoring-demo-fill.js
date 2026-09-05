const button = document.querySelector("#fill-demo-details");
const detailsElement = document.querySelector("#authoring-demo-details");
const status = document.querySelector("#demo-fill-status");

if (button instanceof HTMLButtonElement && detailsElement && status instanceof HTMLElement) {
  const form = button.form;

  if (!(form instanceof HTMLFormElement)) {
    console.error("Demo fill control is not associated with a form", button);
  } else {
    button.addEventListener("click", () => {
      const details = JSON.parse(detailsElement.textContent || "{}");

      for (const [name, value] of Object.entries(details.fields || {})) {
        const control = form.elements.namedItem(name);
        if (
          control instanceof HTMLInputElement ||
          control instanceof HTMLSelectElement ||
          control instanceof HTMLTextAreaElement
        ) {
          control.value = value;
          control.dispatchEvent(new Event("input", { bubbles: true }));
          control.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }

      for (const [name, labels] of Object.entries(details.choice_labels || {})) {
        const control = form.elements.namedItem(name);
        if (!(control instanceof HTMLSelectElement) || !Array.isArray(labels)) {
          continue;
        }
        for (const option of control.options) {
          option.selected = labels.includes(option.textContent.trim());
        }
        control.dispatchEvent(new Event("input", { bubbles: true }));
        control.dispatchEvent(new Event("change", { bubbles: true }));
      }

      const ministry = form.elements.namedItem("ministry");
      if (ministry instanceof HTMLSelectElement) {
        const availableOptions = Array.from(ministry.options).filter((option) => option.value);
        if (availableOptions.length === 1) {
          ministry.value = availableOptions[0].value;
          ministry.dispatchEvent(new Event("input", { bubbles: true }));
          ministry.dispatchEvent(new Event("change", { bubbles: true }));
        }
      }

      status.textContent = status.dataset.filledMessage || "";
      status.hidden = false;
    });
  }
}
