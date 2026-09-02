(function () {
  "use strict";

  const root = document.getElementById("prd-write-app");
  if (!root) return;

  const detailApi = root.dataset.detailApi;
  const aiBase = root.dataset.aiApiBase;
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const sectionsRoot = document.getElementById("prd-sections");
  const scope = document.getElementById("coach-scope");
  const messagesRoot = document.getElementById("coach-messages");
  const form = document.getElementById("coach-form");
  const input = document.getElementById("coach-input");
  const submit = document.getElementById("coach-submit");
  const cancel = document.getElementById("coach-cancel");
  const alertBox = document.getElementById("prd-alert");
  const draftModalElement = document.getElementById("draft-modal");
  const draftModal = bootstrap.Modal.getOrCreateInstance(draftModalElement);
  const draftContent = document.getElementById("draft-content");
  const draftError = document.getElementById("draft-error");
  const draftApply = document.getElementById("draft-apply");
  let detail = null;
  let activeJobId = null;
  let currentDraft = null;

  function decodeSafeText(value) {
    const area = document.createElement("textarea");
    area.innerHTML = value || "";
    return area.value;
  }

  async function api(url, options) {
    const response = await fetch(url, {
      credentials: "same-origin",
      ...options,
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken,
        ...(options?.headers || {})
      }
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) {
      const error = new Error(payload.error?.message || "요청을 처리하지 못했습니다.");
      error.code = payload.error?.code;
      error.details = payload.error?.details;
      throw error;
    }
    return payload.data;
  }

  function showAlert(message, kind) {
    alertBox.className = "alert alert-" + (kind || "danger");
    alertBox.textContent = message;
  }

  function clearAlert() {
    alertBox.className = "alert d-none";
    alertBox.textContent = "";
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function renderDetail(data) {
    detail = data;
    document.getElementById("prd-description").textContent = data.prd.description || "한 줄 소개가 없습니다.";
    document.getElementById("prd-status").textContent = data.prd.status;
    sectionsRoot.replaceChildren();
    scope.replaceChildren(new Option("전체 PRD", ""));
    const canRequestAi = data.permissions.can_request_ai && data.prd.status !== "completed";
    input.disabled = !canRequestAi;
    submit.disabled = !canRequestAi;
    if (!canRequestAi) input.placeholder = "현재 권한 또는 PRD 상태에서는 AI를 요청할 수 없습니다.";

    data.sections.forEach(function (section) {
      scope.add(new Option(section.title, String(section.id)));
      const card = element("article", "card");
      const header = element("div", "card-header bg-white");
      header.append(element("h2", "h5 mb-1", section.title));
      if (section.guide) header.append(element("p", "text-secondary small mb-0", section.guide));
      card.append(header);
      const body = element("div", "card-body vstack gap-3");
      section.questions.forEach(function (question) {
        const block = element("div", "border rounded p-3");
        const top = element("div", "d-flex justify-content-between gap-3 align-items-start");
        top.append(element("h3", "h6", question.prompt));
        if (canRequestAi) {
          const button = element("button", "btn btn-outline-primary btn-sm", "AI 초안");
          button.type = "button";
          button.addEventListener("click", function () { requestDraft(question, button); });
          top.append(button);
        }
        block.append(top);
        const answer = element("div", "question-answer text-secondary", question.answer?.content || "아직 답변이 없습니다.");
        answer.dataset.questionId = question.id;
        block.append(answer);
        body.append(block);
      });
      card.append(body);
      sectionsRoot.append(card);
    });
  }

  async function loadConversation() {
    messagesRoot.replaceChildren(element("p", "text-secondary", "대화를 불러오는 중입니다."));
    try {
      const query = scope.value ? "?section_id=" + encodeURIComponent(scope.value) : "";
      const data = await api(aiBase + "conversation/" + query);
      messagesRoot.replaceChildren();
      if (!data.messages.length) {
        messagesRoot.append(element("p", "text-secondary", "이 범위에서 AI 코치와 나눈 대화가 없습니다."));
      }
      data.messages.forEach(function (message) {
        const wrap = element("div", "mb-2");
        const bubble = element(
          "div",
          "coach-message coach-message-" + message.role,
          decodeSafeText(message.content)
        );
        wrap.append(bubble);
        if (message.role === "user" && ["failed", "timed_out"].includes(message.job?.status)) {
          const retry = element("button", "btn btn-link btn-sm float-end", "다시 시도");
          retry.type = "button";
          retry.addEventListener("click", function () { retryJob(message.job.id); });
          wrap.append(retry);
        }
        messagesRoot.append(wrap);
      });
      messagesRoot.scrollTop = messagesRoot.scrollHeight;
    } catch (error) {
      messagesRoot.replaceChildren(element("p", "text-danger", error.message));
    }
  }

  function setBusy(busy, jobId) {
    submit.disabled = busy;
    input.disabled = busy;
    activeJobId = jobId || null;
    cancel.classList.toggle("d-none", !busy || !jobId);
  }

  async function pollJob(jobId, onSuccess) {
    for (;;) {
      await new Promise(function (resolve) { setTimeout(resolve, 1500); });
      const job = await api(aiBase + "jobs/" + jobId + "/");
      if (["queued", "running", "retry_wait", "cancel_requested"].includes(job.status)) continue;
      if (job.status === "succeeded") onSuccess(job);
      else showAlert(job.error?.message || "AI 요청이 완료되지 않았습니다.");
      return job;
    }
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    clearAlert();
    const message = input.value.trim();
    if (!message) return;
    const key = crypto.randomUUID();
    setBusy(true);
    try {
      const job = await api(aiBase + "chat/", {
        method: "POST",
        headers: {"Idempotency-Key": key},
        body: JSON.stringify({section_id: scope.value || null, message: message})
      });
      input.value = "";
      setBusy(true, job.id);
      await loadConversation();
      await pollJob(job.id, loadConversation);
      await loadConversation();
    } catch (error) {
      showAlert(error.message);
    } finally {
      setBusy(false);
    }
  });

  cancel.addEventListener("click", async function () {
    if (!activeJobId) return;
    try {
      await api(aiBase + "jobs/" + activeJobId + "/cancel/", {method: "POST", body: "{}"});
      await loadConversation();
    } catch (error) {
      showAlert(error.message);
    }
  });

  async function retryJob(jobId) {
    clearAlert();
    try {
      const job = await api(aiBase + "jobs/" + jobId + "/retry/", {method: "POST", body: "{}"});
      setBusy(true, job.id);
      await pollJob(job.id, loadConversation);
      await loadConversation();
    } catch (error) {
      showAlert(error.message);
    } finally {
      setBusy(false);
    }
  }

  async function requestDraft(question, button) {
    clearAlert();
    button.disabled = true;
    button.textContent = "생성 중…";
    try {
      const job = await api(aiBase + "drafts/", {
        method: "POST",
        headers: {"Idempotency-Key": crypto.randomUUID()},
        body: JSON.stringify({question_id: question.id})
      });
      await pollJob(job.id, function (completed) {
        currentDraft = {
          jobId: completed.id,
          questionId: question.id,
          questionVersion: completed.output.question_version
        };
        document.getElementById("draft-question").textContent = question.prompt;
        draftContent.value = decodeSafeText(completed.output.draft);
        draftError.classList.add("d-none");
        draftModal.show();
      });
    } catch (error) {
      showAlert(error.message);
    } finally {
      button.disabled = false;
      button.textContent = "AI 초안";
    }
  }

  draftApply.addEventListener("click", async function () {
    if (!currentDraft) return;
    draftApply.disabled = true;
    draftError.classList.add("d-none");
    try {
      const data = await api(aiBase + "drafts/" + currentDraft.jobId + "/apply/", {
        method: "POST",
        body: JSON.stringify({
          question_version: currentDraft.questionVersion,
          content: draftContent.value
        })
      });
      const answer = sectionsRoot.querySelector('[data-question-id="' + data.question_id + '"]');
      if (answer) answer.textContent = data.answer.content;
      draftModal.hide();
      showAlert("AI 초안을 PRD 답변에 반영했습니다.", "success");
      const target = detail.sections.flatMap(function (section) { return section.questions; })
        .find(function (question) { return question.id === data.question_id; });
      if (target) target.version = data.question_version;
    } catch (error) {
      draftError.textContent = error.code === "version_conflict"
        ? "질문이 변경되었습니다. 화면을 새로고침한 뒤 초안을 다시 만들어 주세요."
        : error.message;
      draftError.classList.remove("d-none");
    } finally {
      draftApply.disabled = false;
    }
  });

  scope.addEventListener("change", loadConversation);

  api(detailApi)
    .then(function (data) { renderDetail(data); return loadConversation(); })
    .catch(function (error) { showAlert(error.message); });
}());
