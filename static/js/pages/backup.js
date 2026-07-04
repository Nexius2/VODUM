(function vodumBackupPage() {
  const configEl = document.getElementById("vodum-backup-config");
  const config = (() => {
    if (!configEl) return {};
    try {
      return JSON.parse(configEl.textContent || "{}");
    } catch (error) {
      console.error("[vodum] invalid backup config", error);
      return {};
    }
  })();

  const labels = config.i18n || {};
  const shouldAutoRefreshBackups = Boolean(config.autoRefreshBackups);
  const escapeHtml = window.htmlEscape || ((value) => String(value ?? "").replace(/[&<>\"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "\"": "&quot;",
    "'": "&#39;"
  }[char])));

  window.showRestoreWaitingModal = function () {
    const modal = document.getElementById("restore-waiting-modal");
    if (!modal) return;

    modal.classList.remove("hidden");
    modal.classList.add("flex");
  };

  function formatBackupSize(bytes) {
    const mb = Number(bytes || 0) / 1024 / 1024;
    return `${mb.toFixed(2)} MB`;
  }

  function closeBackupMenus() {
    document.querySelectorAll('[id^="backup-menu-"]').forEach((menu) => {
      menu.classList.add("hidden");
    });
  }

  function toggleBackupMenu(index) {
    document.querySelectorAll('[id^="backup-menu-"]').forEach((menu) => {
      if (menu.id !== `backup-menu-${index}`) {
        menu.classList.add("hidden");
      }
    });

    const menu = document.getElementById(`backup-menu-${index}`);
    if (menu) {
      menu.classList.toggle("hidden");
    }
  }

  function openRestoreConfirm() {
    const modal = document.getElementById("restoreConfirmModal");
    const modalText = document.getElementById("restoreConfirmModalText");
    if (!modal || !modalText) return;

    modalText.textContent = labels.confirmRestore || "";
    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
  }

  function closeRestoreConfirm() {
    const modal = document.getElementById("restoreConfirmModal");
    if (!modal) return;

    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
  }

  function restoreBackup(filename) {
    const hiddenInput = document.getElementById("selected-backup-input");
    if (!hiddenInput) return;

    hiddenInput.value = filename;
    closeBackupMenus();
    openRestoreConfirm();
  }

  let deleteBackupFilename = null;

  function openDeleteBackupModal(filename) {
    deleteBackupFilename = filename;

    const nameEl = document.getElementById("delete-backup-name");
    const modal = document.getElementById("delete-backup-modal");
    if (!nameEl || !modal) return;

    nameEl.textContent = filename;
    modal.classList.remove("hidden");
    modal.classList.add("flex");
  }

  function closeDeleteBackupModal() {
    const modal = document.getElementById("delete-backup-modal");
    if (!modal) return;

    modal.classList.add("hidden");
    modal.classList.remove("flex");
    deleteBackupFilename = null;
  }

  function confirmDeleteBackup() {
    if (!deleteBackupFilename) return;

    const filename = deleteBackupFilename;
    closeDeleteBackupModal();
    fetch("/backup/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "same-origin",
      body: JSON.stringify({ filename })
    }).then(() => {
      window.location.reload();
    });
  }
  function renderBackupRows(backups) {
    const tbody = document.getElementById("backups-table-body");
    if (!tbody) return;

    tbody.innerHTML = backups.map((backup, index) => {
      const safeName = escapeHtml(backup.name);
      const filenameJs = JSON.stringify(backup.name);
      const menuId = `api-${index}`;

      return `
        <tr class="border-t border-slate-800 overflow-visible">
          <td class="px-3 py-2 font-mono text-[11px]">
            <a href="/backup/download/${encodeURIComponent(backup.name)}" class="hover:text-primary transition-colors">${safeName}</a>
          </td>
          <td class="px-3 py-2 text-slate-300">${formatBackupSize(backup.size)}</td>
          <td class="px-3 py-2 text-slate-400">${escapeHtml(backup.mtime)}</td>
          <td class="px-3 py-2 text-center relative z-[200]">
            <button type="button" data-backup-menu-toggle="${menuId}" class="inline-flex items-center justify-center w-8 h-8 rounded-lg hover:bg-slate-800/80 text-slate-400 hover:text-slate-200 transition">
              <svg xmlns="http://www.w3.org/2000/svg" class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24"><circle cx="12" cy="5" r="2"></circle><circle cx="12" cy="12" r="2"></circle><circle cx="12" cy="19" r="2"></circle></svg>
            </button>
            <div id="backup-menu-${menuId}" class="hidden absolute right-3 bottom-10 z-[9999] w-44 overflow-hidden rounded-xl border border-slate-800 bg-slate-900 shadow-2xl">
              <a href="/backup/download/${encodeURIComponent(backup.name)}" class="flex items-center gap-2 px-4 py-2.5 text-xs text-slate-300 hover:bg-slate-800 transition"><span aria-hidden="true">&darr;</span><span>${escapeHtml(labels.download || "Download")}</span></a>
              <button type="button" data-backup-restore="${safeName}" class="w-full flex items-center gap-2 px-4 py-2.5 text-xs text-left text-amber-300 hover:bg-slate-800 transition"><span aria-hidden="true">&#8635;</span><span>${escapeHtml(labels.restore || "Restore")}</span></button>
              <button type="button" data-backup-delete="${safeName}" class="w-full flex items-center gap-2 px-4 py-2.5 text-xs text-left text-rose-300 hover:bg-slate-800 transition"><span aria-hidden="true">&times;</span><span>${escapeHtml(labels.delete || "Delete")}</span></button>
            </div>
          </td>
        </tr>
      `;
    }).join("");
  }

  async function refreshBackupListOnce() {
    const response = await fetch("/api/backup/list", {
      cache: "no-store",
      headers: { "Accept": "application/json" }
    });

    if (!response.ok) return;

    const data = await response.json();
    renderBackupRows(data.backups || []);
  }

  async function isAutoBackupStillActive() {
    try {
      const response = await fetch("/api/tasks/list", {
        cache: "no-store",
        headers: { "Accept": "application/json" }
      });
      if (!response.ok) return false;
      const data = await response.json();
      const task = (data.tasks || []).find((item) => item.name === "auto_backup");
      return task && ["queued", "running"].includes(task.status);
    } catch (error) {
      return false;
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".js-restore-backup-form").forEach(function (form) {
      form.addEventListener("submit", function () {
        window.showRestoreWaitingModal();
      });
    });

    document.addEventListener("click", function (event) {
      const menuToggle = event.target.closest("[data-backup-menu-toggle]");
      if (menuToggle) {
        toggleBackupMenu(menuToggle.dataset.backupMenuToggle);
        return;
      }

      const restoreButton = event.target.closest("[data-backup-restore]");
      if (restoreButton) {
        restoreBackup(restoreButton.dataset.backupRestore || "");
        return;
      }

      const deleteButton = event.target.closest("[data-backup-delete]");
      if (deleteButton) {
        openDeleteBackupModal(deleteButton.dataset.backupDelete || "");
        return;
      }

      if (event.target.closest("[data-backup-delete-cancel]")) {
        closeDeleteBackupModal();
        return;
      }

      if (event.target.closest("[data-backup-delete-confirm]")) {
        confirmDeleteBackup();
        return;
      }

      const restoreModal = document.getElementById("restoreConfirmModal");
      if (restoreModal && (event.target === restoreModal || event.target.classList.contains("bg-black/70"))) {
        closeRestoreConfirm();
        return;
      }

      const deleteModal = document.getElementById("delete-backup-modal");
      if (deleteModal && event.target === deleteModal) {
        closeDeleteBackupModal();
        return;
      }

      if (!event.target.closest("[data-backup-menu-toggle]") && !event.target.closest('[id^="backup-menu-"]')) {
        closeBackupMenus();
      }
    });

    const restoreCancel = document.getElementById("restoreConfirmCancel");
    if (restoreCancel) {
      restoreCancel.addEventListener("click", closeRestoreConfirm);
    }

    const restoreOk = document.getElementById("restoreConfirmOk");
    const restoreForm = document.getElementById("restore-existing-form");
    if (restoreOk && restoreForm) {
      restoreOk.addEventListener("click", function () {
        closeRestoreConfirm();
        window.showRestoreWaitingModal();
        restoreForm.submit();
      });
    }

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;

      closeRestoreConfirm();
      closeDeleteBackupModal();
      closeBackupMenus();
    });
    if (!shouldAutoRefreshBackups) return;

    let attempts = 0;
    const maxAttempts = 45;
    const timer = window.setInterval(async function () {
      attempts += 1;
      await refreshBackupListOnce();
      const active = await isAutoBackupStillActive();
      if (!active || attempts >= maxAttempts) {
        window.clearInterval(timer);
        await refreshBackupListOnce();
      }
    }, 2000);
  });
})();