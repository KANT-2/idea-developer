(function () {
  "use strict";

  const root = document.getElementById("prd-write-app");
  if (!root) return;

  const detailApi = root.dataset.detailApi;
  const exportApi = root.dataset.exportApi;
  const participantsApi = root.dataset.participantsApi;
  const participantSearchApi = root.dataset.participantSearchApi;
  const participantTeamApi = root.dataset.participantTeamApi;
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
  const commentForm = document.getElementById("comment-form");
  const commentTarget = document.getElementById("comment-target");
  const saveAllButton = document.getElementById("save-all-answers");
  const statusPicker = document.getElementById("prd-status-picker");
  const statusControl = document.getElementById("prd-status-control");
  const statusControlLabel = document.getElementById("prd-status-control-label");
  const statusOptions = Array.from(document.querySelectorAll("[data-prd-status-option]"));
  const deadlineInput = document.getElementById("write-deadline-input");
  const deadlineWarning = document.getElementById("write-deadline-warning");
  const evaluationButton = document.getElementById("run-evaluation");
  const evaluationCancel = document.getElementById("cancel-evaluation");
  const evaluationAlert = document.getElementById("evaluation-alert");
  const exportModalElement = document.getElementById("export-modal");
  const exportPreview = document.getElementById("export-preview");
  const exportPreviewState = document.getElementById("export-preview-state");
  const copyMarkdownButton = document.getElementById("copy-prd-markdown");
  const downloadMarkdownLink = document.getElementById("download-prd-markdown");
  const settingsButton = document.getElementById("prd-settings-button");
  const settingsModalElement = document.getElementById("prd-settings-modal");
  const settingsModal = bootstrap.Modal.getOrCreateInstance(settingsModalElement);
  const settingsEditSection = document.getElementById("prd-settings-edit-section");
  const settingsDangerSection = document.getElementById("prd-settings-danger-section");
  const summaryForm = document.getElementById("prd-summary-form");
  const summaryTitleInput = document.getElementById("prd-summary-title");
  const summaryDescriptionInput = document.getElementById("prd-summary-description");
  const summarySaveButton = document.getElementById("prd-summary-save");
  const summaryError = document.getElementById("prd-summary-error");
  const deletePrdButton = document.getElementById("delete-prd");
  const deleteConfirmElement = document.getElementById("write-delete-confirm-modal");
  const deleteConfirmModal = bootstrap.Modal.getOrCreateInstance(deleteConfirmElement);
  const confirmDeletePrdButton = document.getElementById("confirm-delete-prd");
  const deleteError = document.getElementById("write-delete-error");
  const answerConflictElement = document.getElementById("answer-conflict-modal");
  const answerConflictModal = bootstrap.Modal.getOrCreateInstance(answerConflictElement);
  const answerConflictLatest = document.getElementById("answer-conflict-latest");
  const answerConflictLocal = document.getElementById("answer-conflict-local");
  let answerConflictQuestionId = null;
  let detail = null;
  let activeJobId = null;
  // undefined means the initial render; null means the user collapsed every section.
  let activeSectionId = undefined;
  let questionListMode = false;
  let canManageParticipants = false;
  let canCreateComments = false;
  const pendingAnswers = new Map();
  let savingAllAnswers = false;
  const statusLabels = {in_progress: "진행 중", completed: "완료", held: "보류", dropped: "드랍"};
  const evaluationPersonas = ["pm", "engineering", "investor"];
  let evaluationPersona = "pm";
  let evaluationResults = {};
  let evaluationJobIds = [];
  let exportedMarkdown = "";
  let alertTimer = null;
  let canRequestAi = false;
  let conversationToken = 0;
  const pollIntervalMs = 1500;
  const pollTimeoutMs = 120000;
  const pollNetworkRetryLimit = 3;

  function localDateKey(date) {
    return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
  }

  function isPastDeadline(prd) {
    return Boolean(prd.deadline && prd.deadline < localDateKey(new Date()));
  }

  function renderDeadlineState(prd) {
    const control = deadlineInput.closest(".write-deadline");
    const today = localDateKey(new Date());
    const isOpen = !["completed", "dropped"].includes(prd.status);
    const overdue = isOpen && Boolean(prd.deadline && prd.deadline < today);
    const dueToday = isOpen && prd.deadline === today;
    control.classList.toggle("is-overdue", overdue);
    control.classList.toggle("is-today", dueToday);
    deadlineWarning.classList.toggle("d-none", !overdue && !dueToday);
    deadlineWarning.textContent = overdue ? "마감 지남" : dueToday ? "오늘 마감" : "";
    control.title = overdue
      ? "마감 기한이 지났습니다."
      : dueToday
        ? "오늘이 마감일입니다."
        : "목표 마감일";
  }

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
      // 글자 수로 자르지 않는다. 넘칠 때만 CSS가 말줄임표를 붙이고, 전체 제목은 툴팁으로 보여준다.
      const label = element("span", "", section.title);
      label.title = section.title;
      button.append(element("b", "", rate === 100 ? "✓" : String(index + 1)), label);
      button.addEventListener("click", function () { activeSectionId = section.id; renderDetail(detail); document.querySelector('[data-section-id="' + section.id + '"]')?.scrollIntoView({behavior: "smooth", block: "start"}); });
      steps.append(button);
    });
  }

  function renderDetail(data) {
    detail = data;
    if (activeSectionId === undefined && data.sections.length) activeSectionId = data.sections[0].id;
    document.getElementById("prd-heading").textContent = data.prd.title;
    document.getElementById("prd-description").textContent = data.prd.description || "한 줄 소개가 없습니다.";
    document.title = data.prd.title + " | Idea Developer";
    const status = document.getElementById("prd-status");
    status.textContent = statusLabels[data.prd.status] || data.prd.status;
    status.dataset.status = data.prd.status;
    statusControl.dataset.status = data.prd.status;
    statusControlLabel.textContent = statusLabels[data.prd.status] || data.prd.status;
    statusOptions.forEach(function (option) {
      const value = option.dataset.prdStatusOption;
      option.disabled = (data.prd.status === "completed" && !["completed", "in_progress"].includes(value))
        || (value === "completed" && !["in_progress", "completed"].includes(data.prd.status));
      option.classList.toggle("active", value === data.prd.status);
    });
    statusPicker.classList.toggle("d-none", !data.permissions.can_change_status);
    status.classList.toggle("d-none", Boolean(data.permissions.can_change_status));
    deadlineInput.value = data.prd.deadline || "";
    deadlineInput.disabled = !data.permissions.can_edit_deadline;
    deadlineInput.min = data.prd.auto_completed ? localDateKey(new Date()) : "";
    const canEditSummary = data.permissions.can_edit && data.prd.status !== "completed";
    settingsButton.classList.toggle("d-none", !canEditSummary && !data.permissions.can_delete);
    settingsEditSection.classList.toggle("d-none", !canEditSummary);
    settingsDangerSection.classList.toggle("d-none", !data.permissions.can_delete);
    document.getElementById("write-deadline-label").textContent = data.prd.deadline || "마감일 없음";
    renderDeadlineState(data.prd);
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
    canRequestAi = data.permissions.can_request_ai && data.prd.status !== "completed";
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
      const latestQuestion = error.details?.latest;
      const questionId = latestQuestion ? String(latestQuestion.id) : null;
      const localContent = questionId ? pendingAnswers.get(questionId) : null;
      const latest = await api(detailApi);
      renderDetail(latest);
      if (questionId && localContent !== undefined) {
        answerConflictQuestionId = questionId;
        answerConflictLatest.value = latestQuestion.answer?.content || "";
        answerConflictLocal.value = localContent;
        answerConflictModal.show();
      }
      showAlert("다른 사용자가 먼저 답변을 수정했습니다. 작성 중인 내용은 보존했습니다.", "warning");
    } else {
      showAlert(error.message);
    }
  }

  document.getElementById("answer-conflict-use-latest").addEventListener("click", function () {
    if (answerConflictQuestionId) pendingAnswers.delete(answerConflictQuestionId);
    answerConflictModal.hide();
    answerConflictQuestionId = null;
    renderDetail(detail);
    updateSaveAllButton();
  });

  document.getElementById("answer-conflict-keep-local").addEventListener("click", function () {
    answerConflictModal.hide();
    const editor = answerConflictQuestionId
      ? sectionsRoot.querySelector('.question-editor[data-question-id="' + answerConflictQuestionId + '"]')
      : null;
    if (editor) {
      editor.value = answerConflictLocal.value;
      pendingAnswers.set(answerConflictQuestionId, answerConflictLocal.value);
      editor.focus();
    }
    answerConflictQuestionId = null;
    updateSaveAllButton();
  });

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

  // 코치가 특정 질문의 답변 수정을 제안했을 때, 사용자가 승인해야만 반영되는 카드.
  function buildProposalCard(message) {
    const proposal = message.proposal;
    const card = element("div", "coach-proposal");

    const head = element("div", "coach-proposal-head");
    head.append(element("i", "bi bi-pencil-square"), element("strong", "", "이 답변을 고칠까요?"));
    card.append(head);

    const target = element("div", "coach-proposal-target");
    target.append(
      element("span", "coach-proposal-section", decodeSafeText(proposal.section_title || "")),
      element("span", "coach-proposal-question", decodeSafeText(proposal.question_prompt || ""))
    );
    card.append(target);

    if (proposal.reason) {
      card.append(element("p", "coach-proposal-reason", decodeSafeText(proposal.reason)));
    }

    card.append(element("div", "coach-proposal-preview", decodeSafeText(proposal.content || "")));

    const actions = element("div", "coach-proposal-actions");
    const yes = element("button", "btn btn-primary btn-sm", "네, 반영할게요");
    const no = element("button", "btn btn-outline-secondary btn-sm", "아니오");
    yes.type = "button";
    no.type = "button";
    if (!canRequestAi) {
      yes.disabled = true;
      yes.title = "현재 권한 또는 PRD 상태에서는 반영할 수 없습니다.";
    }
    yes.addEventListener("click", function () {
      applyProposal(message.job.id, proposal, yes, no, card);
    });
    no.addEventListener("click", function () {
      declineProposal(message.job.id, yes, no, card);
    });
    actions.append(no, yes);
    card.append(actions);
    return card;
  }

  async function declineProposal(jobId, yes, no, card) {
    yes.disabled = true;
    no.disabled = true;
    no.textContent = "처리 중…";
    try {
      // 서버에 남겨야 새로고침해도 되살아나지 않고, 다음 요청에서 같은 제안을 막을 수 있다.
      await api(aiBase + "chat/" + jobId + "/decline/", {method: "POST", body: "{}"});
      card.replaceChildren(element("p", "coach-proposal-declined", "제안을 반영하지 않았습니다."));
    } catch (error) {
      yes.disabled = !canRequestAi;
      no.disabled = false;
      no.textContent = "아니오";
      showAlert(error.message);
    }
  }

  async function applyProposal(jobId, proposal, yes, no, card) {
    yes.disabled = true;
    no.disabled = true;
    yes.textContent = "반영 중…";
    try {
      const data = await api(aiBase + "chat/" + jobId + "/apply/", {
        method: "POST",
        body: JSON.stringify({
          question_version: proposal.question_version,
          content: proposal.content
        })
      });
      const editor = sectionsRoot.querySelector('[data-question-id="' + data.question_id + '"]');
      if (editor && editor.tagName === "TEXTAREA") {
        editor.value = data.answer.content;
        editor.dataset.version = data.question_version;
      } else if (editor) {
        editor.textContent = data.answer.content;
      }
      const target = detail?.sections
        .flatMap(function (section) { return section.questions; })
        .find(function (question) { return question.id === data.question_id; });
      if (target) {
        target.version = data.question_version;
        target.answer = {content: data.answer.content};
      }
      card.replaceChildren(element("p", "coach-proposal-applied", "이 답변에 반영했습니다."));
      showAlert("코치 제안을 PRD 답변에 반영했습니다.", "success");
      refreshAnswerProgress();
    } catch (error) {
      yes.disabled = false;
      no.disabled = false;
      yes.textContent = "네, 반영할게요";
      showAlert(
        error.code === "version_conflict"
          ? "그 사이 답변이 바뀌었습니다. 대화를 새로고침한 뒤 다시 시도해 주세요."
          : error.message
      );
    }
  }

  async function loadConversation() {
    const token = ++conversationToken;
    messagesRoot.replaceChildren(element("p", "text-secondary", "대화를 불러오는 중입니다."));
    try {
      const query = scope.value ? "?section_id=" + encodeURIComponent(scope.value) : "";
      const data = await api(aiBase + "conversation/" + query);
      if (token !== conversationToken) return;
      messagesRoot.replaceChildren();
      if (!data.messages.length) {
        messagesRoot.append(element("p", "text-secondary", "이 범위에서 AI 코치와 나눈 대화가 없습니다."));
      }
      data.messages.forEach(function (message) {
        const wrap = element("div", "mb-2");
        const bubble = element(
          "div",
          "coach-message coach-message-" + message.role,
          message.content
        );
        wrap.append(bubble);
        if (message.role === "assistant" && message.proposal && message.job?.id) {
          wrap.append(buildProposalCard(message));
        }
        const stuck = ["failed", "timed_out", "cancelled", "queued", "running", "retry_wait"];
        if (message.role === "user" && canRequestAi && stuck.includes(message.job?.status)) {
          const retry = element("button", "btn btn-link btn-sm float-end", "다시 시도");
          retry.type = "button";
          retry.addEventListener("click", function () { retryJob(message.job.id); });
          wrap.append(retry);
        }
        messagesRoot.append(wrap);
      });
      messagesRoot.scrollTop = messagesRoot.scrollHeight;
    } catch (error) {
      if (token !== conversationToken) return;
      messagesRoot.replaceChildren(element("p", "text-danger", error.message));
    }
  }

  function setBusy(busy, jobId) {
    // 권한이 없으면 작업이 끝나도 입력창을 다시 열지 않는다.
    submit.disabled = busy || !canRequestAi;
    input.disabled = busy || !canRequestAi;
    activeJobId = jobId || null;
    cancel.classList.toggle("d-none", !busy || !jobId);
  }

  async function pollJob(jobId, onSuccess) {
    const pending = ["queued", "running", "retry_wait", "cancel_requested"];
    const deadline = Date.now() + pollTimeoutMs;
    let networkFailures = 0;
    for (;;) {
      await new Promise(function (resolve) { setTimeout(resolve, pollIntervalMs); });

      let job;
      try {
        job = await api(aiBase + "jobs/" + jobId + "/");
        networkFailures = 0;
      } catch (error) {
        // 일시적인 통신 오류로 폴링을 끝내지 않는다. 서버에서는 작업이 계속 진행 중일 수 있다.
        networkFailures += 1;
        if (networkFailures >= pollNetworkRetryLimit) {
          showAlert("서버와 연결이 끊겼습니다. 잠시 후 대화를 새로고침해 결과를 확인해 주세요.");
          return null;
        }
        continue;
      }

      if (!pending.includes(job.status)) {
        if (job.status === "succeeded") onSuccess(job);
        else if (job.status === "cancelled") showAlert("AI 요청을 취소했습니다.", "secondary");
        else showAlert(job.error?.message || "AI 요청이 완료되지 않았습니다.");
        return job;
      }

      if (Date.now() > deadline) {
        showAlert(
          "AI 응답이 오지 않아 대기를 멈췄습니다. 작업 처리기(run_job_worker)가 실행 중인지 확인해 주세요."
        );
        return job;
      }
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
    document.getElementById("write-score-progress").style.strokeDashoffset = "100";
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
    document.getElementById("write-score-progress").style.strokeDashoffset = String(100 - Math.max(0, Math.min(100, score)));
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

  scope.addEventListener("change", loadConversation);

  async function updateMetadata(changes) {
    const data = await api(detailApi + "metadata/", {
      method: "PATCH",
      body: JSON.stringify({...changes, version: detail.prd.version})
    });
    detail.prd.title = data.title;
    detail.prd.description = data.description;
    detail.prd.status = data.status;
    detail.prd.deadline = data.deadline;
    detail.prd.version = data.version;
    renderDetail(detail);
    return data;
  }

  settingsModalElement.addEventListener("show.bs.modal", function () {
    summaryTitleInput.value = detail?.prd.title || "";
    summaryDescriptionInput.value = detail?.prd.description || "";
    summaryError.classList.add("d-none");
    summaryError.textContent = "";
    summaryForm.classList.remove("was-validated");
  });

  summaryForm.addEventListener("submit", async function (event) {
    event.preventDefault();
    if (!summaryForm.checkValidity()) {
      summaryForm.classList.add("was-validated");
      return;
    }
    summarySaveButton.disabled = true;
    summaryError.classList.add("d-none");
    try {
      await updateMetadata({
        title: summaryTitleInput.value.trim(),
        description: summaryDescriptionInput.value.trim()
      });
      settingsModal.hide();
      showAlert("PRD 제목과 한 줄 소개를 수정했습니다.", "success");
    } catch (error) {
      if (error.code === "version_conflict") {
        const latest = await api(detailApi);
        renderDetail(latest);
        summaryTitleInput.value = latest.prd.title;
        summaryDescriptionInput.value = latest.prd.description || "";
        summaryError.textContent = "다른 사용자가 먼저 수정했습니다. 최신 제목과 소개를 불러왔습니다.";
      } else summaryError.textContent = error.message;
      summaryError.classList.remove("d-none");
    } finally {
      summarySaveButton.disabled = false;
    }
  });

  function showAfterHidden(currentElement, nextModal) {
    currentElement.addEventListener("hidden.bs.modal", function showNext() {
      currentElement.removeEventListener("hidden.bs.modal", showNext);
      nextModal.show();
    });
    bootstrap.Modal.getOrCreateInstance(currentElement).hide();
  }

  deletePrdButton.addEventListener("click", function () {
    document.getElementById("write-delete-prd-title").textContent = detail.prd.title;
    deleteError.classList.add("d-none");
    deleteError.textContent = "";
    confirmDeletePrdButton.disabled = false;
    showAfterHidden(settingsModalElement, deleteConfirmModal);
  });

  confirmDeletePrdButton.addEventListener("click", async function () {
    confirmDeletePrdButton.disabled = true;
    deleteError.classList.add("d-none");
    try {
      await api(detailApi + "delete/", {
        method: "DELETE",
        body: JSON.stringify({version: detail.prd.version})
      });
      window.location.href = "/ideas/?deleted=1";
    } catch (error) {
      confirmDeletePrdButton.disabled = false;
      deleteError.textContent = error.message;
      deleteError.classList.remove("d-none");
    }
  });

  async function changePrdStatus(requested) {
    const previous = detail.prd.status;
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
        if (detail.prd.auto_completed && isPastDeadline(detail.prd)) {
          showAlert("자동 완료된 PRD입니다. 먼저 마감 기한을 오늘 이후로 변경해 주세요.", "warning");
          deadlineInput.focus();
          return;
        }
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
      if (error.code === "version_conflict") {
        renderDetail(await api(detailApi));
        showAlert("다른 사용자가 먼저 PRD를 변경했습니다. 최신 상태를 불러왔습니다.", "warning");
      } else showAlert(error.message);
    } finally {
      statusControl.disabled = false;
      if (detail) {
        statusControl.dataset.status = detail.prd.status;
        statusControlLabel.textContent = statusLabels[detail.prd.status] || detail.prd.status;
      } else {
        statusControl.dataset.status = previous;
      }
    }
  }

  statusOptions.forEach(function (option) {
    option.addEventListener("click", function () {
      if (!option.disabled && option.dataset.prdStatusOption !== detail.prd.status) {
        changePrdStatus(option.dataset.prdStatusOption);
      }
    });
  });

  deadlineInput.addEventListener("change", async function () {
    const previous = detail.prd.deadline || "";
    deadlineInput.disabled = true;
    try {
      await updateMetadata({deadline: deadlineInput.value || null});
      showAlert(deadlineInput.value ? "목표 마감일을 변경했습니다." : "목표 마감일을 삭제했습니다.", "success");
    } catch (error) {
      if (error.code === "version_conflict") {
        renderDetail(await api(detailApi));
        showAlert("다른 사용자가 먼저 PRD를 변경했습니다. 최신 마감일을 불러왔습니다.", "warning");
      } else {
        deadlineInput.value = previous;
        showAlert(error.message);
      }
    } finally {
      deadlineInput.disabled = !detail.permissions.can_edit_deadline;
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
    if (detail.prd.auto_completed && isPastDeadline(detail.prd)) {
      showAlert("자동 완료된 PRD입니다. 먼저 마감 기한을 오늘 이후로 변경해 주세요.", "warning");
      deadlineInput.focus();
      return;
    }
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

  const participantController = window.PrdWriteParticipants.create({
    api: api,
    element: element,
    participantsApi: participantsApi,
    participantSearchApi: participantSearchApi,
    participantTeamApi: participantTeamApi,
    canManageParticipants: function () { return canManageParticipants; }
  });

  const commentController = window.PrdWriteComments.create({
    api: api,
    element: element,
    participantAvatar: participantController.avatar,
    commentsApi: commentsApi,
    getDetail: function () { return detail; }
  });

  const contributionController = window.PrdWriteContributions.create({
    api: api,
    element: element,
    contributionsApi: contributionsApi,
    getDetail: function () { return detail; }
  });
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
    .then(function (data) {
      renderDetail(data);
      participantController.load();
      commentController.load();
      loadEvaluation();
      return loadConversation();
    })
    .catch(function (error) { showAlert(error.message); });
}());
