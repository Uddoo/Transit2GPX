import "@testing-library/jest-dom/vitest";

if (typeof HTMLDialogElement !== "undefined") {
  if (!("showModal" in HTMLDialogElement.prototype)) {
    Object.defineProperty(HTMLDialogElement.prototype, "showModal", {
      configurable: true,
      value(this: HTMLDialogElement) {
        this.setAttribute("open", "");
      },
    });
  }
  if (!("close" in HTMLDialogElement.prototype)) {
    Object.defineProperty(HTMLDialogElement.prototype, "close", {
      configurable: true,
      value(this: HTMLDialogElement) {
        this.removeAttribute("open");
      },
    });
  }
}
