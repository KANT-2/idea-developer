(function () {
  "use strict";

  const root = document.getElementById("prd-write-app");
  if (!root) return;

  const detailApi = root.dataset.detailApi;
  const exportApi = root.dataset.exportApi;
  const participantsApi = root.dataset.participantsApi;
  const participantSearchApi = root.dataset.participantSearchApi;
  const commentsApi = root.dataset.commentsApi;
  const contributionsApi = root.dataset.contributionsApi;
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
  const participantAlert = document.getElementById("participant-alert");
  const participantList = document.getElementById("participant-list");
  const participantResults = document.getElementById("participant-search-results");
  const commentList = document.getElementById("comment-list");
  const commentForm = document.getElementById("comment-form");
  const commentInput = document.getElementById("comment-input");
  const commentTarget = document.getElementById("comment-target");
  const commentSubmit = document.getElementById("comment-submit");
  const commentPanelAlert = document.getElementById("comment-panel-alert");
  const commentPagination = document.getElementById("comment-pagination");
  const contributionList = document.getElementById("contribution-list");
  const contributionAlert = document.getElementById("contribution-alert");
  const saveAllButton = document.getElementById("save-all-answers");
  const statusControl = document.getElementById("prd-status-control");
  const deadlineInput = document.getElementById("write-deadline-input");
  const evaluationButton = document.getElementById("run-evaluation");
  const evaluationCancel = document.getElementById("cancel-evaluation");
  const evaluationAlert = document.getElementById("evaluation-alert");
  const exportModalElement = document.getElementById("export-modal");
  const exportPreview = document.getElementById("export-preview");
  const exportPreviewState = document.getElementById("export-preview-state");
  const copyMarkdownButton = document.getElementById("copy-prd-markdown");
  const downloadMarkdownLink = document.getElementById("download-prd-markdown");
  let detail = null;
  let activeJobId = null;
  let currentDraft = null;
  // undefined means the initial render; null means the user collapsed every section.
  let activeSectionId = undefined;
  let questionListMode = false;
  let currentParticipants = [];
  let canManageParticipants = false;
  let canCreateComments = false;
  let commentPage = 1;
  const commentPageSize = 10;
  const pendingAnswers = new Map();
  let savingAllAnswers = false;
  const evaluationPersonas = ["pm", "engineering", "investor"];
  let evaluationPersona = "pm";
  let evaluationResults = {};
  let evaluationJobIds = [];
  let exportedMarkdown = "";
  let alertTimer = null;

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
    const contentType = response.headers.get("content-type") || "";
    if (!contentType.includes("application/json")) {
      throw new Error(response.ok
        ? "서버 응답 형식을 확인하지 못했습니다. 다시 시도해 주세요."
        : "서버에서 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.");
    }
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
    if (alertTimer) window.clearTimeout(alertTimer);
    alertBox.className = "alert write-alert alert-" + (kind || "danger");
    alertBox.textContent = message;
    alertTimer = window.setTimeout(clearAlert, kind === "success" ? 3000 : 5000);
  }

  function clearAlert() {
    if (alertTimer) window.clearTimeout(alertTimer);
    alertTimer = null;
    alertBox.className = "alert write-alert d-none";
    alertBox.textContent = "";
  }

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function sectionRate(section) {
    const activeQuestions = section.questions.filter(function (question) { return !question.is_held; });
    if (!activeQuestions.length) return 0;
    return Math.round(activeQuestions.filter(function (question) { return question.is_completed; }).length * 100 / activeQuestions.length);
  }

  function renderProgress(data) {
    const rate = data.prd.completion_rate;
    document.getElementById("write-completion-label").textContent = rate + "%";
    document.getElementById("write-step-progress-bar").style.width = rate + "%";
    const progressRoot = document.getElementById("write-section-progress");
    if (!progressRoot) return;
    progressRoot.replaceChildren();
    data.sections.forEach(function (section) {
      const value = sectionRate(section);
      const row = element("div", "score-row");
      const bar = element("i"); bar.append(element("b")); bar.firstChild.style.width = value + "%";
      row.append(element("span", "", section.title), bar, element("strong", "", value + "%"));
      progressRoot.append(row);
    });
  }

  function renderSteps(data) {
    const steps = document.getElementById("write-steps");
    steps.replaceChildren();
    data.sections.forEach(function (section, index) {
      const rate = sectionRate(section);
      const button = element("button", "write-step" + (rate === 100 ? " done" : "") + (String(section.id) === String(activeSectionId) ? " active" : ""));
      button.type = "button";
      button.append(element("b", "", rate === 100 ? "✓" : String(index + 1)), element("span", "", section.title.length > 9 ? section.title.slice(0, 9) : section.title));
      button.addEventListener("click", function () { activeSectionId = section.id; renderDetail(detail); document.querySelector('[data-section-id="' + section.id + '"]')?.scrollIntoView({behavior: "smooth", block: "start"}); });
      steps.append(button);
    });
  }

  function renderDetail(data) {
    detail = data;
    if (activeSectionId === undefined && data.sections.length) activeSectionId = data.sections[0].id;
    document.getElementById("prd-description").textContent = data.prd.description || "한 줄 소개가 없습니다.";
    const status = document.getElementById("prd-status");
    const statusLabels = {in_progress: "진행 중", completed: "완료", held: "보류", dropped: "드랍"};
    status.textContent = statusLabels[data.prd.status] || data.prd.status;
    status.dataset.status = data.prd.status;
    statusControl.value = data.prd.status;
    statusControl.dataset.status = data.prd.status;
    Array.from(statusControl.options).forEach(function (option) {
      option.disabled = (data.prd.status === "completed" && !["completed", "in_progress"].includes(option.value))
        || (option.value === "completed" && !["in_progress", "completed"].includes(data.prd.status));
    });
    statusControl.classList.toggle("d-none", !data.permissions.can_change_status);
    status.classList.toggle("d-none", Boolean(data.permissions.can_change_status));
    deadlineInput.value = data.prd.deadline || "";
    deadlineInput.disabled = !data.permissions.can_edit_deadline || data.prd.status === "completed";
    document.getElementById("write-deadline-label").textContent = data.prd.deadline || "마감일 없음";
    document.getElementById("active-section-count").textContent = data.sections.length + "개 활성 섹션";
    document.getElementById("complete-prd").classList.toggle("d-none", !data.permissions.can_complete || data.prd.status === "completed");
    document.getElementById("reopen-prd").classList.toggle("d-none", !data.permissions.can_reopen || data.prd.status !== "completed");
    document.getElementById("contribution-toggle").classList.toggle("d-none", !data.permissions.can_view_contributions);
    canManageParticipants = Boolean(data.permissions.can_manage_participants) && data.prd.status !== "completed";
    document.getElementById("manage-participants").classList.toggle("d-none", !canManageParticipants);
    document.getElementById("participant-add-section").classList.toggle("d-none", !canManageParticipants);
    canCreateComments = Boolean(data.permissions.can_comment || data.permissions.can_review_comment);
    commentForm.classList.toggle("d-none", !canCreateComments);
    if (data.prd.status === "completed" && data.permissions.can_review_comment) {
      document.getElementById("comment-permission-hint").textContent = "선택한 위치에 완료 후 튜터 리뷰 코멘트로 등록됩니다.";
    } else {
      document.getElementById("comment-permission-hint").textContent = "PRD 전체 또는 질문을 선택해 의견을 남길 수 있습니다.";
    }
    renderProgress(data);
    renderSteps(data);
    sectionsRoot.replaceChildren();
    scope.replaceChildren(new Option("전체 PRD", ""));
    const previousCommentTarget = commentTarget.value;
    commentTarget.replaceChildren(new Option("PRD 전체", ""));
    const canRequestAi = data.permissions.can_request_ai && data.prd.status !== "completed";
    const canEditAnswers = data.permissions.can_edit && data.prd.status !== "completed";
    saveAllButton.classList.toggle("d-none", !canEditAnswers);
    input.disabled = !canRequestAi;
    submit.disabled = !canRequestAi;
    evaluationButton.disabled = !canRequestAi;
    if (!canRequestAi) input.placeholder = "현재 권한 또는 PRD 상태에서는 AI를 요청할 수 없습니다.";

    function buildQuestionBlock(question, extraClass) {
      const block = element("div", "write-question" + (question.is_held ? " is-held" : "") + (extraClass ? " " + extraClass : ""));
      const top = element("div", "write-question-head");
      top.append(element("h3", "", question.prompt));
      if (canEditAnswers) {
        const hold = element("button", "question-hold-button" + (question.is_held ? " active" : ""), question.is_held ? "보류 해제" : "보류");
        hold.type = "button";
        hold.setAttribute("aria-pressed", String(question.is_held));
        hold.addEventListener("click", function () { toggleQuestionHold(question, hold); });
        top.append(hold);
      } else if (question.is_held) {
        top.append(element("span", "question-held-badge", "보류"));
      }
      block.append(top);
      if (question.is_held) {
        const held = element("div", "question-held-panel");
        held.append(
          element("strong", "", "진행도와 AI 진단에서 제외된 질문입니다."),
          element("p", "", question.answer?.content ? "기존 답변은 그대로 보존되어 있습니다." : "보류를 해제하면 다시 답변을 작성할 수 있습니다.")
        );
        block.append(held);
        return block;
      }
      if (canEditAnswers) {
        const editor = element("textarea", "form-control question-editor");
        editor.rows = 4;
        editor.maxLength = 12000;
        const savedContent = question.answer?.content || "";
        editor.value = pendingAnswers.has(String(question.id)) ? pendingAnswers.get(String(question.id)) : savedContent;
        editor.placeholder = "이 질문에 대한 팀의 답변을 작성해 주세요.";
        editor.dataset.questionId = question.id;
        editor.dataset.version = question.version;
        editor.dataset.savedContent = savedContent;
        const save = element("button", "btn btn-outline-primary btn-sm question-save-button", "저장");
        save.type = "button";
        save.disabled = !pendingAnswers.has(String(question.id));
        editor.addEventListener("input", function () {
          if (editor.value === editor.dataset.savedContent) pendingAnswers.delete(String(question.id));
          else pendingAnswers.set(String(question.id), editor.value);
          save.disabled = !pendingAnswers.has(String(question.id));
          updateSaveAllButton();
        });
        const footer = element("div", "write-answer-footer");
        const saved = element("small", "", question.answer ? "저장된 답변" : "아직 저장되지 않았습니다.");
        const actions = element("span", "write-answer-actions");
        actions.append(save);
        save.addEventListener("click", function () { saveOneAnswer(String(question.id), save); });
        footer.append(saved, actions);
        block.append(editor, footer);
      } else {
        const answer = element("div", "question-answer", question.answer?.content || "아직 답변이 없습니다.");
        answer.dataset.questionId = question.id;
        block.append(answer);
      }
      return block;
    }

    if (questionListMode) {
      const intro = element("div", "write-question-list-intro");
      intro.append(
        element("i", "bi bi-list-check"),
        element("span", "", "모든 질문을 섹션별로 한 번에 펼쳐 보고 연속해서 작성할 수 있습니다.")
      );
      sectionsRoot.append(intro);
    }

    data.sections.forEach(function (section, index) {
      scope.add(new Option(section.title, String(section.id)));
      section.questions.forEach(function (question) {
        commentTarget.add(new Option(section.title + " · " + question.prompt + (question.is_held ? " (보류)" : ""), String(question.id)));
      });
      const rate = sectionRate(section);
      if (questionListMode) {
        const activeQuestions = section.questions.filter(function (question) { return !question.is_held; });
        const answeredCount = activeQuestions.filter(function (question) { return question.is_completed; }).length;
        const heldCount = section.questions.length - activeQuestions.length;
        const group = element("section", "write-question-group" + (String(section.id) === String(activeSectionId) ? " active" : ""));
        group.dataset.sectionId = section.id;
        const groupHead = element("div", "write-question-group-head");
        const titleWrap = element("div", "write-question-group-title");
        titleWrap.append(
          element("i", ""),
          element("span", "write-question-group-index", String(index + 1)),
          element("h3", "", section.title)
        );
        const summary = element("span", "write-question-group-summary", answeredCount + "/" + activeQuestions.length + " · " + rate + "%" + (heldCount ? " · 보류 " + heldCount : ""));
        groupHead.append(titleWrap, summary);
        group.append(groupHead);
        if (section.guide) group.append(element("p", "write-question-group-guide", section.guide));
        const questionBody = element("div", "write-question-group-body");
        section.questions.forEach(function (question) { questionBody.append(buildQuestionBlock(question, "write-question-list-item")); });
        group.append(questionBody);
        sectionsRoot.append(group);
        return;
      }

      const card = element("article", "write-section" + (String(section.id) === String(activeSectionId) ? " active" : ""));
      card.dataset.sectionId = section.id;
      const toggle = element("button", "write-section-toggle"); toggle.type = "button";
      const copy = element("span", "write-section-title"); copy.append(element("strong", "", section.title), element("small", "", section.guide || "작성 가이드를 확인해 주세요."));
      toggle.append(element("span", "write-section-index", String(index + 1)), copy, element("span", "write-section-badge" + (rate === 100 ? " done" : ""), rate === 100 ? "완료" : rate ? "작성 중" : "시작 전"), element("i", "bi bi-chevron-down write-section-chevron"));
      toggle.addEventListener("click", function () { activeSectionId = String(activeSectionId) === String(section.id) ? null : section.id; renderDetail(detail); });
      card.append(toggle);
      const body = element("div", "write-section-body");
      section.questions.forEach(function (question) { body.append(buildQuestionBlock(question)); });
      card.append(body); sectionsRoot.append(card);
    });
    if (Array.from(commentTarget.options).some(function (option) { return option.value === previousCommentTarget; })) commentTarget.value = previousCommentTarget;
    updateSaveAllButton();
  }

  function setExportTab(name) {
    const preview = name === "preview";
    document.getElementById("export-check-tab").classList.toggle("active", !preview);
    document.getElementById("export-preview-tab").classList.toggle("active", preview);
    document.getElementById("export-check-tab").setAttribute("aria-selected", String(!preview));
    document.getElementById("export-preview-tab").setAttribute("aria-selected", String(preview));
    document.getElementById("export-check-panel").classList.toggle("d-none", preview);
    document.getElementById("export-preview-panel").classList.toggle("d-none", !preview);
  }

  function renderExportCheck() {
    if (!detail) return;
    document.getElementById("export-prd-title").textContent = detail.prd.title;
    document.getElementById("export-progress-value").textContent = detail.prd.completion_rate + "%";
    document.querySelector(".export-progress-ring").style.setProperty("--export-score", detail.prd.completion_rate + "%");
    const list = document.getElementById("export-section-list");
    list.replaceChildren();
    detail.sections.forEach(function (section) {
      const active = section.questions.filter(function (question) { return !question.is_held; });
      const answered = active.filter(function (question) { return question.is_completed; }).length;
      const rate = sectionRate(section);
      const row = element("div", "export-section-row");
      const copy = element("div", "export-section-copy");
      copy.append(element("strong", "", section.title), element("small", "", answered + "/" + active.length + "개 질문 작성"));
      const progress = element("span", "export-section-bar");
      progress.append(element("i"));
      progress.firstChild.style.width = rate + "%";
      row.append(copy, progress, element("b", "", rate + "%"));
      list.append(row);
    });
  }

  async function loadMarkdownPreview() {
    exportedMarkdown = "";
    copyMarkdownButton.disabled = true;
    exportPreview.classList.add("d-none");
    exportPreviewState.className = "export-preview-state";
    exportPreviewState.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> 미리보기를 준비하고 있습니다.';
    try {
      const response = await fetch(exportApi, {credentials: "same-origin"});
      if (!response.ok) throw new Error("PRD 내보내기 내용을 불러오지 못했습니다.");
      exportedMarkdown = await response.text();
      exportPreview.textContent = exportedMarkdown;
      exportPreview.classList.remove("d-none");
      exportPreviewState.classList.add("d-none");
      copyMarkdownButton.disabled = false;
    } catch (error) {
      exportPreviewState.className = "export-preview-state danger";
      exportPreviewState.textContent = error.message;
    }
  }

  function updateSaveAllButton() {
    const count = pendingAnswers.size;
    saveAllButton.disabled = savingAllAnswers || count === 0;
    saveAllButton.innerHTML = savingAllAnswers
      ? '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> 저장 중…'
      : '<i class="bi bi-cloud-check"></i> 전체 저장' + (count ? ' <span class="save-count">' + count + '</span>' : '');
  }

  function findQuestion(questionId) {
    return detail.sections.flatMap(function (section) { return section.questions; })
      .find(function (question) { return String(question.id) === String(questionId); });
  }

  function refreshAnswerProgress() {
    const completed = detail.sections.flatMap(function (section) { return section.questions; })
      .filter(function (item) { return !item.is_held && item.is_completed; }).length;
    const total = detail.sections.reduce(function (count, section) {
      return count + section.questions.filter(function (item) { return !item.is_held; }).length;
    }, 0);
    detail.prd.completion_rate = total ? Math.round(completed * 100 / total) : 0;
    renderProgress(detail);
    renderSteps(detail);
  }

  async function toggleQuestionHold(question, button) {
    const key = String(question.id);
    const nextHeld = !question.is_held;
    if (nextHeld && pendingAnswers.has(key) && !window.confirm("저장하지 않은 답변이 있습니다. 답변을 버리고 질문을 보류하시겠습니까?")) return;
    button.disabled = true;
    try {
      const data = await api(detailApi + "questions/" + question.id + "/hold/", {
        method: "PATCH",
        body: JSON.stringify({is_held: nextHeld, version: question.version})
      });
      question.is_held = data.question.is_held;
      question.version = data.question.version;
      question.is_completed = data.question.is_completed;
      question.answer = data.question.answer;
      detail.prd.completion_rate = data.completion_rate;
      if (nextHeld) pendingAnswers.delete(key);
      renderDetail(detail);
      markEvaluationStale();
      showAlert(nextHeld ? "질문을 보류했습니다. 진행도와 AI 진단에서 제외됩니다." : "질문 보류를 해제했습니다.", "success");
    } catch (error) {
      if (error.code === "version_conflict") {
        pendingAnswers.delete(key);
        renderDetail(await api(detailApi));
        showAlert("다른 사용자가 먼저 질문을 변경했습니다. 최신 내용을 다시 불러왔습니다.", "warning");
      } else showAlert(error.message);
    } finally {
      button.disabled = false;
    }
  }

  async function persistPendingAnswer(questionId) {
    const editor = sectionsRoot.querySelector('.question-editor[data-question-id="' + questionId + '"]');
    const question = findQuestion(questionId);
    if (!editor || !question || !pendingAnswers.has(questionId)) return false;
    const data = await api(detailApi + "questions/" + question.id + "/answer/", {
      method: "PATCH",
      body: JSON.stringify({content: pendingAnswers.get(questionId), version: Number(editor.dataset.version)})
    });
    editor.dataset.version = data.version;
    editor.dataset.savedContent = data.answer?.content || "";
    question.version = data.version;
    question.answer = data.answer;
    question.is_completed = data.is_completed;
    pendingAnswers.delete(questionId);
    markEvaluationStale();
    const savedState = editor.closest(".write-question")?.querySelector(".write-answer-footer small");
    if (savedState) {
      savedState.textContent = "방금 저장됨";
      savedState.className = "small text-success";
    }
    const questionSave = editor.closest(".write-question")?.querySelector(".question-save-button");
    if (questionSave) questionSave.disabled = true;
    return true;
  }

  async function handleAnswerSaveError(error) {
    if (error.code === "version_conflict") {
      pendingAnswers.clear();
      const latest = await api(detailApi);
      renderDetail(latest);
      showAlert("다른 사용자가 먼저 답변을 수정했습니다. 최신 내용을 다시 불러왔습니다.", "warning");
    } else {
      showAlert(error.message);
    }
  }

  async function saveOneAnswer(questionId, button) {
    if (!pendingAnswers.has(questionId)) return;
    clearAlert();
    button.disabled = true;
    button.textContent = "저장 중…";
    try {
      await persistPendingAnswer(questionId);
      refreshAnswerProgress();
      showAlert("답변을 저장했습니다.", "success");
    } catch (error) {
      await handleAnswerSaveError(error);
    } finally {
      button.textContent = "저장";
      button.disabled = !pendingAnswers.has(questionId);
      updateSaveAllButton();
    }
  }

  async function saveAllAnswers() {
    if (savingAllAnswers || !pendingAnswers.size) return;
    clearAlert();
    savingAllAnswers = true;
    updateSaveAllButton();
    let savedCount = 0;
    try {
      const questionIds = Array.from(pendingAnswers.keys());
      for (const questionId of questionIds) {
        if (await persistPendingAnswer(questionId)) savedCount += 1;
      }
      refreshAnswerProgress();
      showAlert(savedCount + "개 답변을 저장했습니다.", "success");
    } catch (error) {
      await handleAnswerSaveError(error);
    } finally {
      savingAllAnswers = false;
      updateSaveAllButton();
    }
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

  function evaluationStateLabel(score) {
    if (score >= 80) return "충족도 높음";
    if (score >= 60) return "핵심 보완 필요";
    if (score >= 35) return "구체화 필요";
    return "초기 정리 필요";
  }

  function evaluationStatusLabel(status) {
    return {good: "충족", needs_improvement: "보완 필요", missing: "근거 부족"}[status] || "확인 필요";
  }

  function setEvaluationNotice(message, kind) {
    evaluationAlert.textContent = message;
    evaluationAlert.className = "evaluation-alert" + (kind ? " " + kind : "");
  }

  function renderEvaluationEmpty() {
    document.getElementById("write-score-value").textContent = "—";
    document.getElementById("write-score-ring").style.setProperty("--score", "0%");
    document.getElementById("write-score-ring").classList.add("is-pending");
    document.getElementById("score-state").textContent = "진단 전";
    document.getElementById("write-score-label").textContent = "아직 진단하지 않았습니다";
    document.getElementById("write-score-feedback").textContent = "AI 진단을 실행하면 세 관점의 충족도와 보완점을 한 번에 확인할 수 있습니다.";
    document.getElementById("write-section-diagnostics").replaceChildren(
      Object.assign(element("div", "evaluation-empty"), {innerHTML: '<i class="bi bi-stars"></i><span>AI 진단 후 섹션별 피드백이 표시됩니다.</span>'})
    );
    evaluationAlert.className = "evaluation-alert d-none";
  }

  function renderEvaluationResult(job, isCurrent) {
    const output = job.output || {};
    const score = Number(output.overall_score || 0);
    const ring = document.getElementById("write-score-ring");
    ring.classList.remove("is-pending");
    ring.style.setProperty("--score", score + "%");
    document.getElementById("write-score-value").textContent = score;
    document.getElementById("score-state").textContent = isCurrent ? (output.persona_label || "AI 진단") : "업데이트 필요";
    document.getElementById("write-score-label").textContent = evaluationStateLabel(score);
    document.getElementById("write-score-feedback").textContent = decodeSafeText(output.summary || "진단 결과를 확인해 주세요.");
    if (!isCurrent) setEvaluationNotice("진단 후 답변이 변경되었습니다. 최신 내용으로 다시 진단해 주세요.", "warning");
    else evaluationAlert.className = "evaluation-alert d-none";

    const root = document.getElementById("write-section-diagnostics");
    root.replaceChildren();
    (output.sections || []).forEach(function (row) {
      const section = detail?.sections.find(function (item) { return item.id === row.section_id; });
      if (!section) return;
      const button = element("button", "diagnosis-card");
      button.type = "button";
      button.dataset.state = row.status === "good" ? "good" : row.status === "missing" ? "empty" : "working";
      const copy = element("span", "diagnosis-copy");
      copy.append(element("strong", "", section.title), element("span", "", decodeSafeText(row.feedback)));
      button.append(
        element("span", "diagnosis-badge", evaluationStatusLabel(row.status)),
        copy,
        element("small", "", row.score + "점")
      );
      button.addEventListener("click", function () {
        activeSectionId = section.id;
        renderDetail(detail);
        document.querySelector('[data-section-id="' + section.id + '"]')?.scrollIntoView({behavior: "smooth", block: "start"});
      });
      root.append(button);
    });
  }

  function renderSelectedEvaluation() {
    const selected = evaluationResults[evaluationPersona];
    if (selected?.job?.status === "succeeded") {
      renderEvaluationResult(selected.job, selected.isCurrent);
      return;
    }
    renderEvaluationEmpty();
    if (selected?.job) setEvaluationNotice("선택한 관점의 AI 진단이 진행 중입니다.", "working");
  }

  function setEvaluationBusy(busy, jobIds) {
    evaluationJobIds = busy ? (Array.isArray(jobIds) ? jobIds : (jobIds ? [jobIds] : [])) : [];
    evaluationButton.disabled = busy || !detail?.permissions.can_request_ai || detail?.prd.status === "completed";
    evaluationButton.innerHTML = busy
      ? '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span> 세 관점 진단 중…'
      : '<i class="bi bi-stars"></i> AI 진단하기';
    evaluationCancel.classList.toggle("d-none", !busy || !evaluationJobIds.length);
  }

  async function loadEvaluation() {
    try {
      const data = await api(aiBase + "evaluation/");
      evaluationResults = {};
      evaluationPersonas.forEach(function (persona) {
        const job = data.jobs?.[persona];
        if (job) evaluationResults[persona] = {
          job: job,
          isCurrent: Boolean(data.is_current_by_persona?.[persona])
        };
      });
      if (!Object.keys(evaluationResults).length && data.job?.output?.persona) {
        evaluationResults[data.job.output.persona] = {job: data.job, isCurrent: data.is_current};
      }
      if (!Object.keys(evaluationResults).length) {
        renderEvaluationEmpty();
        return;
      }
      const activeJobs = Object.values(evaluationResults).map(function (item) { return item.job; })
        .filter(function (job) { return ["queued", "running", "retry_wait", "cancel_requested"].includes(job.status); });
      renderSelectedEvaluation();
      if (activeJobs.length) {
        setEvaluationNotice("PM·엔지니어링·투자자 관점 진단을 진행하고 있습니다.", "working");
        setEvaluationBusy(true, activeJobs.map(function (job) { return job.id; }));
        await Promise.allSettled(activeJobs.map(function (job) { return pollJob(job.id, function () {}); }));
        setEvaluationBusy(false);
        await loadEvaluation();
      }
    } catch (error) {
      setEvaluationNotice(error.message, "danger");
    }
  }

  function markEvaluationStale() {
    Object.values(evaluationResults).forEach(function (result) { result.isCurrent = false; });
    if (document.getElementById("write-score-value").textContent !== "—") {
      document.getElementById("score-state").textContent = "업데이트 필요";
      setEvaluationNotice("답변이 변경되었습니다. 저장을 마친 뒤 다시 진단해 주세요.", "warning");
    }
  }

  document.querySelectorAll("[data-evaluation-persona]").forEach(function (button) {
    button.addEventListener("click", function () {
      evaluationPersona = button.dataset.evaluationPersona;
      document.querySelectorAll("[data-evaluation-persona]").forEach(function (item) {
        item.classList.toggle("active", item === button);
      });
      renderSelectedEvaluation();
    });
  });

  evaluationButton.addEventListener("click", async function () {
    clearAlert();
    setEvaluationBusy(true);
    setEvaluationNotice("세 관점의 AI 진단 요청을 등록하고 있습니다.", "working");
    try {
      const batchKey = crypto.randomUUID();
      const requests = await Promise.allSettled(evaluationPersonas.map(function (persona) {
        return api(aiBase + "evaluation/run/", {
          method: "POST",
          headers: {"Idempotency-Key": batchKey + "-" + persona},
          body: JSON.stringify({persona: persona})
        });
      }));
      const jobs = requests.filter(function (result) { return result.status === "fulfilled"; })
        .map(function (result) { return result.value; });
      if (!jobs.length) throw requests.find(function (result) { return result.status === "rejected"; }).reason;
      setEvaluationBusy(true, jobs.map(function (job) { return job.id; }));
      await Promise.allSettled(jobs.map(function (job) { return pollJob(job.id, function () {}); }));
      await loadEvaluation();
      if (requests.some(function (result) { return result.status === "rejected"; })) {
        setEvaluationNotice("일부 관점의 진단을 시작하지 못했습니다. 다시 실행해 주세요.", "warning");
      }
    } catch (error) {
      setEvaluationNotice(error.message, "danger");
    } finally {
      setEvaluationBusy(false);
    }
  });

  evaluationCancel.addEventListener("click", async function () {
    if (!evaluationJobIds.length) return;
    try {
      await Promise.allSettled(evaluationJobIds.map(function (jobId) {
        return api(aiBase + "jobs/" + jobId + "/cancel/", {method: "POST", body: "{}"});
      }));
      setEvaluationNotice("진행 중인 진단 요청을 취소했습니다.", "warning");
    } catch (error) {
      setEvaluationNotice(error.message, "danger");
    } finally {
      setEvaluationBusy(false);
    }
  });

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
      if (answer && answer.tagName === "TEXTAREA") {
        answer.value = data.answer.content;
        answer.dataset.version = data.question_version;
      } else if (answer) answer.textContent = data.answer.content;
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

  async function updateMetadata(changes) {
    const data = await api(detailApi + "metadata/", {
      method: "PATCH",
      body: JSON.stringify({...changes, version: detail.prd.version})
    });
    detail.prd.status = data.status;
    detail.prd.deadline = data.deadline;
    detail.prd.version = data.version;
    renderDetail(detail);
    return data;
  }

  statusControl.addEventListener("change", async function () {
    const previous = detail.prd.status;
    const requested = statusControl.value;
    statusControl.disabled = true;
    try {
      if (requested === "completed") {
        if (!window.confirm("PRD를 완료하면 일반 편집이 잠깁니다. 완료하시겠습니까?")) return;
        try {
          await api(detailApi + "complete/", {method: "POST", body: JSON.stringify({confirm_incomplete: false})});
        } catch (error) {
          const needsConfirmation = error.details && error.details.confirm_incomplete;
          if (!needsConfirmation || !window.confirm("아직 답변하지 않은 질문이 있습니다. 그래도 완료하시겠습니까?")) throw error;
          await api(detailApi + "complete/", {method: "POST", body: JSON.stringify({confirm_incomplete: true})});
        }
        renderDetail(await api(detailApi));
        showAlert("PRD를 완료했습니다.", "success");
      } else if (previous === "completed") {
        if (requested !== "in_progress") throw new Error("완료된 PRD는 먼저 진행 중으로 다시 열어 주세요.");
        const reason = window.prompt("PRD를 다시 여는 이유를 입력해 주세요.");
        if (!reason || !reason.trim()) return;
        await api(detailApi + "reopen/", {method: "POST", body: JSON.stringify({reason: reason.trim()})});
        renderDetail(await api(detailApi));
        showAlert("PRD를 다시 열었습니다.", "success");
      } else {
        await updateMetadata({status: requested});
        showAlert("PRD 상태를 변경했습니다.", "success");
      }
    } catch (error) {
      statusControl.value = previous;
      showAlert(error.message);
    } finally {
      statusControl.disabled = false;
      if (detail) statusControl.value = detail.prd.status;
    }
  });

  deadlineInput.addEventListener("change", async function () {
    const previous = detail.prd.deadline || "";
    deadlineInput.disabled = true;
    try {
      await updateMetadata({deadline: deadlineInput.value || null});
      showAlert(deadlineInput.value ? "목표 마감일을 변경했습니다." : "목표 마감일을 삭제했습니다.", "success");
    } catch (error) {
      deadlineInput.value = previous;
      showAlert(error.message);
    } finally {
      deadlineInput.disabled = !detail.permissions.can_edit_deadline || detail.prd.status === "completed";
    }
  });

  document.getElementById("complete-prd").addEventListener("click", async function (event) {
    const button = event.currentTarget;
    if (!window.confirm("PRD를 완료하면 일반 편집이 잠깁니다. 완료하시겠습니까?")) return;
    button.disabled = true;
    try {
      await api(detailApi + "complete/", {method: "POST", body: JSON.stringify({confirm_incomplete: false})});
      renderDetail(await api(detailApi));
      showAlert("PRD를 완료했습니다.", "success");
    } catch (error) {
      const needsConfirmation = error.details && error.details.confirm_incomplete;
      if (needsConfirmation && window.confirm("아직 답변하지 않은 질문이 있습니다. 그래도 완료하시겠습니까?")) {
        await api(detailApi + "complete/", {method: "POST", body: JSON.stringify({confirm_incomplete: true})});
        renderDetail(await api(detailApi));
        showAlert("미완성 질문을 확인하고 PRD를 완료했습니다.", "success");
      } else if (!needsConfirmation) showAlert(error.message);
    } finally {
      button.disabled = false;
    }
  });

  document.getElementById("reopen-prd").addEventListener("click", async function (event) {
    const reason = window.prompt("PRD를 다시 여는 이유를 입력해 주세요.");
    if (!reason || !reason.trim()) return;
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await api(detailApi + "reopen/", {method: "POST", body: JSON.stringify({reason: reason.trim()})});
      renderDetail(await api(detailApi));
      showAlert("PRD를 다시 열었습니다.", "success");
    } catch (error) {
      showAlert(error.message);
    } finally {
      button.disabled = false;
    }
  });

  function avatarColor(user) {
    const rawId = Number(user.user_id);
    if (Number.isSafeInteger(rawId)) return (Math.imul(rawId, -1640531527) >>> 0) % 8;
    const name = user.display_name || "?";
    let hash = 0;
    for (let index = 0; index < name.length; index += 1) hash = ((hash * 31) + name.charCodeAt(index)) >>> 0;
    return hash % 8;
  }

  function participantAvatar(participant, className) {
    const name = participant.display_name || "?";
    const avatar = element("span", className + " avatar-color-" + avatarColor(participant), name.slice(0, 2));
    avatar.title = name + " · " + participant.role;
    return avatar;
  }

  function showParticipantAlert(message, kind) {
    participantAlert.className = "alert alert-" + (kind || "danger");
    participantAlert.textContent = message;
  }

  function clearParticipantAlert() {
    participantAlert.className = "alert d-none";
    participantAlert.textContent = "";
  }

  function renderMemberAvatars(totalItems) {
    const members = document.getElementById("write-members");
    members.replaceChildren();
    currentParticipants.slice(0, 6).forEach(function (participant) {
      members.append(participantAvatar(participant, "write-member"));
    });
    if (totalItems > 6) {
      const more = element("span", "write-member avatar-color-7", "+" + (totalItems - 6));
      more.title = "추가 참여자 " + (totalItems - 6) + "명";
      members.append(more);
    }
  }

  function roleSelect(participant) {
    const select = element("select", "form-select form-select-sm");
    const roles = {editor: "편집자", tutor: "튜터", viewer: "뷰어"};
    Object.entries(roles).forEach(function (entry) { select.add(new Option(entry[1], entry[0])); });
    select.value = participant.role;
    select.setAttribute("aria-label", participant.display_name + " 역할");
    select.addEventListener("change", async function () {
      const previousRole = participant.role;
      select.disabled = true;
      try {
        await api(participantsApi + encodeURIComponent(participant.user_id) + "/", {
          method: "PATCH",
          body: JSON.stringify({role: select.value})
        });
        showParticipantAlert(participant.display_name + "님의 역할을 변경했습니다.", "success");
        await loadParticipants();
      } catch (error) {
        select.value = previousRole;
        showParticipantAlert(error.message);
      } finally {
        select.disabled = false;
      }
    });
    return select;
  }

  function renderParticipantManager() {
    document.getElementById("participant-count").textContent = currentParticipants.length + "명";
    participantList.replaceChildren();
    if (!currentParticipants.length) {
      participantList.append(element("div", "participant-empty", "등록된 참여자가 없습니다."));
      return;
    }
    const roleLabels = {owner: "소유자", editor: "편집자", tutor: "튜터", viewer: "뷰어"};
    currentParticipants.forEach(function (participant) {
      const row = element("div", "participant-person");
      const copy = element("div", "participant-person-copy");
      copy.append(element("strong", "", participant.display_name), element("small", "", roleLabels[participant.role] || participant.role));
      const actions = element("div", "participant-person-actions");
      if (participant.role === "owner") {
        actions.append(element("span", "badge rounded-pill text-bg-primary", "owner"));
      } else if (canManageParticipants) {
        const select = roleSelect(participant);
        const remove = element("button", "btn btn-sm btn-outline-danger", "제거");
        remove.type = "button";
        remove.addEventListener("click", async function () {
          if (!window.confirm(participant.display_name + "님을 이 PRD에서 제거하시겠습니까?")) return;
          remove.disabled = true;
          try {
            await api(participantsApi + encodeURIComponent(participant.user_id) + "/", {method: "DELETE"});
            showParticipantAlert(participant.display_name + "님을 참여자에서 제거했습니다.", "success");
            await loadParticipants();
          } catch (error) {
            showParticipantAlert(error.message);
            remove.disabled = false;
          }
        });
        actions.append(select, remove);
      } else {
        actions.append(element("span", "badge rounded-pill text-bg-light border", roleLabels[participant.role] || participant.role));
      }
      row.append(participantAvatar(participant, "participant-person-avatar"), copy, actions);
      participantList.append(row);
    });
  }

  async function loadParticipants() {
    if (!participantsApi) return;
    try {
      const data = await api(participantsApi + "?page_size=100");
      currentParticipants = data.items;
      renderMemberAvatars(data.pagination.total_items);
      renderParticipantManager();
    } catch (error) {
      document.getElementById("write-members").title = error.message;
      showParticipantAlert(error.message);
    }
  }

  function searchResultRow(user) {
    const row = element("div", "participant-result");
    const copy = element("div", "participant-person-copy");
    copy.append(element("strong", "", user.display_name || "이름 없음"), element("small", "", user.email || user.team?.team_name || "활성 사용자"));
    const select = element("select", "form-select form-select-sm");
    [["editor", "편집자"], ["tutor", "튜터"], ["viewer", "뷰어"]].forEach(function (role) { select.add(new Option(role[1], role[0])); });
    select.setAttribute("aria-label", (user.display_name || "사용자") + " 역할");
    const add = element("button", "btn btn-sm " + (user.selected ? "btn-light" : "btn-primary"), user.selected ? "추가됨" : "추가");
    add.type = "button";
    add.disabled = Boolean(user.selected);
    add.addEventListener("click", async function () {
      add.disabled = true;
      try {
        const result = await api(participantsApi, {
          method: "POST",
          body: JSON.stringify({user_id: user.user_id, role: select.value})
        });
        showParticipantAlert(result.created ? user.display_name + "님을 추가했습니다." : "이미 참여 중인 사용자입니다.", result.created ? "success" : "info");
        await loadParticipants();
        add.textContent = "추가됨";
      } catch (error) {
        showParticipantAlert(error.message);
        add.disabled = false;
      }
    });
    const actions = element("div", "participant-person-actions");
    actions.append(select, add);
    row.append(participantAvatar({...user, role: select.value}, "participant-person-avatar"), copy, actions);
    return row;
  }

  document.getElementById("participant-search-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    clearParticipantAlert();
    const query = document.getElementById("participant-search").value.trim();
    if (query.length < 2) {
      showParticipantAlert("이름을 2자 이상 입력해 주세요.", "warning");
      return;
    }
    participantResults.replaceChildren(element("div", "participant-empty", "검색 중…"));
    try {
      const params = new URLSearchParams({
        q: query,
        page_size: "12",
        selected_user_ids: currentParticipants.map(function (participant) { return participant.user_id; }).join(",")
      });
      const data = await api(participantSearchApi + "?" + params.toString());
      participantResults.replaceChildren();
      data.results.forEach(function (user) { participantResults.append(searchResultRow(user)); });
      if (!data.results.length) participantResults.append(element("div", "participant-empty", "검색 결과가 없습니다."));
    } catch (error) {
      participantResults.replaceChildren();
      showParticipantAlert(error.message);
    }
  });

  document.getElementById("participant-modal").addEventListener("show.bs.modal", loadParticipants);

  function showCommentAlert(message, kind) {
    commentPanelAlert.className = "alert alert-" + (kind || "danger") + " comment-panel-alert";
    commentPanelAlert.textContent = message;
  }

  function clearCommentAlert() {
    commentPanelAlert.className = "alert d-none comment-panel-alert";
    commentPanelAlert.textContent = "";
  }

  function commentDate(value) {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return "";
    return new Intl.DateTimeFormat("ko-KR", {month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit"}).format(parsed);
  }

  function questionLabel(questionId) {
    if (!detail || !questionId) return "PRD 전체";
    for (const section of detail.sections) {
      const question = section.questions.find(function (item) { return item.id === questionId; });
      if (question) return section.title + " · " + question.prompt;
    }
    return "질문 코멘트";
  }

  function renderCommentPagination(pagination) {
    commentPagination.replaceChildren();
    commentPagination.classList.toggle("d-none", pagination.total_pages <= 1);
    if (pagination.total_pages <= 1) return;
    const previous = element("button", "btn btn-sm btn-outline-secondary", "이전");
    const next = element("button", "btn btn-sm btn-outline-secondary", "다음");
    previous.type = next.type = "button";
    previous.disabled = pagination.page <= 1;
    next.disabled = pagination.page >= pagination.total_pages;
    previous.addEventListener("click", function () { loadComments(pagination.page - 1); });
    next.addEventListener("click", function () { loadComments(pagination.page + 1); });
    commentPagination.append(previous, element("span", "", pagination.page + " / " + pagination.total_pages), next);
  }

  function editComment(card, comment) {
    const content = card.querySelector(".comment-content");
    const actions = card.querySelector(".comment-actions");
    const editor = element("textarea", "form-control comment-edit-input");
    editor.maxLength = 4000;
    editor.value = comment.content;
    const editActions = element("div", "comment-edit-actions");
    const cancelEdit = element("button", "btn btn-sm btn-light", "취소");
    const saveEdit = element("button", "btn btn-sm btn-primary", "저장");
    cancelEdit.type = saveEdit.type = "button";
    cancelEdit.addEventListener("click", function () { editor.remove(); editActions.remove(); content.classList.remove("d-none"); actions.classList.remove("d-none"); });
    saveEdit.addEventListener("click", async function () {
      if (!editor.value.trim()) return showCommentAlert("코멘트 내용을 입력해 주세요.", "warning");
      saveEdit.disabled = true;
      try {
        await api(commentsApi + comment.id + "/", {method: "PATCH", body: JSON.stringify({content: editor.value.trim()})});
        showCommentAlert("코멘트를 수정했습니다.", "success");
        await loadComments(commentPage);
      } catch (error) { showCommentAlert(error.message); saveEdit.disabled = false; }
    });
    editActions.append(cancelEdit, saveEdit);
    content.classList.add("d-none"); actions.classList.add("d-none");
    content.after(editor, editActions);
    editor.focus();
  }

  async function deleteComment(comment) {
    if (!window.confirm("이 코멘트를 삭제하시겠습니까?")) return;
    try {
      await api(commentsApi + comment.id + "/", {method: "DELETE"});
      showCommentAlert("코멘트를 삭제했습니다.", "success");
      await loadComments(commentPage);
    } catch (error) { showCommentAlert(error.message); }
  }

  function renderComments(data) {
    const count = document.getElementById("comment-count");
    count.textContent = data.pagination.total_items;
    count.classList.toggle("d-none", data.pagination.total_items === 0);
    commentList.replaceChildren();
    if (!data.items.length) {
      commentList.append(element("div", "comment-empty", "아직 등록된 코멘트가 없습니다.\n첫 의견을 남겨보세요."));
      renderCommentPagination(data.pagination);
      return;
    }
    const typeLabels = {general: "일반", guidance: "지도", review: "리뷰", post_completion_review: "완료 후 리뷰"};
    const roleLabels = {owner: "소유자", editor: "편집자", tutor: "튜터", viewer: "뷰어"};
    data.items.forEach(function (comment) {
      const card = element("article", "comment-card");
      const head = element("div", "comment-card-head");
      const author = element("div", "comment-author");
      author.append(
        element("strong", "", comment.author.display_name),
        element("small", "", (roleLabels[comment.author.role_at_created] || comment.author.role_at_created) + " · " + commentDate(comment.created_at))
      );
      head.append(
        participantAvatar({user_id: comment.author.user_id, display_name: comment.author.display_name, role: comment.author.role_at_created}, "participant-person-avatar"),
        author,
        element("span", "comment-kind", typeLabels[comment.comment_type] || comment.comment_type)
      );
      card.append(head, element("p", "comment-content", comment.content));
      card.append(element("span", "comment-question", questionLabel(comment.section_question_id)));
      if (comment.can_modify) {
        const actions = element("div", "comment-actions");
        const edit = element("button", "btn btn-sm btn-light", "수정");
        const remove = element("button", "btn btn-sm btn-link text-danger", "삭제");
        edit.type = remove.type = "button";
        edit.addEventListener("click", function () { editComment(card, comment); });
        remove.addEventListener("click", function () { deleteComment(comment); });
        actions.append(edit, remove);
        card.append(actions);
      }
      commentList.append(card);
    });
    renderCommentPagination(data.pagination);
  }

  async function loadComments(page) {
    if (!commentsApi) return;
    commentPage = Math.max(1, Number(page || commentPage || 1));
    try {
      let data = await api(commentsApi + "?page=" + commentPage + "&page_size=" + commentPageSize);
      if (!data.items.length && commentPage > 1) {
        commentPage -= 1;
        data = await api(commentsApi + "?page=" + commentPage + "&page_size=" + commentPageSize);
      }
      renderComments(data);
    } catch (error) {
      commentList.replaceChildren(element("div", "comment-empty", "코멘트를 불러오지 못했습니다."));
      showCommentAlert(error.message);
    }
  }

  commentForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    clearCommentAlert();
    const content = commentInput.value.trim();
    if (!content) {
      showCommentAlert("코멘트 내용을 입력해 주세요.", "warning");
      return;
    }
    commentSubmit.disabled = true;
    try {
      const selectedQuestionId = commentTarget.value ? Number(commentTarget.value) : null;
      const body = {content: content, section_question_id: selectedQuestionId};
      if (detail.prd.status === "completed" && detail.permissions.can_review_comment) body.comment_type = "post_completion_review";
      await api(commentsApi, {method: "POST", body: JSON.stringify(body)});
      commentInput.value = "";
      commentPage = 1;
      showCommentAlert("코멘트를 등록했습니다.", "success");
      await loadComments(1);
    } catch (error) {
      showCommentAlert(error.message);
    } finally {
      commentSubmit.disabled = false;
    }
  });

  document.getElementById("write-comments-panel").addEventListener("show.bs.offcanvas", function () {
    loadComments(commentPage);
  });

  function showContributionAlert(message, kind) {
    contributionAlert.className = "alert alert-" + (kind || "danger") + " contribution-alert";
    contributionAlert.textContent = message;
  }

  function contributionStatus(value) {
    return {pending: "계산 중", succeeded: "완료", failed: "실패"}[value] || value;
  }

  function renderContributions(data) {
    contributionList.replaceChildren();
    if (!data.items.length) {
      contributionList.append(element("div", "contribution-empty", "아직 생성된 기여도 평가가 없습니다."));
      return;
    }
    data.items.forEach(function (evaluation) {
      const card = element("article", "contribution-card");
      const head = element("div", "contribution-card-head");
      const title = element("div");
      title.append(element("strong", "", "평가 버전 " + evaluation.calculation_version), element("small", "", evaluation.calculated_at ? commentDate(evaluation.calculated_at) : "처리 대기 중"));
      head.append(title, element("span", "contribution-status " + evaluation.status, contributionStatus(evaluation.status)));
      card.append(head);
      if (evaluation.scores.length) {
        const scores = element("div", "contribution-scores");
        evaluation.scores.forEach(function (score) {
          const row = element("div", "contribution-score-row");
          const copy = element("div");
          copy.append(element("strong", "", score.display_name), element("small", "", "메모 " + Math.round(score.memo_contribution) + "% · 코멘트 " + Math.round(score.comment_contribution) + "%"));
          row.append(copy, element("b", "", Math.round(score.total_score) + "%"));
          scores.append(row);
        });
        card.append(scores);
      } else if (evaluation.status === "pending") card.append(element("p", "contribution-note", "백그라운드 작업이 평가를 처리하고 있습니다."));
      else card.append(element("p", "contribution-note", evaluation.failure_code ? "계산 실패: " + evaluation.failure_code : "표시할 점수가 없습니다."));
      if (evaluation.status === "failed") {
        const retry = element("button", "btn btn-sm btn-outline-primary contribution-retry", "동일 입력 재평가");
        retry.type = "button";
        retry.addEventListener("click", async function () {
          retry.disabled = true;
          try {
            await api(contributionsApi + evaluation.calculation_version + "/retry/", {method: "POST", body: "{}"});
            showContributionAlert("재평가를 요청했습니다.", "success");
            await loadContributions();
          } catch (error) { showContributionAlert(error.message); retry.disabled = false; }
        });
        card.append(retry);
      }
      contributionList.append(card);
    });
  }

  async function loadContributions() {
    if (!contributionsApi || !detail?.permissions.can_view_contributions) return;
    try { renderContributions(await api(contributionsApi)); }
    catch (error) { contributionList.replaceChildren(element("div", "contribution-empty", "기여도 결과를 불러오지 못했습니다.")); showContributionAlert(error.message); }
  }

  document.getElementById("write-contribution-panel").addEventListener("show.bs.offcanvas", loadContributions);
  saveAllButton.addEventListener("click", saveAllAnswers);

  exportModalElement.addEventListener("show.bs.modal", function () {
    setExportTab("check");
    renderExportCheck();
    downloadMarkdownLink.href = exportApi;
    loadMarkdownPreview();
  });
  document.getElementById("export-check-tab").addEventListener("click", function () {
    setExportTab("check");
  });
  document.getElementById("export-preview-tab").addEventListener("click", function () {
    setExportTab("preview");
  });
  copyMarkdownButton.addEventListener("click", async function () {
    if (!exportedMarkdown) return;
    try {
      await navigator.clipboard.writeText(exportedMarkdown);
      copyMarkdownButton.innerHTML = '<i class="bi bi-check2"></i> 복사됨';
      window.setTimeout(function () {
        copyMarkdownButton.innerHTML = '<i class="bi bi-clipboard"></i> 복사';
      }, 1800);
    } catch (_error) {
      showAlert("클립보드에 복사하지 못했습니다. 미리보기 내용을 직접 복사해 주세요.");
    }
  });

  document.getElementById("structure-view").addEventListener("click", function () {
    questionListMode = false;
    document.body.classList.remove("question-list-mode");
    this.classList.add("active");
    document.getElementById("question-view").classList.remove("active");
    renderDetail(detail);
  });
  document.getElementById("question-view").addEventListener("click", function () {
    questionListMode = true;
    document.body.classList.add("question-list-mode");
    this.classList.add("active");
    document.getElementById("structure-view").classList.remove("active");
    renderDetail(detail);
  });
  input.addEventListener("keydown", function (event) {
    if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); form.requestSubmit(); }
  });

  api(detailApi)
    .then(function (data) { renderDetail(data); loadParticipants(); loadComments(); loadEvaluation(); return loadConversation(); })
    .catch(function (error) { showAlert(error.message); });
}());
