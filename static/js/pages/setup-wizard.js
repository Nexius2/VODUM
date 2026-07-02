(function vodumSetupWizard() {
  const provider = document.getElementById("wizard_server_type");
  const url = document.getElementById("wizard_server_url");
  const token = document.getElementById("wizard_server_token");

  if (!provider || !url || !token) return;

  function unlock(field) {
    field.readOnly = false;
    if (field === url && field.value.includes("@")) {
      field.value = "";
      token.value = "";
    }
  }

  [url, token].forEach((field) => {
    field.addEventListener("pointerdown", () => unlock(field), { once: true });
    field.addEventListener("focus", () => unlock(field), { once: true });
  });

  function clearCredentialAutofill() {
    if (url.value.includes("@") || (
      url.value && !url.value.startsWith("http://") && !url.value.startsWith("https://")
    )) {
      url.value = "";
      token.value = "";
    }
  }

  [50, 250, 750, 1500].forEach((delay) => window.setTimeout(clearCredentialAutofill, delay));

  function updateExample() {
    url.placeholder = provider.value === "jellyfin"
      ? "http://192.168.1.100:8096"
      : "http://192.168.1.100:32400";
  }

  provider.addEventListener("change", updateExample);
  updateExample();
})();