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


  function initTautulliImport() {
    const tautulliModal = document.getElementById("tautulliImportModal");
    const openBtn = document.getElementById("openTautulliImportModal");
    const closeBtn = document.getElementById("closeTautulliImportModal");
    const confirmBtn = document.getElementById("confirmTautulliImportBtn");
    const form = document.getElementById("tautulliImportForm");
    const fileInput = document.getElementById("tautulliDbFile");
    const errBox = document.getElementById("tautulliFileError");
    const overlay = document.getElementById("tautulliCopyOverlay");
    const statusBox = document.getElementById("tautulliJobStatus");
    const statusMeta = document.getElementById("tautulliJobStatusMeta");
    const statusText = document.getElementById("tautulliJobStatusText");
    const statusErr = document.getElementById("tautulliJobStatusError");

    if (!tautulliModal || !openBtn || !form || !fileInput || !errBox || !statusBox || form.dataset.vodumBound === "1") return;
    form.dataset.vodumBound = "1";

    const statusUrl = config.tautulliStatusUrl || "";
    const msgSelectFile = labels.tautulliSelectFileFirst || "Select a file first.";
    let statusTimer = null;

    function showError(message) {
      errBox.textContent = message;
      errBox.classList.remove("hidden");
    }

    function clearError() {
      errBox.textContent = "";
      errBox.classList.add("hidden");
    }

    function updateButtonState() {
      const hasFile = fileInput.files && fileInput.files.length > 0;
      openBtn.disabled = !hasFile;
      if (hasFile) {
        openBtn.classList.remove("cursor-not-allowed", "opacity-60", "bg-primary/40");
        openBtn.classList.add("cursor-pointer", "bg-primary/80", "hover:bg-primary");
        clearError();
      } else {
        openBtn.classList.remove("cursor-pointer", "bg-primary/80", "hover:bg-primary");
        openBtn.classList.add("cursor-not-allowed", "opacity-60", "bg-primary/40");
      }
    }

    function openModal() {
      if (!fileInput.files || fileInput.files.length === 0) {
        showError(msgSelectFile);
        return;
      }
      tautulliModal.classList.remove("hidden");
      tautulliModal.setAttribute("aria-hidden", "false");
    }

    function closeModal() {
      tautulliModal.classList.add("hidden");
      tautulliModal.setAttribute("aria-hidden", "true");
    }

    function setStatusBoxStyle(kind) {
      statusBox.classList.remove(
        "bg-slate-950", "border-slate-800", "text-slate-200",
        "bg-emerald-900/20", "border-emerald-900/40", "text-emerald-100",
        "bg-red-900/20", "border-red-900/40", "text-red-100"
      );
      if (kind === "ok") {
        statusBox.classList.add("bg-emerald-900/20", "border-emerald-900/40", "text-emerald-100");
      } else if (kind === "err") {
        statusBox.classList.add("bg-red-900/20", "border-red-900/40", "text-red-100");
      } else {
        statusBox.classList.add("bg-slate-950", "border-slate-800", "text-slate-200");
      }
    }

    function stopStatusTimer() {
      if (statusTimer) window.clearInterval(statusTimer);
      statusTimer = null;
    }

    function renderJobStatus(data) {
      if (!data || !data.status || data.status === "none") {
        statusBox.classList.add("hidden");
        return;
      }

      statusBox.classList.remove("hidden");
      statusErr.classList.add("hidden");
      statusErr.textContent = "";
      statusMeta.textContent = data.id ? `#${data.id}` : "";

      if (data.status === "queued") {
        setStatusBoxStyle("info");
        statusText.textContent = "Queued, waiting for the worker to start.";
      } else if (data.status === "running") {
        setStatusBoxStyle("info");
        statusText.textContent = "Running, importing sessions.";
      } else if (data.status === "success") {
        const finishedAt = data.finished_at && window.vodumParseDate ? window.vodumParseDate(data.finished_at) : null;
        const ageMs = finishedAt ? (Date.now() - finishedAt.getTime()) : 0;
        if (finishedAt && ageMs > (2 * 60 * 60 * 1000)) {
          statusBox.classList.add("hidden");
          stopStatusTimer();
          return;
        }
        setStatusBoxStyle("ok");
        statusText.textContent = "Completed successfully.";
        stopStatusTimer();
      } else if (data.status === "error") {
        setStatusBoxStyle("err");
        statusText.textContent = "Failed.";
        if (data.last_error) {
          statusErr.textContent = data.last_error;
          statusErr.classList.remove("hidden");
        }
        stopStatusTimer();
      } else {
        setStatusBoxStyle("info");
        statusText.textContent = `Status: ${data.status}`;
      }
    }

    async function pollJobStatusOnce() {
      if (!statusUrl) return;
      try {
        const response = await fetch(statusUrl, { cache: "no-store" });
        if (!response.ok) return;
        const data = await response.json();
        renderJobStatus(data);
        if (data && (data.status === "queued" || data.status === "running") && !statusTimer) {
          statusTimer = window.setInterval(pollJobStatusOnce, 2000);
        }
      } catch (error) {
        // Status polling is best-effort.
      }
    }

    form.addEventListener("submit", () => {
      if (overlay) {
        overlay.classList.remove("hidden");
        overlay.classList.add("flex");
      }
      openBtn.disabled = true;
      openBtn.classList.add("opacity-60", "cursor-not-allowed");
      if (closeBtn) closeBtn.disabled = true;
      if (confirmBtn) confirmBtn.disabled = true;
      Array.from(form.querySelectorAll("button")).forEach((button) => {
        button.disabled = true;
        button.classList.add("opacity-60", "cursor-not-allowed");
      });
    });

    fileInput.addEventListener("change", updateButtonState);
    openBtn.addEventListener("click", openModal);
    if (closeBtn) closeBtn.addEventListener("click", closeModal);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !tautulliModal.classList.contains("hidden")) closeModal();
    });
    tautulliModal.addEventListener("click", (event) => {
      if (event.target === tautulliModal || event.target?.classList?.contains("bg-black/70")) closeModal();
    });

    updateButtonState();
    pollJobStatusOnce();
  }
  document.addEventListener("DOMContentLoaded", function () {
    initTautulliImport();
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