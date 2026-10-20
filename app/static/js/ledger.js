// 수불 대장 화면: 등록/취소 대화상자, 금액 자동 계산, 서명요청 일괄 선택, 실시간 반영
(function () {
  "use strict";

  // 대화상자 열기/닫기
  document.querySelectorAll("[data-open]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      document.getElementById(btn.dataset.open).showModal();
    });
  });
  document.querySelectorAll("dialog [data-close]").forEach(function (btn) {
    btn.addEventListener("click", function () { btn.closest("dialog").close(); });
  });

  // 금액 = 권종 × 수량
  document.querySelectorAll(".calc-form").forEach(function (form) {
    var sel = form.querySelector(".type-select");
    var qty = form.querySelector(".qty-input");
    var out = form.querySelector(".amount-out");
    function calc() {
      var opt = sel.options[sel.selectedIndex];
      var face = opt ? parseInt(opt.dataset.face || "0", 10) : 0;
      var n = parseInt(qty.value || "0", 10) || 0;
      out.textContent = (face * n).toLocaleString("ko-KR") + "원";
    }
    sel.addEventListener("change", calc);
    qty.addEventListener("input", calc);
  });

  // 수령자: 회사 주소록 검색 (입력 후 0.3초 뒤 조회, 동명이인 표시)
  document.querySelectorAll(".picker").forEach(function (picker) {
    var input = picker.querySelector(".picker-input");
    var value = picker.querySelector(".picker-value");
    var list = picker.querySelector(".picker-results");
    var msg = picker.querySelector(".picker-msg");
    var selected = picker.querySelector(".picker-selected");
    var chip = picker.querySelector(".picker-chip");
    var defaultMsg = msg.textContent;
    var timer = null, seq = 0;

    function describe(p) {
      return [p.department, p.job_title, p.email].filter(Boolean).join(" · ");
    }
    function choose(p) {
      value.value = p.id;
      chip.textContent = p.name + " · " + describe(p);
      selected.hidden = false;
      input.parentNode.hidden = true;
      list.textContent = "";
      msg.textContent = "";
    }
    function reset() {
      value.value = "";
      selected.hidden = true;
      input.parentNode.hidden = false;
      input.value = "";
      list.textContent = "";
      msg.textContent = defaultMsg;
      input.focus();
    }
    function render(people) {
      list.textContent = "";
      var counts = {};
      people.forEach(function (p) { counts[p.name] = (counts[p.name] || 0) + 1; });
      people.forEach(function (p) {
        var li = document.createElement("li");
        li.setAttribute("role", "option");
        var who = document.createElement("span");
        who.className = "who";
        who.textContent = p.name;
        var meta = document.createElement("span");
        meta.className = "meta";
        meta.textContent = describe(p);
        li.appendChild(who);
        if (counts[p.name] > 1) {
          var b = document.createElement("span");
          b.className = "badge same-name";
          b.textContent = "동명이인";
          li.appendChild(b);
        }
        li.appendChild(meta);
        li.addEventListener("click", function () { choose(p); });
        list.appendChild(li);
      });
      msg.textContent = people.length ? "" : "재직 중인 직원 중 일치하는 사람이 없습니다.";
    }
    function lookup() {
      var q = input.value.trim();
      var mine = ++seq;
      if (!q) { list.textContent = ""; msg.textContent = defaultMsg; return; }
      msg.textContent = "검색 중…";
      fetch(picker.dataset.url + "?q=" + encodeURIComponent(q), { credentials: "same-origin", cache: "no-store" })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
        .then(function (res) {
          if (mine !== seq) return; // 더 최근 검색 결과만 표시
          if (!res.ok) { list.textContent = ""; msg.textContent = res.data.error || "주소록 조회 실패"; return; }
          render(res.data.results);
        })
        .catch(function () { if (mine === seq) msg.textContent = "주소록 조회 실패 (네트워크)"; });
    }
    input.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(lookup, 300);
    });
    input.addEventListener("keydown", function (e) {
      if (e.key !== "Enter") return;
      e.preventDefault(); // 검색창의 Enter 로 폼이 제출되지 않게
      var first = list.querySelector("li");
      if (first && list.children.length === 1) first.click();
    });
    picker.querySelector(".picker-clear").addEventListener("click", reset);
    picker.closest("form").addEventListener("submit", function (e) {
      if (!value.value) {
        e.preventDefault();
        msg.textContent = "수령자를 검색해서 목록에서 선택하세요.";
        input.focus();
      }
    });
    picker.closest("dialog").addEventListener("close", function () { if (value.value) reset(); });
  });

  // 취소(정정)
  var voidDlg = document.getElementById("dlg-void");
  var voidForm = document.getElementById("void-form");
  document.querySelectorAll("[data-void]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      voidForm.action = voidForm.dataset.actionTemplate.replace(/\/0\/void$/, "/" + btn.dataset.void + "/void");
      document.getElementById("void-label").textContent = btn.dataset.label;
      voidForm.reset();
      voidDlg.showModal();
    });
  });

  // 서명 요청 일괄 선택
  var checks = Array.prototype.slice.call(document.querySelectorAll(".row-check"));
  var all = document.getElementById("check-all");
  var count = document.getElementById("sel-count");
  var submit = document.getElementById("bulk-submit");
  function refresh() {
    var n = checks.filter(function (c) { return c.checked; }).length;
    count.textContent = n;
    submit.disabled = n === 0;
    all.checked = n > 0 && n === checks.length;
  }
  checks.forEach(function (c) { c.addEventListener("change", refresh); });
  if (all) {
    all.addEventListener("change", function () {
      checks.forEach(function (c) { c.checked = all.checked; });
      refresh();
    });
  }
  document.getElementById("bulk-form").addEventListener("submit", function (e) {
    var n = checks.filter(function (c) { return c.checked; }).length;
    if (!n || !confirm("선택한 " + n + "건에 대해 서명 요청 메일을 발송할까요?")) e.preventDefault();
  });

  // 최신 내역이 보이도록 대장을 맨 아래로 스크롤 (엑셀처럼 오래된 → 최신 순)
  var wrap = document.getElementById("sheet-wrap");
  if (wrap) wrap.scrollTop = wrap.scrollHeight;

  // 실시간 반영: 직원이 서명을 완료하면 화면을 자동으로 새로고침
  var live = document.getElementById("live-status");
  function busy() {
    return document.querySelector("dialog[open]") || checks.some(function (c) { return c.checked; });
  }
  function poll() {
    fetch(live.dataset.url, { credentials: "same-origin", cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || data.version === live.dataset.version) return;
        if (!busy()) { location.reload(); return; }
        live.textContent = "● 새 변경사항이 있습니다 (클릭하여 새로고침)";
        live.classList.add("stale");
      })
      .catch(function () { /* 일시적 네트워크 오류는 무시 */ });
  }
  if (live) {
    live.addEventListener("click", function () { if (live.classList.contains("stale")) location.reload(); });
    setInterval(poll, 10000);
  }
})();
