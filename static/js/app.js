// App shell behaviour and Overview dashboard charts.
(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";

  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (e) { /* storage unavailable: preferences just aren't remembered */ }
    return null;
  }

  var app = document.querySelector("[data-app]");

  // Mobile navigation drawer
  var toggle = document.querySelector("[data-sidebar-toggle]");
  var scrim = document.querySelector("[data-sidebar-close]");
  if (app && toggle && scrim) {
    var setNav = function (open) {
      app.classList.toggle("is-nav-open", open);
      scrim.hidden = !open;
      toggle.setAttribute("aria-expanded", String(open));
      toggle.setAttribute("aria-label", open ? "Close navigation" : "Open navigation");
    };
    toggle.addEventListener("click", function () {
      setNav(!app.classList.contains("is-nav-open"));
    });
    scrim.addEventListener("click", function () { setNav(false); });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape" && app.classList.contains("is-nav-open")) {
        setNav(false);
        toggle.focus();
      }
    });
  }

  // Collapsible sidebar (desktop), remembered per browser
  var collapse = document.querySelector("[data-sidebar-collapse]");
  if (app && collapse) {
    var setCollapsed = function (collapsed) {
      app.classList.toggle("is-collapsed", collapsed);
      collapse.setAttribute("aria-pressed", String(collapsed));
      collapse.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
      collapse.title = collapse.getAttribute("aria-label");
    };
    setCollapsed(store("phogbs.sidebarCollapsed") === "1");
    collapse.addEventListener("click", function () {
      var collapsed = !app.classList.contains("is-collapsed");
      setCollapsed(collapsed);
      store("phogbs.sidebarCollapsed", collapsed ? "1" : "0");
    });
  }

  // Welcome card
  var welcome = document.querySelector("[data-welcome-card]");
  if (welcome) {
    if (store("phogbs.welcomeDismissed") === "1") welcome.hidden = true;
    welcome.querySelector("[data-welcome-close]").addEventListener("click", function () {
      welcome.hidden = true;
      store("phogbs.welcomeDismissed", "1");
    });
  }

  // Sidebar "Search" focuses the top-bar search (or opens search on small screens)
  var searchButton = document.querySelector("[data-focus-search]");
  var searchInput = document.getElementById("global-search");
  if (searchButton && searchInput) {
    searchButton.addEventListener("click", function () {
      if (searchInput.offsetParent !== null) {
        if (app) app.classList.remove("is-nav-open");
        if (scrim) scrim.hidden = true;
        searchInput.focus();
      } else {
        window.location.href = searchInput.form.action;
      }
    });
  }

  // Dropdown menus
  var openMenu = null;
  function closeMenu(restoreFocus) {
    if (!openMenu) return;
    openMenu.panel.hidden = true;
    openMenu.button.setAttribute("aria-expanded", "false");
    if (restoreFocus) openMenu.button.focus();
    openMenu = null;
  }
  document.querySelectorAll("[data-menu]").forEach(function (menu) {
    var button = menu.querySelector("[data-menu-button]");
    var panel = menu.querySelector("[data-menu-panel]");
    if (!button || !panel) return;
    button.addEventListener("click", function (event) {
      event.stopPropagation();
      var wasOpen = openMenu && openMenu.panel === panel;
      closeMenu(false);
      if (!wasOpen) {
        panel.hidden = false;
        button.setAttribute("aria-expanded", "true");
        openMenu = { button: button, panel: panel };
        var first = panel.querySelector("a, button, input");
        if (first) first.focus();
      }
    });
    panel.addEventListener("click", function (event) { event.stopPropagation(); });
  });
  document.addEventListener("click", function () { closeMenu(false); });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeMenu(true);
  });

  // Programme table: search and status filter
  document.querySelectorAll("[data-programme-table]").forEach(function (section) {
    var search = section.querySelector("[data-table-search]");
    var filters = section.querySelectorAll("[data-table-filter]");
    var rows = section.querySelectorAll("[data-row]");
    var noMatch = section.querySelector("[data-no-match]");
    var count = section.querySelector("[data-filter-count]");
    if (!rows.length) return;

    function apply() {
      var term = (search.value || "").trim().toLowerCase();
      var checked = section.querySelector("[data-table-filter]:checked");
      var status = checked ? checked.value : "";
      var visible = 0;
      rows.forEach(function (row) {
        var show = (!term || row.dataset.name.indexOf(term) !== -1) &&
          (!status || row.dataset.status === status);
        row.hidden = !show;
        if (show) visible++;
      });
      if (noMatch) noMatch.hidden = visible > 0;
      if (count) {
        count.hidden = !status;
        count.textContent = status ? "1" : "";
      }
    }
    search.addEventListener("input", apply);
    filters.forEach(function (input) { input.addEventListener("change", apply); });
  });

  // Charts

  function formatValue(value, unit) {
    if (unit === "naira_m") return "₦" + value.toFixed(2).replace(/\.?0+$/, "") + "M";
    return Math.round(value).toLocaleString("en-GB");
  }

  function formatTick(value, unit) {
    if (unit === "naira_m") return value === 0 ? "0" : (Math.round(value * 10) / 10) + "M";
    return String(Math.round(value));
  }

  // Round tick step (1, 2, 2.5 or 5 × 10^n) giving about six gridlines.
  function niceScale(maxValue) {
    var rough = maxValue / 6;
    var power = Math.pow(10, Math.floor(Math.log10(rough)));
    var options = [1, 2, 2.5, 5, 10];
    var step = power * 10;
    for (var i = 0; i < options.length; i++) {
      if (options[i] * power >= rough) { step = options[i] * power; break; }
    }
    var count = Math.ceil(maxValue / step - 1e-9);
    var ticks = [];
    for (var t = 0; t <= count; t++) ticks.push(Math.round(step * t * 1000) / 1000);
    return { max: step * count, ticks: ticks };
  }

  function el(name, attrs, parent) {
    var node = document.createElementNS(SVG_NS, name);
    Object.keys(attrs || {}).forEach(function (key) { node.setAttribute(key, attrs[key]); });
    if (parent) parent.appendChild(node);
    return node;
  }

  function columnPath(x, y, w, h, radius) {
    var r = Math.min(radius, w / 2, h);
    return "M" + x + "," + (y + h) +
      "V" + (y + r) + "Q" + x + "," + y + " " + (x + r) + "," + y +
      "H" + (x + w - r) + "Q" + (x + w) + "," + y + " " + (x + w) + "," + (y + r) +
      "V" + (y + h) + "Z";
  }

  // Smooth path through points without overshooting (monotone cubic).
  function monotonePath(points) {
    var n = points.length;
    if (n < 2) return "";
    var dx = [], slope = [], tangent = [];
    for (var i = 0; i < n - 1; i++) {
      dx[i] = points[i + 1][0] - points[i][0];
      slope[i] = (points[i + 1][1] - points[i][1]) / dx[i];
    }
    tangent[0] = slope[0];
    tangent[n - 1] = slope[n - 2];
    for (i = 1; i < n - 1; i++) {
      tangent[i] = slope[i - 1] * slope[i] <= 0 ? 0 : (slope[i - 1] + slope[i]) / 2;
    }
    for (i = 0; i < n - 1; i++) {
      if (slope[i] === 0) { tangent[i] = tangent[i + 1] = 0; continue; }
      var a = tangent[i] / slope[i], b = tangent[i + 1] / slope[i], h = a * a + b * b;
      if (h > 9) {
        var s = 3 / Math.sqrt(h);
        tangent[i] = s * a * slope[i];
        tangent[i + 1] = s * b * slope[i];
      }
    }
    var d = "M" + points[0][0] + "," + points[0][1];
    for (i = 0; i < n - 1; i++) {
      var step = dx[i] / 3;
      d += "C" + (points[i][0] + step) + "," + (points[i][1] + tangent[i] * step) + " " +
        (points[i + 1][0] - step) + "," + (points[i + 1][1] - tangent[i + 1] * step) + " " +
        points[i + 1][0] + "," + points[i + 1][1];
    }
    return d;
  }

  function makeTooltip(container) {
    var tip = document.createElement("div");
    tip.className = "tooltip";
    tip.hidden = true;
    tip.setAttribute("aria-hidden", "true");
    container.appendChild(tip);
    return tip;
  }

  function showTooltip(tip, container, x, y, title, value) {
    tip.innerHTML = '<p class="tooltip-title"></p><div class="tooltip-row"><span></span><strong></strong></div>';
    tip.querySelector(".tooltip-title").textContent = title;
    tip.querySelector("span").textContent = value.name;
    tip.querySelector("strong").textContent = value.text;
    tip.hidden = false;
    var left = x + 12;
    if (left + tip.offsetWidth > container.clientWidth) left = x - tip.offsetWidth - 12;
    var top = Math.max(0, Math.min(y - tip.offsetHeight - 8, container.clientHeight - tip.offsetHeight));
    tip.style.left = Math.max(0, left) + "px";
    tip.style.top = top + "px";
  }

  function frame(container, data) {
    var values = data.values || [];
    var max = values.length ? Math.max.apply(null, values) : data.emptyMax;
    var scale = niceScale(max || data.emptyMax);
    var width = container.clientWidth;
    var height = container.clientHeight;
    var m = { left: 44, right: 12, top: 12, bottom: 28 };
    var plotH = height - m.top - m.bottom;
    var band = (width - m.left - m.right) / data.labels.length;
    var f = {
      width: width, height: height, m: m, band: band, scale: scale,
      cx: function (i) { return m.left + band * i + band / 2; },
      y: function (v) { return m.top + plotH - (v / scale.max) * plotH; },
    };
    var svg = el("svg", { width: width, height: height, "aria-hidden": "true" });
    scale.ticks.forEach(function (tick) {
      var y = f.y(tick);
      el("line", { x1: m.left, x2: width - m.right, y1: y, y2: y, class: "grid-line" }, svg);
      el("text", { x: m.left - 10, y: y + 4, "text-anchor": "end", class: "tick" }, svg)
        .textContent = formatTick(tick, data.unit);
    });
    var every = band < 30 ? 2 : 1;
    data.labels.forEach(function (label, i) {
      if (i % every) return;
      el("text", { x: f.cx(i), y: height - 6, "text-anchor": "middle", class: "tick" }, svg)
        .textContent = label;
    });
    f.svg = svg;
    return f;
  }

  function renderBars(container, data) {
    var f = frame(container, data);
    var values = data.values || [];
    var barW = Math.min(24, f.band * 0.55);
    if (!values.length) {
      data.labels.forEach(function (_, i) {
        el("rect", { x: f.cx(i) - barW / 2, y: f.y(0) - 4, width: barW, height: 4, rx: 2, class: "bar bar--placeholder" }, f.svg);
      });
      return f.svg;
    }
    var bars = values.map(function (v, i) {
      var y = f.y(v);
      return el("path", { d: columnPath(f.cx(i) - barW / 2, y, barW, Math.max(0, f.y(0) - y), 4), class: "bar" }, f.svg);
    });
    var tip = makeTooltip(container);
    values.forEach(function (v, i) {
      var hit = el("rect", { x: f.cx(i) - f.band / 2, y: f.m.top, width: f.band, height: f.y(0) - f.m.top, class: "hit" }, f.svg);
      hit.addEventListener("mouseenter", function () {
        bars.forEach(function (b, j) { b.classList.toggle("is-dim", j !== i); });
        showTooltip(tip, container, f.cx(i), f.y(v), data.fullLabels[i],
          { name: data.name, text: formatValue(v, data.unit) });
      });
    });
    f.svg.addEventListener("mouseleave", function () {
      tip.hidden = true;
      bars.forEach(function (b) { b.classList.remove("is-dim"); });
    });
    return f.svg;
  }

  function renderLine(container, data) {
    var f = frame(container, data);
    var values = data.values || [];
    if (!values.length) return f.svg;
    var points = values.map(function (v, i) { return [f.cx(i), f.y(v)]; });
    el("path", { d: monotonePath(points), class: "line" }, f.svg);

    var crosshair = el("line", { y1: f.m.top, y2: f.y(0), class: "crosshair", visibility: "hidden" }, f.svg);
    var marker = el("circle", { r: 5, class: "dot", visibility: "hidden" }, f.svg);
    var tip = makeTooltip(container);
    var hit = el("rect", { x: f.m.left, y: f.m.top, width: f.width - f.m.left - f.m.right, height: f.y(0) - f.m.top, class: "hit" }, f.svg);
    hit.addEventListener("mousemove", function (event) {
      var x = event.clientX - container.getBoundingClientRect().left;
      var i = Math.max(0, Math.min(values.length - 1, Math.floor((x - f.m.left) / f.band)));
      var p = points[i];
      crosshair.setAttribute("x1", p[0]);
      crosshair.setAttribute("x2", p[0]);
      crosshair.setAttribute("visibility", "visible");
      marker.setAttribute("cx", p[0]);
      marker.setAttribute("cy", p[1]);
      marker.setAttribute("visibility", "visible");
      showTooltip(tip, container, p[0], p[1], data.fullLabels[i],
        { name: data.name, text: formatValue(values[i], data.unit) });
    });
    hit.addEventListener("mouseleave", function () {
      tip.hidden = true;
      crosshair.setAttribute("visibility", "hidden");
      marker.setAttribute("visibility", "hidden");
    });
    return f.svg;
  }

  var RENDERERS = { bars: renderBars, line: renderLine };

  document.querySelectorAll("[data-chart]").forEach(function (container) {
    var source = document.getElementById(container.dataset.source);
    var render = RENDERERS[container.dataset.chart];
    if (!source || !render) return;
    var data = JSON.parse(source.textContent);
    var draw = function () {
      container.textContent = "";
      if (container.clientWidth > 0) container.appendChild(render(container, data));
    };
    draw();
    if ("ResizeObserver" in window) {
      var lastWidth = container.clientWidth;
      new ResizeObserver(function () {
        if (container.clientWidth !== lastWidth) {
          lastWidth = container.clientWidth;
          draw();
        }
      }).observe(container);
    }
  });
})();
