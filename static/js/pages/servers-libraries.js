(function () {
  function readConfig() {
    const el = document.getElementById("servers-libraries-config");
    if (!el) return {};
    try { return JSON.parse(el.textContent || "{}"); }
    catch (_) { return {}; }
  }

  function initServersLibraries() {
    const form = document.getElementById("lib-form");
    const checkAll = document.getElementById("check-all");
    const buttonZone = document.getElementById("bulk-buttons");
    const removeModal = document.getElementById("bulk-remove-modal");
    const removeModalCancel = document.getElementById("bulk-remove-cancel");
    const removeModalConfirm = document.getElementById("bulk-remove-confirm");
    const removeModalServer = document.getElementById("bulk-remove-server");
    const removeModalCount = document.getElementById("bulk-remove-count");
    const removeModalList = document.getElementById("bulk-remove-list");

    if (!form || !checkAll || !buttonZone || !removeModal || !removeModalCancel || !removeModalConfirm || form.dataset.vodumBound === "1") return;
    form.dataset.vodumBound = "1";

    const config = readConfig();
    const labels = config.labels || {};
    const urls = config.urls || {};
    const checks = Array.from(document.querySelectorAll(".lib-check"));
    let pendingRemoveAction = null;

    function selectedByServer() {
      const byServer = {};
      checks.forEach((checkbox) => {
        if (!checkbox.checked) return;
        const serverId = checkbox.dataset.server;
        if (!byServer[serverId]) byServer[serverId] = { name: checkbox.dataset.serverName, libs: [] };
        byServer[serverId].libs.push({ id: checkbox.value, name: checkbox.dataset.libraryName });
      });
      return byServer;
    }

    function createButton({ text, value, action, className, onClick }) {
      const btn = document.createElement("button");
      btn.type = "submit";
      btn.name = "server_id";
      btn.value = value;
      btn.formAction = action;
      btn.className = className;
      btn.textContent = text;
      if (onClick) btn.addEventListener("click", onClick);
      return btn;
    }

    function closeRemoveModal() {
      pendingRemoveAction = null;
      removeModal.classList.add("hidden");
      removeModal.setAttribute("aria-hidden", "true");
    }

    function openRemoveModal(serverId, serverName, libs) {
      pendingRemoveAction = { serverId, libs };
      removeModalServer.textContent = serverName;
      removeModalCount.textContent = String(libs.length);
      removeModalList.innerHTML = "";

      libs.forEach((lib) => {
        const badge = document.createElement("span");
        badge.className = "inline-flex items-center rounded-full border border-slate-700 bg-slate-800 px-3 py-1 text-xs text-slate-200";
        badge.textContent = lib.name;
        removeModalList.appendChild(badge);
      });

      removeModal.classList.remove("hidden");
      removeModal.setAttribute("aria-hidden", "false");
    }

    function refreshButtons() {
      buttonZone.innerHTML = "";
      const byServer = selectedByServer();

      Object.keys(byServer).forEach((serverId) => {
        const serverName = byServer[serverId].name;
        const libs = byServer[serverId].libs;

        buttonZone.appendChild(createButton({
          text: `${labels.grantActiveUsers || "Grant active users"} ${serverName}`,
          value: serverId,
          action: urls.grant || form.action,
          className: "px-3 py-1 rounded-lg bg-primary hover:bg-primary-dark text-white text-xs",
        }));

        buttonZone.appendChild(createButton({
          text: `${labels.removeAccessAllUsers || "Remove access for all users"} ${serverName}`,
          value: serverId,
          action: urls.remove || form.action,
          className: "px-3 py-1 rounded-lg bg-red-600 hover:bg-red-700 text-white text-xs",
          onClick(event) {
            event.preventDefault();
            openRemoveModal(serverId, serverName, libs);
          },
        }));
      });
    }

    checkAll.addEventListener("change", () => {
      checks.forEach((checkbox) => { checkbox.checked = checkAll.checked; });
      refreshButtons();
    });
    checks.forEach((checkbox) => checkbox.addEventListener("change", refreshButtons));
    removeModalCancel.addEventListener("click", closeRemoveModal);
    removeModal.addEventListener("click", (event) => {
      if (event.target === removeModal || event.target?.classList?.contains("bg-black/70")) closeRemoveModal();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !removeModal.classList.contains("hidden")) closeRemoveModal();
    });

    removeModalConfirm.addEventListener("click", () => {
      if (!pendingRemoveAction) return;
      const { serverId, libs } = pendingRemoveAction;

      checks.forEach((checkbox) => {
        checkbox.checked = checkbox.dataset.server === serverId && libs.some((lib) => lib.id === checkbox.value);
      });
      checkAll.checked = checks.length > 0 && checks.every((checkbox) => checkbox.checked);
      closeRemoveModal();

      const hiddenServerInput = document.createElement("input");
      hiddenServerInput.type = "hidden";
      hiddenServerInput.name = "server_id";
      hiddenServerInput.value = serverId;
      form.appendChild(hiddenServerInput);
      form.action = urls.remove || form.action;
      form.submit();
    });

    refreshButtons();
  }

  document.addEventListener("DOMContentLoaded", initServersLibraries);
  document.addEventListener("htmx:load", initServersLibraries);
})();