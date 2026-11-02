/* 직접 그리는 SVG 센서 그래프
 * PlantGraph.create(holder, {height, table}) -> {load(params)}
 * params: {metric, range, plants}  → GET holder.dataset.url
 */
(function () {
  "use strict";

  var NS = "http://www.w3.org/2000/svg";
  var PAD = { left: 54, right: 18, top: 18, bottom: 30 };

  function el(name, attrs, parent) {
    var node = document.createElementNS(NS, name);
    for (var k in attrs) node.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(node);
    return node;
  }

  function h(tag, cls, text) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  // 서버가 보낸 서울 시각 문자열을 그대로 읽어 표시한다.
  function fmtTime(iso) {
    return +iso.slice(5, 7) + "/" + +iso.slice(8, 10) + " " + iso.slice(11, 16);
  }
  function fmtDay(iso) {
    return +iso.slice(5, 7) + "/" + +iso.slice(8, 10);
  }

  function fmtVal(v, digits) {
    // 천 단위 쉼표 (조도 3,421 lux)
    return v == null ? "–" : Number(v).toLocaleString("ko-KR", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  function niceRange(data) {
    if (data.metric === "moisture" || data.metric === "humidity") return [0, 100];
    var lo = Infinity, hi = -Infinity;
    data.series.forEach(function (s) {
      s.values.forEach(function (v) {
        if (v == null) return;
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      });
    });
    data.thresholds.forEach(function (t) {
      if (t.value < lo) lo = t.value;
      if (t.value > hi) hi = t.value;
    });
    if (!isFinite(lo)) return [0, 1];
    if (data.metric === "light") return [0, Math.max(10, Math.ceil((hi * 1.1) / 5) * 5)];
    lo = Math.floor((lo - 2) / 5) * 5;
    hi = Math.ceil((hi + 2) / 5) * 5;
    return [lo, hi];
  }

  function tickIndices(times, range) {
    var out = [];
    if (range === "today") {
      times.forEach(function (t, i) {
        var hh = +t.slice(11, 13), mm = +t.slice(14, 16);
        if (mm === 0 && hh % 3 === 0) out.push(i);
      });
      return out;
    }
    var prev = null;
    times.forEach(function (t, i) {
      var d = t.slice(0, 10);
      if (d !== prev) out.push(i);
      prev = d;
    });
    if (out.length > 9) out = out.filter(function (_, k) { return k % 2 === 0; });
    return out;
  }

  function create(holder, opts) {
    opts = opts || {};
    var baseHeight = opts.height || 320;
    var desktop = window.matchMedia("(min-width: 1100px)");
    var height = baseHeight;
    var url = holder.getAttribute("data-url");
    var data = null;
    var params = {};
    var cursor = null;

    holder.innerHTML = "";
    var box = h("div", "graph-box");
    box.tabIndex = 0;
    box.setAttribute("role", "group");
    var tip = h("div", "graph-tip");
    tip.hidden = true;
    var live = h("p", "sr-only");
    live.setAttribute("aria-live", "polite");
    var legend = h("ul", "legend");
    holder.appendChild(box);
    holder.appendChild(legend);
    holder.appendChild(live);
    var tableWrap = null;
    if (opts.table) {
      tableWrap = h("details", "data-table-wrap");
      tableWrap.appendChild(h("summary", "", "표로 보기"));
      holder.appendChild(tableWrap);
    }

    var geom = null;

    function render() {
      box.innerHTML = "";
      box.appendChild(tip);
      tip.hidden = true;
      legend.innerHTML = "";
      if (!data) return;
      box.setAttribute("aria-label", data.label + " 그래프. 왼쪽·오른쪽 방향키로 시각별 값을 확인할 수 있어요.");

      if (!data.times.length) {
        var empty = h("div", "graph-empty");
        empty.appendChild(h("p", "", "이 기간에는 측정값이 없어요."));
        var action = opts.emptyAction;
        if (action && (!action.when || action.when(data))) {
          var btn = h("button", "btn btn--small btn--ghost", action.label);
          btn.type = "button";
          btn.addEventListener("click", action.run);
          empty.appendChild(btn);
        }
        box.appendChild(empty);
        renderTable();
        return;
      }

      // 넓은 화면에서는 그래프 높이를 220px 이하로
      height = desktop.matches ? Math.min(baseHeight, 220) : baseHeight;
      var width = Math.max(300, box.clientWidth - 16);
      var svg = el("svg", { class: "graph-svg", viewBox: "0 0 " + width + " " + height, width: width, height: height, "aria-hidden": "true" }, box);
      var times = data.times.map(function (t) { return Date.parse(t); });
      var t0 = times[0], t1 = times[times.length - 1];
      if (t1 === t0) t1 = t0 + 3600 * 1000;
      var yr = niceRange(data);
      var iw = width - PAD.left - PAD.right, ih = height - PAD.top - PAD.bottom;
      var X = function (t) { return PAD.left + ((t - t0) / (t1 - t0)) * iw; };
      var Y = function (v) { return PAD.top + (1 - (v - yr[0]) / (yr[1] - yr[0])) * ih; };
      geom = { times: times, X: X, Y: Y, svg: svg, width: width };

      // 점선 격자 + y축 눈금
      for (var g = 0; g <= 4; g++) {
        var v = yr[0] + ((yr[1] - yr[0]) * g) / 4;
        var y = Y(v);
        el("line", { class: "grid-line", x1: PAD.left, x2: width - PAD.right, y1: y, y2: y }, svg);
        var label = el("text", { x: PAD.left - 6, y: y + 4, "text-anchor": "end" }, svg);
        label.textContent = (Math.round(v * 10) / 10).toLocaleString("ko-KR");
      }
      // x축 눈금
      var lastTickX = -Infinity;
      tickIndices(data.times, data.range).forEach(function (i) {
        var x = X(times[i]);
        if (x - lastTickX < 36) return; // 날짜 글자가 겹치면 건너뛴다
        lastTickX = x;
        el("line", { class: "grid-line", x1: x, x2: x, y1: PAD.top, y2: PAD.top + ih }, svg);
        var t = el("text", { x: x, y: height - 8, "text-anchor": "middle" }, svg);
        t.textContent = data.range === "today" ? data.times[i].slice(11, 16) : fmtDay(data.times[i]);
      });
      el("line", { class: "axis", x1: PAD.left, x2: width - PAD.right, y1: PAD.top + ih, y2: PAD.top + ih }, svg);
      el("line", { class: "axis", x1: PAD.left, x2: PAD.left, y1: PAD.top, y2: PAD.top + ih }, svg);
      var unit = el("text", { x: PAD.left - 6, y: 10, "text-anchor": "end" }, svg);
      unit.textContent = data.unit;

      // 세로선: 실험 조건 변경, 조도 센서 교체(조도 그래프만)
      function marker(iso, mod, text, labelY) {
        if (!iso) return;
        var tc = Date.parse(iso);
        if (tc < t0 || tc > t1) return;
        var xc = X(tc);
        el("line", { class: "changed" + mod, x1: xc, x2: xc, y1: PAD.top, y2: PAD.top + ih }, svg);
        // 오른쪽 끝 가까이면 글자를 선 왼쪽에 쓴다
        var nearRight = xc > width - PAD.right - 140;
        var lc = el("text", {
          class: "changed-label" + (mod ? " changed-label--sensor" : ""),
          x: nearRight ? xc - 4 : xc + 4, y: labelY, "text-anchor": nearRight ? "end" : "start"
        }, svg);
        lc.textContent = text;
      }
      marker(data.condition_changed_at, "", "조건 변경", PAD.top + 10);
      // 위쪽은 기준선 글자와 겹치기 쉬워서 아래쪽에 쓴다
      marker(data.light_unit_changed_at, " changed--sensor", "조도 센서 교체(lux)", PAD.top + ih - 6);
      // 기준선
      var usedLabelY = [];
      data.thresholds.forEach(function (th) {
        if (th.value < yr[0] || th.value > yr[1]) return;
        var yt = Y(th.value);
        el("line", { class: "threshold", x1: PAD.left, x2: width - PAD.right, y1: yt, y2: yt }, svg);
        // 기준선이 가까우면(작물이 여러 개) 글자가 겹치지 않게 아래로 비켜 쓴다.
        var ly = yt - 5;
        while (usedLabelY.some(function (u) { return Math.abs(u - ly) < 13; })) ly += 13;
        usedLabelY.push(ly);
        var lt = el("text", { class: "threshold-label", x: width - PAD.right - 2, y: ly, "text-anchor": "end" }, svg);
        lt.textContent = th.label;
      });

      // 시리즈: 굵고 각진 선 + 마지막 값 네모 점
      data.series.forEach(function (s) {
        var d = "", pen = false, last = null;
        s.values.forEach(function (v, i) {
          if (v == null) { pen = false; return; }
          d += (pen ? "L" : "M") + X(times[i]).toFixed(1) + " " + Y(v).toFixed(1);
          pen = true;
          last = i;
        });
        if (!d) return;
        el("path", { class: "series", d: d, stroke: s.color }, svg);
        if (last != null) {
          el("rect", { class: "last-dot", x: X(times[last]) - 5, y: Y(s.values[last]) - 5, width: 10, height: 10, fill: s.color }, svg);
        }
      });

      cursor = el("line", { class: "cursor", y1: PAD.top, y2: PAD.top + ih, x1: -10, x2: -10, visibility: "hidden" }, svg);
      var overlay = el("rect", { x: PAD.left, y: PAD.top, width: iw, height: ih, fill: "transparent" }, svg);
      overlay.addEventListener("mousemove", function (e) {
        var rect = svg.getBoundingClientRect();
        var px = ((e.clientX - rect.left) / rect.width) * width;
        showIndex(nearest(px));
      });
      overlay.addEventListener("mouseleave", hideCursor);

      // 범례
      data.series.forEach(function (s) {
        var li = h("li");
        var sw = h("span", "legend__line");
        sw.style.setProperty("--c", s.color);
        li.appendChild(sw);
        li.appendChild(document.createTextNode(s.label));
        legend.appendChild(li);
      });
      data.thresholds.forEach(function (th) {
        var li = h("li");
        var sw = h("span", "legend__dash");
        sw.style.setProperty("--c", "#e5533d");
        li.appendChild(sw);
        li.appendChild(document.createTextNode(th.label));
        legend.appendChild(li);
      });
      if (data.condition_changed_at) {
        var li = h("li");
        var sw = h("span", "legend__dash");
        sw.style.setProperty("--c", "var(--t-purple)");
        li.appendChild(sw);
        li.appendChild(document.createTextNode("조건 변경 (" + fmtTime(data.condition_changed_at) + ")"));
        legend.appendChild(li);
      }
      if (data.light_unit_changed_at) {
        var lu = h("li");
        var sw2 = h("span", "legend__dash");
        sw2.style.setProperty("--c", "var(--t-blue)");
        lu.appendChild(sw2);
        lu.appendChild(document.createTextNode("조도 센서 교체 — 이후 lux (" + fmtTime(data.light_unit_changed_at) + ")"));
        legend.appendChild(lu);
      }
      renderTable();
    }

    function nearest(px) {
      var best = 0, bestD = Infinity;
      geom.times.forEach(function (t, i) {
        var d = Math.abs(geom.X(t) - px);
        if (d < bestD) { bestD = d; best = i; }
      });
      return best;
    }

    var current = null;
    function showIndex(i) {
      if (!geom || i == null) return;
      current = i;
      var x = geom.X(geom.times[i]);
      cursor.setAttribute("x1", x);
      cursor.setAttribute("x2", x);
      cursor.setAttribute("visibility", "visible");
      tip.innerHTML = "";
      tip.appendChild(h("div", "graph-tip__time", fmtTime(data.times[i])));
      var spoken = [fmtTime(data.times[i])];
      data.series.forEach(function (s) {
        var row = h("div", "graph-tip__row");
        var dot = h("span", "dot");
        dot.style.setProperty("--c", s.color);
        row.appendChild(dot);
        row.appendChild(document.createTextNode(s.label));
        row.appendChild(h("b", "", fmtVal(s.values[i], data.digits) + data.unit));
        tip.appendChild(row);
        spoken.push(s.label + " " + fmtVal(s.values[i], data.digits) + data.unit);
      });
      tip.hidden = false;
      var scale = box.clientWidth / geom.width;
      var left = x * scale + 14;
      if (left + tip.offsetWidth > box.clientWidth - 6) left = x * scale - tip.offsetWidth - 6;
      tip.style.left = Math.max(4, left) + "px";
      live.textContent = spoken.join(", ");
    }

    function hideCursor() {
      if (cursor) cursor.setAttribute("visibility", "hidden");
      tip.hidden = true;
    }

    box.addEventListener("keydown", function (e) {
      if (!data || !data.times.length) return;
      var n = data.times.length;
      var i = current == null ? n - 1 : current;
      if (e.key === "ArrowLeft") i = Math.max(0, i - 1);
      else if (e.key === "ArrowRight") i = Math.min(n - 1, i + 1);
      else if (e.key === "Home") i = 0;
      else if (e.key === "End") i = n - 1;
      else return;
      e.preventDefault();
      showIndex(i);
    });
    box.addEventListener("focus", function () {
      if (data && data.times.length) showIndex(current == null ? data.times.length - 1 : current);
    });
    box.addEventListener("blur", hideCursor);

    function renderTable() {
      if (!tableWrap) return;
      var old = tableWrap.querySelector(".data-table-scroll");
      if (old) old.remove();
      if (!data || !data.times.length) return;
      var scroll = h("div", "data-table-scroll");
      var table = h("table", "data-table");
      var cap = h("caption", "sr-only", data.label + " (" + data.unit + ")");
      table.appendChild(cap);
      var thead = h("thead"), tr = h("tr");
      tr.appendChild(h("th", "", "시각"));
      data.series.forEach(function (s) { tr.appendChild(h("th", "", s.label + " (" + data.unit + ")")); });
      thead.appendChild(tr);
      table.appendChild(thead);
      var tbody = h("tbody");
      for (var i = data.times.length - 1; i >= 0; i--) {
        var row = h("tr");
        row.appendChild(h("td", "", fmtTime(data.times[i])));
        data.series.forEach(function (s) { row.appendChild(h("td", "", fmtVal(s.values[i], data.digits))); });
        tbody.appendChild(row);
      }
      table.appendChild(tbody);
      scroll.appendChild(table);
      tableWrap.appendChild(scroll);
    }

    function load(p) {
      for (var k in p) if (p[k] != null) params[k] = p[k];
      var qs = new URLSearchParams(params).toString();
      box.innerHTML = '<p class="graph-empty">불러오는 중…</p>';
      return fetch(url + "?" + qs, { credentials: "same-origin" })
        .then(function (res) {
          if (!res.ok) throw new Error("HTTP " + res.status);
          return res.json();
        })
        .then(function (json) {
          data = json;
          current = null;
          render();
        })
        .catch(function () {
          box.innerHTML = '<p class="graph-empty">그래프를 불러오지 못했어요.</p>';
        });
    }

    // PC ↔ 좁은 화면이 바뀌면 높이 기준이 달라지므로 다시 그린다.
    var onMedia = function () { if (data && holder.isConnected) render(); };
    if (desktop.addEventListener) desktop.addEventListener("change", onMedia);
    else if (desktop.addListener) desktop.addListener(onMedia);

    var resizeTimer = null;
    window.addEventListener("resize", function () {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(function () { if (data && holder.isConnected) render(); }, 150);
    });

    return { load: load };
  }

  window.PlantGraph = { create: create };
})();
