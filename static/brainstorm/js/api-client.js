(function () {
  "use strict";

  window.BrainstormApiClient = {
    create: function (options) {
      var csrf = options.csrf;
      var getActiveCanvasId = options.getActiveCanvasId;
      function key() { return window.crypto?.randomUUID ? window.crypto.randomUUID() : Date.now() + "-" + Math.random(); }
      function request(url, options) {
        var activeCanvasId = getActiveCanvasId();
        options = options || {};
        return fetch(url, Object.assign({}, options, {
          credentials: "same-origin",
          headers: Object.assign(
            {"Content-Type": "application/json", "X-CSRFToken": csrf},
            activeCanvasId ? {"X-Brainstorm-Canvas-Id": String(activeCanvasId)} : {},
            options.headers || {}
          )
        })).then(function (response) {
          return response.text().then(function (body) {
            var payload;
            try {
              payload = JSON.parse(body);
            } catch (parseError) {
              var invalidResponse = new Error(
                response.status === 401 || response.redirected
                  ? "로그인 상태가 만료되었습니다. 페이지를 새로고침해 주세요."
                  : response.ok
                  ? "서버 응답을 읽지 못했습니다. 잠시 후 다시 시도해 주세요."
                  : "서버에서 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
              );
              invalidResponse.code = "invalid_response";
              throw invalidResponse;
            }
            if (!response.ok || !payload.ok) {
              var error = new Error(payload.error?.message || "요청을 처리하지 못했습니다.");
              error.code = payload.error?.code || "request_failed"; error.details = payload.error?.details; throw error;
            }
            return payload.data;
          });
        }).catch(function (error) {
          if (error && error.code) throw error;
          var networkError = new Error("서버에 연결하지 못했습니다. 네트워크 상태를 확인해 주세요.");
          networkError.code = "network_error";
          throw networkError;
        });
      }


      return {key: key, request: request};
    }
  };
}());
