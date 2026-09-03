(function () {
  "use strict";

  var root = document.getElementById("brainstorm-root");
  if (!root) return;
  if (!window.React || !window.ReactDOM) {
    root.innerHTML = '<div class="alert alert-danger m-4">React CDN을 불러오지 못했습니다. 네트워크와 CSP 설정을 확인해 주세요.</div>';
    return;
  }

  var h = window.React.createElement;
  var apiBase = root.dataset.apiBase;
  var prdTitle = root.dataset.prdTitle || "PRD";
  var interval = Math.min(5000, Math.max(2000, Number(root.dataset.pollingIntervalMs || 3000)));
  var csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  var NODE_W = 230;
  var NODE_H = 150;
  var LANE_W = 290;
  var LANE_GAP = 20;
  var LANE_TOP = 350;
  var LANE_H = 2200;
  var CANVAS_W = 4800;
  var CANVAS_H = 3200;
  var laneColors = [
    ["#eef2ff", "#c7d2fe", "#4338ca"], ["#ecfeff", "#a5f3fc", "#0e7490"],
    ["#ecfdf5", "#a7f3d0", "#047857"], ["#fff7ed", "#fed7aa", "#c2410c"],
    ["#fdf2f8", "#fbcfe8", "#be185d"], ["#f5f3ff", "#ddd6fe", "#6d28d9"]
  ];

  function key() { return window.crypto?.randomUUID ? window.crypto.randomUUID() : Date.now() + "-" + Math.random(); }
  function request(url, options) {
    options = options || {};
    return fetch(url, Object.assign({}, options, {
      credentials: "same-origin",
      headers: Object.assign({"Content-Type": "application/json", "X-CSRFToken": csrf}, options.headers || {})
    })).then(function (response) {
      return response.text().then(function (body) {
        var payload;
        try {
          payload = JSON.parse(body);
        } catch (parseError) {
          var invalidResponse = new Error(
            response.ok
              ? "서버 응답을 읽지 못했습니다. 잠시 후 다시 시도해 주세요."
              : "서버에서 오류가 발생했습니다. 잠시 후 다시 시도해 주세요."
          );
          invalidResponse.code = "invalid_response";
          throw invalidResponse;
        }
        if (!response.ok || !payload.ok) {
          var error = new Error(payload.error?.message || "요청을 처리하지 못했습니다.");
          error.code = payload.error?.code; error.details = payload.error?.details; throw error;
        }
        return payload.data;
      });
    });
  }

  function BrainstormApp() {
    var statePair = window.React.useState(null), state = statePair[0], setState = statePair[1];
    var syncPair = window.React.useState("loading"), sync = syncPair[0], setSync = syncPair[1];
    var filterPair = window.React.useState("all"), filter = filterPair[0], setFilter = filterPair[1];
    var toolPair = window.React.useState("select"), tool = toolPair[0], setTool = toolPair[1];
    var boardPair = window.React.useState("canvas"), boardView = boardPair[0], setBoardView = boardPair[1];
    var sourcePair = window.React.useState(null), source = sourcePair[0], setSource = sourcePair[1];
    var focusPair = window.React.useState(null), focused = focusPair[0], setFocused = focusPair[1];
    var viewPair = window.React.useState({x: 0, y: 0, zoom: 1}), view = viewPair[0], setView = viewPair[1];
    var noticePair = window.React.useState(null), notice = noticePair[0], setNotice = noticePair[1];
    var busyPair = window.React.useState(false), busy = busyPair[0], setBusy = busyPair[1];
    var jobPair = window.React.useState(null), jobId = jobPair[0], setJobId = jobPair[1];
    var aiPair = window.React.useState(null), aiPanel = aiPair[0], setAiPanel = aiPair[1];
    var editorPair = window.React.useState(null), editor = editorPair[0], setEditor = editorPair[1];
    var assigneeMenuPair = window.React.useState(null), assigneeMenu = assigneeMenuPair[0], setAssigneeMenu = assigneeMenuPair[1];
    var timerRef = window.React.useRef(null);
    var cursorRef = window.React.useRef(null);
    var initialViewport = window.React.useRef(false);
    var viewportSaveRef = window.React.useRef(null);
    var fullSyncGenerationRef = window.React.useRef(0);

    function fullSync() {
      var generation = ++fullSyncGenerationRef.current;
      setSync("loading");
      return request(apiBase + "canvas/", {headers: {"Idempotency-Key": key()}})
        .then(function (data) {
          if (generation !== fullSyncGenerationRef.current) return;
          cursorRef.current = data.cursor; setState(data); setSync("connected");
          if (!initialViewport.current && data.viewport) {
            setView({x: Number(data.viewport.viewport_x || 0), y: Number(data.viewport.viewport_y || 0), zoom: Math.max(.3, Math.min(2, Number(data.viewport.zoom_level || 1)))});
            initialViewport.current = true;
          }
        }).catch(function (error) {
          if (generation !== fullSyncGenerationRef.current) return;
          setSync("disconnected"); setNotice({kind: "warning", text: error.message});
        });
    }

    function poll() {
      if (cursorRef.current === null || !navigator.onLine) return fullSync();
      return request(apiBase + "events/?cursor=" + encodeURIComponent(cursorRef.current)).then(function (data) {
        cursorRef.current = data.cursor;
        if (data.reset_required || data.events.length) return fullSync();
        setSync("connected");
      }).catch(function () { setSync("disconnected"); });
    }

    window.React.useEffect(function () {
      var stopped = false;
      function cycle() { if (stopped) return; poll().finally(function () { timerRef.current = window.setTimeout(cycle, interval); }); }
      function reconnect() { cursorRef.current = null; fullSync(); }
      fullSync().finally(function () { timerRef.current = window.setTimeout(cycle, interval); });
      window.addEventListener("online", reconnect);
      return function () { stopped = true; clearTimeout(timerRef.current); window.removeEventListener("online", reconnect); };
    }, []);

    function refresh(promise, success) {
      setBusy(true); setNotice(null);
      return promise.then(function (data) { if (success) success(data); cursorRef.current = null; return fullSync(); })
        .catch(function (error) { setNotice({kind: error.code === "version_conflict" ? "warning" : "danger", text: error.message}); cursorRef.current = null; return fullSync(); })
        .finally(function () { setBusy(false); });
    }

    function createNote() {
      setEditor({node: null, content: "", color: "yellow"});
    }

    function editNode(node) {
      setEditor({node: node, content: node.content, color: node.color || "yellow"});
    }

    function saveEditor() {
      var content = (editor?.content || "").trim();
      if (!content) return;
      if (editor.node) {
        refresh(request(apiBase + "nodes/" + editor.node.id + "/content/", {method: "PATCH", body: JSON.stringify({content: content, version: editor.node.version})}));
      } else {
        var x = Math.max(20, Math.min(CANVAS_W - NODE_W, (window.innerWidth / 2 - view.x) / view.zoom - NODE_W / 2));
        var y = Math.max(20, Math.min(CANVAS_H - NODE_H, ((window.innerHeight - 190) / 2 - view.y) / view.zoom - NODE_H / 2));
        refresh(request(apiBase + "nodes/", {method: "POST", headers: {"Idempotency-Key": key()}, body: JSON.stringify({content: content, color: editor.color, x: x, y: y, section_id: sectionAt(x, y)})}));
      }
      setEditor(null);
    }

    function statusNode(node, status) {
      var payload = {status: status, version: node.version};
      if (status === "held") payload.connection_versions = state.connections.filter(function (line) { return line.node_a_id === node.id || line.node_b_id === node.id; }).map(function (line) { return {id: line.id, version: line.version}; });
      // Invalidate a canvas request that began before this mutation.  Applying
      // that older response after the hold succeeds would draw the note once
      // more until the next click/render.
      fullSyncGenerationRef.current += 1;
      setBusy(true); setNotice(null);
      request(apiBase + "nodes/" + node.id + "/status/", {method: "PATCH", body: JSON.stringify(payload)})
        .then(function (updated) {
          setFocused(function (current) { return current === updated.id ? null : current; });
          setState(function (previous) {
            var nodes = previous.nodes.filter(function (item) { return item.id !== updated.id; });
            var heldNodes = previous.held_nodes.filter(function (item) { return item.id !== updated.id; });
            var connections = previous.connections;
            if (updated.status === "held") {
              heldNodes.push(updated);
              connections = connections.filter(function (line) { return line.node_a_id !== updated.id && line.node_b_id !== updated.id; });
            } else {
              nodes.push(updated);
            }
            var regularNotes = nodes.filter(function (item) { return item.node_type === "note"; });
            var counts = {
              total: regularNotes.length,
              unclassified: regularNotes.filter(function (item) { return !item.section_id; }).length,
              accepted: regularNotes.filter(function (item) { return !!item.section_id; }).length,
              held: heldNodes.length
            };
            return Object.assign({}, previous, {nodes: nodes, held_nodes: heldNodes, connections: connections, counts: counts});
          });
          cursorRef.current = null;
          setSync("connected");
        })
        .catch(function (error) {
          setNotice({kind: error.code === "version_conflict" ? "warning" : "danger", text: error.message});
          cursorRef.current = null;
          return fullSync();
        })
        .finally(function () { setBusy(false); });
    }

    function assignNode(node, assigneeId) {
      refresh(request(apiBase + "nodes/" + node.id + "/assignee/", {
        method: "PATCH",
        body: JSON.stringify({assignee_id: Number(assigneeId), version: node.version})
      }));
    }

    function deleteNode(node) {
      if (!window.confirm("이 메모를 삭제하시겠습니까? 삭제된 메모는 일반 화면에서 복원할 수 없습니다.")) return;
      refresh(request(apiBase + "nodes/" + node.id + "/", {method: "DELETE", body: JSON.stringify({version: node.version})}));
    }

    function moveNode(node, x, y, sectionId) {
      refresh(request(apiBase + "nodes/" + node.id + "/position/", {method: "PATCH", body: JSON.stringify({version: node.version, x: x, y: y, section_id: sectionId})}));
    }

    function holdNode(node) {
      statusNode(node, "held");
    }

    function canvasWidth() { return Math.max(CANVAS_W, state.sections.length * (LANE_W + LANE_GAP) + 400); }
    function laneIndex(sectionId) { return state.sections.findIndex(function (section) { return section.id === sectionId; }); }
    function displayPosition(node) {
      return {x: Number(node.x), y: Number(node.y)};
    }
    function sectionAt(x, y) {
      var centerX = x + NODE_W / 2, centerY = y + NODE_H / 2;
      for (var index = 0; index < state.sections.length; index += 1) {
        var left = 40 + index * (LANE_W + LANE_GAP);
        if (centerX >= left && centerX <= left + LANE_W && centerY >= LANE_TOP && centerY <= LANE_TOP + LANE_H) return state.sections[index].id;
      }
      return null;
    }

    function createConnection(nodeA, nodeB) {
      var optimisticId = "pending-" + key();
      var optimisticConnection = {
        id: optimisticId,
        node_a_id: nodeA.id,
        node_b_id: nodeB.id,
        version: 0,
        pending: true
      };
      function showOptimisticConnection() {
        setState(function (previous) {
          return Object.assign({}, previous, {
            connections: previous.connections.concat([optimisticConnection])
          });
        });
      }
      if (window.ReactDOM.flushSync) {
        window.ReactDOM.flushSync(showOptimisticConnection);
      } else {
        showOptimisticConnection();
      }
      fullSyncGenerationRef.current += 1;
      setBusy(true); setNotice(null);
      request(apiBase + "connections/", {
        method: "POST",
        headers: {"Idempotency-Key": key()},
        body: JSON.stringify({node_a_id: nodeA.id, node_b_id: nodeB.id, node_a_version: nodeA.version, node_b_version: nodeB.version})
      }).then(function (result) {
        var connection = result.connection;
        setState(function (previous) {
          var connections = previous.connections.filter(function (item) { return item.id !== optimisticId && item.id !== connection.id; });
          connections.push(connection);
          return Object.assign({}, previous, {connections: connections});
        });
        cursorRef.current = null;
        setSync("connected");
      }).catch(function (error) {
        setState(function (previous) {
          return Object.assign({}, previous, {connections: previous.connections.filter(function (item) { return item.id !== optimisticId; })});
        });
        setNotice({kind: error.code === "version_conflict" ? "warning" : "danger", text: error.message});
        cursorRef.current = null;
        return fullSync();
      }).finally(function () { setBusy(false); });
    }

    function deleteConnection(connection) {
      fullSyncGenerationRef.current += 1;
      setBusy(true); setNotice(null);
      request(apiBase + "connections/" + connection.id + "/", {method: "DELETE", body: JSON.stringify({version: connection.version})})
        .then(function () {
          setState(function (previous) {
            return Object.assign({}, previous, {connections: previous.connections.filter(function (item) { return item.id !== connection.id; })});
          });
          cursorRef.current = null;
          setSync("connected");
        }).catch(function (error) {
          setNotice({kind: error.code === "version_conflict" ? "warning" : "danger", text: error.message});
          cursorRef.current = null;
          return fullSync();
        }).finally(function () { setBusy(false); });
    }

    function beginMove(event, node) {
      event.stopPropagation(); setFocused(node.id);
      if (tool === "connect") {
        if (!source) return setSource(node);
        if (source.id === node.id) return setSource(null);
        createConnection(source, node);
        setSource(null); setTool("select"); return;
      }
      if (!state.permissions.can_edit || state.permissions.is_completed || event.button !== 0) return;
      var start = displayPosition(node), sx = event.clientX, sy = event.clientY, moved = false;
      function moving(moveEvent) {
        var deltaX = moveEvent.clientX - sx, deltaY = moveEvent.clientY - sy;
        if (!moved && Math.abs(deltaX) + Math.abs(deltaY) < 5) return;
        moved = true;
        var x = Math.max(10, Math.min(canvasWidth() - NODE_W, start.x + deltaX / view.zoom)), y = Math.max(10, Math.min(CANVAS_H - NODE_H, start.y + deltaY / view.zoom));
        setState(function (previous) { return Object.assign({}, previous, {nodes: previous.nodes.map(function (item) { return item.id === node.id ? Object.assign({}, item, {x: x, y: y}) : item; })}); });
      }
      function done(upEvent) {
        window.removeEventListener("mousemove", moving); window.removeEventListener("mouseup", done);
        if (!moved) return;
        if (document.elementFromPoint(upEvent.clientX, upEvent.clientY)?.closest(".brain-held")) {
          holdNode(node);
          return;
        }
        var x = Math.max(10, Math.min(canvasWidth() - NODE_W, start.x + (upEvent.clientX - sx) / view.zoom)), y = Math.max(10, Math.min(CANVAS_H - NODE_H, start.y + (upEvent.clientY - sy) / view.zoom));
        moveNode(node, x, y, sectionAt(x, y));
      }
      window.addEventListener("mousemove", moving); window.addEventListener("mouseup", done);
    }

    function pan(event) {
      if (![0, 1].includes(event.button) || (event.button === 0 && event.target.closest("[data-node],button,a,input,textarea"))) return;
      event.preventDefault();
      var sx = event.clientX, sy = event.clientY, ox = view.x, oy = view.y;
      function moving(moveEvent) { setView({x: ox + moveEvent.clientX - sx, y: oy + moveEvent.clientY - sy, zoom: view.zoom}); }
      function done(upEvent) { window.removeEventListener("mousemove", moving); window.removeEventListener("mouseup", done); var next = {x: ox + upEvent.clientX - sx, y: oy + upEvent.clientY - sy, zoom: view.zoom}; setView(next); saveView(next); }
      window.addEventListener("mousemove", moving); window.addEventListener("mouseup", done);
    }
    function saveView(next) { request(apiBase + "viewport/", {method: "PUT", body: JSON.stringify({viewport_x: next.x, viewport_y: next.y, zoom_level: next.zoom})}).catch(function () {}); }
    function saveViewSoon(next) { clearTimeout(viewportSaveRef.current); viewportSaveRef.current = setTimeout(function () { saveView(next); }, 250); }
    function zoom(amount, anchorX, anchorY) {
      var nextZoom = Math.max(.3, Math.min(2, Math.round((view.zoom + amount) * 100) / 100));
      var px = anchorX === undefined ? window.innerWidth / 2 : anchorX, py = anchorY === undefined ? (window.innerHeight - 190) / 2 : anchorY;
      var worldX = (px - view.x) / view.zoom, worldY = (py - view.y) / view.zoom;
      var next = {x: px - worldX * nextZoom, y: py - worldY * nextZoom, zoom: nextZoom};
      setView(next); saveViewSoon(next);
    }
    function wheelCanvas(event) {
      event.preventDefault();
      if (event.ctrlKey || event.metaKey) {
        var rect = event.currentTarget.getBoundingClientRect();
        zoom(event.deltaY < 0 ? .1 : -.1, event.clientX - rect.left, event.clientY - rect.top);
        return;
      }
      var next = {x: view.x - event.deltaX, y: view.y - event.deltaY, zoom: view.zoom};
      setView(next); saveViewSoon(next);
    }

    function autoLayout() {
      var counters = {};
      var nodes = state.nodes.filter(function (node) { return node.node_type === "note" && node.status !== "held"; }).map(function (node) {
        var keyName = node.section_id ? String(node.section_id) : "none", index = counters[keyName] || 0; counters[keyName] = index + 1;
        if (!node.section_id) return {id: node.id, version: node.version, section_id: null, x: 55 + (index % 6) * 205, y: 115 + Math.floor(index / 6) * 145};
        return {id: node.id, version: node.version, section_id: node.section_id, x: 55 + laneIndex(node.section_id) * (LANE_W + LANE_GAP) + (index % 2) * 128, y: LANE_TOP + 90 + Math.floor(index / 2) * 155};
      });
      if (nodes.length) refresh(request(apiBase + "auto-layout/", {method: "POST", body: JSON.stringify({nodes: nodes})}));
    }

    function pollJob(id, completed) {
      setJobId(id);
      function check() { request(apiBase + "ai/jobs/" + id + "/").then(function (job) { if (["queued", "running", "retry_wait", "cancel_requested"].includes(job.status)) return setTimeout(check, 1500); setBusy(false); setJobId(null); if (job.status === "succeeded") completed(job); else setNotice({kind: "warning", text: job.error?.message || "AI 작업이 실패했습니다."}); }).catch(function (error) { setBusy(false); setNotice({kind: "danger", text: error.message}); }); }
      check();
    }
    function loadClassificationResult() {
      setBusy(true); setNotice(null);
      request(apiBase + "canvas/", {headers: {"Idempotency-Key": key()}})
        .then(function (serverState) {
          var result = {
            counts: {
              total: serverState.counts.total,
              classified: serverState.counts.accepted,
              unclassified: serverState.counts.unclassified,
              held: serverState.counts.held
            },
            sections: serverState.sections.map(function (section) {
              return Object.assign({}, section, {
                note_count: serverState.nodes.filter(function (node) {
                  return node.node_type === "note" && node.section_id === section.id;
                }).length
              });
            })
          };
          setAiPanel({type: "classification_result", result: result});
        })
        .catch(function (error) { setNotice({kind: "danger", text: error.message}); })
        .finally(function () { setBusy(false); });
    }
    function previewPrd() {
      var selectedDefaults = [];
      setBusy(true); request(apiBase + "ai/prd-apply/preview/", {method: "POST", headers: {"Idempotency-Key": key()}, body: JSON.stringify({selected_default_nodes: selectedDefaults})}).then(function (result) { if (!result.job) { setBusy(false); return setNotice({kind: "info", text: result.message}); } pollJob(result.id, function (job) { setAiPanel({type: "prd", job: job}); }); }).catch(function (error) { setBusy(false); setNotice({kind: "danger", text: error.message}); });
    }
    function applyPrd() {
      var job = aiPanel.job;
      refresh(request(apiBase + "ai/prd-apply/apply/", {method: "POST", headers: {"Idempotency-Key": key()}, body: JSON.stringify({preview_request_id: job.id, node_versions: job.preview.node_versions, approved_questions: (job.output.answers || []).map(function (row) { return {question_id: row.question_id, version: row.question_version}; })})}), function () { setAiPanel(null); });
    }

    if (!state) return h("div", {className: "brain-loading"}, h("span", {className: "spinner-border text-primary"}), h("p", null, "React 캔버스를 불러오는 중입니다."));
    var canEdit = state.permissions.can_edit && !state.permissions.is_completed;
    var visible = state.nodes.filter(function (node) { return node.node_type === "title" || filter === "all" || node.status === filter; });
    var positions = {}; visible.forEach(function (node) { positions[node.id] = displayPosition(node); });

    function toolButton(value, icon, label) { return h("button", {type: "button", className: "brain-tool " + (tool === value ? "active" : ""), onClick: function () { setTool(value); if (value !== "connect") setSource(null); }}, h("i", {className: icon}), label); }
    function line(connection) {
      var a = positions[connection.node_a_id], b = positions[connection.node_b_id]; if (!a || !b) return null;
      var x1 = a.x + NODE_W / 2, y1 = a.y + NODE_H / 2, x2 = b.x + NODE_W / 2, y2 = b.y + NODE_H / 2;
      return h("g", {key: connection.id}, h("path", {d: "M " + x1 + " " + y1 + " C " + (x1 + x2) / 2 + " " + y1 + ", " + (x1 + x2) / 2 + " " + y2 + ", " + x2 + " " + y2, className: "brain-connection" + (connection.pending ? " pending" : "")}), canEdit && !connection.pending ? h("circle", {cx: (x1 + x2) / 2, cy: (y1 + y2) / 2, r: 9, className: "brain-connection-delete", onClick: function () { deleteConnection(connection); }}) : null);
    }
    function note(node) {
      var p = positions[node.id], selected = focused === node.id, connect = source?.id === node.id;
      var assignee = (state.participants || []).find(function (participant) { return participant.user_id === node.assignee_id; });
      return h("article", {key: node.id, "data-node": "true", "data-color": node.color, className: "brain-note " + (selected ? "selected " : "") + (connect ? "connect-source" : ""), style: {left: p.x, top: p.y}, onMouseDown: function (event) { beginMove(event, node); }, onDoubleClick: function (event) { event.stopPropagation(); if (canEdit) editNode(node); }},
        h("div", {className: "brain-note-top"}, h("span", {className: "brain-note-status " + node.status}, node.status === "accepted" ? "채택" : "아이디어"), canEdit ? h("div", {className: "brain-note-controls", onMouseDown: function (event) { event.stopPropagation(); }}, h("button", {type: "button", onClick: function (event) { event.stopPropagation(); editNode(node); }, title: "내용 수정", "aria-label": "내용 수정"}, "✎"), h("button", {type: "button", onClick: function (event) { event.stopPropagation(); deleteNode(node); }, title: "삭제", "aria-label": "삭제"}, "×")) : null),
        h("p", null, node.content),
        h("footer", null, h("span", null, "v" + node.version), h("span", {title: assignee ? "담당자 " + assignee.display_name : "담당자 없음"}, assignee ? "담당 " + assignee.display_name : "담당자 없음")),
        selected && canEdit ? h("div", {className: "brain-note-actions", onMouseDown: function (event) { event.stopPropagation(); }},
          h("button", {type: "button", onClick: function () { editNode(node); }}, "수정"),
          h("button", {type: "button", onClick: function () { statusNode(node, "held"); }}, "보류"),
          assigneeButton(node)) : null);
    }

    function member(userId) {
      return (state.participants || []).find(function (participant) { return participant.user_id === userId; });
    }

    function initials(name) {
      return String(name || "?").trim().slice(0, 2);
    }

    function participantColor(userId) {
      var colors = ["#4f46e5", "#0284c7", "#059669", "#d97706", "#db2777", "#7c3aed", "#ea580c"];
      return colors[Math.abs(Number(userId) || 0) % colors.length];
    }

    function roleLabel(role) {
      return {owner: "소유자", editor: "편집자", tutor: "튜터", viewer: "조회자"}[role] || role || "참여자";
    }

    function openAssigneeMenu(event, node) {
      event.preventDefault(); event.stopPropagation();
      var rect = event.currentTarget.getBoundingClientRect();
      var width = 244, height = Math.min(360, 82 + (state.participants || []).length * 48);
      var left = Math.max(10, Math.min(rect.right - width, window.innerWidth - width - 10));
      var above = rect.bottom + height > window.innerHeight - 12;
      setAssigneeMenu({node: node, left: left, top: above ? null : rect.bottom + 7, bottom: above ? window.innerHeight - rect.top + 7 : null});
    }

    function assigneeButton(node) {
      var assigned = member(node.assignee_id);
      return h("button", {type: "button", className: "brain-assignee-trigger", onMouseDown: function (event) { event.stopPropagation(); }, onClick: function (event) { openAssigneeMenu(event, node); }, title: "담당자 변경"},
        h("b", {style: {background: participantColor(assigned?.user_id)}}, initials(assigned?.display_name)),
        h("span", null, h("small", null, "담당자"), h("strong", null, assigned?.display_name || "담당자 없음")),
        h("i", {className: "bi bi-chevron-down"})
      );
    }

    function renderAssigneeMenu() {
      if (!assigneeMenu) return null;
      var node = assigneeMenu.node;
      return window.ReactDOM.createPortal(h(window.React.Fragment, null,
        h("button", {type: "button", className: "brain-assignee-dismiss", onMouseDown: function () { setAssigneeMenu(null); }, "aria-label": "담당자 메뉴 닫기"}),
        h("aside", {className: "brain-assignee-menu", style: {left: assigneeMenu.left, top: assigneeMenu.top, bottom: assigneeMenu.bottom}, onMouseDown: function (event) { event.stopPropagation(); }},
          h("header", null, h("div", null, h("span", null, "ASSIGNEE"), h("strong", null, "담당자 지정")), h("button", {type: "button", onClick: function () { setAssigneeMenu(null); }, "aria-label": "닫기"}, "×")),
          h("p", null, "PRD 참여자 중 이 아이디어를 맡을 팀원을 선택하세요."),
          h("div", null, (state.participants || []).map(function (participant) {
            var selected = participant.user_id === node.assignee_id;
            return h("button", {key: participant.user_id, type: "button", className: selected ? "selected" : "", onClick: function () { setAssigneeMenu(null); assignNode(node, participant.user_id); }},
              h("b", {style: {background: participantColor(participant.user_id)}}, initials(participant.display_name)),
              h("span", null, h("strong", null, participant.display_name), h("small", null, roleLabel(participant.role))),
              selected ? h("i", {className: "bi bi-check-lg"}) : null
            );
          }))
        )
      ), document.body);
    }

    function moveToSection(node, sectionId) {
      var sectionNodes = state.nodes.filter(function (item) { return item.node_type === "note" && item.section_id === sectionId && item.status !== "held" && item.id !== node.id; });
      if (sectionId === null) {
        moveNode(node, 55 + (sectionNodes.length % 6) * 205, 115 + Math.floor(sectionNodes.length / 6) * 145, null);
        return;
      }
      var index = sectionNodes.length;
      moveNode(node, 55 + laneIndex(sectionId) * (LANE_W + LANE_GAP) + (index % 2) * 128, LANE_TOP + 90 + Math.floor(index / 2) * 155, sectionId);
    }

    function dropNode(event, sectionId) {
      event.preventDefault();
      var nodeId = event.dataTransfer.getData("text/brain-node");
      var node = state.nodes.find(function (item) { return item.id === nodeId; });
      if (node && canEdit) moveToSection(node, sectionId);
    }

    function dropHeld(event) {
      event.preventDefault();
      var nodeId = event.dataTransfer.getData("text/brain-node");
      var node = state.nodes.find(function (item) { return item.id === nodeId; });
      if (node && canEdit) holdNode(node);
    }

    function compactCard(node) {
      var owner = member(node.author_id), assignee = member(node.assignee_id);
      return h("article", {
        key: node.id,
        className: "brain-board-card",
        "data-color": node.color,
        draggable: canEdit,
        onDragStart: function (event) { event.dataTransfer.setData("text/brain-node", node.id); event.dataTransfer.effectAllowed = "move"; }
      },
      h("div", {className: "brain-board-card-head"},
        h("span", {className: "brain-note-status " + node.status}, node.status === "accepted" ? "✓ 채택" : "아이디어"),
        canEdit ? h("div", {className: "brain-card-actions"},
          h("button", {type: "button", onClick: function () { editNode(node); }, title: "내용 수정"}, "✎"),
          h("button", {type: "button", onClick: function () { deleteNode(node); }, title: "삭제"}, "×")
        ) : null),
      h("p", null, node.content),
      h("div", {className: "brain-card-people"},
        h("span", {className: "brain-person", title: "작성자 " + (owner?.display_name || "알 수 없음")}, h("b", null, initials(owner?.display_name)), h("small", null, owner?.display_name || "작성자")),
        h("span", {className: "brain-person assignee", title: "담당자 " + (assignee?.display_name || "없음")}, h("i", null, "→"), h("b", null, initials(assignee?.display_name)), h("small", null, assignee?.display_name || "담당자 없음"))
      ),
      canEdit ? h("div", {className: "brain-card-controls"},
        h("button", {type: "button", onClick: function () { statusNode(node, "held"); }}, "보류"),
        assigneeButton(node)
      ) : null);
    }

    function boardColumn(section, index) {
      var color = laneColors[index % laneColors.length];
      var nodes = visible.filter(function (node) { return node.node_type === "note" && node.section_id === section.id; });
      return h("section", {key: section.id, className: "brain-board-column", style: {"--lane-bg": color[0], "--lane-border": color[1], "--lane-accent": color[2]}, onDragOver: function (event) { if (canEdit) event.preventDefault(); }, onDrop: function (event) { dropNode(event, section.id); }},
        h("header", null,
          h("span", null, String(index + 1).padStart(2, "0")),
          h("div", null, h("strong", null, section.title), h("small", null, nodes.length + "개 아이디어")),
          state.permissions.can_apply_ai && !state.permissions.is_completed ? h("button", {type: "button", onClick: previewPrd}, "✦ AI PRD 적용") : null
        ),
        h("div", {className: "brain-board-stack"}, nodes.length ? nodes.map(compactCard) : h("div", {className: "brain-column-empty"}, h("i", {className: "bi bi-lightbulb"}), h("span", null, "아이디어를 이 칸으로 끌어오세요")))
      );
    }

    function renderBoard() {
      var unclassified = visible.filter(function (node) { return node.node_type === "note" && !node.section_id; });
      return h("main", {className: "brain-board-view"},
        h("section", {className: "brain-unclassified-strip", onDragOver: function (event) { if (canEdit) event.preventDefault(); }, onDrop: function (event) { dropNode(event, null); }},
          h("header", null, h("div", null, h("strong", null, "미분류 아이디어"), h("span", null, unclassified.length)), h("p", null, "AI 분류 전이거나 직접 옮길 메모입니다.")),
          h("div", null, unclassified.length ? unclassified.map(compactCard) : h("div", {className: "brain-strip-empty"}, "미분류 메모가 없습니다."))
        ),
        h("div", {className: "brain-board-columns"}, state.sections.map(boardColumn))
      );
    }

    function renderList() {
      var groups = [{id: null, title: "미분류"}].concat(state.sections);
      return h("main", {className: "brain-list-view"}, h("div", {className: "brain-list-wrap"},
        h("header", {className: "brain-list-heading"}, h("div", null, h("span", null, "IDEA INVENTORY"), h("h2", null, "전체 아이디어 목록")), h("strong", null, visible.filter(function (node) { return node.node_type === "note"; }).length + "개")),
        groups.map(function (group, index) {
          var nodes = visible.filter(function (node) { return node.node_type === "note" && node.section_id === group.id; });
          return h("section", {key: group.id || "none", className: "brain-list-group"},
            h("header", null, h("i", {style: {background: laneColors[index % laneColors.length][2]}}), h("strong", null, group.title), h("span", null, nodes.length)),
            nodes.length ? h("div", null, nodes.map(function (node) { var assigned = member(node.assignee_id); return h("article", {key: node.id}, h("span", {className: "brain-note-status " + node.status}, node.status === "accepted" ? "채택" : "기본"), h("p", null, node.content), h("small", null, "담당 " + (assigned?.display_name || "없음")), canEdit ? h("button", {type: "button", onClick: function () { editNode(node); }}, "열기") : null); })) : h("p", {className: "brain-list-empty"}, "등록된 아이디어가 없습니다."));
        })
      ));
    }

    function renderCanvas() {
      return h("main", {className: "brain-stage", onMouseDown: pan, onWheel: wheelCanvas},
        h("div", {className: "brain-canvas-hint"}, h("i", {className: "bi bi-arrows-move"}), " 빈 공간을 드래그해 이동 · 휠로 패닝 · Ctrl+휠로 확대/축소"),
        h("div", {className: "brain-zoom"}, h("button", {onClick: function () { zoom(.1); }}, "+"), h("span", null, Math.round(view.zoom * 100) + "%"), h("button", {onClick: function () { zoom(-.1); }}, "−"), h("button", {onClick: function () { var next = {x: 0, y: 0, zoom: 1}; setView(next); saveView(next); }}, "⌂")),
        h("div", {className: "brain-canvas", style: {width: canvasWidth(), height: CANVAS_H, transform: "translate(" + view.x + "px," + view.y + "px) scale(" + view.zoom + ")"}},
          h("section", {className: "brain-free-zone", style: {width: canvasWidth() - 80}}, h("div", null, h("strong", null, "미분류 아이디어"), h("span", null, state.counts.unclassified)), h("p", null, "메모를 자유롭게 작성한 뒤 아래 섹션으로 드래그해 분류하세요")),
          state.sections.map(function (section, index) { var color = laneColors[index % laneColors.length], count = visible.filter(function (node) { return node.section_id === section.id; }).length; return h("section", {key: section.id, className: "brain-lane", style: {left: 40 + index * (LANE_W + LANE_GAP), top: LANE_TOP, width: LANE_W, height: LANE_H, background: color[0], borderColor: color[1]}}, h("header", {style: {background: color[1], color: color[2]}}, h("span", null, String(index + 1).padStart(2, "0")), h("strong", null, section.title), h("small", null, count + "개 아이디어")), state.permissions.can_apply_ai && !state.permissions.is_completed ? h("button", {className: "brain-lane-apply", style: {color: color[2], borderColor: color[1]}, onClick: previewPrd}, "✦ AI PRD 적용") : null); }),
          h("svg", {className: "brain-lines", width: canvasWidth(), height: CANVAS_H}, state.connections.map(line)),
          visible.map(note)));
    }

    function renderEditor() {
      if (!editor) return null;
      var colorOptions = ["yellow", "blue", "pink", "green", "orange", "purple"];
      var current = member(state.current_user_id);
      return window.ReactDOM.createPortal(h("div", {className: "brain-editor-backdrop", onMouseDown: function (event) { if (event.target === event.currentTarget) setEditor(null); }},
        h("section", {className: "brain-editor-modal", role: "dialog", "aria-modal": "true", "aria-labelledby": "brain-editor-title"},
          h("header", null, h("div", null, h("span", null, editor.node ? "EDIT IDEA" : "NEW IDEA"), h("h2", {id: "brain-editor-title"}, editor.node ? "아이디어 수정" : "새 메모 추가")), h("button", {type: "button", onClick: function () { setEditor(null); }, "aria-label": "닫기"}, "×")),
          h("div", {className: "brain-editor-body"},
            !editor.node ? h("div", {className: "brain-color-picker"}, colorOptions.map(function (color) { return h("button", {key: color, type: "button", "data-color": color, className: editor.color === color ? "active" : "", onClick: function () { setEditor(Object.assign({}, editor, {color: color})); }, "aria-label": color + " 색상"}); })) : null,
            h("textarea", {autoFocus: true, rows: 5, maxLength: 2000, value: editor.content, placeholder: "아이디어를 자유롭게 적어보세요…", onChange: function (event) { setEditor(Object.assign({}, editor, {content: event.target.value})); }}),
            h("div", {className: "brain-editor-author"}, h("span", null, "작성자"), h("b", null, initials(current?.display_name)), h("strong", null, current?.display_name || "로그인 사용자"), h("small", null, "작성자는 변경할 수 없습니다."))
          ),
          h("footer", null, h("button", {type: "button", className: "btn btn-light", onClick: function () { setEditor(null); }}, "취소"), h("button", {type: "button", className: "btn btn-primary", disabled: !(editor.content || "").trim(), onClick: saveEditor}, editor.node ? "수정 저장" : "메모 추가"))
        )), document.body);
    }

    function renderAiPanel() {
      if (!aiPanel) return null;
      var body;
      if (aiPanel.type === "classification_result") {
        var result = aiPanel.result, counts = result.counts;
        body = h("div", null,
          h("p", {className: "lead"}, "활성 메모 " + counts.total + "개 중 " + counts.classified + "개가 섹션에 분류되어 있습니다."),
          h("div", {className: "brain-result-counts"},
            h("span", null, "분류됨 ", h("strong", null, counts.classified)),
            h("span", null, "미분류 ", h("strong", null, counts.unclassified)),
            h("span", null, "보류 ", h("strong", null, counts.held))
          ),
          h("h3", null, "섹션별 분류 결과"),
          h("ul", null, result.sections.map(function (row) {
            return h("li", {key: row.id}, h("span", null, String(row.position).padStart(2, "0") + " " + row.title), h("strong", null, row.note_count + "개"));
          }))
        );
      } else {
        body = h("div", null,
          (aiPanel.job.output.answers || []).map(function (row) { return h("article", {key: row.question_id}, h("strong", null, row.question_prompt || "질문 " + row.question_id), h("p", null, row.draft)); }),
          h("button", {className: "btn btn-primary w-100", onClick: applyPrd}, "질문별 통합 답변 저장")
        );
      }
      return h("aside", {className: "brain-ai-panel"},
        h("header", null,
          h("div", null, h("span", null, aiPanel.type === "classification_result" ? "CLASSIFICATION RESULT" : "AI RESULT"), h("h2", null, aiPanel.type === "classification_result" ? "분류 결과" : "PRD 반영 미리보기")),
          h("button", {type: "button", onClick: function () { setAiPanel(null); }}, "×")
        ),
        h("div", {className: "brain-ai-body"}, body)
      );
    }

    function changeBoard(value) {
      setBoardView(value); setSource(null); setTool("select");
    }

    return h("div", {className: "brain-react-shell"},
      h("header", {className: "brain-topbar"},
        h("div", {className: "brain-project"}, h("a", {href: "/ideas/prds/" + root.dataset.prdId + "/", className: "brain-back"}, h("i", {className: "bi bi-arrow-left"}), " PRD로 돌아가기"), h("span", {className: "brain-divider"}), h("div", null, h("strong", {className: "brain-title"}, prdTitle), h("small", null, "브레인스토밍 보드"))),
        h("nav", {className: "brain-view-tabs", "aria-label": "브레인스토밍 보기 방식"}, [
          ["board", "bi bi-kanban", "섹션 보드"], ["canvas", "bi bi-bounding-box", "자유 캔버스"], ["list", "bi bi-list-ul", "아이디어 목록"]
        ].map(function (item) { return h("button", {key: item[0], type: "button", className: boardView === item[0] ? "active" : "", onClick: function () { changeBoard(item[0]); }}, h("i", {className: item[1]}), item[2]); })),
        h("div", {className: "brain-top-actions"}, h("span", {className: "brain-sync " + sync}, sync === "connected" ? "● 동기화됨" : "● 재연결 중"), state.permissions.can_apply_ai && !state.permissions.is_completed ? h("button", {type: "button", className: "btn btn-sm btn-outline-primary", disabled: busy, onClick: previewPrd}, "PRD에 반영") : null)
      ),
      h("div", {className: "brain-toolbar"},
        h("div", {className: "brain-counts"}, h("span", null, state.counts.total + "개 메모"), h("span", {className: "warn"}, "미분류 " + state.counts.unclassified), h("span", {className: "good"}, "✓ " + state.counts.accepted + "개 채택")),
        boardView === "canvas" ? h("div", {className: "brain-tools"}, toolButton("select", "bi bi-cursor", "선택"), toolButton("connect", "bi bi-bezier2", "연결")) : null,
        canEdit ? h("button", {type: "button", className: "brain-add", onClick: createNote}, h("i", {className: "bi bi-plus-lg"}), " 메모 추가") : null,
        h("div", {className: "brain-filter"}, ["all", "accepted", "default"].map(function (value) { return h("button", {key: value, type: "button", className: filter === value ? "active" : "", onClick: function () { setFilter(value); }}, {all: "전체", accepted: "채택됨", default: "미분류"}[value]); })),
        boardView === "canvas" && canEdit ? h("button", {type: "button", className: "btn btn-sm brain-auto", disabled: busy, onClick: autoLayout}, h("i", {className: "bi bi-grid-3x3-gap"}), " 자동 정렬") : null,
        h("div", {className: "brain-ai-actions"}, h("button", {type: "button", disabled: busy, onClick: loadClassificationResult}, h("i", {className: "bi bi-diagram-3"}), " 분류 결과"))
      ),
      boardView === "canvas" && tool === "connect" ? h("div", {className: "brain-connect-banner"}, source ? "두 번째 메모를 선택해 주세요" : "연결할 첫 번째 메모를 선택해 주세요", h("button", {onClick: function () { setTool("select"); setSource(null); }}, "취소")) : null,
      notice ? h("div", {className: "brain-notice alert alert-" + notice.kind}, notice.text, h("button", {type: "button", className: "btn-close", onClick: function () { setNotice(null); }})) : null,
      boardView === "board" ? renderBoard() : boardView === "canvas" ? renderCanvas() : renderList(),
      h("section", {className: "brain-held", onDragOver: function (event) { if (canEdit) event.preventDefault(); }, onDrop: dropHeld}, h("header", null, h("strong", null, "⏸ 보류 구역"), h("span", null, state.held_nodes.length), h("small", null, "메모를 이곳으로 끌어오거나 보류 버튼을 누르면 보류됩니다")), h("div", null, state.held_nodes.map(function (node) { return h("article", {key: node.id, "data-color": node.color}, h("p", null, node.content), canEdit ? h("button", {onClick: function () { statusNode(node, "default"); }}, "미분류로 이동 →") : null); }))),
      renderEditor(), renderAssigneeMenu(), renderAiPanel(),
      busy ? h("div", {className: "brain-busy"}, h("span", {className: "spinner-border spinner-border-sm"}), jobId ? " AI 작업 처리 중" : " 저장 중") : null);
  }

  window.ReactDOM.createRoot(root).render(h(BrainstormApp));
}());
