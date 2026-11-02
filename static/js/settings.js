/* 알림 설정: 바꿀 때마다 저장 */
(function () {
  "use strict";

  var section = document.querySelector("[data-settings]");
  if (!section) return;
  var url = section.getAttribute("data-url");
  var note = section.querySelector("[data-save-note]");

  section.addEventListener("change", function (e) {
    var input = e.target.closest("[data-field]");
    if (!input) return;
    var field = input.getAttribute("data-field");
    var value = input.type === "checkbox" ? input.checked : input.value;
    App.postJSON(url, { field: field, value: value })
      .then(function () {
        note.textContent = "저장했어요.";
      })
      .catch(function () {
        if (input.type === "checkbox") input.checked = !input.checked;
        note.textContent = "저장하지 못했어요. 다시 시도해 주세요.";
      });
  });
})();
