(function vodumLogsFilters() {
  const form = document.getElementById("logsFilterForm");
  const searchInput = document.getElementById("searchInput");
  const levelSelect = document.getElementById("levelSelect");
  const pageInput = document.getElementById("pageInput");

  if (!form || !searchInput || !levelSelect || !pageInput) return;

  let timer = null;
  const debounceMs = 350;

  function submitAndResetPage() {
    pageInput.value = "1";
    form.submit();
  }

  searchInput.addEventListener("input", () => {
    window.clearTimeout(timer);
    timer = window.setTimeout(submitAndResetPage, debounceMs);
  });

  levelSelect.addEventListener("change", submitAndResetPage);

  searchInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      window.clearTimeout(timer);
      submitAndResetPage();
    }
  });
})();