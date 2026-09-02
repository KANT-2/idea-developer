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
    return h("div", { className: "brainstorm-app" },
      h("div", { className: "d-flex justify-content-between align-items-center mb-3" },
        h("h1", { className: "h4 mb-0" }, "브레인스토밍"),
        h("span", { className: statusClass, role: "status" },
          syncStatus === "connected" ? "동기화됨" : "재연결 중")
      ),
      h("div", { className: "row g-2 mb-3" }, [
        ["전체", state.counts.total], ["미분류", state.counts.unclassified],
        ["채택", state.counts.accepted], ["보류", state.counts.held],
      ].map(function (entry) {
        return h("div", { className: "col-6 col-md-3", key: entry[0] },
          h("div", { className: "border rounded p-2 bg-white" },
            h("span", { className: "text-muted me-2" }, entry[0]), h("strong", null, String(entry[1]))));
      })),
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
