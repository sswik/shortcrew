/**
 * 백오피스 LNB (Tailwind `data-*` 변형과 연동)
 * - 데스크톱: `data-collapsed` + localStorage
 * - 모바일/태블릿: `data-open` + 오버레이 `data-open`
 */
(function () {
  const sidebar = document.getElementById("admin-sidebar");
  const overlay = document.getElementById("admin-sidebar-overlay");
  const mobileBtn = document.getElementById("admin-mobile-menu");
  const collapseBtn = document.getElementById("admin-lnb-collapse");
  const LS_KEY = "shortcrewAdminLnbCollapsed";

  function mqDesktop() {
    return window.matchMedia("(min-width: 1024px)").matches;
  }

  function setOverlay(on) {
    if (!overlay) return;
    overlay.setAttribute("data-open", on ? "true" : "false");
    overlay.setAttribute("aria-hidden", on ? "false" : "true");
  }

  function closeMobile() {
    if (!sidebar) return;
    sidebar.removeAttribute("data-open");
    setOverlay(false);
    if (mobileBtn) mobileBtn.setAttribute("aria-expanded", "false");
  }

  function applyDesktopCollapsed(collapsed) {
    if (!sidebar) return;
    if (collapsed) {
      sidebar.setAttribute("data-collapsed", "true");
    } else {
      sidebar.removeAttribute("data-collapsed");
    }
    if (collapseBtn) {
      collapseBtn.setAttribute("aria-expanded", collapsed ? "false" : "true");
      collapseBtn.setAttribute(
        "aria-label",
        collapsed ? "메뉴 펼치기" : "메뉴 접기",
      );
    }
  }

  collapseBtn?.addEventListener("click", function () {
    if (!mqDesktop() || !sidebar) return;
    const next = sidebar.getAttribute("data-collapsed") !== "true";
    applyDesktopCollapsed(next);
    try {
      localStorage.setItem(LS_KEY, next ? "1" : "0");
    } catch (_) {
      /* ignore */
    }
  });

  mobileBtn?.addEventListener("click", function () {
    if (mqDesktop()) return;
    if (!sidebar) return;
    const open = sidebar.getAttribute("data-open") !== "true";
    if (open) {
      sidebar.setAttribute("data-open", "true");
      setOverlay(true);
      mobileBtn.setAttribute("aria-expanded", "true");
    } else {
      closeMobile();
    }
  });

  overlay?.addEventListener("click", closeMobile);

  window.addEventListener("resize", function () {
    if (!sidebar) return;
    if (mqDesktop()) {
      closeMobile();
      try {
        applyDesktopCollapsed(localStorage.getItem(LS_KEY) === "1");
      } catch (_) {
        applyDesktopCollapsed(false);
      }
    } else {
      sidebar.removeAttribute("data-collapsed");
      applyDesktopCollapsed(false);
    }
  });

  if (sidebar && mqDesktop()) {
    try {
      applyDesktopCollapsed(localStorage.getItem(LS_KEY) === "1");
    } catch (_) {
      applyDesktopCollapsed(false);
    }
  }
})();
