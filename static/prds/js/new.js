(function () {
  "use strict";
  const root = document.getElementById("new-prd-app");
  if (!root) return;

  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const currentUserId = Number(root.dataset.currentUserId);
  const currentUserName = root.dataset.currentUserName || "나";
  const selected = new Map();
  let selectedType = "";
  let teamUsers = [];
  let teamLoaded = false;
  let searchTimer = null;
  let searchSequence = 0;

  const alertBox = document.getElementById("new-alert");
  const results = document.getElementById("participant-results");
  const selectedRoot = document.getElementById("selected-participants");
  const picker = document.getElementById("participant-picker");
  const pickerToggle = document.getElementById("participant-picker-toggle");
  const searchInput = document.getElementById("participant-search");
  const searchHelp = document.getElementById("participant-search-help");
  const searchSpinner = document.getElementById("participant-search-spinner");
  const addTeamButton = document.getElementById("add-team");

  async function api(url, options) {
    const response = await fetch(url, {credentials: "same-origin", ...options, headers: {"Content-Type": "application/json", "X-CSRFToken": csrf, ...(options?.headers || {})}});
    const body = await response.json();
    if (!response.ok || !body.ok) {
      const error = new Error(body.error?.message || "요청을 처리하지 못했습니다.");
      error.details = body.error?.details;
      throw error;
    }
    return body.data;
  }

  function requestKey() {
    return window.crypto?.randomUUID ? window.crypto.randomUUID() : Date.now() + "-" + Math.random();
  }

  function showError(error) {
    alertBox.className = "alert alert-danger";
    const details = error.details && typeof error.details === "object" ? " " + Object.values(error.details).flat().join(" ") : "";
    alertBox.textContent = error.message + details;
    window.scrollTo({top: 0, behavior: "smooth"});
  }

  function initials(name) {
    const compact = String(name || "?").trim().replace(/\s+/g, "");
    return compact.slice(0, 2) || "?";
  }

  function makeSelectedParticipant(user, owner) {
    const item = document.createElement("div");
    item.className = "selected-participant";
    item.title = user.display_name + (owner ? " · 소유자" : " · 편집자");
    const avatar = document.createElement("span");
    avatar.className = "selected-participant-avatar";
    avatar.textContent = initials(user.display_name);
    const name = document.createElement("span");
    name.className = "selected-participant-name";
    name.textContent = user.display_name;
    item.append(avatar, name);
    if (owner) {
      const badge = document.createElement("span");
      badge.className = "selected-participant-owner";
      badge.textContent = "본인";
      item.append(badge);
    } else {
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "selected-participant-remove";
      remove.setAttribute("aria-label", user.display_name + " 제거");
      remove.title = user.display_name + " 제거";
      remove.textContent = "−";
      remove.addEventListener("click", function () {
        selected.delete(Number(user.user_id));
        renderSelected();
        renderTeamState();
        if (searchInput.value.trim().length >= 2) scheduleSearch(0);
      });
      item.append(remove);
    }
    return item;
  }

  function renderSelected() {
    selectedRoot.replaceChildren();
    selectedRoot.append(makeSelectedParticipant({user_id: currentUserId, display_name: currentUserName}, true));
    selected.forEach(function (user) {
      if (Number(user.user_id) !== currentUserId) selectedRoot.append(makeSelectedParticipant(user, false));
    });
  }

  function addUser(user) {
    const userId = Number(user.user_id);
    if (!userId || userId === currentUserId || selected.has(userId)) return;
    selected.set(userId, {...user, user_id: userId});
    renderSelected();
    renderTeamState();
  }

  function allTeamMembersAdded() {
    const others = teamUsers.filter(function (user) { return Number(user.user_id) !== currentUserId; });
    return others.length > 0 && others.every(function (user) { return selected.has(Number(user.user_id)); });
  }

  function renderTeamState() {
    if (!teamLoaded) return;
    const otherCount = teamUsers.filter(function (user) { return Number(user.user_id) !== currentUserId; }).length;
    const allAdded = allTeamMembersAdded();
    addTeamButton.disabled = otherCount === 0 || allAdded;
    document.getElementById("team-add-state").textContent = allAdded ? "전원 추가됨" : otherCount ? otherCount + "명 추가" : "추가할 팀원 없음";
  }

  async function loadTeam() {
    if (teamLoaded) return;
    const description = document.getElementById("team-description");
    try {
      const data = await api(root.dataset.teamApi + "?selected_user_ids=" + encodeURIComponent(Array.from(selected.keys()).join(",")));
      teamUsers = data.users || [];
      teamLoaded = true;
      const teamAvailable = data.participants_enabled !== false && data.team;
      document.getElementById("team-name").textContent = data.team?.team_name || "현재 팀";
      description.textContent = teamAvailable ? "현재 회차의 팀원을 한 번에 추가합니다." : (data.message || "연결된 회차 팀이 없습니다.");
      renderTeamState();
    } catch (error) {
      teamLoaded = true;
      teamUsers = [];
      description.textContent = "팀 정보를 불러오지 못했습니다. 이름으로 검색해 주세요.";
      document.getElementById("team-add-state").textContent = "사용 불가";
      addTeamButton.disabled = true;
    }
  }

  function resultButton(user) {
    const button = document.createElement("button");
    const userId = Number(user.user_id);
    const isAdded = userId === currentUserId || selected.has(userId) || user.selected;
    button.type = "button";
    button.className = "participant-result-row";
    button.disabled = isAdded;
    const avatar = document.createElement("span");
    avatar.className = "participant-result-avatar";
    avatar.textContent = initials(user.display_name);
    const copy = document.createElement("span");
    copy.className = "participant-result-copy";
    const name = document.createElement("strong");
    name.textContent = user.display_name;
    const detail = document.createElement("small");
    detail.textContent = user.email || user.team?.team_name || "PRD 편집자로 추가";
    copy.append(name, detail);
    const state = document.createElement("span");
    state.className = "participant-result-state";
    state.textContent = isAdded ? "추가됨" : "추가";
    button.append(avatar, copy, state);
    button.addEventListener("click", function () {
      addUser(user);
      button.disabled = true;
      state.textContent = "추가됨";
    });
    return button;
  }

  async function search() {
    const query = searchInput.value.trim();
    const sequence = ++searchSequence;
    results.replaceChildren();
    if (query.length < 2) {
      searchHelp.classList.remove("d-none");
      searchHelp.textContent = "이름을 2자 이상 입력해 주세요.";
      searchSpinner.classList.add("d-none");
      return;
    }
    searchHelp.classList.add("d-none");
    searchSpinner.classList.remove("d-none");
    try {
      const ids = [currentUserId].concat(Array.from(selected.keys())).filter(Boolean);
      const params = new URLSearchParams({q: query, selected_user_ids: ids.join(",")});
      const data = await api(root.dataset.searchApi + "?" + params);
      if (sequence !== searchSequence) return;
      results.replaceChildren();
      data.results.forEach(function (user) { results.append(resultButton(user)); });
      if (!data.results.length) {
        searchHelp.classList.remove("d-none");
        searchHelp.textContent = "검색 결과가 없습니다.";
      }
    } catch (error) {
      if (sequence !== searchSequence) return;
      searchHelp.classList.remove("d-none");
      searchHelp.textContent = error.message;
    } finally {
      if (sequence === searchSequence) searchSpinner.classList.add("d-none");
    }
  }

  function scheduleSearch(delay) {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(search, delay === undefined ? 280 : delay);
  }

  function setPicker(open) {
    picker.classList.toggle("d-none", !open);
    pickerToggle.setAttribute("aria-expanded", String(open));
    if (open) {
      loadTeam();
      window.setTimeout(function () { searchInput.focus(); }, 0);
    }
  }

  document.querySelectorAll(".prd-type-card").forEach(function (button) {
    button.addEventListener("click", function () {
      selectedType = button.dataset.type;
      document.querySelectorAll(".prd-type-card").forEach(function (item) { item.classList.toggle("selected", item === button); });
      document.getElementById("to-details").disabled = false;
    });
  });

  function showStep(number) {
    document.getElementById("new-step-1").classList.toggle("d-none", number !== 1);
    document.getElementById("new-step-2").classList.toggle("d-none", number !== 2);
    document.getElementById("step-indicator-1").classList.toggle("active", number === 1);
    document.getElementById("step-indicator-2").classList.toggle("active", number === 2);
  }

  document.getElementById("to-details").addEventListener("click", function () { showStep(2); loadTeam(); });
  document.getElementById("back-to-types").addEventListener("click", function () { setPicker(false); showStep(1); });
  pickerToggle.addEventListener("click", function () { setPicker(picker.classList.contains("d-none")); });
  document.addEventListener("mousedown", function (event) {
    if (!picker.classList.contains("d-none") && !event.target.closest(".participant-add-wrap")) setPicker(false);
  });
  searchInput.addEventListener("input", function () { scheduleSearch(); });
  searchInput.addEventListener("keydown", function (event) {
    if (event.key === "Enter") { event.preventDefault(); scheduleSearch(0); }
    if (event.key === "Escape") setPicker(false);
  });
  addTeamButton.addEventListener("click", function () {
    teamUsers.forEach(addUser);
    renderTeamState();
  });

  document.getElementById("new-prd-form").addEventListener("submit", async function (event) {
    event.preventDefault();
    const form = event.currentTarget;
    if (!form.checkValidity()) { form.classList.add("was-validated"); return; }
    const submit = document.getElementById("create-prd");
    submit.disabled = true;
    submit.textContent = "생성 중…";
    try {
      const data = await api(root.dataset.createApi, {method: "POST", headers: {"Idempotency-Key": requestKey()}, body: JSON.stringify({prd_type: selectedType, title: document.getElementById("prd-title").value.trim(), description: document.getElementById("prd-description").value.trim(), deadline: document.getElementById("prd-deadline").value || null, participant_user_ids: Array.from(selected.keys())})});
      window.location.href = "/ideas/prds/" + data.prd.id + "/";
    } catch (error) {
      showError(error);
      submit.disabled = false;
      submit.textContent = "PRD 생성";
    }
  });

  renderSelected();
}());
