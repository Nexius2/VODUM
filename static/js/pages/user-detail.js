(function () {
  function readJsonConfig(id) {
    const element = document.getElementById(id);
    if (!element) return {};

    try {
      return JSON.parse(element.textContent || "{}");
    } catch (error) {
      console.error(`Invalid JSON configuration in #${id}`, error);
      return {};
    }
  }

  function bindExpirationOverride() {
    const subscriptionSelect = document.getElementById("subscription_template_id");
    const overrideCheckbox = document.getElementById("expiration_date_override_cb");
    const notice = document.getElementById("lifetime_override_notice");

    if (!subscriptionSelect || !overrideCheckbox || overrideCheckbox.dataset.vodumBound === "1") return;
    overrideCheckbox.dataset.vodumBound = "1";

    const config = readJsonConfig("user-general-expiration-config");
    const serverExpirationLocked = config.server_expiration_locked === true;

    function updateLifetimeOverride() {
      if (serverExpirationLocked) {
        overrideCheckbox.checked = true;
        overrideCheckbox.disabled = true;

        if (notice) {
          notice.classList.remove("hidden");
          notice.textContent = config.server_expiration_label || "";
        }
        return;
      }

      const selected = subscriptionSelect.options[subscriptionSelect.selectedIndex];
      const isLifetime = selected?.dataset?.lifetime === "1";

      if (isLifetime) {
        overrideCheckbox.checked = true;
        overrideCheckbox.disabled = true;
        notice?.classList.remove("hidden");
        return;
      }

      overrideCheckbox.disabled = false;
      overrideCheckbox.checked = overrideCheckbox.dataset.original === "1";
      notice?.classList.add("hidden");
    }

    subscriptionSelect.addEventListener("change", updateLifetimeOverride);
    updateLifetimeOverride();
  }

  function appendTextElement(parent, className, text) {
    const element = document.createElement("div");
    element.className = className;
    element.textContent = text;
    parent.appendChild(element);
  }

  function bindReferrerPicker() {
    const modal = document.getElementById("modal_referrer_picker");
    const openButton = document.getElementById("btn_open_referrer_modal");
    const closeButton = document.getElementById("btn_close_referrer_modal");
    const input = document.getElementById("referrer_search_input");
    const list = document.getElementById("referrer_candidates");
    const hiddenInput = document.getElementById("referrer_user_id");
    const display = document.getElementById("referrer_display");

    if (!modal || !openButton || !closeButton || !input || !list || !hiddenInput || !display) return;
    if (modal.dataset.vodumReferrerBound === "1") return;
    modal.dataset.vodumReferrerBound = "1";

    const config = readJsonConfig("user-general-expiration-config");
    let requestNumber = 0;

    function createCandidateButton(candidate) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "w-full text-left px-4 py-3 hover:bg-slate-800";
      button.dataset.id = String(candidate.id ?? "");
      button.dataset.username = candidate.username || "";
      button.dataset.email = candidate.email || "";

      appendTextElement(button, "text-sm font-medium text-slate-100", candidate.username || "—");
      appendTextElement(button, "text-xs text-slate-400", candidate.email || "");
      appendTextElement(button, "text-xs text-slate-500 mt-1", `${config.referrals_total || "Referrals"}: ${candidate.referrals_count || 0}`);
      return button;
    }

    function createNoReferrerButton() {
      const button = createCandidateButton({ id: "", username: config.no_referrer || "-" });
      button.classList.add("border-b", "border-slate-800");
      button.lastElementChild?.remove();
      appendTextElement(button, "text-xs text-slate-500 mt-1", config.referrer_none_help || "");
      return button;
    }

    async function loadCandidates(query = "") {
      const currentRequest = ++requestNumber;
      const url = new URL(config.referrer_candidates_url || "/api/users/referrer-candidates", window.location.origin);
      url.searchParams.set("q", query);

      try {
        const response = await fetch(url, { headers: { Accept: "application/json" } });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const rows = await response.json();
        if (currentRequest !== requestNumber) return;

        list.replaceChildren(createNoReferrerButton());
        if (!rows.length) {
          appendTextElement(list, "px-4 py-3 text-sm text-slate-400", config.no_user_found || "");
          return;
        }
        rows.forEach((candidate) => list.appendChild(createCandidateButton(candidate)));
      } catch (error) {
        if (currentRequest === requestNumber) console.error("Unable to load referrer candidates", error);
      }
    }

    function closeModal() {
      modal.classList.add("hidden");
    }

    openButton.addEventListener("click", () => {
      modal.classList.remove("hidden");
      input.value = "";
      loadCandidates();
      setTimeout(() => input.focus(), 30);
    });
    closeButton.addEventListener("click", closeModal);
    modal.querySelector(".absolute.inset-0")?.addEventListener("click", closeModal);
    input.addEventListener("input", () => loadCandidates(input.value.trim()));
    list.addEventListener("click", (event) => {
      const button = event.target.closest("button[data-id]");
      if (!button) return;

      hiddenInput.value = button.dataset.id || "";
      if (!button.dataset.id) {
        const empty = document.createElement("span");
        empty.className = "text-slate-500";
        empty.textContent = config.no_referrer || "-";
        display.replaceChildren(empty);
      } else {
        display.textContent = `${button.dataset.username || ""}${button.dataset.email ? ` — ${button.dataset.email}` : ""}`;
      }
      closeModal();
    });
  }

  function bindJellyfinPasswordModal() {
    const modal = document.getElementById("jellyfinPasswordModal");
    const openButton = document.getElementById("openJellyfinPasswordModalBtn");
    const closeButton = document.getElementById("closeJellyfinPasswordModalBtn");
    const cancelButton = document.getElementById("cancelJellyfinPasswordModalBtn");
    const form = document.getElementById("jellyfinPasswordForm");
    const resultBox = document.getElementById("jf_password_result");
    if (!modal || !openButton || !form || !resultBox || modal.dataset.vodumJellyfinBound === "1") return;
    modal.dataset.vodumJellyfinBound = "1";

    const config = readJsonConfig("user-general-expiration-config");
    const resultClasses = {
      success: "rounded-xl border border-emerald-800 bg-emerald-950/30 px-4 py-3 text-sm text-emerald-300",
      error: "rounded-xl border border-rose-800 bg-rose-950/30 px-4 py-3 text-sm text-rose-300",
    };

    function showResult(kind, message) {
      resultBox.className = resultClasses[kind];
      resultBox.textContent = message;
    }

    function closeModal() {
      modal.classList.add("hidden");
      resultBox.classList.add("hidden");
      resultBox.textContent = "";
      form.reset();
    }

    openButton.addEventListener("click", () => modal.classList.remove("hidden"));
    closeButton?.addEventListener("click", closeModal);
    cancelButton?.addEventListener("click", closeModal);
    modal.querySelector(".absolute.inset-0")?.addEventListener("click", closeModal);

    const selectAll = document.getElementById("jf_select_all_servers");
    selectAll?.addEventListener("change", () => {
      document.querySelectorAll(".jf-server-checkbox").forEach((checkbox) => {
        checkbox.checked = selectAll.checked;
      });
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      try {
        const response = await fetch(config.jellyfin_password_url, {
          method: "POST",
          body: new FormData(form),
          headers: { Accept: "application/json" },
        });
        const rawText = await response.text();
        let data;
        try {
          data = JSON.parse(rawText);
        } catch (_) {
          showResult("error", rawText || config.invalid_json_response || "Invalid JSON response");
          return;
        }

        if (data.ok) {
          showResult("success", (config.jellyfin_password_success || "Updated on {count} server(s).").replace("{count}", data.updated));
        } else {
          showResult("error", (data.errors || [data.error || config.unknown_error || "Unknown error"]).join("\n"));
        }
      } catch (error) {
        console.error(error);
        showResult("error", config.request_failed || "Request failed.");
      }
    });
  }

  function bindAccessCollapsibles() {
    const config = readJsonConfig("user-access-config");
    const moreText = config.collapse_show_more || "Show more";
    const lessText = config.collapse_show_less || "Show less";

    [["plexBox", "plexToggle", "plexFade"], ["jellyfinBox", "jellyfinToggle", "jellyfinFade"]].forEach(([boxId, buttonId, fadeId]) => {
      const box = document.getElementById(boxId);
      const button = document.getElementById(buttonId);
      const fade = document.getElementById(fadeId);
      if (!box || !button || button.dataset.vodumBound === "1") return;
      button.dataset.vodumBound = "1";
      let expanded = false;
      button.addEventListener("click", () => {
        expanded = !expanded;
        box.classList.toggle("max-h-48", !expanded);
        box.classList.toggle("max-h-[9999px]", expanded);
        fade?.classList.toggle("hidden", expanded);
        button.textContent = expanded ? lessText : moreText;
      });
    });

    const box = document.getElementById("emailsBox");
    const inner = document.getElementById("emailsInner");
    const fade = document.getElementById("emailsFade");
    const button = document.getElementById("emailsToggle");
    const buttonWrap = document.getElementById("emailsToggleWrap");
    if (!box || !inner || !button || !buttonWrap || button.dataset.vodumBound === "1") return;
    button.dataset.vodumBound = "1";
    let expanded = false;

    function needsToggle() {
      return inner.scrollHeight > 193;
    }

    function applyState() {
      const toggleNeeded = needsToggle();
      buttonWrap.classList.toggle("hidden", !toggleNeeded);
      const showExpanded = expanded || !toggleNeeded;
      box.classList.toggle("max-h-48", !showExpanded);
      box.classList.toggle("max-h-[9999px]", showExpanded);
      inner.classList.toggle("overflow-y-auto", !showExpanded);
      fade?.classList.toggle("hidden", showExpanded);
      button.textContent = expanded ? lessText : moreText;
    }

    applyState();
    button.addEventListener("click", () => {
      expanded = !expanded;
      applyState();
    });
    window.addEventListener("resize", applyState);
  }

  function bindUserMerge() {
    const overlay = document.getElementById("mergeOverlay");
    if (!overlay || overlay.dataset.vodumBound === "1") return;
    overlay.dataset.vodumBound = "1";

    const config = readJsonConfig("user-merge-config");
    const mergeForm = document.getElementById("mergeForm");
    const otherIdInput = document.getElementById("mergeOtherId");
    const confirmButton = document.getElementById("mergeConfirmBtn");
    const confirmModal = document.getElementById("mergeConfirmModal");
    const finalConfirmButton = document.getElementById("mergeFinalConfirmBtn");
    const allCandidates = document.getElementById("mergeAllCandidates");
    const moreButton = document.getElementById("mergeMoreBtn");
    const previewContent = document.getElementById("mergePreviewContent");
    const previewLoading = document.getElementById("mergePreviewLoading");
    const previewError = document.getElementById("mergePreviewError");
    const previewChanges = document.getElementById("mergePreviewChanges");
    const targetName = document.getElementById("mergeTargetName");
    const targetEmail = document.getElementById("mergeTargetEmail");
    const targetScore = document.getElementById("mergeTargetScore");
    let selectedCandidate = null;

    function closeConfirmModal() {
      confirmModal?.classList.add("hidden");
    }
    function clearSelection() {
      document.querySelectorAll(".merge-candidate").forEach((candidate) => {
        candidate.classList.remove("border-amber-700", "bg-amber-900/10");
        candidate.classList.add("border-slate-800");
        candidate.setAttribute("aria-selected", "false");
      });
      selectedCandidate = null;
      if (otherIdInput) otherIdInput.value = "";
      if (confirmButton) {
        confirmButton.disabled = true;
        confirmButton.classList.add("opacity-50", "cursor-not-allowed");
        confirmButton.classList.remove("hover:bg-amber-800");
      }
    }
    function openOverlay() {
      overlay.classList.remove("hidden");
      document.body.classList.add("overflow-hidden");
      clearSelection();
    }
    function closeOverlay() {
      overlay.classList.add("hidden");
      document.body.classList.remove("overflow-hidden");
      closeConfirmModal();
    }
    window.openMergeOverlay = openOverlay;
    window.closeMergeOverlay = closeOverlay;
    window.closeMergeConfirmModal = closeConfirmModal;
    window.toggleAllMergeCandidates = () => {
      if (!allCandidates || !moreButton) return;
      const show = allCandidates.classList.contains("hidden");
      allCandidates.classList.toggle("hidden");
      moreButton.textContent = show ? config.show_top : config.show_all;
    };

    function fillConfirm(candidate) {
      if (!candidate) return;
      if (targetName) targetName.textContent = candidate.querySelector(".font-medium")?.innerText.trim() || "—";
      const info = candidate.querySelector(".text-xs.text-slate-400")?.innerText.trim() || "";
      const parts = info.split("·").map((part) => part.trim());
      if (targetEmail) targetEmail.textContent = parts[0] || "—";
      if (targetScore) targetScore.textContent = parts[1] ? `(${parts[1]})` : "—";
    }
    function selectCandidate(candidate) {
      clearSelection();
      selectedCandidate = candidate;
      candidate.classList.remove("border-slate-800");
      candidate.classList.add("border-amber-700", "bg-amber-900/10");
      candidate.setAttribute("aria-selected", "true");
      const otherId = candidate.dataset.otherId || "";
      if (otherIdInput) otherIdInput.value = otherId;
      if (confirmButton && otherId) {
        confirmButton.disabled = false;
        confirmButton.classList.remove("opacity-50", "cursor-not-allowed");
        confirmButton.classList.add("hover:bg-amber-800");
      }
      fillConfirm(candidate);
    }

    function appendPreviewRow(label, value, source) {
      const row = document.createElement("div");
      row.className = "rounded-lg border border-slate-800 bg-slate-950/60 p-3";
      const header = document.createElement("div");
      header.className = "flex items-center justify-between gap-2";
      appendTextElement(header, "text-xs text-slate-400", label);
      const badge = document.createElement("span");
      badge.className = source === "master" ? "px-2 py-0.5 text-[11px] rounded bg-emerald-900/40 text-emerald-300"
        : source === "target" ? "px-2 py-0.5 text-[11px] rounded bg-amber-900/40 text-amber-300"
          : "px-2 py-0.5 text-[11px] rounded bg-slate-800 text-slate-300";
      badge.textContent = source === "master" || source === "target" ? source : "computed";
      header.appendChild(badge);
      row.appendChild(header);
      appendTextElement(row, "mt-1 text-slate-200 break-words", value == null || value === "" ? "—" : String(value));
      previewContent?.appendChild(row);
    }
    function appendChangeList(changes) {
      if (!previewChanges || !changes) return;
      const title = document.createElement("div");
      title.className = "text-slate-300 font-semibold mb-1";
      title.textContent = `${config.preview_moved_title}:`;
      const list = document.createElement("ul");
      list.className = "list-disc pl-5 space-y-1";
      [[config.preview_media_users, changes.media_users_to_move], [config.preview_user_identities, changes.identities_to_move], [config.preview_sent_emails, changes.sent_emails_to_move], [config.preview_media_jobs, changes.media_jobs_to_move]].forEach(([label, value]) => {
        const item = document.createElement("li");
        item.textContent = `${label}: ${value}`;
        list.appendChild(item);
      });
      previewChanges.replaceChildren(title, list);
      previewChanges.classList.remove("hidden");
    }
    async function loadPreview(otherId) {
      if (!previewContent) return;
      previewError?.classList.add("hidden");
      previewChanges?.classList.add("hidden");
      previewContent.replaceChildren();
      previewLoading?.classList.remove("hidden");
      try {
        const url = new URL(config.preview_url, window.location.origin);
        url.searchParams.set("other_id", otherId);
        const response = await fetch(url, { headers: { Accept: "application/json" } });
        const data = await response.json();
        if (!response.ok) throw new Error(data?.error || "preview_failed");
        (config.fields || []).forEach(([label, key]) => appendPreviewRow(label, data.result?.[key], data.sources?.[key]));
        appendChangeList(data.changes);
      } catch (error) {
        if (previewError) {
          previewError.textContent = `${config.preview_error || "Preview error"}: ${error.message || error}`;
          previewError.classList.remove("hidden");
        }
      } finally {
        previewLoading?.classList.add("hidden");
      }
    }

    overlay.addEventListener("click", (event) => { if (event.target === overlay) closeOverlay(); });
    confirmModal?.addEventListener("click", (event) => { if (event.target === confirmModal) closeConfirmModal(); });
    document.addEventListener("click", (event) => {
      const candidate = event.target.closest?.(".merge-candidate");
      if (candidate) selectCandidate(candidate);
    });
    document.addEventListener("keydown", (event) => {
      if ((event.key === "Enter" || event.key === " ") && document.activeElement?.classList.contains("merge-candidate")) {
        event.preventDefault();
        selectCandidate(document.activeElement);
      }
    });
    const mainForm = document.getElementById("user_main_form");
    mainForm?.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && event.target?.tagName === "INPUT") event.preventDefault();
    });
    mainForm?.addEventListener("submit", () => {
      mainForm.querySelectorAll('input[data-dyn="1"]').forEach((input) => input.remove());
      document.querySelectorAll('form[action*="toggle_library"]').forEach((form) => {
        const library = form.querySelector('input[name="library_id"]');
        if (!library) return;
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = `library_${library.value}`;
        input.value = form.querySelector("button")?.classList.contains("bg-emerald-500") ? "1" : "0";
        input.dataset.dyn = "1";
        mainForm.appendChild(input);
      });
      document.querySelectorAll('input[name^="allow_sync_"], input[name^="allow_camera_upload_"], input[name^="allow_channels_"], input[name^="filter_movies_"], input[name^="filter_television_"], input[name^="filter_music_"]').forEach((source) => {
        const input = document.createElement("input");
        input.type = "hidden";
        input.name = source.name;
        input.value = source.type === "checkbox" ? (source.checked ? "1" : "0") : (source.value || "");
        input.dataset.dyn = "1";
        mainForm.appendChild(input);
      });
    });
    mergeForm?.addEventListener("submit", (event) => {
      event.preventDefault();
      if (!otherIdInput?.value) return;
      fillConfirm(selectedCandidate);
      loadPreview(otherIdInput.value);
      confirmModal?.classList.remove("hidden");
    });
    finalConfirmButton?.addEventListener("click", () => {
      if (!otherIdInput?.value) return;
      closeConfirmModal();
      mergeForm?.submit();
    });
    const params = new URLSearchParams(window.location.search);
    if (params.get("merge") === "1") {
      openOverlay();
      params.delete("merge");
      window.history.replaceState({}, "", `${window.location.pathname}${params.size ? `?${params}` : ""}`);
    }
  }

  function bindMonitoringFrameSkeleton() {
    const frame = document.querySelector("[data-user-monitoring-iframe]");
    const skeleton = document.querySelector("[data-user-monitoring-skeleton]");
    if (!frame || !skeleton || frame.dataset.vodumSkeletonBound === "1") return;
    frame.dataset.vodumSkeletonBound = "1";
    const timeout = window.setTimeout(() => {
      skeleton.classList.remove("animate-pulse");
      skeleton.replaceChildren(Object.assign(document.createElement("div"), {
        className: "flex h-full items-center justify-center text-sm text-slate-400",
        textContent: skeleton.dataset.errorLabel || "Unable to load content.",
      }));
    }, 10000);
    frame.addEventListener("load", () => {
      window.clearTimeout(timeout);
      skeleton.classList.add("hidden");
    }, { once: true });
  }

  function initUserDetail() {
    bindExpirationOverride();
    bindReferrerPicker();
    bindJellyfinPasswordModal();
    bindAccessCollapsibles();
    bindUserMerge();
    bindMonitoringFrameSkeleton();
  }

  document.addEventListener("DOMContentLoaded", initUserDetail);
  document.addEventListener("htmx:load", initUserDetail);
})();
