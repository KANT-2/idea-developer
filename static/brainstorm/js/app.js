(function () {
  "use strict";

  var mountNode = document.getElementById("brainstorm-root");
  if (!mountNode) return;
  if (!window.React || !window.ReactDOM) {
    mountNode.innerHTML =
      '<div class="alert alert-danger" role="alert">' +
      "브레인스토밍 화면 구성 요소를 불러오지 못했습니다. 네트워크 또는 CSP 설정을 확인해 주세요." +
      "</div>";
    return;
  }

  var apiBase = mountNode.dataset.apiBase;
  var rawInterval = Number(mountNode.dataset.pollingIntervalMs || 3000);
  var pollingInterval = Math.min(5000, Math.max(2000, rawInterval));
  var h = window.React.createElement;
  var csrfToken = document.querySelector('meta[name="csrf-token"]');
  csrfToken = csrfToken ? csrfToken.content : "";

  function requestJson(url, options) {
    options = options || {};
    options.credentials = "same-origin";
    options.headers = Object.assign({
      "Content-Type": "application/json",
      "X-CSRFToken": csrfToken,
    }, options.headers || {});
    return window.fetch(url, options).then(function (response) {
      return response.json().then(function (body) {
        if (!response.ok || !body.ok) {
          var error = new Error(body.error ? body.error.message : "요청을 처리하지 못했습니다.");
          error.code = body.error ? body.error.code : "request_failed";
          error.details = body.error ? body.error.details : null;
          throw error;
        }
        return body.data;
      });
    });
  }

  function requestKey() {
    return window.crypto && window.crypto.randomUUID
      ? window.crypto.randomUUID()
      : String(Date.now()) + "-" + String(Math.random());
  }

  function replaceById(items, item) {
    return items.filter(function (current) {
      return current.id !== item.id;
    }).concat([item]);
  }

  function applyEvents(previous, payload) {
    var next = {
      canvas: previous.canvas,
      sections: previous.sections,
      nodes: previous.nodes.slice(),
      held_nodes: previous.held_nodes.slice(),
      connections: previous.connections.slice(),
      counts: payload.counts || previous.counts,
      permissions: previous.permissions,
      cursor: payload.cursor,
    };
    payload.events.forEach(function (event) {
      if (event.action === "auto_layout_applied" && event.after.nodes) {
        event.after.nodes.forEach(function (position) {
          next.nodes = next.nodes.map(function (node) {
            return node.id === position.id ? Object.assign({}, node, position) : node;
          });
        });
        return;
      }
      if (event.target_type === "node") {
        next.nodes = next.nodes.filter(function (node) {
          return node.id !== event.target_id;
        });
        next.held_nodes = next.held_nodes.filter(function (node) {
          return node.id !== event.target_id;
        });
        next.connections = next.connections.filter(function (connection) {
          return connection.node_a_id !== event.target_id && connection.node_b_id !== event.target_id;
        });
        if (event.snapshot && !event.snapshot.is_deleted) {
          if (event.snapshot.status === "held") {
            next.held_nodes = replaceById(next.held_nodes, event.snapshot);
          } else {
            next.nodes = replaceById(next.nodes, event.snapshot);
          }
        }
        (event.related_connections || []).forEach(function (connection) {
          next.connections = replaceById(next.connections, connection);
        });
      } else if (event.target_type === "connection") {
        next.connections = next.connections.filter(function (connection) {
          return connection.id !== event.target_id;
        });
        if (event.snapshot && !event.snapshot.is_deleted) {
          next.connections = replaceById(next.connections, event.snapshot);
        }
      }
    });
    return next;
  }

  function BrainstormApp() {
    var statePair = window.React.useState(null);
    var state = statePair[0];
    var setState = statePair[1];
    var statusPair = window.React.useState("loading");
    var syncStatus = statusPair[0];
    var setSyncStatus = statusPair[1];
    var cursorRef = window.React.useRef(null);
    var timerRef = window.React.useRef(null);
    var stoppedRef = window.React.useRef(false);
    var analysisPair = window.React.useState(null);
    var analysis = analysisPair[0];
    var setAnalysis = analysisPair[1];
    var classificationPair = window.React.useState(null);
    var classification = classificationPair[0];
    var setClassification = classificationPair[1];
    var selectedPair = window.React.useState({});
    var selected = selectedPair[0];
    var setSelected = selectedPair[1];
    var aiStatusPair = window.React.useState({ busy: false, jobId: null, error: null });
    var aiStatus = aiStatusPair[0];
    var setAiStatus = aiStatusPair[1];

    function schedule(delay) {
      window.clearTimeout(timerRef.current);
      if (!stoppedRef.current) timerRef.current = window.setTimeout(poll, delay);
    }

    function fullSync() {
      setSyncStatus("loading");
      return window.fetch(apiBase + "canvas/", { credentials: "same-origin" })
        .then(function (response) {
          if (!response.ok) throw new Error("full_sync_failed");
          return response.json();
        })
        .then(function (body) {
          cursorRef.current = body.data.cursor;
          setState(body.data);
          setSyncStatus("connected");
          schedule(pollingInterval);
        })
        .catch(function () {
          setSyncStatus("disconnected");
          schedule(pollingInterval);
        });
    }

    function poll() {
      if (cursorRef.current === null || !navigator.onLine) {
        fullSync();
        return;
      }
      window.fetch(apiBase + "events/?cursor=" + encodeURIComponent(cursorRef.current), {
        credentials: "same-origin",
      }).then(function (response) {
        if (!response.ok) throw new Error("poll_failed");
        return response.json();
      }).then(function (body) {
        if (body.data.reset_required) {
          fullSync();
          return;
        }
        cursorRef.current = body.data.cursor;
        setState(function (previous) {
          return previous ? applyEvents(previous, body.data) : previous;
        });
        setSyncStatus("connected");
        schedule(body.data.has_more ? 0 : pollingInterval);
      }).catch(function () {
        setSyncStatus("disconnected");
        schedule(pollingInterval);
      });
    }

    function pollAiJob(jobId, onSuccess) {
      requestJson(apiBase + "ai/jobs/" + jobId + "/").then(function (job) {
        if (["queued", "running", "retry_wait", "cancel_requested"].indexOf(job.status) >= 0) {
          window.setTimeout(function () { pollAiJob(jobId, onSuccess); }, 1500);
          return;
        }
        if (job.status === "succeeded") {
          setAiStatus({ busy: false, jobId: null, error: null });
          onSuccess(job);
          return;
        }
        setAiStatus({
          busy: false,
          jobId: job.id,
          error: job.error ? job.error.message : "AI 작업을 완료하지 못했습니다.",
        });
      }).catch(function (error) {
        setAiStatus({ busy: false, jobId: jobId, error: error.message });
      });
    }

    function requestAi(kind) {
      setAiStatus({ busy: true, jobId: null, error: null });
      requestJson(apiBase + "ai/" + kind + "/", {
        method: "POST",
        headers: { "Idempotency-Key": requestKey() },
        body: "{}",
      }).then(function (result) {
        if (result.job === null) {
          setAiStatus({ busy: false, jobId: null, error: result.message });
          if (kind === "analysis") {
            setAnalysis({ statistics: result.statistics, output: null, message: result.message });
          }
          return;
        }
        setAiStatus({ busy: true, jobId: result.id, error: null });
        pollAiJob(result.id, function (job) {
          if (kind === "analysis") {
            setAnalysis({ statistics: job.statistics, output: job.output, message: null });
          } else {
            var defaults = {};
            (job.output.recommendations || []).forEach(function (row) { defaults[row.node_id] = true; });
            setSelected(defaults);
            setClassification({ jobId: job.id, recommendations: job.output.recommendations || [] });
          }
        });
      }).catch(function (error) {
        setAiStatus({ busy: false, jobId: null, error: error.message });
      });
    }

    function cancelAi() {
      if (!aiStatus.jobId) return;
      requestJson(apiBase + "ai/jobs/" + aiStatus.jobId + "/cancel/", {
        method: "POST",
        body: "{}",
      }).then(function () {
        setAiStatus({ busy: false, jobId: null, error: "AI 작업을 취소했습니다." });
      }).catch(function (error) {
        setAiStatus({ busy: false, jobId: aiStatus.jobId, error: error.message });
      });
    }

    function retryAi() {
      if (!aiStatus.jobId) return;
      requestJson(apiBase + "ai/jobs/" + aiStatus.jobId + "/retry/", {
        method: "POST",
        body: "{}",
      }).then(function (job) {
        setAiStatus({ busy: true, jobId: job.id, error: null });
        pollAiJob(job.id, function (completed) {
          if (completed.feature_type === "BRAINSTORM_ANALYSIS") {
            setAnalysis({ statistics: completed.statistics, output: completed.output, message: null });
          } else {
            var defaults = {};
            (completed.output.recommendations || []).forEach(function (row) {
              defaults[row.node_id] = true;
            });
            setSelected(defaults);
            setClassification({
              jobId: completed.id,
              recommendations: completed.output.recommendations || [],
            });
          }
        });
      }).catch(function (error) {
        setAiStatus({ busy: false, jobId: aiStatus.jobId, error: error.message });
      });
    }

    function applyClassification() {
      if (!classification) return;
      var selections = classification.recommendations.filter(function (row) {
        return selected[row.node_id];
      }).map(function (row) {
        return {
          node_id: row.node_id,
          section_id: row.section_id,
          version: row.node_version,
        };
      });
      setAiStatus({ busy: true, jobId: null, error: null });
      requestJson(apiBase + "ai/classification/apply/", {
        method: "POST",
        headers: { "Idempotency-Key": requestKey() },
        body: JSON.stringify({ job_id: classification.jobId, selections: selections }),
      }).then(function () {
        setClassification(null);
        setSelected({});
        setAiStatus({ busy: false, jobId: null, error: null });
        cursorRef.current = null;
        fullSync();
      }).catch(function (error) {
        setAiStatus({ busy: false, jobId: null, error: error.message });
      });
    }

    window.React.useEffect(function () {
      function reconnect() {
        cursorRef.current = null;
        fullSync();
      }
      stoppedRef.current = false;
      window.addEventListener("online", reconnect);
      fullSync();
      return function () {
        stoppedRef.current = true;
        window.clearTimeout(timerRef.current);
        window.removeEventListener("online", reconnect);
      };
    }, []);

    if (!apiBase) return h("div", { className: "alert alert-danger" }, "PRD API 경로가 없습니다.");
    if (!state) {
      return h("div", { className: "d-flex justify-content-center py-5", role: "status" },
        h("span", { className: "spinner-border text-primary", "aria-hidden": "true" }),
        h("span", { className: "visually-hidden" }, "브레인스토밍 동기화 중")
      );
    }
    var statusClass = syncStatus === "connected" ? "text-success" : "text-warning";
    var canRequestAi = state.permissions.can_request_ai && !state.permissions.is_completed;
    return h("div", { className: "brainstorm-app" },
      h("div", { className: "d-flex justify-content-between align-items-center mb-3" },
        h("h1", { className: "h4 mb-0" }, "브레인스토밍"),
        h("div", { className: "d-flex align-items-center gap-2" },
          canRequestAi ? h("button", {
            type: "button", className: "btn btn-outline-primary btn-sm",
            disabled: aiStatus.busy, onClick: function () { requestAi("analysis"); },
          }, "AI 분석") : null,
          canRequestAi ? h("button", {
            type: "button", className: "btn btn-outline-primary btn-sm",
            disabled: aiStatus.busy, onClick: function () { requestAi("classification"); },
          }, "AI로 분류") : null,
          aiStatus.busy && aiStatus.jobId ? h("button", {
            type: "button", className: "btn btn-outline-secondary btn-sm", onClick: cancelAi,
          }, "취소") : null,
          h("span", { className: statusClass, role: "status" },
            syncStatus === "connected" ? "동기화됨" : "재연결 중"))
      ),
      aiStatus.error ? h("div", { className: "alert alert-warning" },
        aiStatus.error,
        aiStatus.jobId && !aiStatus.busy ? h("button", {
          type: "button", className: "btn btn-link btn-sm", onClick: retryAi,
        }, "다시 시도") : null) : null,
      h("div", { className: "row g-2 mb-3" }, [
        ["전체", state.counts.total], ["미분류", state.counts.unclassified],
        ["채택", state.counts.accepted], ["보류", state.counts.held],
      ].map(function (entry) {
        return h("div", { className: "col-6 col-md-3", key: entry[0] },
          h("div", { className: "border rounded p-2 bg-white" },
            h("span", { className: "text-muted me-2" }, entry[0]), h("strong", null, String(entry[1]))));
      })),
      analysis ? h("section", { className: "card mb-3", "aria-label": "AI 분석 결과" },
        h("div", { className: "card-header" }, "AI 분석 결과"),
        h("div", { className: "card-body brainstorm-ai-result" },
          analysis.message ? h("p", { className: "mb-0" }, analysis.message) : null,
          analysis.statistics ? h("p", { className: "text-muted" },
            "서버 집계: 전체 " + analysis.statistics.total + " · 채택 " +
            analysis.statistics.accepted + " · 보류 " + analysis.statistics.held +
            " · 미분류 " + analysis.statistics.unclassified) : null,
          analysis.output ? h("div", null,
            h("p", null, analysis.output.summary),
            h("h3", { className: "h6" }, "섹션별 분석"),
            h("ul", null, analysis.output.section_findings.map(function (row) {
              return h("li", { key: String(row.section_id) }, row.finding);
            })),
            h("h3", { className: "h6" }, "부족한 주제"),
            h("ul", null, analysis.output.missing_topics.map(function (row, index) {
              return h("li", { key: String(index) }, row.topic + " — " + row.reason);
            }))) : null)) : null,
      classification ? h("section", { className: "card mb-3", "aria-label": "AI 분류 미리보기" },
        h("div", { className: "card-header" }, "AI 분류 미리보기"),
        h("div", { className: "card-body brainstorm-ai-scroll" },
          classification.recommendations.map(function (row) {
            var section = state.sections.find(function (item) { return item.id === row.section_id; });
            return h("label", { className: "d-flex gap-2 border-bottom py-2", key: row.node_id },
              h("input", {
                type: "checkbox", className: "form-check-input", checked: !!selected[row.node_id],
                onChange: function (event) {
                  var checked = event.target.checked;
                  setSelected(function (previous) {
                    return Object.assign({}, previous, (function () {
                      var changed = {}; changed[row.node_id] = checked; return changed;
                    }()));
                  });
                },
              }),
              h("span", null,
                h("strong", { className: "d-block" }, row.node_content),
                h("small", { className: "text-muted" },
                  "추천: " + (section ? section.title : row.section_id) + " · " + row.reason)));
          })),
        h("div", { className: "card-footer text-end" },
          h("button", {
            type: "button", className: "btn btn-primary btn-sm", disabled: aiStatus.busy,
            onClick: applyClassification,
          }, "선택한 추천 반영"))) : null,
      h("div", { className: "list-group" }, state.nodes.map(function (node) {
        return h("div", { className: "list-group-item", key: node.id },
          h("strong", null, node.content),
          h("small", { className: "d-block text-muted" },
            "version " + node.version + (node.section_id ? " · section " + node.section_id : " · 미분류")));
      }))
    );
  }

  window.ReactDOM.createRoot(mountNode).render(h(BrainstormApp));
})();
