/* 온보딩: 회원가입/로그인 탭, 이름 짓기 안내 */
(function () {
  "use strict";

  var tabs = document.querySelectorAll('[role="tab"]');
  function select(tab) {
    tabs.forEach(function (t) {
      var on = t === tab;
      t.setAttribute("aria-selected", on ? "true" : "false");
      t.tabIndex = on ? 0 : -1;
      document.getElementById(t.getAttribute("aria-controls")).hidden = !on;
    });
  }
  tabs.forEach(function (tab, i) {
    tab.tabIndex = tab.getAttribute("aria-selected") === "true" ? 0 : -1;
    tab.addEventListener("click", function () { select(tab); });
    tab.addEventListener("keydown", function (e) {
      var next = null;
      if (e.key === "ArrowRight") next = tabs[(i + 1) % tabs.length];
      if (e.key === "ArrowLeft") next = tabs[(i - 1 + tabs.length) % tabs.length];
      if (next) { e.preventDefault(); select(next); next.focus(); }
    });
  });

  // 이름을 비워 두고 보내면 바로 안내한다. (서버에서도 다시 검사)
  var nameForm = document.querySelector("[data-name-form]");
  if (nameForm) {
    var input = nameForm.querySelector('input[name="name"]');
    var error = nameForm.querySelector("[data-name-error]");
    nameForm.addEventListener("submit", function (e) {
      if (!input.value.trim()) {
        e.preventDefault();
        error.textContent = "이름을 지어 주세요.";
        input.setAttribute("aria-invalid", "true");
        input.focus();
      }
    });
    input.addEventListener("input", function () {
      if (input.value.trim()) {
        error.textContent = "";
        input.removeAttribute("aria-invalid");
      }
    });
  }
})();
