(function () {
  function initServersLibraries() {
    if (document.documentElement.dataset.vodumLibrariesBound === "1") return;
    document.documentElement.dataset.vodumLibrariesBound = "1";

    const removeModal = document.getElementById("bulk-remove-modal");
    const removeForm = document.getElementById("library-remove-form");
    const removeModalCancel = document.getElementById("bulk-remove-cancel");
    const removeModalConfirm = document.getElementById("bulk-remove-confirm");
    const removeModalServer = document.getElementById("bulk-remove-server");
    const removeModalCount = document.getElementById("bulk-remove-count");
    const removeModalList = document.getElementById("bulk-remove-list");
    const removeServerInput = document.getElementById("library-remove-server-id");
    const removeLibraryInput = document.getElementById("library-remove-library-id");

    function closeMenus(exceptId) {
      document.querySelectorAll('[id^="library-menu-"]').forEach((menu) => {
        if (menu.id !== exceptId) menu.classList.add("hidden");
      });
      document.querySelectorAll("[data-library-menu-toggle]").forEach((button) => {
        const isOpen = `library-menu-${button.dataset.libraryMenuToggle}` === exceptId;
        button.setAttribute("aria-expanded", isOpen ? "true" : "false");
      });
    }

    function closeRemoveModal() {
      if (!removeModal) return;
      removeModal.classList.add("hidden");
      removeModal.setAttribute("aria-hidden", "true");
    }

    document.addEventListener("click", (event) => {
      const toggle = event.target.closest("[data-library-menu-toggle]");
      if (toggle) {
        event.stopPropagation();
        const menuId = `library-menu-${toggle.dataset.libraryMenuToggle}`;
        const menu = document.getElementById(menuId);
        const opening = menu?.classList.contains("hidden");
        closeMenus(opening ? menuId : null);
        if (opening) menu?.classList.remove("hidden");
        return;
      }

      const remove = event.target.closest("[data-library-remove]");
      if (remove && removeModal && removeForm) {
        closeMenus();
        removeServerInput.value = remove.dataset.serverId || "";
        removeLibraryInput.value = remove.dataset.libraryRemove || "";
        removeModalServer.textContent = remove.dataset.serverName || "—";
        removeModalCount.textContent = "1";
        removeModalList.replaceChildren();
        const badge = document.createElement("span");
        badge.className = "inline-flex items-center rounded-full border border-slate-700 bg-slate-800 px-3 py-1 text-xs text-slate-200";
        badge.textContent = remove.dataset.libraryName || "";
        removeModalList.appendChild(badge);
        removeModal.classList.remove("hidden");
        removeModal.setAttribute("aria-hidden", "false");
        return;
      }

      if (!event.target.closest('[id^="library-menu-"]')) closeMenus();
      if (event.target === removeModal || event.target?.classList?.contains("bg-black/70")) closeRemoveModal();
    });

    removeModalCancel?.addEventListener("click", closeRemoveModal);
    removeModalConfirm?.addEventListener("click", () => removeForm?.submit());
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      closeMenus();
      closeRemoveModal();
    });
  }

  document.addEventListener("DOMContentLoaded", initServersLibraries);
  document.addEventListener("htmx:load", initServersLibraries);
})();
