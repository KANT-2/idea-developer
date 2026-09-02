(function () {
  "use strict";

  var mountNode = document.getElementById("brainstorm-root");
  if (!mountNode) {
    return;
  }

  if (!window.React || !window.ReactDOM) {
    mountNode.innerHTML =
      '<div class="alert alert-danger" role="alert">' +
      "브레인스토밍 화면 구성 요소를 불러오지 못했습니다. 네트워크 또는 CSP 설정을 확인해 주세요." +
      "</div>";
    return;
  }

  var element = window.React.createElement(
    "div",
    { className: "alert alert-info", role: "status" },
    "브레인스토밍 앱 마운트가 준비되었습니다."
  );
  window.ReactDOM.createRoot(mountNode).render(element);
})();
