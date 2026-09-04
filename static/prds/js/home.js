(function () {
  "use strict";
  const root = document.getElementById("prd-home-app");
  if (!root) return;
  const state = {scope: "mine", tab: "all", status: "", sort: "default", page: 1};
  const labels = {new_product: "신규 프로젝트", new_feature: "신규 기능", improvement: "기능 개선", in_progress: "진행 중", completed: "완료", held: "홀딩", dropped: "드랍"};
  const list = document.getElementById("home-list");
  const loading = document.getElementById("home-loading");
  const empty = document.getElementById("home-empty");
  const alertBox = document.getElementById("home-alert");

  function el(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
  function avatarColor(user) {
    const rawId = Number(user.user_id);
    if (Number.isSafeInteger(rawId)) return (Math.imul(rawId, -1640531527) >>> 0) % 8;
    const name = user.display_name || "?";
    let hash = 0;
    for (let index = 0; index < name.length; index += 1) hash = ((hash * 31) + name.charCodeAt(index)) >>> 0;
    return hash % 8;
  }
  function showError(message) { alertBox.className = "alert alert-danger"; alertBox.textContent = message; }
  function pageUrl(id) { return "/ideas/prds/" + encodeURIComponent(id) + "/"; }
  function brainstormUrl(id) { return pageUrl(id) + "brainstorm/"; }
  function localDateKey(date) {
    return [date.getFullYear(), String(date.getMonth() + 1).padStart(2, "0"), String(date.getDate()).padStart(2, "0")].join("-");
  }
  function relativeTime(value) {
    const seconds = Math.max(0, Math.floor((Date.now() - new Date(value).getTime()) / 1000));
    if (seconds < 60) return "방금 전";
    if (seconds < 3600) return Math.floor(seconds / 60) + "분 전";
    if (seconds < 86400) return Math.floor(seconds / 3600) + "시간 전";
    if (seconds < 172800) return "어제";
    if (seconds < 604800) return Math.floor(seconds / 86400) + "일 전";
    return new Intl.DateTimeFormat("ko-KR", {month: "numeric", day: "numeric"}).format(new Date(value));
  }
  function renderRecentList(target, activities) {
    target.replaceChildren();
    if (!activities.length) {
      target.append(el("div", "home-activity-empty", "아직 표시할 활동이 없습니다."));
      return;
    }
    activities.forEach(function (activity) {
      const link = el("a", "home-recent-item");
      link.href = pageUrl(activity.prd_id);
      const user = {user_id: activity.actor_user_id, display_name: activity.actor_display_name};
      const avatar = el("span", "home-recent-avatar avatar-color-" + avatarColor(user), (activity.actor_display_name || "?").slice(0, 2));
      const copy = el("div", "home-recent-copy");
      const sentence = el("p");
      sentence.append(
        el("strong", "", activity.actor_display_name),
        document.createTextNode("님이 "),
        el("em", "", activity.prd_title),
        document.createTextNode("의 " + activity.description)
      );
      const time = el("time", "", relativeTime(activity.created_at));
      time.dateTime = activity.created_at;
      copy.append(sentence, time);
      link.append(avatar, copy);
      target.append(link);
    });
  }
  function renderActivity(data) {
    const weeklyRoot = document.getElementById("home-weekly-activity");
    const recentRoot = document.getElementById("home-recent-activity");
    if (!weeklyRoot || !recentRoot) return;
    const days = data.weekly_activity || [];
    const maximum = Math.max(1, ...days.map(function (day) { return day.count; }));
    const today = localDateKey(new Date());
    weeklyRoot.replaceChildren();
    days.forEach(function (day) {
      const item = el("div", "home-activity-day" + (day.date === today ? " is-today" : ""));
      const track = el("div", "home-activity-track");
      const bar = el("i", "home-activity-bar");
      bar.style.height = (day.count ? Math.max(12, Math.round(day.count * 100 / maximum)) : 6) + "%";
      track.title = day.date + " · " + day.count + "회";
      track.append(bar);
      item.append(track, el("span", "", day.day_label), el("strong", "", day.count ? day.count + "회" : "–"));
      weeklyRoot.append(item);
    });

    const activities = data.recent_activity || [];
    renderRecentList(recentRoot, activities);
    const moreButton = document.getElementById("recent-activity-more");
    if (moreButton) moreButton.classList.toggle("d-none", (data.recent_activity_pagination?.total_items || 0) <= activities.length);
  }
  async function fetchData() {
    loading.classList.remove("d-none"); list.replaceChildren(); empty.classList.add("d-none"); alertBox.className = "alert d-none";
    const query = new URLSearchParams({scope: state.scope, tab: state.tab, sort: state.sort, page: String(state.page)}); if (state.status) query.append("status", state.status);
    try {
      const response = await fetch(root.dataset.apiUrl + "?" + query, {credentials: "same-origin"}); const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message || "홈 정보를 불러오지 못했습니다.");
      render(payload.data);
    } catch (error) { showError(error.message); } finally { loading.classList.add("d-none"); }
  }
  function render(data) {
    document.getElementById("home-greeting").textContent = "안녕하세요, " + data.user.display_name + "님 👋";
    const k = data.kpis; document.getElementById("kpi-total").textContent = k.total_prds + "건"; document.getElementById("kpi-progress").textContent = k.in_progress_prds + "건"; document.getElementById("kpi-average").textContent = k.average_completion_rate + "%"; document.getElementById("kpi-completed").textContent = k.completed_prds + "건"; document.getElementById("kpi-ai").textContent = k.ai_coaching_count + "회"; document.getElementById("kpi-due").textContent = k.due_this_week + "건";
    renderActivity(data);
    list.replaceChildren(); empty.classList.toggle("d-none", data.items.length !== 0);
    document.getElementById("home-empty-title").textContent = state.scope === "viewer" ? "뷰어로 참여한 PRD가 없습니다." : "조건에 맞는 PRD가 없습니다.";
    document.getElementById("home-empty-create").classList.toggle("d-none", state.scope === "viewer");
    data.items.forEach(function (item) {
      const col = el("div", "col-12 col-md-6 col-xl-4"); const card = el("article", "card h-100 border idea-card-hover idea-clickable"); card.tabIndex = 0; card.setAttribute("role", "link");
      const body = el("div", "card-body d-flex flex-column"); const badges = el("div", "d-flex flex-wrap gap-2 mb-2"); badges.append(el("span", "badge text-bg-light", labels[item.prd_type] || item.prd_type), el("span", "badge " + (item.status === "completed" ? "text-bg-success" : item.status === "in_progress" ? "text-bg-warning" : "text-bg-secondary"), labels[item.status] || item.status)); if (item.my_role === "viewer") badges.append(el("span", "badge viewer-role-badge", "뷰어")); if (item.show_new_badge) badges.append(el("span", "badge text-bg-primary", "NEW"));
      const title = el("h3", "h6 fw-bold", item.title); const description = el("p", "small text-secondary prd-card-description", item.description || "한 줄 소개가 없습니다.");
      const progressText = el("div", "d-flex justify-content-between small mb-1"); progressText.append(el("span", "text-secondary", "완성도"), el("strong", "", item.completion_rate + "%")); const progress = el("div", "progress mb-3"); progress.style.height = "6px"; const bar = el("div", "progress-bar"); bar.style.width = item.completion_rate + "%"; progress.append(bar);
      const footer = el("div", "d-flex justify-content-between align-items-center mt-auto pt-2 border-top"); const avatars = el("div", "d-flex align-items-center"); item.participants.forEach(function (p) { const a = el("span", "participant-avatar avatar-color-" + avatarColor(p), (p.display_name || "?").slice(0, 2)); a.title = p.display_name; avatars.append(a); }); if (item.participant_count > 4) avatars.append(el("span", "small text-secondary ms-1", "+" + (item.participant_count - 4)));
      const meta = el("div", "small text-secondary text-end", (item.d_day || "마감일 없음") + " · AI " + item.ai_coaching_count + "회"); footer.append(avatars, meta); body.append(badges, title, description, progressText, progress, footer); card.append(body);
      card.addEventListener("click", function () { window.location.href = pageUrl(item.id); }); card.addEventListener("keydown", function (event) { if (event.key === "Enter") window.location.href = pageUrl(item.id); });
      const brain = el("a", "btn btn-sm btn-outline-primary position-absolute top-0 end-0 m-3", "아이디어 맵"); brain.href = brainstormUrl(item.id); brain.addEventListener("click", function (event) { event.stopPropagation(); }); card.style.position = "relative"; body.style.paddingTop = "3.25rem"; card.append(brain); col.append(card); list.append(col);
    }); renderPages(data.pagination);
  }
  function renderPages(p) { const rootPages = document.getElementById("home-pagination"); rootPages.replaceChildren(); for (let i = 1; i <= p.total_pages; i += 1) { const li = el("li", "page-item" + (i === p.page ? " active" : "")); const button = el("button", "page-link", String(i)); button.addEventListener("click", function () { state.page = i; fetchData(); }); li.append(button); rootPages.append(li); } }
  async function fetchRecentActivity(page) {
    const modalList = document.getElementById("recent-activity-modal-list");
    const modalLoading = document.getElementById("recent-activity-modal-loading");
    const modalAlert = document.getElementById("recent-activity-modal-alert");
    if (!modalList || !root.dataset.recentActivityApiUrl) return;
    modalLoading.classList.remove("d-none");
    modalAlert.classList.add("d-none");
    modalList.replaceChildren();
    try {
      const query = new URLSearchParams({page: String(page), page_size: "8"});
      const response = await fetch(root.dataset.recentActivityApiUrl + "?" + query, {credentials: "same-origin"});
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message || "최근 활동을 불러오지 못했습니다.");
      renderRecentList(modalList, payload.data.items);
      renderRecentPages(payload.data.pagination);
    } catch (error) {
      modalAlert.textContent = error.message;
      modalAlert.classList.remove("d-none");
    } finally {
      modalLoading.classList.add("d-none");
    }
  }
  function renderRecentPages(pagination) {
    const paginationRoot = document.getElementById("recent-activity-pagination");
    paginationRoot.replaceChildren();
    for (let page = 1; page <= pagination.total_pages; page += 1) {
      const item = el("li", "page-item" + (page === pagination.page ? " active" : ""));
      const button = el("button", "page-link", String(page));
      button.type = "button";
      button.setAttribute("aria-label", "최근 활동 " + page + "페이지");
      button.addEventListener("click", function () { fetchRecentActivity(page); });
      item.append(button);
      paginationRoot.append(item);
    }
  }
  document.querySelectorAll(".home-scope-tab").forEach(function (button) { button.addEventListener("click", function () { state.scope = button.dataset.scope; state.page = 1; document.querySelectorAll(".home-scope-tab").forEach(function (item) { const active = item === button; item.classList.toggle("active", active); item.setAttribute("aria-selected", String(active)); }); document.getElementById("home-scope-description").textContent = state.scope === "viewer" ? "읽기 권한으로 참여한 PRD를 모아봅니다." : "작성하거나 편집에 참여하는 PRD입니다."; fetchData(); }); });
  document.querySelectorAll(".home-tab").forEach(function (button) { button.addEventListener("click", function () { state.tab = button.dataset.tab; state.page = 1; document.querySelectorAll(".home-tab").forEach(function (item) { item.className = "btn " + (item === button ? "btn-primary" : "btn-outline-primary") + " home-tab"; }); fetchData(); }); });
  document.getElementById("home-status").addEventListener("change", function (event) { state.status = event.target.value; state.page = 1; fetchData(); }); document.getElementById("home-sort").addEventListener("change", function (event) { state.sort = event.target.value; state.page = 1; fetchData(); });
  document.querySelectorAll(".home-kpi[data-status]").forEach(function (button) { button.addEventListener("click", function () { state.status = button.dataset.status; document.getElementById("home-status").value = state.status; state.page = 1; fetchData(); }); });
  document.getElementById("recent-activity-modal")?.addEventListener("show.bs.modal", function () { fetchRecentActivity(1); });
  fetchData();
}());
