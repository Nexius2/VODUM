(function communicationsCampaignsPage() {
  function bindDiscordCounter() {
    const body = document.getElementById("campaign_body");
    const counter = document.getElementById("campaign_discord_counter");
    if (!body || !counter) return;

    const refresh = function () {
      const count = body.value.length;
      const parts = Math.max(1, Math.ceil(count / 1900));
      counter.textContent = (counter.dataset.label || "{count} · Discord: {parts}")
        .replace("{count}", String(count))
        .replace("{parts}", String(parts));
      counter.classList.toggle("text-amber-300", parts > 1);
      counter.classList.toggle("text-slate-500", parts <= 1);
    };

    body.addEventListener("input", refresh);
    refresh();
  }

  function getDeleteModal() {
    return document.getElementById("deleteModal");
  }

  function openDeleteModal() {
    const modal = getDeleteModal();
    if (!modal) return;
    modal.classList.remove("hidden");
    modal.classList.add("flex");
  }

  function closeDeleteModal() {
    const modal = getDeleteModal();
    if (!modal) return;
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  }

  function confirmDelete() {
    const form = document.querySelector("form");
    const campaignAction = document.getElementById("campaign_action");
    if (!form || !campaignAction) return;

    campaignAction.value = "delete";

    let hiddenAction = form.querySelector('input[name="action"][type="hidden"]');
    if (!hiddenAction) {
      hiddenAction = document.createElement("input");
      hiddenAction.type = "hidden";
      hiddenAction.name = "action";
      form.appendChild(hiddenAction);
    }
    hiddenAction.value = "delete";
    form.submit();
  }

  document.addEventListener("DOMContentLoaded", function () {
    bindDiscordCounter();
    const testSwitch = document.getElementById("campaign_test_switch");
    const hiddenTest = document.getElementById("is_test");
    if (testSwitch && hiddenTest) {
      testSwitch.addEventListener("change", function () {
        hiddenTest.value = testSwitch.checked ? "1" : "0";
      });
    }

    document.querySelectorAll("[data-campaign-delete-open]").forEach(function (button) {
      button.addEventListener("click", openDeleteModal);
    });
    document.querySelectorAll("[data-campaign-delete-close]").forEach(function (button) {
      button.addEventListener("click", closeDeleteModal);
    });
    document.querySelectorAll("[data-campaign-delete-confirm]").forEach(function (button) {
      button.addEventListener("click", confirmDelete);
    });

    const modal = getDeleteModal();
    if (modal) {
      modal.addEventListener("click", function (event) {
        if (event.target === modal) {
          closeDeleteModal();
        }
      });
    }

    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") {
        closeDeleteModal();
      }
    });
  });
})();
