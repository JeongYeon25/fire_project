/* 홈 화면 식물 상담소.
   - 화분을 고르면 그 화분의 대화를 불러온다(GET /plants/<pk>/chat/history/).
   - 질문은 보낼 때의 화분에 묶는다. 답이 왔을 때 다른 화분을 보고 있으면 화면에 붙이지 않는다
     (서버에는 그 화분 대화로 저장돼 있어서, 돌아가면 기록에 보인다).
   - 마지막으로 고른 화분은 이 브라우저에만 기억한다(localStorage, DB 변경 없음). 주소의 ?ask=가 있으면 그게 먼저다.
   - 답변은 HTML로 해석하지 않는다 — 모든 글은 textContent로만 넣는다(HTML 문자열 삽입 금지). */
(function () {
  "use strict";

  var root = document.querySelector("[data-chat]");
  if (!root) return;

  var MAX_SHOWN = 10;
  var radios = Array.prototype.slice.call(root.querySelectorAll('input[name="counsel-plant"]'));
  var log = root.querySelector("[data-chat-log]");
  var form = root.querySelector("[data-chat-form]");
  var input = root.querySelector("[data-chat-input]");
  var send = root.querySelector("[data-chat-send]");
  var count = root.querySelector("[data-chat-count]");
  var error = root.querySelector("[data-chat-error]");
  var empty = root.querySelector("[data-chat-empty]");
  var tools = root.querySelector("[data-chat-tools]");
  var remaining = root.querySelector("[data-chat-remaining]");
  var note = root.querySelector("[data-chat-note]");
  var suggestBox = root.querySelector("[data-chat-suggestions]");
  var storeKey = root.getAttribute("data-store-key");
  var max = parseInt(input.getAttribute("maxlength"), 10);

  var pending = {};      // 화분 pk → 보내는 중
  var historySeq = 0;    // 늦게 온 이전 기록 응답을 버리기 위한 번호

  function current() {
    var r = radios.filter(function (x) { return x.checked; })[0];
    return r || radios[0];
  }
  function currentPk() { return current().value; }

  function el(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function bubble(role, text, at, isError) {
    var li = el("li", "chat-msg chat-msg--" + role + (isError ? " chat-msg--error" : ""));
    li.appendChild(el("span", "chat-msg__who", (role === "user" ? "나" : "AI") + (at ? " · " + at : "")));
    li.appendChild(el("p", "chat-msg__text", text));
    return li;
  }

  function loadingBubble() {
    var li = el("li", "chat-msg chat-msg--assistant chat-msg--loading");
    li.setAttribute("data-chat-loading", "");
    li.appendChild(el("span", "chat-msg__who", "AI"));
    var p = el("p", "chat-msg__text chat-dots", "생각하는 중");
    p.appendChild(el("span", "chat-dots__anim", ""));
    li.appendChild(p);
    return li;
  }

  function request(url, method, payload) {
    var opts = { method: method, credentials: "same-origin", headers: { Accept: "application/json" } };
    if (method === "POST") {
      opts.headers["Content-Type"] = "application/json";
      opts.headers["X-CSRFToken"] = window.App.csrfToken();
      opts.body = JSON.stringify(payload || {});
    }
    return fetch(url, opts).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (data) { return { ok: res.ok, data: data }; });
    });
  }

  function save(pk) {
    try { window.localStorage.setItem(storeKey, pk); } catch (e) { /* 저장소를 못 쓰면 기억하지 않는다 */ }
  }
  function saved() {
    try { return window.localStorage.getItem(storeKey); } catch (e) { return null; }
  }

  function updateCount() { count.textContent = input.value.length + "/" + max; }
  function updateBusy() {
    var busy = !!pending[currentPk()];
    send.disabled = busy;
    root.querySelectorAll("[data-chat-suggest]").forEach(function (b) { b.disabled = busy; });
  }
  function showRemaining(n) {
    if (!remaining) return;
    remaining.hidden = n == null;
    if (n != null) remaining.textContent = "오늘 남은 질문 " + n + "회";
  }
  function trim() { while (log.children.length > MAX_SHOWN) log.removeChild(log.firstElementChild); }
  function refreshEmpty() {
    var has = log.children.length > 0;
    empty.hidden = has;
    tools.hidden = !has;
  }

  function renderSuggestions(list) {
    while (suggestBox.firstChild) suggestBox.removeChild(suggestBox.firstChild);
    (list || []).forEach(function (q) {
      var b = el("button", "chip", q);
      b.type = "button";
      b.setAttribute("data-chat-suggest", "");
      suggestBox.appendChild(b);
    });
  }

  function render(data) {
    while (log.firstChild) log.removeChild(log.firstChild);
    (data.messages || []).forEach(function (m) { log.appendChild(bubble(m.role, m.content, m.at, m.is_error)); });
    if (pending[String(data.plant)]) log.appendChild(loadingBubble());
    note.textContent = data.note || "";
    note.hidden = !data.note;
    renderSuggestions(data.suggestions);
    showRemaining(data.remaining);
    refreshEmpty();
    updateBusy();
    log.scrollTop = log.scrollHeight;
  }

  function select(radio) {
    radio.checked = true;
    save(radio.value);
    error.textContent = "";
    var seq = ++historySeq;
    var pk = radio.value;
    log.setAttribute("aria-busy", "true");
    request(radio.getAttribute("data-history-url"), "GET").then(function (res) {
      if (seq !== historySeq || currentPk() !== pk) return; // 그 사이 다른 화분을 골랐다
      log.removeAttribute("aria-busy");
      if (!res.ok) { error.textContent = "대화를 불러오지 못했어요. 잠시 후 다시 해 주세요."; return; }
      render(res.data);
    }).catch(function () {
      if (seq === historySeq) error.textContent = "대화를 불러오지 못했어요. 잠시 후 다시 해 주세요.";
    });
  }

  radios.forEach(function (r) {
    r.addEventListener("change", function () { if (r.checked) select(r); });
  });

  // 처음 고를 화분: 주소의 ?ask=가 있으면 서버가 고른 것, 없으면 이 브라우저에 기억한 화분(내 화분일 때만)
  if (!root.getAttribute("data-from-url")) {
    var remembered = saved();
    var match = radios.filter(function (r) { return r.value === remembered; })[0];
    if (match && !match.checked) select(match);
  } else {
    save(currentPk());
  }

  input.addEventListener("input", updateCount);
  updateCount();

  // 모바일: 키보드가 올라와도 입력창이 보이게
  function keepInputVisible() { input.scrollIntoView({ block: "center", behavior: "smooth" }); }
  input.addEventListener("focus", function () { setTimeout(keepInputVisible, 300); });
  if (window.visualViewport) {
    window.visualViewport.addEventListener("resize", function () {
      if (document.activeElement === input) keepInputVisible();
    });
  }

  suggestBox.addEventListener("click", function (e) {
    var b = e.target.closest("[data-chat-suggest]");
    if (!b || b.disabled) return;
    input.value = b.textContent;
    updateCount();
    if (form.requestSubmit) form.requestSubmit();
    else form.dispatchEvent(new Event("submit", { cancelable: true }));
  });

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var radio = current();
    var pk = radio.value; // 이 질문은 보낼 때의 화분에 묶는다
    if (pending[pk]) return;
    var text = input.value.trim();
    error.textContent = "";
    if (!text) { error.textContent = "질문을 적어 주세요."; input.focus(); return; }
    if (text.length > max) { error.textContent = "질문은 " + max + "자까지 적을 수 있어요."; return; }

    var mine = bubble("user", text, "");
    var loading = loadingBubble();
    log.appendChild(mine);
    log.appendChild(loading);
    refreshEmpty();
    pending[pk] = true;
    updateBusy();
    log.scrollTop = log.scrollHeight;

    request(radio.getAttribute("data-ask-url"), "POST", { question: text })
      .then(function (res) {
        var here = currentPk() === pk;
        if (loading.parentNode) loading.parentNode.removeChild(loading);
        if (!res.ok) {
          if (mine.parentNode) mine.parentNode.removeChild(mine);
          if (here) {
            error.textContent = res.data.error || "질문을 보내지 못했어요. 잠시 후 다시 해 주세요.";
            showRemaining(res.data.remaining);
            refreshEmpty();
          }
          return;
        }
        showRemaining(res.data.remaining);
        if (!here || String(res.data.plant) !== pk) return; // 다른 화분을 보고 있으면 붙이지 않는다
        if (mine.parentNode) {
          mine.querySelector(".chat-msg__who").textContent = "나 · " + res.data.question.at;
        } else {
          // 기다리는 동안 화분을 바꿨다 돌아와 기록을 다시 그렸으면 질문은 이미 기록에 있다
          var stale = log.querySelector("[data-chat-loading]");
          if (stale) log.removeChild(stale);
        }
        var a = res.data.answer;
        log.appendChild(bubble("assistant", a.content, a.at, a.is_error));
        input.value = "";
        updateCount();
        trim();
        refreshEmpty();
      })
      .catch(function () {
        if (loading.parentNode) loading.parentNode.removeChild(loading);
        if (mine.parentNode) mine.parentNode.removeChild(mine);
        if (currentPk() === pk) error.textContent = "연결이 끊겼어요. 잠시 후 다시 해 주세요.";
        refreshEmpty();
      })
      .then(function () {
        delete pending[pk];
        if (currentPk() === pk) {
          var stale = log.querySelector("[data-chat-loading]");
          if (stale) log.removeChild(stale);
        }
        updateBusy();
        log.scrollTop = log.scrollHeight;
      });
  });

  root.querySelector("[data-chat-clear]").addEventListener("click", function () {
    var radio = current();
    var pk = radio.value;
    if (!window.confirm("이 화분과 나눈 상담소 대화를 모두 지울까요? 지운 대화는 되돌릴 수 없어요.")) return;
    request(radio.getAttribute("data-clear-url"), "POST").then(function (res) {
      if (currentPk() !== pk) return;
      if (!res.ok) { error.textContent = "대화를 지우지 못했어요. 잠시 후 다시 해 주세요."; return; }
      while (log.firstChild) log.removeChild(log.firstChild);
      refreshEmpty();
    });
  });
})();
