/* 공통: CSRF, JSON POST, 창 모양 팝업 */
(function () {
  "use strict";

  function csrfToken() {
    var meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  }

  function postJSON(url, data) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
      body: JSON.stringify(data),
    }).then(function (res) {
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    });
  }

  var dialog = document.getElementById("app-dialog");
  var lastTrigger = null;

  function openDialog(opts) {
    if (!dialog) return;
    var bar = dialog.querySelector(".dialog-bar");
    var body = dialog.querySelector(".dialog-body");
    dialog.querySelector("#app-dialog-title").textContent = opts.title || "";
    bar.style.setProperty("--title", "var(--t-" + (opts.color || "teal") + ")");
    lastTrigger = document.activeElement;

    if (opts.template) {
      body.innerHTML = "";
      body.appendChild(document.importNode(opts.template.content, true));
      dialog.showModal();
      document.dispatchEvent(new CustomEvent("dialog:loaded", { detail: { body: body } }));
      return;
    }
    body.innerHTML = '<p class="dialog-loading">불러오는 중…</p>';
    dialog.showModal();
    fetch(opts.url, { credentials: "same-origin" })
      .then(function (res) {
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.text();
      })
      .then(function (html) {
        body.innerHTML = html;
        document.dispatchEvent(new CustomEvent("dialog:loaded", { detail: { body: body } }));
      })
      .catch(function () {
        body.innerHTML = '<p class="dialog-loading">내용을 불러오지 못했어요. 잠시 후 다시 열어 주세요.</p>';
      });
  }

  function closeDialog() {
    if (dialog && dialog.open) dialog.close();
  }

  if (dialog) {
    dialog.addEventListener("click", function (e) {
      if (e.target === dialog || e.target.closest("[data-dialog-close]")) closeDialog();
    });
    dialog.addEventListener("close", function () {
      if (lastTrigger && document.contains(lastTrigger)) lastTrigger.focus();
    });
  }

  // data-panel-url 또는 data-open-template 이 있는 버튼은 팝업을 연다.
  document.addEventListener("click", function (e) {
    var trigger = e.target.closest("[data-panel-url], [data-open-template]");
    if (!trigger) return;
    e.preventDefault();
    var templateId = trigger.getAttribute("data-open-template");
    openDialog({
      url: trigger.getAttribute("data-panel-url"),
      template: templateId ? document.getElementById(templateId) : null,
      title: trigger.getAttribute("data-panel-title"),
      color: trigger.getAttribute("data-panel-color"),
    });
  });

  // data-focus="입력칸 id" 링크: 그 입력칸으로 이동해서 바로 쓸 수 있게(빈 화면 안내 버튼, "+ 설명 추가")
  document.addEventListener("click", function (e) {
    var link = e.target.closest("[data-focus]");
    if (!link) return;
    var target = document.getElementById(link.getAttribute("data-focus"));
    if (!target) return;
    e.preventDefault();
    target.scrollIntoView({ block: "center" });
    target.focus();
  });

  // data-confirm 이 있는 폼은 보내기 전에 한 번 더 묻는다.
  document.addEventListener("submit", function (e) {
    var form = e.target.closest("form[data-confirm]");
    if (form && !window.confirm(form.getAttribute("data-confirm"))) e.preventDefault();
  });

  window.App = { csrfToken: csrfToken, postJSON: postJSON, openDialog: openDialog, closeDialog: closeDialog };
})();
