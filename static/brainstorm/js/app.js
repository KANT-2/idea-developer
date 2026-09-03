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
    var prdPreviewPair = window.React.useState(null);
    var prdPreview = prdPreviewPair[0];
    var setPrdPreview = prdPreviewPair[1];
    var prdApprovedPair = window.React.useState({});
    var prdApproved = prdApprovedPair[0];
    var setPrdApproved = prdApprovedPair[1];
    var prdDefaultsPair = window.React.useState({});
    var prdDefaults = prdDefaultsPair[0];
    var setPrdDefaults = prdDefaultsPair[1];
    var prdScopePair = window.React.useState("all");
    var prdScope = prdScopePair[0];
    var setPrdScope = prdScopePair[1];
    var canvasRequestKeyRef = window.React.useRef(requestKey());
    var filterPair = window.React.useState("all");
    var nodeFilter = filterPair[0];
    var setNodeFilter = filterPair[1];

    function schedule(delay) {
      window.clearTimeout(timerRef.current);
      if (!stoppedRef.current) timerRef.current = window.setTimeout(poll, delay);
    }

    function fullSync() {
      setSyncStatus("loading");
      return window.fetch(apiBase + "canvas/", {
        credentials: "same-origin",
        headers: { "Idempotency-Key": canvasRequestKeyRef.current },
      })
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
          } else if (completed.feature_type === "BRAINSTORM_CLASSIFICATION") {
            var defaults = {};
            (completed.output.recommendations || []).forEach(function (row) {
              defaults[row.node_id] = true;
            });
            setSelected(defaults);
            setClassification({
              jobId: completed.id,
              recommendations: completed.output.recommendations || [],
            });
          } else if (completed.feature_type === "BRAINSTORM_PRD_APPLY") {
            var approvals = {};
            (completed.output.answers || []).forEach(function (row) {
              approvals[String(row.question_id)] = true;
            });
            setPrdApproved(approvals);
            setPrdPreview({
              jobId: completed.id,
              answers: completed.output.answers || [],
              warnings: completed.output.warnings || [],
              unusedNodeIds: completed.output.unused_node_ids || [],
              excludedUnclassifiedIds:
                completed.preview.excluded_unclassified_accepted_node_ids || [],
              preview: completed.preview,
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

    function requestPrdPreview() {
      var payload = {
        selected_default_nodes: state.nodes.filter(function (node) {
          return node.node_type === "note" && node.status === "default" &&
            !!prdDefaults[node.id] &&
            (prdScope === "all" || String(node.section_id) === prdScope);
        }).map(function (node) {
          return { node_id: node.id, version: node.version };
        }),
      };
      if (prdScope !== "all") payload.section_id = Number(prdScope);
      setAiStatus({ busy: true, jobId: null, error: null });
      requestJson(apiBase + "ai/prd-apply/preview/", {
        method: "POST",
        headers: { "Idempotency-Key": requestKey() },
        body: JSON.stringify(payload),
      }).then(function (result) {
        if (result.job === null) {
          setAiStatus({ busy: false, jobId: null, error: result.message });
          return;
        }
        setAiStatus({ busy: true, jobId: result.id, error: null });
        pollAiJob(result.id, function (job) {
          var approvals = {};
          (job.output.answers || []).forEach(function (row) {
            approvals[String(row.question_id)] = true;
          });
          setPrdApproved(approvals);
          setPrdPreview({
            jobId: job.id,
            answers: job.output.answers || [],
            warnings: job.output.warnings || [],
            unusedNodeIds: job.output.unused_node_ids || [],
            excludedUnclassifiedIds:
              job.preview.excluded_unclassified_accepted_node_ids || [],
            preview: job.preview,
          });
        });
      }).catch(function (error) {
        setAiStatus({ busy: false, jobId: null, error: error.message });
      });
    }

    function applyPrdPreview() {
      if (!prdPreview) return;
      var approved = prdPreview.answers.filter(function (row) {
        return prdApproved[String(row.question_id)];
      }).map(function (row) {
        return { question_id: row.question_id, version: row.question_version };
      });
      setAiStatus({ busy: true, jobId: null, error: null });
      requestJson(apiBase + "ai/prd-apply/apply/", {
        method: "POST",
        headers: { "Idempotency-Key": requestKey() },
        body: JSON.stringify({
          preview_request_id: prdPreview.jobId,
          node_versions: prdPreview.preview.node_versions,
          approved_questions: approved,
        }),
      }).then(function () {
        setPrdPreview(null);
        setPrdApproved({});
        setPrdDefaults({});
        setAiStatus({ busy: false, jobId: null, error: null });
        cursorRef.current = null;
        fullSync();
      }).catch(function (error) {
        setAiStatus({ busy: false, jobId: null, error: error.message });
      });
    }

    function refreshAfter(action) {
      return action.then(function () {
        cursorRef.current = null;
        return fullSync();
      }).catch(function (error) {
        setAiStatus({ busy: false, jobId: null, error: error.message });
        if (error.code === "version_conflict") {
          cursorRef.current = null;
          fullSync();
        }
      });
    }

    function createNote() {
      var content = window.prompt("새 메모 내용을 입력해 주세요.");
      if (!content || !content.trim()) return;
      refreshAfter(requestJson(apiBase + "nodes/", {
        method: "POST",
        headers: { "Idempotency-Key": requestKey() },
        body: JSON.stringify({
          content: content.trim(), color: "yellow",
          x: 40 + (state.nodes.length % 6) * 40,
          y: 40 + Math.floor(state.nodes.length / 6) * 40,
          section_id: null,
        }),
      }));
    }

    function editNote(node) {
      var content = window.prompt("메모 내용을 수정해 주세요.", node.content);
      if (content === null || !content.trim()) return;
      refreshAfter(requestJson(apiBase + "nodes/" + node.id + "/content/", {
        method: "PATCH", body: JSON.stringify({ content: content.trim(), version: node.version }),
      }));
    }

    function changeNodeStatus(node, status) {
      var payload = { status: status, version: node.version };
      if (status === "held") {
        payload.connection_versions = state.connections.filter(function (connection) {
          return connection.node_a_id === node.id || connection.node_b_id === node.id;
        }).map(function (connection) { return { id: connection.id, version: connection.version }; });
      }
      refreshAfter(requestJson(apiBase + "nodes/" + node.id + "/status/", {
        method: "PATCH", body: JSON.stringify(payload),
      }));
    }

    function moveNode(node, rawSectionId) {
      refreshAfter(requestJson(apiBase + "nodes/" + node.id + "/position/", {
        method: "PATCH",
        body: JSON.stringify({
          version: node.version, section_id: rawSectionId ? Number(rawSectionId) : null,
          x: node.x, y: node.y,
        }),
      }));
    }

    function deleteNode(node) {
      if (!window.confirm("이 메모를 삭제하시겠습니까? 30일 동안 복원할 수 있습니다.")) return;
      refreshAfter(requestJson(apiBase + "nodes/" + node.id + "/", {
        method: "DELETE", body: JSON.stringify({ version: node.version }),
      }));
    }

    function restoreHeld(node) {
      changeNodeStatus(node, "default");
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
    var canApplyAi = state.permissions.can_apply_ai && !state.permissions.is_completed;
    return h("div", { className: "brainstorm-app" },
      h("div", { className: "d-flex justify-content-between align-items-center mb-3" },
        h("h1", { className: "h4 mb-0" }, "브레인스토밍"),
        h("div", { className: "d-flex align-items-center gap-2" },
          state.permissions.can_edit && !state.permissions.is_completed ? h("button", {
            type: "button", className: "btn btn-primary btn-sm", onClick: createNote,
          }, "+ 메모") : null,
          canRequestAi ? h("button", {
            type: "button", className: "btn btn-outline-primary btn-sm",
            disabled: aiStatus.busy, onClick: function () { requestAi("analysis"); },
          }, "AI 분석") : null,
          canRequestAi ? h("button", {
            type: "button", className: "btn btn-outline-primary btn-sm",
            disabled: aiStatus.busy, onClick: function () { requestAi("classification"); },
          }, "AI로 분류") : null,
          canApplyAi ? h("select", {
            className: "form-select form-select-sm brainstorm-ai-scope",
            value: prdScope, disabled: aiStatus.busy,
            onChange: function (event) { setPrdScope(event.target.value); },
            "aria-label": "PRD 반영 범위",
          }, [h("option", { value: "all", key: "all" }, "전체 PRD")].concat(
            state.sections.map(function (section) {
              return h("option", { value: String(section.id), key: section.id }, section.title);
            }))) : null,
          canApplyAi ? h("button", {
            type: "button", className: "btn btn-primary btn-sm",
            disabled: aiStatus.busy, onClick: requestPrdPreview,
          }, "PRD 반영 미리보기") : null,
          aiStatus.busy && aiStatus.jobId ? h("button", {
            type: "button", className: "btn btn-outline-secondary btn-sm", onClick: cancelAi,
          }, "취소") : null,
          h("a", { className: "btn btn-outline-secondary btn-sm", href: apiBase + "export/markdown/" }, "Markdown"),
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
      h("div", { className: "d-flex justify-content-between align-items-center mb-3" },
        h("select", {
          className: "form-select form-select-sm w-auto", value: nodeFilter,
          onChange: function (event) { setNodeFilter(event.target.value); },
          "aria-label": "메모 상태 필터",
        }, [h("option", { value: "all", key: "all" }, "모든 메모"), h("option", { value: "default", key: "default" }, "기본"), h("option", { value: "accepted", key: "accepted" }, "채택")]),
        h("small", { className: "text-muted" }, "최종 위치·섹션·상태 변경만 서버에 저장됩니다.")),
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
      prdPreview ? h("section", { className: "card mb-3", "aria-label": "AI PRD 반영 미리보기" },
        h("div", { className: "card-header" }, "AI PRD 반영 미리보기"),
        h("div", { className: "card-body brainstorm-ai-scroll" },
          prdPreview.warnings.length ? h("div", { className: "alert alert-warning" },
            prdPreview.warnings.join(" · ")) : null,
          prdPreview.excludedUnclassifiedIds.length ? h("div", {
            className: "alert alert-info",
          }, "미분류 채택 메모 " + prdPreview.excludedUnclassifiedIds.length +
            "개는 섹션 지정 전 자동 반영하지 않습니다.") : null,
          prdPreview.answers.map(function (row) {
            var evidence = row.source_node_ids.map(function (nodeId) {
              var node = state.nodes.find(function (item) { return item.id === nodeId; });
              return node ? node.content : nodeId;
            });
            return h("article", { className: "border rounded p-3 mb-3", key: row.question_id },
              h("label", { className: "d-flex gap-2 align-items-center mb-2" },
                h("input", {
                  type: "checkbox", className: "form-check-input",
                  checked: !!prdApproved[String(row.question_id)],
                  onChange: function (event) {
                    var changed = {}; changed[String(row.question_id)] = event.target.checked;
                    setPrdApproved(function (previous) {
                      return Object.assign({}, previous, changed);
                    });
                  },
                }),
                h("strong", null, row.question_prompt || ("질문 " + row.question_id))),
              h("div", { className: "row g-2" },
                h("div", { className: "col-md-6" },
                  h("h3", { className: "h6 text-muted" }, "기존 답변"),
                  h("div", { className: "brainstorm-answer-compare" },
                    row.existing_answer || "작성된 답변 없음")),
                h("div", { className: "col-md-6" },
                  h("h3", { className: "h6 text-primary" }, "AI 통합 결과"),
                  h("div", { className: "brainstorm-answer-compare" }, row.draft))),
              h("p", { className: "small mt-2 mb-1" },
                "근거 메모: " + (evidence.length ? evidence.join(" · ") : "없음")),
              h("p", { className: "small text-muted mb-0" },
                "유지: " + row.preserved_existing_points.join(" · ") +
                " / 추가: " + row.added_points.join(" · ")+
                " / 신뢰도: " + row.confidence));
          }),
          prdPreview.unusedNodeIds.length ? h("p", { className: "small text-muted" },
            "사용되지 않은 메모: " + prdPreview.unusedNodeIds.join(", ")) : null),
        h("div", { className: "card-footer text-end" },
          h("button", {
            type: "button", className: "btn btn-primary btn-sm",
            disabled: aiStatus.busy || !Object.keys(prdApproved).some(function (key) {
              return prdApproved[key];
            }),
            onClick: applyPrdPreview,
          }, "승인한 질문만 PRD에 저장"))) : null,
      h("div", { className: "row g-3" }, state.nodes.filter(function (node) {
        return node.node_type === "title" || nodeFilter === "all" || node.status === nodeFilter;
      }).map(function (node) {
        return h("div", { className: "col-md-6 col-xl-4", key: node.id },
          h("article", { className: "card h-100 brainstorm-note", "data-color": node.color },
          h("div", { className: "card-body" },
          canApplyAi && node.node_type === "note" && node.status === "default" && node.section_id ?
            h("label", { className: "float-end small" },
              h("input", {
                type: "checkbox", className: "form-check-input me-1",
                checked: !!prdDefaults[node.id],
                onChange: function (event) {
                  var changed = {}; changed[node.id] = event.target.checked;
                  setPrdDefaults(function (previous) {
                    return Object.assign({}, previous, changed);
                  });
                },
              }), "PRD 반영에 추가") : null,
          h("strong", { className: "d-block mb-2" }, node.content),
          h("small", { className: "d-block text-muted" },
            "version " + node.version + (node.section_id ? " · section " + node.section_id : " · 미분류")),
          state.permissions.can_edit && !state.permissions.is_completed && node.node_type === "note" ? h("div", { className: "mt-3 d-flex flex-wrap gap-1" },
            h("button", { type: "button", className: "btn btn-sm btn-outline-secondary", onClick: function () { editNote(node); } }, "수정"),
            h("select", { className: "form-select form-select-sm brainstorm-section-select", value: node.section_id || "", onChange: function (event) { moveNode(node, event.target.value); }, "aria-label": "메모 섹션" },
              [h("option", { value: "", key: "none" }, "미분류")].concat(state.sections.map(function (section) { return h("option", { value: String(section.id), key: section.id }, section.title); }))),
            node.status !== "accepted" ? h("button", { type: "button", className: "btn btn-sm btn-outline-success", onClick: function () { changeNodeStatus(node, "accepted"); } }, "채택") : h("button", { type: "button", className: "btn btn-sm btn-outline-secondary", onClick: function () { changeNodeStatus(node, "default"); } }, "채택 취소"),
            h("button", { type: "button", className: "btn btn-sm btn-outline-warning", onClick: function () { changeNodeStatus(node, "held"); } }, "보류"),
            h("button", { type: "button", className: "btn btn-sm btn-outline-danger", onClick: function () { deleteNode(node); } }, "삭제")) : null)));
      })),
      state.held_nodes.length ? h("section", { className: "mt-4" },
        h("h2", { className: "h5" }, "보류 메모"),
        h("div", { className: "list-group" }, state.held_nodes.map(function (node) {
          return h("div", { className: "list-group-item d-flex justify-content-between align-items-center gap-2", key: node.id },
            h("span", null, node.content),
            state.permissions.can_edit && !state.permissions.is_completed ? h("button", { type: "button", className: "btn btn-sm btn-outline-primary", onClick: function () { restoreHeld(node); } }, "미분류로 복원") : null);
        }))) : null
    );
  }

  window.ReactDOM.createRoot(mountNode).render(h(BrainstormApp));
})();
