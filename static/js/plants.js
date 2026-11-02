/* 내 식물: 상세 팝업 안의 항목 칩·게이지·비교 그래프 */
(function () {
  "use strict";

  document.addEventListener("dialog:loaded", function (e) {
    var body = e.detail.body;
    var holder = body.querySelector("[data-mini-graph]");
    var graph = null;
    if (holder && window.PlantGraph) {
      graph = PlantGraph.create(holder, { height: 220 });
      graph.load({
        metric: holder.getAttribute("data-metric"),
        range: holder.getAttribute("data-range"),
        plants: holder.getAttribute("data-plants"),
      });
    }

    body.querySelectorAll("[data-metric-chip]").forEach(function (chip) {
      chip.addEventListener("click", function () {
        var metric = chip.getAttribute("data-metric-chip");
        body.querySelectorAll("[data-metric-chip]").forEach(function (c) {
          c.setAttribute("aria-pressed", c === chip ? "true" : "false");
        });
        body.querySelectorAll("[data-metric-gauge]").forEach(function (g) {
          g.hidden = g.getAttribute("data-metric-gauge") !== metric;
        });
        if (graph) graph.load({ metric: metric });
      });
    });
  });

  // 화분 이름 폼(새 식물 추가, 작물 바꾸기 / 이름 바꾸기): 작물에 맞는 입력 예시, 빈 이름 안내, 작물 변경 확인
  function exampleFor(form) {
    var radio = form.querySelector('input[name="crop"]:checked');
    if (radio) return radio.getAttribute("data-example");
    var select = form.querySelector('select[name="crop"]');
    return select ? select.options[select.selectedIndex].getAttribute("data-example") : "";
  }

  document.addEventListener("change", function (e) {
    var form = e.target.closest("form[data-plant-name-form]");
    if (!form || e.target.name !== "crop") return;
    var example = exampleFor(form);
    if (example) form.querySelector('input[name="name"]').placeholder = "예: " + example;
  });

  document.addEventListener("input", function (e) {
    var form = e.target.closest("form[data-plant-name-form]");
    if (!form || e.target.name !== "name" || !e.target.value.trim()) return;
    form.querySelector("[data-name-error]").textContent = "";
    e.target.removeAttribute("aria-invalid");
  });

  document.addEventListener("submit", function (e) {
    var form = e.target.closest("form[data-plant-name-form]");
    if (!form) return;
    var input = form.querySelector('input[name="name"]');
    if (!input.value.trim()) {
      e.preventDefault();
      form.querySelector("[data-name-error]").textContent = "이름을 지어 주세요.";
      input.setAttribute("aria-invalid", "true");
      input.focus();
      return;
    }
    var select = form.querySelector("select[data-initial]");
    var message = form.getAttribute("data-crop-confirm");
    if (select && message && select.value !== select.getAttribute("data-initial") && !window.confirm(message)) {
      e.preventDefault();
    }
  });

  // ?add=1 로 들어오면 새 식물 추가 팝업을 바로 연다(빈 화면 안내의 [새 식물 추가] 버튼).
  if (/[?&]add=1/.test(location.search)) {
    var addCard = document.querySelector('[data-open-template="add-plant-template"]');
    if (addCard) addCard.click();
  }
  // ?upload=1 로 들어오면 사진 올리기 팝업을 바로 연다.
  if (/[?&]upload=1/.test(location.search)) {
    var uploadBtn = document.querySelector('[data-open-template="photo-upload-template"]');
    if (uploadBtn) uploadBtn.click();
  }

  // ?open=<id> 로 들어오면 그 화분 팝업을 바로 연다.
  var grid = document.querySelector("[data-open-id]");
  var openId = grid && grid.getAttribute("data-open-id");
  if (openId) {
    var btn = document.querySelector('[data-plant-id="' + openId + '"]');
    if (btn) btn.click();
  }
})();
