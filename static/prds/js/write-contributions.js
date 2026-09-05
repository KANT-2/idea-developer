(function () {
  "use strict";

  window.PrdWriteContributions = {
    create: function (options) {
      var api = options.api;
      var element = options.element;
      var contributionsApi = options.contributionsApi;
      var getDetail = options.getDetail;
      var contributionList = document.getElementById("contribution-list");
      var contributionAlert = document.getElementById("contribution-alert");

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
        if (!contributionsApi || !getDetail()?.permissions.can_view_contributions) return;
        try { renderContributions(await api(contributionsApi)); }
        catch (error) { contributionList.replaceChildren(element("div", "contribution-empty", "기여도 결과를 불러오지 못했습니다.")); showContributionAlert(error.message); }
      }

      document.getElementById("write-contribution-panel").addEventListener("show.bs.offcanvas", loadContributions);

      return {load: loadContributions};
    }
  };
}());
