(() => {
  "use strict";
  const entryKey = "atlas-entry";
  const root = document.documentElement;
  const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
  let entryTime = 0;
  try {
    entryTime = Number(sessionStorage.getItem(entryKey));
    sessionStorage.removeItem(entryKey);
  } catch (_) { /* Navigation remains usable when storage is unavailable. */ }

  if (location.pathname === "/explore" && entryTime > 0 && Date.now() - entryTime < 15000 && !reducedMotion()) {
    root.classList.add("atlas-entering");
    let revealed = false;
    const reveal = () => {
      if (revealed) return;
      revealed = true;
      requestAnimationFrame(() => requestAnimationFrame(() => {
        root.classList.add("atlas-entered");
        setTimeout(() => root.classList.remove("atlas-entering", "atlas-entered"), 1000);
      }));
    };
    window.addEventListener("atlas:ready", reveal, { once: true });
    // Never leave the application hidden if a script or request fails.
    setTimeout(reveal, 8000);
  }

  document.addEventListener("click", (event) => {
    const link = event.target.closest?.("[data-enter-atlas]");
    if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    if (document.body.classList.contains("is-leaving")) return;
    try { sessionStorage.setItem(entryKey, String(Date.now())); } catch (_) { /* Standard navigation fallback. */ }
    document.body.classList.add("is-leaving");
    link.setAttribute("aria-disabled", "true");
    setTimeout(() => location.assign(link.href), reducedMotion() ? 0 : 200);
  });

  window.addEventListener("pageshow", () => {
    document.body.classList.remove("is-leaving");
    document.querySelector("[data-enter-atlas]")?.removeAttribute("aria-disabled");
  });
})();
