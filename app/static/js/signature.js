// 전자서명 패드 (PC 마우스 / 모바일 터치 / 펜 모두 지원, 외부 라이브러리 없음)
(function () {
  "use strict";
  var canvas = document.getElementById("sig-pad");
  if (!canvas) return;
  var ctx = canvas.getContext("2d");
  var form = document.getElementById("sign-form");
  var hidden = document.getElementById("signature-data");
  var drawing = false, hasInk = false, last = null, width = 0;

  function setup() {
    var rect = canvas.getBoundingClientRect();
    // 모바일 주소창이 숨겨질 때 등 높이만 바뀌는 resize, 화면에 보이지 않는 순간(폭 0)은 무시
    if (!rect.width || Math.round(rect.width) === width) return;
    width = Math.round(rect.width);
    // 화면 회전 등으로 폭이 바뀌어도 이미 그린 서명은 유지
    var keep = null;
    if (hasInk) {
      keep = document.createElement("canvas");
      keep.width = canvas.width;
      keep.height = canvas.height;
      keep.getContext("2d").drawImage(canvas, 0, 0);
    }
    var ratio = Math.max(window.devicePixelRatio || 1, 1);
    canvas.width = rect.width * ratio;
    canvas.height = rect.height * ratio;
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    clear();
    if (keep) {
      ctx.drawImage(keep, 0, 0, rect.width, rect.height);
      hasInk = true;
    }
  }
  function clear() {
    var rect = canvas.getBoundingClientRect();
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, rect.width, rect.height);
    hasInk = false;
  }
  function point(e) {
    var rect = canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  canvas.addEventListener("pointerdown", function (e) {
    e.preventDefault();
    canvas.setPointerCapture(e.pointerId);
    drawing = true;
    last = point(e);
    ctx.beginPath();
    ctx.arc(last.x, last.y, 1.2, 0, Math.PI * 2);
    ctx.fillStyle = "#111";
    ctx.fill();
    hasInk = true;
  });
  canvas.addEventListener("pointermove", function (e) {
    if (!drawing) return;
    e.preventDefault();
    var p = point(e);
    ctx.strokeStyle = "#111";
    ctx.lineWidth = e.pointerType === "pen" && e.pressure ? 1.5 + e.pressure * 2 : 2.6;
    ctx.lineCap = "round";
    ctx.lineJoin = "round";
    ctx.beginPath();
    ctx.moveTo(last.x, last.y);
    ctx.lineTo(p.x, p.y);
    ctx.stroke();
    last = p;
    hasInk = true;
  });
  function stop() { drawing = false; last = null; }
  canvas.addEventListener("pointerup", stop);
  canvas.addEventListener("pointercancel", stop);
  canvas.addEventListener("pointerleave", stop);

  document.getElementById("sig-clear").addEventListener("click", clear);
  window.addEventListener("resize", setup);
  setup();

  form.addEventListener("submit", function (e) {
    if (!hasInk) {
      e.preventDefault();
      alert("서명란에 서명해 주세요.");
      return;
    }
    hidden.value = canvas.toDataURL("image/png");
    document.getElementById("sig-submit").disabled = true;
  });
})();
