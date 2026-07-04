document.addEventListener("DOMContentLoaded", function () {
  const configForm = document.getElementById("comm_config_form");
  const statusEl = document.getElementById("autosave_status");

  function setStatus(text) {
    if (statusEl) {
      statusEl.textContent = text || "";
    }
  }

  const emailToggle = document.querySelector('input[name="mailing_enabled"]');
  const discordToggle = document.querySelector('input[name="discord_enabled"]');
  const emailContent = document.getElementById("email_content");
  const discordContent = document.getElementById("discord_content");

  function syncVisibility() {
    if (emailContent && emailToggle) {
      emailContent.classList.toggle("hidden", !emailToggle.checked);
    }
    if (discordContent && discordToggle) {
      discordContent.classList.toggle("hidden", !discordToggle.checked);
    }
  }

  let saveTimer = null;

  async function saveNow() {
    if (!configForm) {
      return;
    }
    setStatus("Saving...");

    try {
      const response = await fetch(configForm.action, {
        method: "POST",
        headers: { "X-Requested-With": "XMLHttpRequest" },
        body: new FormData(configForm),
        credentials: "same-origin",
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      setStatus("Saved");
      window.setTimeout(function () {
        setStatus("");
      }, 1200);
    } catch (error) {
      setStatus("Save failed");
      window.setTimeout(function () {
        setStatus("");
      }, 2500);
      console.error("Auto-save failed", error);
    }
  }

  function scheduleSave(delayMs) {
    if (!configForm) {
      return;
    }
    if (saveTimer) {
      window.clearTimeout(saveTimer);
    }
    saveTimer = window.setTimeout(saveNow, delayMs);
  }

  if (configForm) {
    configForm.querySelectorAll("input, select, textarea").forEach(function (element) {
      if (element.tagName === "BUTTON") {
        return;
      }

      if (element.type === "password") {
        element.addEventListener("blur", function () {
          scheduleSave(0);
        });
        return;
      }

      element.addEventListener("input", function () {
        scheduleSave(700);
      });
      element.addEventListener("change", function () {
        scheduleSave(0);
      });
    });
  }

  if (emailToggle) {
    emailToggle.addEventListener("change", function () {
      syncVisibility();
      scheduleSave(0);
    });
  }
  if (discordToggle) {
    discordToggle.addEventListener("change", function () {
      syncVisibility();
      scheduleSave(0);
    });
  }
  syncVisibility();

  const providerSelect = document.getElementById("smtp_provider");
  const hostInput = document.getElementById("smtp_host");
  const portInput = document.getElementById("smtp_port");
  const tlsInput = document.getElementById("smtp_tls");

  function showHelp(value) {
    document.querySelectorAll(".smtp-help").forEach(function (element) {
      element.classList.add("hidden");
    });
    const selected = document.getElementById(`help_${value}`);
    const fallback = document.getElementById("help_custom");
    if (selected) {
      selected.classList.remove("hidden");
    } else if (fallback) {
      fallback.classList.remove("hidden");
    }
  }

  function applyProvider(value) {
    if (!hostInput || !portInput) {
      return;
    }
    if (value === "gmail") {
      hostInput.value = "smtp.gmail.com";
      portInput.value = 587;
      if (tlsInput) tlsInput.checked = true;
    } else if (value === "outlook") {
      hostInput.value = "smtp.office365.com";
      portInput.value = 587;
      if (tlsInput) tlsInput.checked = true;
    } else if (value === "yahoo") {
      hostInput.value = "smtp.mail.yahoo.com";
      portInput.value = 587;
      if (tlsInput) tlsInput.checked = true;
    }
  }

  function guessProviderFromHost(host) {
    const normalizedHost = (host || "").trim().toLowerCase();
    if (normalizedHost === "smtp.gmail.com") return "gmail";
    if (normalizedHost === "smtp.office365.com") return "outlook";
    if (normalizedHost === "smtp.mail.yahoo.com") return "yahoo";
    return "custom";
  }

  if (providerSelect) {
    providerSelect.value = guessProviderFromHost(hostInput ? hostInput.value : "");
    showHelp(providerSelect.value);
    providerSelect.addEventListener("change", function () {
      const value = providerSelect.value;
      showHelp(value);
      if (value !== "custom") {
        applyProvider(value);
      }
    });
  }

  const authMethodSelect = document.getElementById("smtp_auth_method");
  const smtpPasswordBlock = document.getElementById("smtp_password_block");
  const smtpOauthBlock = document.getElementById("smtp_oauth_block");

  function syncSmtpAuthBlocks() {
    const useOauth = authMethodSelect && authMethodSelect.value === "oauth2";
    if (smtpPasswordBlock) smtpPasswordBlock.classList.toggle("hidden", useOauth);
    if (smtpOauthBlock) smtpOauthBlock.classList.toggle("hidden", !useOauth);
  }

  if (authMethodSelect) {
    authMethodSelect.addEventListener("change", function () {
      syncSmtpAuthBlocks();
      scheduleSave(0);
    });
    syncSmtpAuthBlocks();
  }

  function bindPasswordToggle(inputId, buttonId) {
    const input = document.getElementById(inputId);
    const button = document.getElementById(buttonId);
    if (!input || !button) {
      return;
    }
    button.addEventListener("click", function () {
      const isPassword = input.type === "password";
      input.type = isPassword ? "text" : "password";
      button.textContent = isPassword ? "Hide" : "Show";
    });
  }

  bindPasswordToggle("smtp_pass", "toggle_pass");
  bindPasswordToggle("smtp_oauth_access_token", "toggle_oauth_token");
  bindPasswordToggle("discord_bot_token", "toggle_discord_token");

  const discordTokenInput = document.getElementById("discord_bot_token");
  const testDiscordForm = document.getElementById("test_discord_form");
  const testDiscordToken = document.getElementById("test_discord_token");
  if (testDiscordForm && testDiscordToken && discordTokenInput) {
    testDiscordForm.addEventListener("submit", function () {
      testDiscordToken.value = discordTokenInput.value || "";
    });
  }

  const orderInput = document.getElementById("notifications_order");
  const orderList = document.getElementById("order_list");
  if (orderInput && orderList) {
    const labels = {
      email: { title: "Email", subtitle: "Email notification" },
      discord: { title: "Discord", subtitle: "Discord DM" },
    };

    function parseOrder(value) {
      const parts = (value || "").split(",").map(function (part) {
        return part.trim();
      }).filter(Boolean);
      const unique = [];
      parts.forEach(function (part) {
        if ((part === "email" || part === "discord") && !unique.includes(part)) {
          unique.push(part);
        }
      });
      if (!unique.includes("email")) unique.push("email");
      if (!unique.includes("discord")) unique.push("discord");
      return unique;
    }

    function renderOrder() {
      const order = parseOrder(orderInput.value);
      orderInput.value = order.join(",");
      orderList.replaceChildren();

      order.forEach(function (key, index) {
        const row = document.createElement("div");
        row.className = "flex items-center justify-between bg-slate-950 border border-slate-800 rounded-xl px-3 py-2";

        const left = document.createElement("div");
        const title = document.createElement("div");
        title.className = "text-sm text-slate-200 font-medium";
        title.textContent = labels[key].title;
        const subtitle = document.createElement("div");
        subtitle.className = "text-[11px] text-slate-500";
        subtitle.textContent = labels[key].subtitle;
        left.appendChild(title);
        left.appendChild(subtitle);

        const right = document.createElement("div");
        right.className = "flex items-center gap-2";

        const up = document.createElement("button");
        up.type = "button";
        up.className = "w-8 h-8 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs";
        up.textContent = "Up";
        up.disabled = index === 0;

        const down = document.createElement("button");
        down.type = "button";
        down.className = "w-10 h-8 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs";
        down.textContent = "Down";
        down.disabled = index === order.length - 1;

        up.addEventListener("click", function () {
          if (index === 0) return;
          const previous = order[index - 1];
          order[index - 1] = order[index];
          order[index] = previous;
          orderInput.value = order.join(",");
          renderOrder();
          scheduleSave(0);
        });

        down.addEventListener("click", function () {
          if (index === order.length - 1) return;
          const next = order[index + 1];
          order[index + 1] = order[index];
          order[index] = next;
          orderInput.value = order.join(",");
          renderOrder();
          scheduleSave(0);
        });

        right.appendChild(up);
        right.appendChild(down);
        row.appendChild(left);
        row.appendChild(right);
        orderList.appendChild(row);
      });
    }

    renderOrder();
  }
});