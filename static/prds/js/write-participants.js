(function () {
  "use strict";

  window.PrdWriteParticipants = {
    create: function (options) {
      var api = options.api;
      var element = options.element;
      var participantsApi = options.participantsApi;
      var participantSearchApi = options.participantSearchApi;
      var participantTeamApi = options.participantTeamApi;
      var participantAlert = document.getElementById("participant-alert");
      var participantList = document.getElementById("participant-list");
      var participantResults = document.getElementById("participant-search-results");
      var participantPicker = document.getElementById("participant-picker");
      var participantPickerToggle = document.getElementById("manage-participants");
      var participantSearchInput = document.getElementById("participant-search");
      var participantSearchHelp = document.getElementById("participant-search-help");
      var participantSearchSpinner = document.getElementById("participant-search-spinner");
      var participantAddTeam = document.getElementById("participant-add-team");
      var currentParticipants = [];
      var participantTeamUsers = [];
      var participantTeamLoaded = false;
      var participantSearchTimer = null;
      var participantSearchSequence = 0;

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
        participantAlert.className = "write-participant-alert " + (kind || "danger");
        participantAlert.textContent = message;
      }

      function clearParticipantAlert() {
        participantAlert.className = "write-participant-alert d-none";
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
              body: JSON.stringify({role: select.value, version: participant.version})
            });
            showParticipantAlert(participant.display_name + "님의 역할을 변경했습니다.", "success");
            await loadParticipants();
          } catch (error) {
            select.value = previousRole;
            if (error.code === "version_conflict") {
              await loadParticipants();
              showParticipantAlert("다른 사용자가 먼저 역할을 변경했습니다. 최신 참여자 정보를 불러왔습니다.", "warning");
            } else showParticipantAlert(error.message);
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
          } else if (options.canManageParticipants()) {
            const select = roleSelect(participant);
            const remove = element("button", "btn btn-sm btn-outline-danger", "제거");
            remove.type = "button";
            remove.addEventListener("click", async function () {
              if (!window.confirm(participant.display_name + "님을 이 PRD에서 제거하시겠습니까?")) return;
              remove.disabled = true;
              try {
                await api(participantsApi + encodeURIComponent(participant.user_id) + "/", {
                  method: "DELETE",
                  body: JSON.stringify({version: participant.version})
                });
                showParticipantAlert(participant.display_name + "님을 참여자에서 제거했습니다.", "success");
                await loadParticipants();
              } catch (error) {
                if (error.code === "version_conflict") {
                  await loadParticipants();
                  showParticipantAlert("다른 사용자가 먼저 참여자 정보를 변경했습니다. 최신 목록을 불러왔습니다.", "warning");
                } else showParticipantAlert(error.message);
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
          participantTeamState();
        } catch (error) {
          document.getElementById("write-members").title = error.message;
          showParticipantAlert(error.message);
        }
      }

      function participantTeamState() {
        if (!participantTeamLoaded) return;
        const currentIds = new Set(currentParticipants.map(function (participant) { return Number(participant.user_id); }));
        const available = participantTeamUsers.filter(function (user) { return !currentIds.has(Number(user.user_id)); });
        participantAddTeam.disabled = available.length === 0;
        document.getElementById("participant-team-state").textContent = available.length ? available.length + "명 추가" : "전원 추가됨";
      }

      async function loadParticipantTeam() {
        if (!participantTeamApi || participantTeamLoaded) { participantTeamState(); return; }
        try {
          const params = new URLSearchParams({
            selected_user_ids: currentParticipants.map(function (participant) { return participant.user_id; }).join(",")
          });
          const data = await api(participantTeamApi + "?" + params.toString());
          participantTeamUsers = data.users || [];
          participantTeamLoaded = true;
          document.getElementById("participant-team-name").textContent = data.team?.team_name || "현재 팀";
          document.getElementById("participant-team-description").textContent = data.team ? "현재 회차의 팀원을 한 번에 추가합니다." : (data.message || "연결된 회차 팀이 없습니다.");
          participantTeamState();
        } catch (error) {
          participantTeamUsers = [];
          participantTeamLoaded = true;
          participantAddTeam.disabled = true;
          document.getElementById("participant-team-description").textContent = "팀 정보를 불러오지 못했습니다. 이름으로 검색해 주세요.";
          document.getElementById("participant-team-state").textContent = "사용 불가";
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

      async function searchParticipants() {
        clearParticipantAlert();
        const query = participantSearchInput.value.trim();
        const sequence = ++participantSearchSequence;
        participantResults.replaceChildren();
        if (query.length < 2) {
          participantSearchHelp.classList.remove("d-none");
          participantSearchHelp.textContent = "이름을 2자 이상 입력해 주세요.";
          participantSearchSpinner.classList.add("d-none");
          return;
        }
        participantSearchHelp.classList.add("d-none");
        participantSearchSpinner.classList.remove("d-none");
        try {
          const params = new URLSearchParams({
            q: query,
            page_size: "12",
            selected_user_ids: currentParticipants.map(function (participant) { return participant.user_id; }).join(",")
          });
          const data = await api(participantSearchApi + "?" + params.toString());
          if (sequence !== participantSearchSequence) return;
          participantResults.replaceChildren();
          data.results.forEach(function (user) { participantResults.append(searchResultRow(user)); });
          if (!data.results.length) {
            participantSearchHelp.classList.remove("d-none");
            participantSearchHelp.textContent = "검색 결과가 없습니다.";
          }
        } catch (error) {
          if (sequence !== participantSearchSequence) return;
          participantResults.replaceChildren();
          participantSearchHelp.classList.remove("d-none");
          participantSearchHelp.textContent = error.message;
        } finally {
          if (sequence === participantSearchSequence) participantSearchSpinner.classList.add("d-none");
        }
      }

      function scheduleParticipantSearch(delay) {
        window.clearTimeout(participantSearchTimer);
        participantSearchTimer = window.setTimeout(searchParticipants, delay === undefined ? 280 : delay);
      }

      function setParticipantPicker(open) {
        participantPicker.classList.toggle("d-none", !open);
        participantPickerToggle.setAttribute("aria-expanded", String(open));
        if (open) {
          positionParticipantPicker();
          Promise.all([loadParticipants(), loadParticipantTeam()]).then(participantTeamState);
          window.setTimeout(function () { participantSearchInput.focus(); }, 0);
        }
      }

      function positionParticipantPicker() {
        if (participantPicker.classList.contains("d-none")) return;
        const buttonRect = participantPickerToggle.getBoundingClientRect();
        const right = Math.max(12, window.innerWidth - buttonRect.right);
        participantPicker.style.top = Math.round(buttonRect.bottom + 8) + "px";
        participantPicker.style.right = Math.round(right) + "px";
      }

      participantPickerToggle.addEventListener("click", function () {
        setParticipantPicker(participantPicker.classList.contains("d-none"));
      });
      document.addEventListener("mousedown", function (event) {
        if (!participantPicker.classList.contains("d-none") && !event.target.closest("#write-members-wrap")) setParticipantPicker(false);
      });
      window.addEventListener("resize", positionParticipantPicker);
      participantSearchInput.addEventListener("input", function () { scheduleParticipantSearch(); });
      participantSearchInput.addEventListener("keydown", function (event) {
        if (event.key === "Enter") { event.preventDefault(); scheduleParticipantSearch(0); }
        if (event.key === "Escape") setParticipantPicker(false);
      });
      participantAddTeam.addEventListener("click", async function () {
        const currentIds = new Set(currentParticipants.map(function (participant) { return Number(participant.user_id); }));
        const available = participantTeamUsers.filter(function (user) { return !currentIds.has(Number(user.user_id)); });
        if (!available.length) return;
        participantAddTeam.disabled = true;
        document.getElementById("participant-team-state").textContent = "추가 중…";
        let added = 0;
        try {
          for (const user of available) {
            const result = await api(participantsApi, {method: "POST", body: JSON.stringify({user_id: user.user_id, role: "editor"})});
            if (result.created) added += 1;
          }
          await loadParticipants();
          participantTeamState();
          showParticipantAlert(added + "명의 팀원을 추가했습니다.", "success");
        } catch (error) {
          await loadParticipants();
          participantTeamState();
          showParticipantAlert(error.message);
        }
      });


      return {load: loadParticipants, avatar: participantAvatar};
    }
  };
}());
