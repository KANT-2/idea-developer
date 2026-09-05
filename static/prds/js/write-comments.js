(function () {
  "use strict";

  window.PrdWriteComments = {
    create: function (options) {
      var api = options.api;
      var element = options.element;
      var participantAvatar = options.participantAvatar;
      var commentsApi = options.commentsApi;
      var getDetail = options.getDetail;
      var commentList = document.getElementById("comment-list");
      var commentForm = document.getElementById("comment-form");
      var commentInput = document.getElementById("comment-input");
      var commentTarget = document.getElementById("comment-target");
      var commentSubmit = document.getElementById("comment-submit");
      var commentPanelAlert = document.getElementById("comment-panel-alert");
      var commentPagination = document.getElementById("comment-pagination");
      var commentPage = 1;
      var commentPageSize = 10;

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
        if (!getDetail() || !questionId) return "PRD 전체";
        for (const section of getDetail().sections) {
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
            const localContent = editor.value.trim();
            await api(commentsApi + comment.id + "/", {
              method: "PATCH",
              body: JSON.stringify({content: localContent, version: comment.version})
            });
            showCommentAlert("코멘트를 수정했습니다.", "success");
            await loadComments(commentPage);
          } catch (error) {
            if (error.code === "version_conflict") {
              const latestContent = error.details?.latest?.content || "";
              if (error.details?.latest?.version) comment.version = error.details.latest.version;
              const preview = latestContent.length > 120 ? latestContent.slice(0, 120) + "…" : latestContent;
              showCommentAlert("다른 사용자가 먼저 수정했습니다. 최신 내용: “" + preview + "” 작성 중인 내용은 입력창에 유지했습니다.", "warning");
            } else showCommentAlert(error.message);
            saveEdit.disabled = false;
          }
        });
        editActions.append(cancelEdit, saveEdit);
        content.classList.add("d-none"); actions.classList.add("d-none");
        content.after(editor, editActions);
        editor.focus();
      }

      async function deleteComment(comment) {
        if (!window.confirm("이 코멘트를 삭제하시겠습니까?")) return;
        try {
          await api(commentsApi + comment.id + "/", {
            method: "DELETE",
            body: JSON.stringify({version: comment.version})
          });
          showCommentAlert("코멘트를 삭제했습니다.", "success");
          await loadComments(commentPage);
        } catch (error) {
          if (error.code === "version_conflict") {
            await loadComments(commentPage);
            showCommentAlert("다른 사용자가 먼저 코멘트를 변경했습니다. 최신 목록을 불러왔습니다.", "warning");
          } else showCommentAlert(error.message);
        }
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
          if (getDetail().prd.status === "completed" && getDetail().permissions.can_review_comment) body.comment_type = "post_completion_review";
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


      return {load: loadComments};
    }
  };
}());
