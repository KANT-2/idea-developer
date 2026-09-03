(function () {
  "use strict";
  const root = document.getElementById("prd-home-app");
  if (!root) return;
  const state = {tab: "all", status: "", sort: "default", page: 1};
  const labels = {new_product: "신규 프로젝트", new_feature: "신규 기능", improvement: "기능 개선", in_progress: "진행 중", completed: "완료", held: "홀딩", dropped: "드랍"};
  const list = document.getElementById("home-list");
  const loading = document.getElementById("home-loading");
  const empty = document.getElementById("home-empty");
  const alertBox = document.getElementById("home-alert");

  function el(tag, className, text) { const node = document.createElement(tag); if (className) node.className = className; if (text !== undefined) node.textContent = text; return node; }
  function showError(message) { alertBox.className = "alert alert-danger"; alertBox.textContent = message; }
  function pageUrl(id) { return "/ideas/prds/" + encodeURIComponent(id) + "/"; }
  function brainstormUrl(id) { return pageUrl(id) + "brainstorm/"; }
  async function fetchData() {
    loading.classList.remove("d-none"); list.replaceChildren(); empty.classList.add("d-none"); alertBox.className = "alert d-none";
    const query = new URLSearchParams({tab: state.tab, sort: state.sort, page: String(state.page)}); if (state.status) query.append("status", state.status);
    try {
      const response = await fetch(root.dataset.apiUrl + "?" + query, {credentials: "same-origin"}); const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error?.message || "홈 정보를 불러오지 못했습니다.");
      render(payload.data);
    } catch (error) { showError(error.message); } finally { loading.classList.add("d-none"); }
  }
  function render(data) {
    document.getElementById("home-greeting").textContent = "안녕하세요, " + data.user.display_name + "님 👋";
    const k = data.kpis; document.getElementById("kpi-total").textContent = k.total_prds + "건"; document.getElementById("kpi-progress").textContent = k.in_progress_prds + "건"; document.getElementById("kpi-average").textContent = k.average_completion_rate + "%"; document.getElementById("kpi-completed").textContent = k.completed_prds + "건"; document.getElementById("kpi-ai").textContent = k.ai_coaching_count + "회"; document.getElementById("kpi-due").textContent = k.due_this_week + "건";
    list.replaceChildren(); empty.classList.toggle("d-none", data.items.length !== 0);
    data.items.forEach(function (item) {
      const col = el("div", "col-12 col-md-6 col-xl-4"); const card = el("article", "card h-100 border idea-card-hover idea-clickable"); card.tabIndex = 0; card.setAttribute("role", "link");
      const body = el("div", "card-body d-flex flex-column"); const badges = el("div", "d-flex flex-wrap gap-2 mb-2"); badges.append(el("span", "badge text-bg-light", labels[item.prd_type] || item.prd_type), el("span", "badge " + (item.status === "completed" ? "text-bg-success" : item.status === "in_progress" ? "text-bg-warning" : "text-bg-secondary"), labels[item.status] || item.status)); if (item.show_new_badge) badges.append(el("span", "badge text-bg-primary", "NEW"));
      const title = el("h3", "h6 fw-bold", item.title); const description = el("p", "small text-secondary prd-card-description", item.description || "한 줄 소개가 없습니다.");
      const progressText = el("div", "d-flex justify-content-between small mb-1"); progressText.append(el("span", "text-secondary", "완성도"), el("strong", "", item.completion_rate + "%")); const progress = el("div", "progress mb-3"); progress.style.height = "6px"; const bar = el("div", "progress-bar"); bar.style.width = item.completion_rate + "%"; progress.append(bar);
      const footer = el("div", "d-flex justify-content-between align-items-center mt-auto pt-2 border-top"); const avatars = el("div", "d-flex align-items-center"); item.participants.forEach(function (p) { const a = el("span", "participant-avatar", (p.display_name || "?").slice(0, 2)); a.title = p.display_name; avatars.append(a); }); if (item.participant_count > 4) avatars.append(el("span", "small text-secondary ms-1", "+" + (item.participant_count - 4)));
      const meta = el("div", "small text-secondary text-end", (item.d_day || "마감일 없음") + " · AI " + item.ai_coaching_count + "회"); footer.append(avatars, meta); body.append(badges, title, description, progressText, progress, footer); card.append(body);
      card.addEventListener("click", function () { window.location.href = pageUrl(item.id); }); card.addEventListener("keydown", function (event) { if (event.key === "Enter") window.location.href = pageUrl(item.id); });
      const brain = el("a", "btn btn-sm btn-outline-primary position-absolute top-0 end-0 m-3", "아이디어 맵"); brain.href = brainstormUrl(item.id); brain.addEventListener("click", function (event) { event.stopPropagation(); }); card.style.position = "relative"; body.style.paddingTop = "3.25rem"; card.append(brain); col.append(card); list.append(col);
    }); renderPages(data.pagination);
  }
  function renderPages(p) { const rootPages = document.getElementById("home-pagination"); rootPages.replaceChildren(); for (let i = 1; i <= p.total_pages; i += 1) { const li = el("li", "page-item" + (i === p.page ? " active" : "")); const button = el("button", "page-link", String(i)); button.addEventListener("click", function () { state.page = i; fetchData(); }); li.append(button); rootPages.append(li); } }
  document.querySelectorAll(".home-tab").forEach(function (button) { button.addEventListener("click", function () { state.tab = button.dataset.tab; state.page = 1; document.querySelectorAll(".home-tab").forEach(function (item) { item.className = "btn " + (item === button ? "btn-primary" : "btn-outline-primary") + " home-tab"; }); fetchData(); }); });
  document.getElementById("home-status").addEventListener("change", function (event) { state.status = event.target.value; state.page = 1; fetchData(); }); document.getElementById("home-sort").addEventListener("change", function (event) { state.sort = event.target.value; state.page = 1; fetchData(); });
  document.querySelectorAll(".home-kpi[data-status]").forEach(function (button) { button.addEventListener("click", function () { state.status = button.dataset.status; document.getElementById("home-status").value = state.status; state.page = 1; fetchData(); }); });
  fetchData();
}());
