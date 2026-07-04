(function subscriptionsGiftsPage() {
  function readConfig() {
    const node = document.getElementById("subscriptions-gifts-config");
    if (!node) return {};
    try {
      return JSON.parse(node.textContent || "{}");
    } catch (error) {
      return {};
    }
  }

  const i18n = readConfig();

  function escapeHtml(value) {
    return (value ?? "").toString().replace(/[&<>"']/g, function (match) {
      return {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
      }[match];
    });
  }

  function normalizeGiftSearch(value) {
    return (value || "")
      .toString()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .trim();
  }

  function showAlert(type, html) {
    const alertBox = document.getElementById("page-alert");
    if (!alertBox) return;
    alertBox.classList.remove("hidden");
    alertBox.className = type === "success"
      ? "mb-6 rounded-lg bg-emerald-500/10 border border-emerald-500 text-emerald-300 px-4 py-3"
      : "mb-6 rounded-lg bg-red-500/10 border border-red-500 text-red-300 px-4 py-3";
    alertBox.innerHTML = html;
    alertBox.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function toggleGiftTarget(mode) {
    document.getElementById("server-select")?.classList.toggle("hidden", mode !== "server");
    document.getElementById("user-select")?.classList.toggle("hidden", mode !== "user");

    ["all", "server", "user"].forEach(function (name) {
      const card = document.getElementById(`card-${name}`);
      if (!card) return;
      card.classList.remove("border-primary", "bg-primary/10");
      card.classList.add("border-slate-800");
    });

    const active = document.getElementById(`card-${mode}`);
    if (active) {
      active.classList.remove("border-slate-800");
      active.classList.add("border-primary", "bg-primary/10");
    }
  }

  function selectDuration(input) {
    document.querySelectorAll(".duration-card").forEach(function (card) {
      card.classList.remove("border-emerald-400", "bg-emerald-400/10");
      card.classList.add("border-slate-800");
    });
    const card = input.closest("label")?.querySelector(".duration-card");
    if (card) {
      card.classList.remove("border-slate-800");
      card.classList.add("border-emerald-400", "bg-emerald-400/10");
    }
  }

  function initGiftUserSearch() {
    const jsonEl = document.getElementById("gift-users-json");
    const input = document.getElementById("gift-user-search");
    const hidden = document.getElementById("gift-user-id");
    const results = document.getElementById("gift-user-results");
    const selected = document.getElementById("gift-user-selected");
    if (!jsonEl || !input || !hidden || !results || !selected) return;

    let users = [];
    try {
      users = JSON.parse(jsonEl.textContent || "[]");
    } catch (error) {
      users = [];
    }

    const prepared = users.map(function (user) {
      const label = `${user.username || ""}${user.email ? ` (${user.email})` : ""}`.trim();
      const details = [user.firstname, user.lastname, user.email, user.second_email, user.discord_name, user.media_search, user.id]
        .filter(Boolean)
        .join(" ");
      return { ...user, label, search: normalizeGiftSearch(`${label} ${details}`) };
    });

    function clearSelection() {
      hidden.value = "";
      selected.classList.add("hidden");
      selected.textContent = "";
    }

    function render(query) {
      const normalizedQuery = normalizeGiftSearch(query);
      results.innerHTML = "";
      if (normalizedQuery.length < 2) {
        results.classList.add("hidden");
        return;
      }

      const matches = prepared.filter(function (user) {
        return user.search.includes(normalizedQuery);
      }).slice(0, 30);

      if (!matches.length) {
        results.innerHTML = `<div class="px-3 py-2 text-sm text-slate-400">${escapeHtml(i18n.noUserFound || "No user found")}</div>`;
        results.classList.remove("hidden");
        return;
      }

      results.innerHTML = matches.map(function (user) {
        const details = [user.firstname, user.lastname, user.second_email, user.discord_name].filter(Boolean).join(" - ");
        return `
          <button type="button"
                  class="gift-user-result w-full text-left px-3 py-2 hover:bg-primary/25 hover:ring-1 hover:ring-primary/50 border-b border-slate-800 last:border-b-0 transition-all"
                  data-user-id="${escapeHtml(user.id)}"
                  data-user-label="${escapeHtml(user.label)}">
            <div class="text-sm text-slate-100">${escapeHtml(user.label)}</div>
            <div class="text-xs text-slate-400">${escapeHtml(details)}</div>
          </button>
        `;
      }).join("");
      results.classList.remove("hidden");

      results.querySelectorAll(".gift-user-result").forEach(function (button) {
        button.addEventListener("click", function () {
          hidden.value = button.dataset.userId || "";
          input.value = button.dataset.userLabel || "";
          selected.textContent = button.dataset.userLabel || "";
          selected.classList.remove("hidden");
          results.classList.add("hidden");
        });
      });
    }

    input.addEventListener("input", function () {
      clearSelection();
      render(input.value);
    });
    input.addEventListener("focus", function () {
      render(input.value);
    });
    document.addEventListener("click", function (event) {
      if (!event.target.closest("#user-select")) {
        results.classList.add("hidden");
      }
    });
  }

  function closeGiftModal() {
    document.getElementById("gift-modal")?.classList.add("hidden");
  }

  function openGiftRunModal(run) {
    const modal = document.getElementById("gift-modal");
    if (!modal) return;

    let scope = i18n.giftHistoryScopeAll || "All users";
    if (run.target_type === "server") {
      scope = `${i18n.giftHistoryScopeServer || "Server users"}${run.server_name ? `: ${run.server_name}` : ""}`;
    } else if (run.target_type === "user") {
      scope = `${i18n.giftHistoryUser || "User"}${run.target_username ? `: ${run.target_username}` : ""}`;
    }

    const setText = function (id, value) {
      const element = document.getElementById(id);
      if (element) element.textContent = value || "-";
    };

    setText("gift-modal-title", scope);
    setText("gift-modal-subtitle", window.vodumFormatDateTime ? window.vodumFormatDateTime(run.created_at || "") : run.created_at || "");
    setText("gift-modal-target", scope);
    setText("gift-modal-duration", `+${run.days_added} ${i18n.giftHistoryDays || "days"}`);
    setText("gift-modal-server", run.server_name || "-");
    setText("gift-modal-reason", run.reason || "-");
    setText("gift-modal-users-count", `${run.users_updated || 0}`);

    const usersBox = document.getElementById("gift-modal-users");
    const usersLabel = document.getElementById("gift-modal-users-label");
    if (usersBox) usersBox.innerHTML = `<div class="text-slate-400 text-sm">${escapeHtml(i18n.loading || "Loading")}...</div>`;
    if (usersLabel) usersLabel.textContent = "";
    modal.classList.remove("hidden");

    fetch(`/api/subscriptions/gifts/${run.id}`, { cache: "no-store" })
      .then(function (response) { return response.json(); })
      .then(function (response) {
        if (!response || response.status !== "ok") {
          if (usersBox) usersBox.innerHTML = `<div class="text-red-300 text-sm">${escapeHtml(response?.error || i18n.unknownError || "Unknown error")}</div>`;
          return;
        }
        const users = response.users || [];
        if (!usersBox) return;
        if (usersLabel) usersLabel.textContent = `${users.length} ${i18n.giftHistoryUser || "users"}`;
        if (!users.length) {
          usersBox.innerHTML = `<div class="text-slate-400 text-sm">${escapeHtml(i18n.noUserFound || "No user found")}</div>`;
          return;
        }
        usersBox.innerHTML = users.map(function (user) {
          return `<div class="px-2 py-1 rounded-lg bg-slate-950/40 border border-slate-800">${escapeHtml(user.username)}</div>`;
        }).join("");
      })
      .catch(function () {
        if (usersBox) usersBox.innerHTML = `<div class="text-red-300 text-sm">${escapeHtml(i18n.requestFailed || "Request failed")}</div>`;
      });
  }

  function renderGiftHistory(items) {
    const box = document.getElementById("gift-history");
    if (!box) return;

    if (!items || items.length === 0) {
      box.className = "text-sm text-slate-200";
      box.innerHTML = `<div class="text-slate-400">${escapeHtml(i18n.giftHistoryEmpty || "No gifts yet")}</div>`;
      return;
    }

    box.className = "text-sm text-slate-200 max-h-[520px] overflow-auto rounded-xl border border-slate-800 divide-y divide-slate-800";
    box.innerHTML = items.map(function (run, index) {
      let scope = i18n.giftHistoryScopeAll || "All users";
      if (run.target_type === "server") {
        scope = `${i18n.giftHistoryScopeServer || "Server users"}${run.server_name ? `: ${escapeHtml(run.server_name)}` : ""}`;
      } else if (run.target_type === "user") {
        scope = `${i18n.giftHistoryUser || "User"}${run.target_username ? `: ${escapeHtml(run.target_username)}` : ""}`;
      }
      const duration = `+${run.days_added} ${i18n.giftHistoryDays || "days"}`;
      const comment = run.reason ? escapeHtml(run.reason) : "-";
      const created = run.created_at && window.vodumFormatDateTime ? escapeHtml(window.vodumFormatDateTime(run.created_at)) : "";
      const usersCount = `${run.users_updated || 0} ${i18n.giftHistoryUser || "users"}`;
      return `
        <button type="button" class="gift-row w-full text-left px-4 py-3 bg-slate-950/30 hover:bg-slate-950/60 transition" data-run-index="${index}">
          <div class="flex items-start justify-between gap-4">
            <div class="min-w-0">
              <div class="flex items-center gap-2 flex-wrap">
                <span class="font-semibold text-slate-100">${scope}</span>
                <span class="text-xs text-slate-500">-</span>
                <span class="font-medium text-slate-200">${escapeHtml(duration)}</span>
                <span class="text-xs text-slate-500">-</span>
                <span class="text-xs text-slate-400">${escapeHtml(usersCount)}</span>
              </div>
              <div class="text-sm text-slate-300 mt-1 truncate">${comment}</div>
            </div>
            <div class="shrink-0 text-xs text-slate-400">${created}</div>
          </div>
        </button>
      `;
    }).join("");

    box.querySelectorAll(".gift-row").forEach(function (button) {
      button.addEventListener("click", function () {
        const run = items[Number(button.dataset.runIndex)];
        if (run) openGiftRunModal(run);
      });
    });
  }

  function loadGiftHistory() {
    const box = document.getElementById("gift-history");
    if (!box) return;

    fetch("/api/subscriptions/gifts", { cache: "no-store" })
      .then(function (response) { return response.json(); })
      .then(function (response) {
        if (!response || response.status !== "ok") {
          box.className = "text-sm text-slate-200";
          box.innerHTML = `<div class="text-red-300">${escapeHtml(response?.error || i18n.unknownError || "Unknown error")}</div>`;
          return;
        }
        renderGiftHistory(response.items || []);
      })
      .catch(function (error) {
        console.error("Gift history fetch error:", error);
        box.className = "text-sm text-slate-200";
        box.innerHTML = `<div class="text-red-300">${escapeHtml(i18n.requestFailed || "Request failed")}</div>`;
      });
  }

  function submitGift(form) {
    fetch(form.action, { method: "POST", body: new FormData(form), credentials: "same-origin" })
      .then(function (response) { return response.json(); })
      .then(function (response) {
        if (response.status === "ok") {
          showAlert("success", `<strong>${response.users_updated}</strong> ${escapeHtml(i18n.usersUpdated || "users updated")} (+${response.days_added} ${escapeHtml(i18n.daysAdded || "days added")})`);
          loadGiftHistory();
        } else {
          showAlert("error", escapeHtml(response.error || i18n.unknownError || "Unknown error"));
        }
      })
      .catch(function () {
        showAlert("error", escapeHtml(i18n.requestFailed || "Request failed"));
      });
  }

  function startGiftHistoryLive() {
    loadGiftHistory();
    window.setInterval(function () {
      if (!document.hidden) loadGiftHistory();
    }, 5000);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-gift-target-option]").forEach(function (input) {
      input.addEventListener("change", function () {
        toggleGiftTarget(input.value || input.dataset.giftTargetOption);
      });
    });
    document.querySelectorAll("[data-gift-duration-option]").forEach(function (input) {
      input.addEventListener("change", function () { selectDuration(input); });
    });
    document.querySelectorAll("[data-gift-modal-close]").forEach(function (button) {
      button.addEventListener("click", closeGiftModal);
    });
    document.querySelector("[data-gift-modal]")?.addEventListener("click", closeGiftModal);
    document.querySelector("[data-gift-modal-panel]")?.addEventListener("click", function (event) {
      event.stopPropagation();
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") closeGiftModal();
    });
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) loadGiftHistory();
    });

    const form = document.querySelector("[data-gift-form]");
    if (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        submitGift(form);
      });
    }

    initGiftUserSearch();
    toggleGiftTarget("all");
    startGiftHistoryLive();
  });
})();