/* 할 일 체크 저장: 자동 할 일(data-todo-key) / 내가 넣은 할 일(data-task-url) */
(function () {
  "use strict";

  var note = document.querySelector("[data-todo-note]");
  var autoList = document.querySelector("[data-todo-url]");
  var autoUrl = autoList ? autoList.getAttribute("data-todo-url") : null;

  function fail(box) {
    box.checked = !box.checked;
    if (note) note.textContent = "저장하지 못했어요. 다시 눌러 주세요.";
  }

  document.addEventListener("change", function (e) {
    var box = e.target;
    if (box.hasAttribute && box.hasAttribute("data-todo-key") && autoUrl) {
      App.postJSON(autoUrl, { key: box.getAttribute("data-todo-key"), checked: box.checked })
        .then(function () { if (note) note.textContent = ""; })
        .catch(function () { fail(box); });
    } else if (box.hasAttribute && box.hasAttribute("data-task-url")) {
      var item = box.closest(".task-item");
      App.postJSON(box.getAttribute("data-task-url"), { done: box.checked })
        .then(function (res) {
          if (item) item.classList.toggle("is-done", res.done);
          if (note) note.textContent = "";
        })
        .catch(function () { fail(box); });
    }
  });
})();
