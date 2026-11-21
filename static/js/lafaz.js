// Live character count for the dictation sheet. Text template comes from the page (i18n), not from this file.
(function () {
  function update(area) {
    var out = document.getElementById("count");
    if (!out || !area.dataset.countTemplate) return;
    out.textContent = area.dataset.countTemplate
      .replace("{n}", String(area.value.length))
      .replace("{max}", String(area.maxLength));
  }
  document.addEventListener("input", function (e) {
    if (e.target && e.target.id === "text") update(e.target);
  });
})();
