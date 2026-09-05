(function () {
  "use strict";

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
  // 기본 크기의 항목 하나가 이름표를 빼고 무리 없이 담는 메모 수.
  var REGION_FREE_SLOTS = 2;
  var BOARD_MAX = {w: 4600, h: 2900};
  function resizeBoard(total, busiestRegion) {
    // 항목이 7개라 메모가 7개 늘 때마다 각 항목이 한 자리씩 더 필요하다.
    var byTotal = Math.ceil(Math.max(0, Number(total || 0) - BOARD_FREE_SLOTS) / 7);
    // 전체 수가 적어도 한 항목에 몰리면 그 항목부터 자리가 모자란다.
    // 서로 가리기 시작하는 것은 대개 이쪽이 원인이라 더 큰 쪽을 따른다.
    var byRegion = Math.max(0, Number(busiestRegion || 0) - REGION_FREE_SLOTS);
    var steps = Math.max(byTotal, byRegion);
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


  window.BrainstormLayout = {
    NODE_W: NODE_W,
    NODE_H: NODE_H,
    CANVAS_W: CANVAS_W,
    CANVAS_H: CANVAS_H,
    BOARD: BOARD,
    resizeBoard: resizeBoard,
    trayBox: trayBox,
    setRegionWeights: setRegionWeights,
    regionPath: regionPath,
    regionBounds: regionBounds,
    regionCenter: regionCenter,
    fitBoardView: fitBoardView,
    hitContext: hitContext,
    laneColors: laneColors
  };
}());
