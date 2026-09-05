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
  var activeCanvasId = null;
  var NODE_W = 230;
  var NODE_H = 150;
  var LANE_W = 290;
  var LANE_GAP = 20;
  var LANE_TOP = 350;
  var LANE_H = 2200;
  var CANVAS_W = 4200;
  var CANVAS_H = 2400;
  // 도화지 네모 하나를 곡선으로 갈라 영역을 만든다.
  // 이웃한 조각이 같은 경계식을 쓰므로 사이에 빈틈이 생기지 않는다.
  // 메모를 넉넉히 놓을 수 있도록 크게 잡는다.
  // 대신 화면을 열 때 도화지 전체가 보이도록 배율을 자동으로 맞춘다.
  // 네모 밖은 여백으로 두어 분류하지 않은 메모를 놓는 자리로 쓴다.
  // 도화지 = 네모(항목 영역) + 오른쪽 여백(미분류 자리).
  // 화면을 열면 이 둘이 나란히 한눈에 들어와야 한다.
  var TRAY_W = 700;            // 오른쪽 미분류 여백의 너비
  var TRAY_GAP = 46;           // 네모와 여백 사이 간격
  var BOARD_BASE = {x: 55, y: 45, w: 1900, h: 1150};
  var BOARD = {x: BOARD_BASE.x, y: BOARD_BASE.y, w: BOARD_BASE.w, h: BOARD_BASE.h};
  // 메모가 늘면 네모도 자란다. 비어 있을 때 크게 열어 둘 이유가 없고,
  // 많아지면 놓을 자리가 필요하므로 개수를 따라 넓힌다.
  var BOARD_FREE_SLOTS = 14;
  var BOARD_MAX = {w: 4600, h: 2900};
  function resizeBoard(total) {
    // 항목이 7개라 메모가 7개 늘 때마다 각 항목이 한 자리씩 더 필요하다.
    var over = Math.max(0, Number(total || 0) - BOARD_FREE_SLOTS);
    var steps = Math.ceil(over / 7);
    BOARD.w = Math.min(BOARD_MAX.w, BOARD_BASE.w + steps * 260);
    BOARD.h = Math.min(BOARD_MAX.h, BOARD_BASE.h + steps * 170);
  }
  // 미분류 메모를 두는 오른쪽 여백. 네모가 자라면 같이 밀린다.
  function trayBox() {
    return {x: BOARD.x + BOARD.w + TRAY_GAP, y: BOARD.y, w: TRAY_W, h: BOARD.h};
  }
  // 화면에 들어와야 할 전체 폭·높이 = 네모 + 간격 + 여백.
  function canvasContentSize() {
    return {w: BOARD.x * 2 + BOARD.w + TRAY_GAP + TRAY_W, h: BOARD.y * 2 + BOARD.h};
  }
  var REGION_CELLS = [
    {row: 0, col: 0}, {row: 0, col: 1}, {row: 0, col: 2},
    {row: 1, col: 0}, {row: 1, col: 1}, {row: 1, col: 2},
    {row: 2, col: 0}
  ];
  var ROW_COUNT = 3;
  // 메모가 많이 붙은 항목이 더 넓은 땅을 갖도록 영역별 무게를 둔다.
  // 아무것도 없을 때는 모두 1이라 균등하게 나뉜다.
  var regionWeights = REGION_CELLS.map(function () { return 1; });
  function setRegionWeights(counts) {
    regionWeights = REGION_CELLS.map(function (cell, index) {
      // 비어 있어도 이름표가 들어갈 최소 땅은 남긴다.
      return 1 + Math.min(6, Number(counts[index] || 0)) * 0.55;
    });
  }
  function cellsInRow(row) {
    return REGION_CELLS.map(function (cell, index) { return {cell: cell, index: index}; })
      .filter(function (item) { return item.cell.row === row; });
  }
  // 무게 목록을 0~1 사이 누적 경계로 바꾼다. 한 조각이 지나치게 작아지지 않도록 눌러 준다.
  function toEdges(weights) {
    var floor = 0.16, total = weights.reduce(function (sum, value) { return sum + value; }, 0) || 1;
    var shares = weights.map(function (value) { return Math.max(floor, value / total); });
    var scale = shares.reduce(function (sum, value) { return sum + value; }, 0);
    var edges = [0], running = 0;
    shares.forEach(function (share) { running += share / scale; edges.push(running); });
    edges[edges.length - 1] = 1;
    return edges;
  }
  function rowEdges() {
    var weights = [];
    for (var row = 0; row < ROW_COUNT; row += 1) {
      weights.push(cellsInRow(row).reduce(function (sum, item) { return sum + regionWeights[item.index]; }, 0));
    }
    return toEdges(weights);
  }
  function rowSplits(row) {
    var edges = toEdges(cellsInRow(row).map(function (item) { return regionWeights[item.index]; }));
    return edges.slice(1, -1);
  }
  // 가로 경계선: 도화지를 가로지르며 물결친다. 위아래 두 조각이 이 선을 함께 쓴다.
  function edgeY(edge, xRatio) {
    var edges = rowEdges();
    var base = BOARD.y + BOARD.h * edges[edge];
    if (edge === 0 || edge === edges.length - 1) return base;
    return base + Math.sin(xRatio * Math.PI * 2.2 + edge * 1.9) * 34;
  }
  // 세로 경계선: 양 끝(모서리)에서는 흔들림이 0이라 조각들이 정확히 맞물린다.
  function edgeX(colRatio, row, t) {
    var base = BOARD.x + BOARD.w * colRatio;
    if (colRatio === 0 || colRatio === 1) return base;
    return base + Math.sin(Math.PI * t) * 44 * (row % 2 === 0 ? 1 : -1);
  }
  function cellRatios(cell) {
    var lefts = [0].concat(rowSplits(cell.row)).concat([1]);
    return {left: lefts[cell.col], right: lefts[cell.col + 1]};
  }
  function regionPoints(index) {
    var cell = REGION_CELLS[index % REGION_CELLS.length];
    var side = cellRatios(cell);
    var topEdge = cell.row, bottomEdge = cell.row + 1;
    var steps = 26;
    var points = [];
    // 위 경계: 왼쪽 → 오른쪽
    for (var a = 0; a <= steps; a += 1) {
      var xr = side.left + (side.right - side.left) * (a / steps);
      points.push([BOARD.x + BOARD.w * xr, edgeY(topEdge, xr)]);
    }
    // 오른쪽 경계: 위 → 아래
    for (var b = 1; b <= steps; b += 1) {
      var t = b / steps;
      var yTop = edgeY(topEdge, side.right), yBottom = edgeY(bottomEdge, side.right);
      points.push([edgeX(side.right, cell.row, t), yTop + (yBottom - yTop) * t]);
    }
    // 아래 경계: 오른쪽 → 왼쪽
    for (var c = 1; c <= steps; c += 1) {
      var xr2 = side.right + (side.left - side.right) * (c / steps);
      points.push([BOARD.x + BOARD.w * xr2, edgeY(bottomEdge, xr2)]);
    }
    // 왼쪽 경계: 아래 → 위
    for (var d = 1; d < steps; d += 1) {
      var u = 1 - d / steps;
      var yTop2 = edgeY(topEdge, side.left), yBottom2 = edgeY(bottomEdge, side.left);
      points.push([edgeX(side.left, cell.row, u), yTop2 + (yBottom2 - yTop2) * u]);
    }
    return points;
  }
  function regionPath(index) {
    return regionPoints(index).reduce(function (path, point, i) {
      return path + (i === 0 ? "M " : " L ") + point[0].toFixed(1) + " " + point[1].toFixed(1);
    }, "") + " Z";
  }
  // 곡선 영역을 감싸는 최소 사각형. 빈 자리를 훑을 범위로 쓴다.
  function regionBounds(index) {
    var points = regionPoints(index);
    var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    points.forEach(function (point) {
      minX = Math.min(minX, point[0]); maxX = Math.max(maxX, point[0]);
      minY = Math.min(minY, point[1]); maxY = Math.max(maxY, point[1]);
    });
    return {x: minX, y: minY, w: maxX - minX, h: maxY - minY};
  }
  // 영역 이름표와 메모 배치에 쓸 대략의 중심.
  function regionCenter(index) {
    var cell = REGION_CELLS[index % REGION_CELLS.length];
    var side = cellRatios(cell);
    var midRatio = (side.left + side.right) / 2;
    return {
      x: BOARD.x + BOARD.w * midRatio,
      y: (edgeY(cell.row, midRatio) + edgeY(cell.row + 1, midRatio)) / 2,
      w: BOARD.w * (side.right - side.left),
      h: BOARD.h * (rowEdges()[cell.row + 1] - rowEdges()[cell.row]),
      top: edgeY(cell.row, midRatio)
    };
  }
  // 곡선 안에 점이 들어있는지는 브라우저의 Path2D 판정을 그대로 쓴다.
  var hitContext = document.createElement("canvas").getContext("2d");
  // 도화지가 화면에 통째로 들어오도록 배율과 위치를 계산한다.
  function fitBoardView() {
    var stage = document.querySelector(".brain-stage");
    var width = stage ? stage.clientWidth : window.innerWidth;
    var height = stage ? stage.clientHeight : window.innerHeight - 220;
    var margin = 28;
    var content = canvasContentSize();
    var zoom = Math.max(.2, Math.min(1.4, Math.min(
      (width - margin * 2) / content.w,
      (height - margin * 2) / content.h
    )));
    return {
      x: (width - content.w * zoom) / 2,
      y: margin / 2,
      zoom: zoom
    };
  }
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
      headers: Object.assign(
        {"Content-Type": "application/json", "X-CSRFToken": csrf},
        activeCanvasId ? {"X-Brainstorm-Canvas-Id": String(activeCanvasId)} : {},
        options.headers || {}
      )
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
    // 연결선이 많아지면 서로 어지럽게 교차한다. 메모를 가리키거나 고른 동안만
    // 그 메모로 이어진 선을 도드라지게 하고 나머지는 옅게 깔아 둔다.
    var hoverPair = window.React.useState(null), hoveredNode = hoverPair[0], setHoveredNode = hoverPair[1];
    var viewPair = window.React.useState({x: 0, y: 0, zoom: 1}), view = viewPair[0], setView = viewPair[1];
    var noticePair = window.React.useState(null), notice = noticePair[0], setNotice = noticePair[1];
    var busyPair = window.React.useState(false), busy = busyPair[0], setBusy = busyPair[1];
    var jobPair = window.React.useState(null), jobId = jobPair[0], setJobId = jobPair[1];
    var aiPair = window.React.useState(null), aiPanel = aiPair[0], setAiPanel = aiPair[1];
    var editorPair = window.React.useState(null), editor = editorPair[0], setEditor = editorPair[1];
    var assigneeMenuPair = window.React.useState(null), assigneeMenu = assigneeMenuPair[0], setAssigneeMenu = assigneeMenuPair[1];
    var heldExpandedPair = window.React.useState(true), heldExpanded = heldExpandedPair[0], setHeldExpanded = heldExpandedPair[1];
    var versionsOpenPair = window.React.useState(true), versionsOpen = versionsOpenPair[0], setVersionsOpen = versionsOpenPair[1];
    var timerRef = window.React.useRef(null);
    var cursorRef = window.React.useRef(null);
    var initialViewport = window.React.useRef(false);
    var viewportSaveRef = window.React.useRef(null);
    // 지금 끌고 있는 메모. 이 메모만은 자리 정리에서 빼 손을 그대로 따라오게 한다.
    var draggingRef = window.React.useRef(null);
    // 첫 그림에는 이름표 글자가 아직 없어 자리를 어림잡을 수밖에 없다.
    // 글자가 생긴 다음 한 번 더 그려서 잰 크기로 자리를 확정한다.
    var measuredPair = window.React.useState(false), measured = measuredPair[0], setMeasured = measuredPair[1];
    window.React.useEffect(function () {
      if (!measured && state) setMeasured(true);
    });
    var fullSyncGenerationRef = window.React.useRef(0);

    function fullSync(canvasId) {
      if (canvasId !== undefined && canvasId !== null) {
        activeCanvasId = canvasId;
        initialViewport.current = false;
      }
      var generation = ++fullSyncGenerationRef.current;
      setSync("loading");
      return request(apiBase + "canvas/", {headers: {"Idempotency-Key": key()}})
        .then(function (data) {
          if (generation !== fullSyncGenerationRef.current) return;
          activeCanvasId = data.canvas.id;
          cursorRef.current = data.cursor; setState(data); setSync("connected");
          if (!initialViewport.current) {
            resizeBoard((data.nodes || []).filter(function (n) { return n.node_type === "note" && n.status !== "held"; }).length);
            // 페이지를 열 때는 언제나 도화지 전체가 한눈에 들어오게 맞춘다.
            // 지난번에 확대해 둔 배율을 그대로 복원하면 들어오자마자 축소해야 한다.
            setView(fitBoardView());
            initialViewport.current = true;
            // 첫 계산은 무대가 아직 그려지기 전일 수 있어 한 번 더 맞춘다.
            window.requestAnimationFrame(function () {
              window.requestAnimationFrame(function () { setView(fitBoardView()); });
            });
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
        // 배율로 나눈 좌표는 소수점이 길게 남는다. 서버가 자릿수를 12개로 제한하므로 반올림한다.
        var x = Math.round(Math.max(20, Math.min(CANVAS_W - NODE_W, (window.innerWidth / 2 - view.x) / view.zoom - NODE_W / 2)));
        var y = Math.round(Math.max(20, Math.min(CANVAS_H - NODE_H, ((window.innerHeight - 190) / 2 - view.y) / view.zoom - NODE_H / 2)));
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
      // 배율로 나눈 좌표는 소수점이 길게 남는다. 서버가 자릿수를 12개로 제한하므로 반올림한다.
      x = Math.round(x); y = Math.round(y);
      // 서버 응답을 기다리지 않고 화면에 먼저 반영한다.
      // 영역 크기가 메모 수를 따라가므로 놓는 즉시 땅이 넓어지는 것이 보여야 한다.
      setState(function (current) {
        if (!current) return current;
        return Object.assign({}, current, {
          nodes: current.nodes.map(function (item) {
            return item.id === node.id
              ? Object.assign({}, item, {x: x, y: y, section_id: sectionId})
              : item;
          })
        });
      });
      refresh(request(apiBase + "nodes/" + node.id + "/position/", {method: "PATCH", body: JSON.stringify({version: node.version, x: x, y: y, section_id: sectionId})}));
    }

    function holdNode(node) {
      statusNode(node, "held");
    }

    function canvasWidth() { return CANVAS_W; }
    function laneIndex(sectionId) { return state.sections.findIndex(function (section) { return section.id === sectionId; }); }
    // 이름표가 차지하는 띠의 높이. 번호·제목·개수 세 줄이 여기에 들어간다.
    var LABEL_BAND = 118;
    // 그리는 위치는 저장된 좌표 그대로다.
    // 끌고 다니는 동안 밀어내면 메모가 손을 따라오지 않아 어디에 놓이는지 알 수 없다.
    // 자리 정리는 손을 뗀 뒤 settleInRegion이 한 번만 한다.
    function displayPosition(node) {
      return {x: Number(node.x), y: Number(node.y)};
    }
    function overlaps(ax, ay, aw, ah, bx, by, bw, bh) {
      return ax < bx + bw && ax + aw > bx && ay < by + bh && ay + ah > by;
    }
    // 이름표가 놓인 자리. 메모가 조금이라도 겹치면 안 된다.
    // 번호·제목·개수의 실제 글자 크기를 재서 쓴다. 제목 길이가 영역마다 달라
    // 어림잡은 폭으로는 긴 제목의 끝을 가리게 된다.
    function labelBox(index) {
      var box = regionCenter(index);
      var group = document.querySelectorAll(".brain-region")[index];
      var texts = group ? group.querySelectorAll("text") : [];
      var pad = 14;
      var minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      for (var i = 0; i < texts.length; i += 1) {
        try {
          var b = texts[i].getBBox();
          minX = Math.min(minX, b.x); maxX = Math.max(maxX, b.x + b.width);
          minY = Math.min(minY, b.y); maxY = Math.max(maxY, b.y + b.height);
        } catch (error) { /* 아직 그려지지 않은 글자는 건너뛴다 */ }
      }
      if (minX < maxX) {
        return {x: minX - pad, y: minY - pad, w: maxX - minX + pad * 2, h: maxY - minY + pad * 2};
      }
      // 화면에 없으면 이름표가 차지할 자리를 어림잡는다.
      var half = Math.min(260, Math.max(120, box.w / 2 - 20));
      return {x: box.x - half, y: box.top + 18, w: half * 2, h: LABEL_BAND};
    }
    // 미분류는 칸이 아니라 그냥 빈 여백이라 이름표가 상단 한 줄뿐이다.
    // 실제 글자 크기를 재서 그 자리에 메모가 걸리면 아래로 비켜 준다.
    function trayLabelBox() {
      var tray = trayBox();
      var title = document.querySelector(".brain-tray-title");
      var hint = document.querySelector(".brain-tray-hint");
      var pad = 14, minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
      [title, hint].forEach(function (el) {
        if (!el) return;
        try {
          var b = el.getBBox();
          minX = Math.min(minX, b.x); maxX = Math.max(maxX, b.x + b.width);
          minY = Math.min(minY, b.y); maxY = Math.max(maxY, b.y + b.height);
        } catch (error) { /* 아직 그려지지 않은 글자는 건너뛴다 */ }
      });
      if (minX < maxX) {
        return {x: minX - pad, y: minY - pad, w: maxX - minX + pad * 2, h: maxY - minY + pad * 2, bottom: maxY + pad};
      }
      return {x: tray.x, y: tray.y, w: tray.w, h: 92, bottom: tray.y + 92};
    }
    // 놓은 자리를 영역 안의 빈 곳으로 옮겨 준다.
    // 네 모서리가 모두 영역 안에 들어가야 하므로 곡선 밖으로 삐져나오지 않는다.
    // taken은 이미 자리를 차지한 메모들의 좌표다.
    function settleInRegion(index, wantX, wantY, taken) {
      var path = new Path2D(regionPath(index));
      var bounds = regionBounds(index);
      var label = labelBox(index);
      var GAP = 10;
      // 경계선에 딱 붙으면 어느 영역 것인지 헷갈린다. 이만큼은 안쪽으로 들여 놓는다.
      var PAD = 24;
      // 네 모서리에 각 변의 가운데까지 본다.
      // 곡선이 안쪽으로 부풀면 모서리만으로는 선을 넘은 것을 놓친다.
      function inside(x, y, pad) {
        var left = x - pad, top = y - pad;
        var right = x + NODE_W + pad, bottom = y + NODE_H + pad;
        var midX = (left + right) / 2, midY = (top + bottom) / 2;
        var probes = [
          [left, top], [right, top], [left, bottom], [right, bottom],
          [midX, top], [midX, bottom], [left, midY], [right, midY]
        ];
        return probes.every(function (point) {
          return hitContext.isPointInPath(path, point[0], point[1]);
        });
      }
      // level 0: 여백·이름표·이웃을 모두 지킨다.
      // level 1: 이웃과의 겹침만 눈감는다. 좁은 영역에 메모가 몰린 경우다.
      // level 2: 안쪽 여백까지 포기한다. 그래도 영역 밖과 이름표는 끝까지 지킨다.
      function fits(x, y, level) {
        if (!inside(x, y, level >= 2 ? 0 : PAD)) return false;
        if (overlaps(x, y, NODE_W, NODE_H, label.x, label.y, label.w, label.h)) return false;
        if (level >= 1) return true;
        return !taken.some(function (spot) {
          return overlaps(x, y, NODE_W, NODE_H, spot.x - GAP, spot.y - GAP, NODE_W + GAP * 2, NODE_H + GAP * 2);
        });
      }
      // 놓은 자리가 이미 멀쩡하면 그대로 둔다.
      if (fits(wantX, wantY, 0)) return {x: wantX, y: wantY};
      function nearest(level) {
        var step = 14, best = null, bestDistance = Infinity;
        for (var y = bounds.y; y <= bounds.y + bounds.h - NODE_H; y += step) {
          for (var x = bounds.x; x <= bounds.x + bounds.w - NODE_W; x += step) {
            var distance = (x - wantX) * (x - wantX) + (y - wantY) * (y - wantY);
            if (distance >= bestDistance || !fits(x, y, level)) continue;
            best = {x: x, y: y}; bestDistance = distance;
          }
        }
        return best;
      }
      return nearest(0) || nearest(1) || nearest(2);
    }
    // 화면에 그릴 자리를 한 번에 정한다.
    // 영역의 넓이가 메모 수를 따라 움직이는 탓에, 메모 하나를 옮기면 다른 영역의
    // 경계까지 밀려서 잘 놓여 있던 메모가 선을 넘거나 이름표를 덮는다.
    // 그래서 그릴 때마다 어긋난 것만 안쪽으로 들인다. 저장된 좌표는 건드리지 않으므로
    // 서버에 다시 쓰지 않고, 함께 편집 중인 사람과 부딪히지도 않는다.
    function layoutPositions(nodes) {
      var placed = {};
      var dragging = draggingRef.current;
      nodes.forEach(function (node) { placed[node.id] = {x: Number(node.x), y: Number(node.y)}; });
      state.sections.forEach(function (section, index) {
        var taken = [];
        nodes.forEach(function (node) {
          if (node.node_type === "title" || node.section_id !== section.id) return;
          // 끌고 있는 메모는 손을 따라와야 한다. 자리만 차지한 것으로 친다.
          if (node.id === dragging) return taken.push(placed[node.id]);
          var spot = settleInRegion(index, placed[node.id].x, placed[node.id].y, taken);
          if (spot) placed[node.id] = spot;
          taken.push(placed[node.id]);
        });
      });
      // 분류하지 않은 메모가 네모에 걸쳐 있으면 어느 항목인지 알 수 없다.
      // 왼쪽 여백은 메모 하나가 들어갈 만큼도 안 되므로 오른쪽 여백으로 내보낸다.
      var trayLabel = trayLabelBox();
      nodes.forEach(function (node) {
        if (node.section_id || node.node_type === "title" || node.id === dragging) return;
        var spot = placed[node.id];
        if (overlaps(spot.x, spot.y, NODE_W, NODE_H, BOARD.x, BOARD.y, BOARD.w, BOARD.h)) {
          spot = {x: BOARD.x + BOARD.w + Math.round(TRAY_GAP / 2), y: spot.y};
        }
        // "미분류" 이름표는 여백 맨 위 한 줄뿐이다. 거기에 걸리면 바로 아래로 내린다.
        if (overlaps(spot.x, spot.y, NODE_W, NODE_H, trayLabel.x, trayLabel.y, trayLabel.w, trayLabel.h)) {
          spot = {x: spot.x, y: trayLabel.bottom};
        }
        placed[node.id] = spot;
      });
      return placed;
    }
    // 메모를 고르면 아래에 뜨는 조작 막대의 자리를 정한다.
    // 그대로 두면 항목 경계를 넘거나 다른 메모·이름표·연결선을 덮는다.
    // 아래·위·왼쪽아래·왼쪽위 순서로 시도해 아무것도 가리지 않는 자리를 고른다.
    var ACTIONS_W = 290, ACTIONS_H = 46, ACTIONS_GAP = 7;
    function actionsOffset(node, spot) {
      var index = node.section_id ? laneIndex(node.section_id) : -1;
      var path = index >= 0 ? new Path2D(regionPath(index)) : null;
      var others = visible.filter(function (row) {
        return row.id !== node.id && row.node_type !== "title" && positions[row.id];
      }).map(function (row) { return positions[row.id]; });
      var labels = state.sections.map(function (section, i) { return labelBox(i); });
      var candidates = [
        {dx: 0, dy: NODE_H + ACTIONS_GAP},
        {dx: 0, dy: -(ACTIONS_H + ACTIONS_GAP)},
        {dx: NODE_W - ACTIONS_W, dy: NODE_H + ACTIONS_GAP},
        {dx: NODE_W - ACTIONS_W, dy: -(ACTIONS_H + ACTIONS_GAP)}
      ];
      for (var i = 0; i < candidates.length; i += 1) {
        var x = spot.x + candidates[i].dx, y = spot.y + candidates[i].dy;
        // 항목 안에 완전히 들어가는가.
        if (path) {
          var corners = [[x, y], [x + ACTIONS_W, y], [x, y + ACTIONS_H], [x + ACTIONS_W, y + ACTIONS_H]];
          if (!corners.every(function (p) { return hitContext.isPointInPath(path, p[0], p[1]); })) continue;
        }
        // 다른 메모나 항목 이름을 덮지 않는가.
        var clash = others.some(function (row) {
          return overlaps(x, y, ACTIONS_W, ACTIONS_H, row.x, row.y, NODE_W, NODE_H);
        }) || labels.some(function (box) {
          return overlaps(x, y, ACTIONS_W, ACTIONS_H, box.x, box.y, box.w, box.h);
        });
        if (!clash) return candidates[i];
      }
      return candidates[0];
    }
    // 같은 영역에 이미 놓인 메모들의 좌표.
    function takenSpots(sectionId, exceptId) {
      return state.nodes.filter(function (item) {
        return item.id !== exceptId && item.section_id === sectionId
          && item.node_type === "note" && item.status !== "held";
      }).map(function (item) { return {x: Number(item.x), y: Number(item.y)}; });
    }
    function sectionAt(x, y) {
      var centerX = x + NODE_W / 2, centerY = y + NODE_H / 2;
      for (var index = 0; index < state.sections.length; index += 1) {
        if (hitContext.isPointInPath(new Path2D(regionPath(index)), centerX, centerY)) {
          return state.sections[index].id;
        }
      }
      // 어느 영역에도 닿지 않으면 도화지의 빈 공간이므로 분류하지 않은 상태로 둔다.
      return null;
    }
    // 영역 안에서 메모가 겹치지 않게 놓을 자리를 고른다.
    // 격자로 어림잡은 뒤 settleInRegion에 맡겨 곡선 밖과 이름표를 피하게 한다.
    function slotInRegion(index, order, taken) {
      var box = regionCenter(index);
      var perRow = Math.max(1, Math.floor((box.w * 0.78) / (NODE_W * 0.62)));
      var column = order % perRow, row = Math.floor(order / perRow);
      var guessX = box.x - (perRow * NODE_W * 0.62) / 2 + column * NODE_W * 0.62;
      var guessY = box.top + LABEL_BAND + 8 + row * NODE_H * 0.72;
      return settleInRegion(index, guessX, guessY, taken || []) || {x: guessX, y: guessY};
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
      // 화면에 보이는 자리에서 잡아야 손에 쥐는 순간 메모가 튀지 않는다.
      var start = positions[node.id] || displayPosition(node);
      var sx = event.clientX, sy = event.clientY, moved = false;
      function moving(moveEvent) {
        var deltaX = moveEvent.clientX - sx, deltaY = moveEvent.clientY - sy;
        if (!moved && Math.abs(deltaX) + Math.abs(deltaY) < 5) return;
        moved = true;
        draggingRef.current = node.id;
        var x = Math.max(10, Math.min(canvasWidth() - NODE_W, start.x + deltaX / view.zoom)), y = Math.max(10, Math.min(CANVAS_H - NODE_H, start.y + deltaY / view.zoom));
        setState(function (previous) { return Object.assign({}, previous, {nodes: previous.nodes.map(function (item) { return item.id === node.id ? Object.assign({}, item, {x: x, y: y}) : item; })}); });
      }
      function done(upEvent) {
        window.removeEventListener("mousemove", moving); window.removeEventListener("mouseup", done);
        draggingRef.current = null;
        if (!moved) return;
        if (document.elementFromPoint(upEvent.clientX, upEvent.clientY)?.closest(".brain-held")) {
          holdNode(node);
          return;
        }
        var x = Math.max(10, Math.min(canvasWidth() - NODE_W, start.x + (upEvent.clientX - sx) / view.zoom)), y = Math.max(10, Math.min(CANVAS_H - NODE_H, start.y + (upEvent.clientY - sy) / view.zoom));
        // 손을 뗀 지금에서야 자리를 정리한다.
        var sectionId = sectionAt(x, y), spot = {x: x, y: y}, index = sectionId ? laneIndex(sectionId) : -1;
        if (index >= 0) spot = settleInRegion(index, x, y, takenSpots(sectionId, node.id)) || spot;
        moveNode(node, spot.x, spot.y, sectionId);
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
      var counters = {}, placed = {};
      var nodes = state.nodes.filter(function (node) { return node.node_type === "note" && node.status !== "held"; }).map(function (node) {
        var keyName = node.section_id ? String(node.section_id) : "none", order = counters[keyName] || 0; counters[keyName] = order + 1;
        // 분류하지 않은 메모는 오른쪽 여백에 두 줄로 늘어놓는다.
        if (!node.section_id) {
          var tray = trayBox();
          return {id: node.id, version: node.version, section_id: null, x: tray.x + 24 + (order % 2) * (NODE_W + 20), y: tray.y + 92 + Math.floor(order / 2) * (NODE_H + 18)};
        }
        // 같은 영역에 앞서 배치한 자리를 넘겨야 서로 겹치지 않는다.
        var taken = placed[keyName] || (placed[keyName] = []);
        var slot = slotInRegion(laneIndex(node.section_id), order, taken);
        taken.push(slot);
        return {id: node.id, version: node.version, section_id: node.section_id, x: Math.round(slot.x), y: Math.round(slot.y)};
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
    var canCreateNote = state.permissions.can_create_note && !state.permissions.is_completed;
    var visible = state.nodes.filter(function (node) { return node.node_type === "title" || filter === "all" || node.status === filter; });
    var positions = layoutPositions(visible);

    function toolButton(value, icon, label) { return h("button", {type: "button", className: "brain-tool " + (tool === value ? "active" : ""), onClick: function () { setTool(value); if (value !== "connect") setSource(null); }}, h("i", {className: icon}), label); }
    // 연결선이 상관없는 메모 위를 지나가면 그 메모까지 이어진 것처럼 보이고,
    // 항목 이름 위를 지나가면 글자를 읽기 어렵다. 둘 다 피해서 잇는다.
    // 조종점 두 개를 따로 밀 수 있어야 한쪽 끝에 가까이 붙은 것도 비켜 갈 수 있다.
    // blockers는 {x, y, w, h, margin} 꼴의 사각형들이다.
    function routeConnection(x1, y1, x2, y2, blockers) {
      var dx = x2 - x1, dy = y2 - y1;
      var length = Math.sqrt(dx * dx + dy * dy) || 1;
      var awayX = -dy / length, awayY = dx / length;
      function control(first, second) {
        return {
          ax: x1 + dx / 3 + awayX * first, ay: y1 + dy / 3 + awayY * first,
          bx: x1 + dx * 2 / 3 + awayX * second, by: y1 + dy * 2 / 3 + awayY * second
        };
      }
      function hits(c) {
        // 이은 두 메모는 blockers에서 이미 빠졌으므로 선 전체를 살핀다.
        for (var step = 1; step <= 47; step += 1) {
          var t = step / 48, u = 1 - t;
          var px = u * u * u * x1 + 3 * u * u * t * c.ax + 3 * u * t * t * c.bx + t * t * t * x2;
          var py = u * u * u * y1 + 3 * u * u * t * c.ay + 3 * u * t * t * c.by + t * t * t * y2;
          var blocked = blockers.some(function (spot) {
            var edge = spot.margin;
            return px > spot.x - edge && px < spot.x + spot.w + edge
              && py > spot.y - edge && py < spot.y + spot.h + edge;
          });
          if (blocked) return true;
        }
        return false;
      }
      // 0은 곧은 선. 그다음부터 양쪽을 함께, 앞쪽만, 뒤쪽만 순서로 넓혀 간다.
      var steps = [110, 220, 340, 470, 620];
      var shapes = [control(0, 0)];
      steps.forEach(function (amount) {
        [amount, -amount].forEach(function (signed) {
          shapes.push(control(signed, signed));
          shapes.push(control(signed, 0));
          shapes.push(control(0, signed));
        });
      });
      for (var i = 0; i < shapes.length; i += 1) {
        if (!hits(shapes[i])) return shapes[i];
      }
      // 어느 쪽으로도 못 비키면 곧게 잇는다.
      return shapes[0];
    }
    // 한 메모에 여러 선이 붙으면 모두 같은 중심에서 출발해 겹쳐 보인다.
    // 강조 중인 메모에서는 선들을 테두리에 부챗살처럼 나눠 붙여 서로 떨어뜨린다.
    function spreadAnchor(spotlight, connection, cx, cy, towardX, towardY) {
      if (!spotlight) return {x: cx, y: cy};
      var siblings = state.connections.filter(function (row) {
        return row.node_a_id === spotlight || row.node_b_id === spotlight;
      });
      if (siblings.length < 2) return {x: cx, y: cy};
      // 상대 메모의 방향 순서대로 줄을 세워야 선끼리 꼬이지 않는다.
      var ordered = siblings.map(function (row) {
        var otherId = row.node_a_id === spotlight ? row.node_b_id : row.node_a_id;
        var other = positions[otherId];
        return {id: row.id, angle: other ? Math.atan2(other.y - cy, other.x - cx) : 0};
      }).sort(function (left, right) { return left.angle - right.angle; });
      var slot = ordered.findIndex(function (row) { return row.id === connection.id; });
      if (slot < 0) return {x: cx, y: cy};
      // 상대 쪽을 향한 방향을 기준으로 좌우로 고르게 벌린다.
      var base = Math.atan2(towardY - cy, towardX - cx);
      var spread = Math.min(1.1, 0.34 * (ordered.length - 1));
      var offset = ordered.length < 2 ? 0 : -spread / 2 + spread * (slot / (ordered.length - 1));
      var angle = base + offset;
      var radiusX = NODE_W / 2 - 6, radiusY = NODE_H / 2 - 6;
      return {x: cx + Math.cos(angle) * radiusX, y: cy + Math.sin(angle) * radiusY};
    }
    function line(connection) {
      var a = positions[connection.node_a_id], b = positions[connection.node_b_id]; if (!a || !b) return null;
      var x1 = a.x + NODE_W / 2, y1 = a.y + NODE_H / 2, x2 = b.x + NODE_W / 2, y2 = b.y + NODE_H / 2;
      // 강조 중인 메모 쪽 끝만 부챗살로 벌려 선끼리 겹치지 않게 한다.
      var spotlightId = hoveredNode || focused;
      if (spotlightId === connection.node_a_id) {
        var fanA = spreadAnchor(spotlightId, connection, x1, y1, x2, y2);
        x1 = fanA.x; y1 = fanA.y;
      } else if (spotlightId === connection.node_b_id) {
        var fanB = spreadAnchor(spotlightId, connection, x2, y2, x1, y1);
        x2 = fanB.x; y2 = fanB.y;
      }
      var blockers = visible.filter(function (node) {
        return node.node_type !== "title" && node.id !== connection.node_a_id && node.id !== connection.node_b_id;
      }).map(function (node) {
        var spot = positions[node.id];
        return spot ? {x: spot.x, y: spot.y, w: NODE_W, h: NODE_H, margin: 12} : null;
      }).filter(Boolean);
      // 항목 이름표도 피해야 한다. labelBox가 이미 여유를 두고 재므로 조금만 더 준다.
      state.sections.forEach(function (section, index) {
        var box = labelBox(index);
        blockers.push({x: box.x, y: box.y, w: box.w, h: box.h, margin: 4});
      });
      var bend = routeConnection(x1, y1, x2, y2, blockers);
      // 곡선의 한가운데. 삭제 단추를 여기에 둔다.
      var handleX = (x1 + 3 * bend.ax + 3 * bend.bx + x2) / 8;
      var handleY = (y1 + 3 * bend.ay + 3 * bend.by + y2) / 8;
      var curve = "M " + x1 + " " + y1 + " C " + bend.ax.toFixed(1) + " " + bend.ay.toFixed(1)
        + ", " + bend.bx.toFixed(1) + " " + bend.by.toFixed(1) + ", " + x2 + " " + y2;
      // 가리키거나 고른 메모가 있으면 그 메모로 이어진 선만 살리고 나머지는 죽인다.
      var spotlight = hoveredNode || focused;
      var touches = spotlight && (connection.node_a_id === spotlight || connection.node_b_id === spotlight);
      var emphasis = !spotlight ? "" : touches ? " highlighted" : " dimmed";
      return h("g", {key: connection.id}, h("path", {d: curve, className: "brain-connection" + emphasis + (connection.pending ? " pending" : "")}), canEdit && !connection.pending ? h("circle", {cx: handleX, cy: handleY, r: 9, className: "brain-connection-delete" + emphasis, onClick: function () { deleteConnection(connection); }}) : null);
    }
    function note(node) {
      var p = positions[node.id], selected = focused === node.id, connect = source?.id === node.id;
      var assignee = (state.participants || []).find(function (participant) { return participant.user_id === node.assignee_id; });
      return h("article", {key: node.id, "data-node": "true", "data-color": node.color, className: "brain-note " + (selected ? "selected " : "") + (connect ? "connect-source" : ""), style: {left: p.x, top: p.y}, onMouseDown: function (event) { beginMove(event, node); }, onMouseEnter: function () { setHoveredNode(node.id); }, onMouseLeave: function () { setHoveredNode(function (current) { return current === node.id ? null : current; }); }, onDoubleClick: function (event) { event.stopPropagation(); if (canEdit) editNode(node); }},
        h("div", {className: "brain-note-top"}, h("span", {className: "brain-note-status " + node.status}, node.status === "accepted" ? "채택" : "아이디어"), canEdit ? h("div", {className: "brain-note-controls", onMouseDown: function (event) { event.stopPropagation(); }}, h("button", {type: "button", onClick: function (event) { event.stopPropagation(); editNode(node); }, title: "내용 수정", "aria-label": "내용 수정"}, "✎"), h("button", {type: "button", onClick: function (event) { event.stopPropagation(); deleteNode(node); }, title: "삭제", "aria-label": "삭제"}, "×")) : null),
        h("p", null, node.content),
        h("footer", null, h("span", null, "v" + node.version), h("span", {title: assignee ? "담당자 " + assignee.display_name : "담당자 없음"}, assignee ? "담당 " + assignee.display_name : "담당자 없음")),
        selected && canEdit ? (function () {
          var place = actionsOffset(node, p);
          return h("div", {className: "brain-note-actions", style: {left: place.dx, top: place.dy}, onMouseDown: function (event) { event.stopPropagation(); }},
            h("button", {type: "button", onClick: function () { statusNode(node, "held"); }}, "보류"),
            assigneeButton(node));
        })() : null);
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
        moveNode(node, trayBox().x + 24 + (sectionNodes.length % 2) * 252, trayBox().y + 92 + Math.floor(sectionNodes.length / 2) * 162, null);
        return;
      }
      var slot = slotInRegion(laneIndex(sectionId), sectionNodes.length, takenSpots(sectionId, node.id));
      moveNode(node, slot.x, slot.y, sectionId);
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
      // 그리기 전에 도화지 크기와 영역 배분을 메모 수에 맞춰 다시 계산한다.
      resizeBoard(visible.length);
      setRegionWeights(state.sections.map(function (section) {
        return visible.filter(function (node) { return node.section_id === section.id; }).length;
      }));
      return h("main", {className: "brain-stage", onMouseDown: pan, onWheel: wheelCanvas},
        h("div", {className: "brain-canvas-hint"}, h("i", {className: "bi bi-arrows-move"}), " 빈 공간을 드래그해 이동 · 휠로 패닝 · Ctrl+휠로 확대/축소"),
        h("div", {className: "brain-zoom"}, h("button", {onClick: function () { zoom(.1); }}, "+"), h("span", null, Math.round(view.zoom * 100) + "%"), h("button", {onClick: function () { zoom(-.1); }}, "−"), h("button", {title: "도화지 전체 보기", onClick: function () { var next = fitBoardView(); setView(next); saveView(next); }}, "⌂")),
        h("div", {className: "brain-canvas", style: {width: canvasWidth(), height: CANVAS_H, transform: "translate(" + view.x + "px," + view.y + "px) scale(" + view.zoom + ")"}},
          h("svg", {className: "brain-regions", width: CANVAS_W, height: CANVAS_H},
            h("rect", {className: "brain-board", x: BOARD.x, y: BOARD.y, width: BOARD.w, height: BOARD.h, rx: 26}),
            // 미분류는 칸을 가진 영역이 아니라 그냥 빈 여백이다. 테두리 없이 이름만 위쪽에 둔다.
            h("text", {className: "brain-tray-title", x: trayBox().x + trayBox().w / 2, y: trayBox().y + 42}, "미분류"),
            h("text", {className: "brain-tray-hint", x: trayBox().x + trayBox().w / 2, y: trayBox().y + 68},
              state.counts.unclassified + "개 · 네모 밖에 두면 분류되지 않습니다"),
            state.sections.map(function (section, index) {
              var color = laneColors[index % laneColors.length];
              var box = regionCenter(index);
              var count = visible.filter(function (node) { return node.section_id === section.id; }).length;
              return h("g", {key: section.id, className: "brain-region"},
                h("path", {d: regionPath(index), fill: color[0], stroke: color[1]}),
                h("text", {className: "brain-region-index", x: box.x, y: box.top + 46, fill: color[2]}, String(index + 1).padStart(2, "0")),
                h("text", {className: "brain-region-title", x: box.x, y: box.top + 76, fill: color[2]}, section.title),
                h("text", {className: "brain-region-count", x: box.x, y: box.top + 98, fill: color[2]}, count + "개 아이디어")
              );
            })),
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

    function switchCanvas(canvasId) {
      if (busy || canvasId === state.canvas.id) return;
      setSource(null); setFocused(null); setAssigneeMenu(null); setAiPanel(null);
      cursorRef.current = null;
      fullSync(canvasId);
    }

    function createCanvasVersion() {
      if (busy) return;
      setBusy(true); setNotice(null);
      request(apiBase + "boards/", {
        method: "POST",
        headers: {"Idempotency-Key": key()},
        body: JSON.stringify({source_canvas_id: state.canvas.id})
      }).then(function (created) {
        cursorRef.current = null;
        return fullSync(created.id);
      }).catch(function (error) {
        setNotice({kind: "danger", text: error.message});
      }).finally(function () { setBusy(false); });
    }

    function renderVersionSidebar() {
      var versions = state.versions || [];
      var latestVersionNumber = versions.reduce(function (latest, row) {
        return Math.max(latest, Number(row.version_number) || 0);
      }, 0);
      return h("aside", {className: "brain-version-sidebar" + (versionsOpen ? "" : " collapsed")},
        h("header", null,
          versionsOpen ? h("span", null, "BOARD VERSIONS") : null,
          h("button", {type: "button", onClick: function () { setVersionsOpen(function (value) { return !value; }); }, title: versionsOpen ? "버전 목록 접기" : "버전 목록 펼치기", "aria-label": versionsOpen ? "버전 목록 접기" : "버전 목록 펼치기"}, h("i", {className: "bi " + (versionsOpen ? "bi-chevron-left" : "bi-chevron-right")}))
        ),
        versionsOpen ? h("nav", {"aria-label": "캔버스 버전"}, versions.map(function (row) {
          return h("button", {key: row.id, type: "button", className: row.id === state.canvas.id ? "active" : "", onClick: function () { switchCanvas(row.id); }},
            h("span", null, "ver." + row.version_number),
            row.version_number === latestVersionNumber ? h("small", null, "최신") : null
          );
        })) : null,
        versionsOpen && canEdit ? h("button", {type: "button", className: "brain-version-add", disabled: busy, onClick: createCanvasVersion, title: "현재 보드를 복제해 새 버전 만들기", "aria-label": "새 캔버스 버전 만들기"}, h("i", {className: "bi bi-plus-lg"}), h("span", null, "새 보드")) : null
      );
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
        canCreateNote ? h("button", {type: "button", className: "brain-add", onClick: createNote}, h("i", {className: "bi bi-plus-lg"}), " 메모 추가") : null,
        h("div", {className: "brain-filter"}, ["all", "accepted", "default"].map(function (value) { return h("button", {key: value, type: "button", className: filter === value ? "active" : "", onClick: function () { setFilter(value); }}, {all: "전체", accepted: "채택됨", default: "미분류"}[value]); })),
        boardView === "canvas" && canEdit ? h("button", {type: "button", className: "btn btn-sm brain-auto", disabled: busy, onClick: autoLayout}, h("i", {className: "bi bi-grid-3x3-gap"}), " 자동 정렬") : null,
        h("div", {className: "brain-ai-actions"}, h("button", {type: "button", disabled: busy, onClick: loadClassificationResult}, h("i", {className: "bi bi-diagram-3"}), " 분류 결과"))
      ),
      h("div", {className: "brain-workspace"},
        renderVersionSidebar(),
        h("div", {className: "brain-version-content"},
          boardView === "canvas" && tool === "connect" ? h("div", {className: "brain-connect-banner"}, source ? "두 번째 메모를 선택해 주세요" : "연결할 첫 번째 메모를 선택해 주세요", h("button", {onClick: function () { setTool("select"); setSource(null); }}, "취소")) : null,
          notice ? h("div", {className: "brain-notice alert alert-" + notice.kind}, notice.text, h("button", {type: "button", className: "btn-close", onClick: function () { setNotice(null); }})) : null,
          boardView === "board" ? renderBoard() : boardView === "canvas" ? renderCanvas() : renderList(),
          h("section", {className: "brain-held" + (heldExpanded ? "" : " collapsed"), onDragOver: function (event) { if (canEdit) event.preventDefault(); }, onDrop: dropHeld},
            h("header", null,
              h("strong", null, "⏸ 보류 구역"),
              h("span", null, state.held_nodes.length),
              h("small", null, "메모를 이곳으로 끌어오거나 보류 버튼을 누르면 보류됩니다"),
              h("button", {type: "button", className: "brain-held-toggle", "aria-expanded": heldExpanded, onClick: function () { setHeldExpanded(function (current) { return !current; }); }},
                h("span", null, heldExpanded ? "접기" : "펼치기"),
                h("i", {className: "bi " + (heldExpanded ? "bi-chevron-down" : "bi-chevron-up"), "aria-hidden": "true"})
              )
            ),
            h("div", {className: "brain-held-list"}, state.held_nodes.map(function (node) { return h("article", {key: node.id, "data-color": node.color}, h("p", null, node.content), canEdit ? h("button", {onClick: function () { statusNode(node, "default"); }}, "미분류로 이동 →") : null); }))
          )
        )
      ),
      renderEditor(), renderAssigneeMenu(), renderAiPanel(),
      busy ? h("div", {className: "brain-busy"}, h("span", {className: "spinner-border spinner-border-sm"}), jobId ? " AI 작업 처리 중" : " 저장 중") : null);
  }

  window.ReactDOM.createRoot(root).render(h(BrainstormApp));
}());
