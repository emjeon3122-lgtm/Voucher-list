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
