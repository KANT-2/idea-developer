(function () {
  "use strict";

  var script = document.currentScript;
  var requestUrl = script.dataset.requestUrl;
  var verifyUrl = script.dataset.verifyUrl;
  var csrfToken = document.querySelector('meta[name="csrf-token"]').content;
  var emailForm = document.getElementById("email-step");
  var codeForm = document.getElementById("code-step");
  var emailInput = document.getElementById("login-email");
  var codeInput = document.getElementById("login-code");
  var maskedEmail = document.getElementById("masked-email");
  var timerNode = document.getElementById("code-timer");
  var messageNode = document.getElementById("login-message");
  var resendButton = document.getElementById("resend-code-button");
  var challengeId = null;
  var timerId = null;
  var busy = false;

  function showMessage(message, type) {
    messageNode.textContent = message;
    messageNode.className = "alert alert-" + type;
  }

  function setBusy(button, value) {
    busy = value;
    button.disabled = value;
    button.querySelector(".button-label").classList.toggle("d-none", value);
    button.querySelector(".spinner-border").classList.toggle("d-none", !value);
  }

  async function postJson(url, payload) {
    var response = await fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
      body: JSON.stringify(payload),
    });
    var body = await response.json();
    if (!response.ok) {
      var error = new Error(body.error && body.error.message ? body.error.message : "요청에 실패했습니다.");
      error.code = body.error && body.error.code;
      throw error;
    }
    return body.data;
  }

  function startCountdown(seconds) {
    window.clearInterval(timerId);
    var remaining = seconds;
    function render() {
      var minutes = Math.floor(remaining / 60);
      var rest = String(remaining % 60).padStart(2, "0");
      timerNode.textContent = remaining > 0 ? "남은 시간 " + minutes + ":" + rest : "인증번호가 만료되었습니다.";
      if (remaining <= 0) {
        window.clearInterval(timerId);
        showMessage("인증번호가 만료되었습니다. 다시 요청해 주세요.", "warning");
      }
      remaining -= 1;
    }
    render();
    timerId = window.setInterval(render, 1000);
  }

  function scheduleResend(seconds) {
    resendButton.disabled = true;
    window.setTimeout(function () { resendButton.disabled = false; }, seconds * 1000);
  }

  async function requestCode(button) {
    if (busy) return;
    var cooldownSeconds = null;
    setBusy(button, true);
    try {
      var data = await postJson(requestUrl, { email: emailInput.value.trim() });
      challengeId = data.challenge_id;
      maskedEmail.textContent = data.masked_email;
      emailForm.classList.add("d-none");
      codeForm.classList.remove("d-none");
      cooldownSeconds = data.resend_after_seconds;
      startCountdown(data.expires_in_seconds);
      showMessage(data.message, "info");
      codeInput.focus();
    } catch (error) {
      showMessage(error.message || "네트워크 오류가 발생했습니다.", "danger");
    } finally {
      setBusy(button, false);
      if (cooldownSeconds !== null) scheduleResend(cooldownSeconds);
    }
  }

  emailForm.addEventListener("submit", function (event) {
    event.preventDefault();
    if (emailForm.reportValidity()) requestCode(document.getElementById("request-code-button"));
  });

  codeForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    if (busy || !codeForm.reportValidity()) return;
    var button = document.getElementById("verify-code-button");
    setBusy(button, true);
    try {
      var data = await postJson(verifyUrl, { challenge_id: challengeId, code: codeInput.value });
      window.location.assign(data.redirect_url);
    } catch (error) {
      showMessage(error.message || "네트워크 오류가 발생했습니다.", "danger");
      codeInput.select();
    } finally {
      setBusy(button, false);
    }
  });

  resendButton.addEventListener("click", function () {
    if (!busy) requestCode(resendButton);
  });

  codeInput.addEventListener("input", function () {
    codeInput.value = codeInput.value.replace(/\D/g, "").slice(0, 6);
  });
})();
