(function () {
  const source = document.getElementById("migration-source-server");
  const destination = document.getElementById("migration-destination-server");
  const configNode = document.getElementById("migration-incompatible-servers");
  const messagesNode = document.getElementById("migration-validation-messages");

  if (!source || !destination || !configNode) {
    return;
  }

  let incompatible = {};
  let messages = {};
  try {
    incompatible = JSON.parse(configNode.textContent || "{}");
  } catch (error) {
    incompatible = {};
  }

  try {
    messages = JSON.parse(messagesNode ? messagesNode.textContent || "{}" : "{}");
  } catch (error) {
    messages = {};
  }

  function refreshDestinations() {
    const blocked = new Set((incompatible[source.value] || []).map(String));
    Array.from(destination.options).forEach(function (option) {
      if (option.value) {
        option.disabled = blocked.has(option.value);
      }
    });
    if (blocked.has(destination.value)) {
      destination.value = "";
    }
  }

  source.addEventListener("change", refreshDestinations);
  refreshDestinations();

  const dryRunForm = document.getElementById("migration-dry-run-form");
  const validation = document.getElementById("migration-dry-run-validation");

  function setInvalid(element, invalid) {
    element.classList.toggle("border-amber-500", invalid);
    element.classList.toggle("ring-1", invalid);
    element.classList.toggle("ring-amber-500", invalid);
  }

  function hideValidation() {
    if (validation) {
      validation.classList.add("hidden");
      validation.textContent = "";
    }
    setInvalid(source, false);
    setInvalid(destination, false);
  }

  if (dryRunForm) {
    dryRunForm.addEventListener("submit", function (event) {
      const missingSource = !source.value;
      const missingDestination = !destination.value;
      if (!missingSource && !missingDestination) {
        return;
      }

      event.preventDefault();
      setInvalid(source, missingSource);
      setInvalid(destination, missingDestination);
      if (validation) {
        validation.textContent = missingSource && missingDestination
          ? messages.serversRequired || "Please choose a source server and a destination server."
          : missingSource
            ? messages.sourceRequired || "Please choose a source server."
            : messages.destinationRequired || "Please choose a destination server.";
        validation.classList.remove("hidden");
      }
    });

    source.addEventListener("change", hideValidation);
    destination.addEventListener("change", hideValidation);
  }
})();