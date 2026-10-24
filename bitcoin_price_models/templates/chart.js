// Bitcoin price models chart: TradingView Lightweight Charts v5 (standalone build).
// Reads window.CHART_PAYLOAD and builds one chart with two switchable modes.
(function () {
  "use strict";

  const LWC = window.LightweightCharts;
  const PAYLOAD = window.CHART_PAYLOAD;

  // Colours, alphas and widths
  const COLOR_PRICE_DEFAULT = "#2196F3";
  const HEX_COLOR_PATTERN = /^#([0-9a-fA-F]{6})$/;
  const HEX_RADIX = 16;
  const ALPHA_AREA_TOP = 0.35;
  const ALPHA_AREA_BOTTOM = 0.02;
  const COLOR_MARKER = "#E53935";
  const COLOR_BACKGROUND = "#ffffff";
  const COLOR_TEXT = "#1f2933";
  const COLOR_GRID = "#eceff3";
  const COLOR_BORDER = "#d5dbe3";
  const COLOR_HALVING = "#6b7785";
  const COLOR_HALVING_TEXT = "#4a5560";
  const ALPHA_RAINBOW = 0.55;
  const ALPHA_HALVING = 0.6;
  const ANCHOR_VALUE = 1;
  const WIDTH_THIN = 1;
  const WIDTH_NORMAL = 2;
  const WIDTH_GOLDEN = 3;
  const HALVING_FONT_PX = 11;
  const HALVING_LABEL_PAD_PX = 4;
  const HALVING_DASH_PX = 5;
  const RAINBOW_CULL_MARGIN_PX = 50;
  const FONT_STACK = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif";

  const MODE_GOLDEN = "golden";
  const MODE_POWERLAW = "powerlaw";
  const THOUSAND = 1000;
  const MILLION = 1e6;
  const BILLION = 1e9;
  const SMALL_PRICE_PRECISION = 2;
  const TINY_PRICE_LIMIT = 0.1;
  const TINY_PRICE_PRECISION = 3;
  const MIN_MOVE = 0.01;
  // ~7,900 daily bars must fit in ~1,500 px, far below the 0.5 px default
  const MIN_BAR_SPACING_PX = 0.01;
  const GOLDEN_RIGHT_MARGIN_DAYS = 90;
  const MS_PER_DAY = 86400000;
  // The default 0.2 / 0.1 margins are applied in log space and add ~2 decades above the data
  // on a ~8-decade axis, so keep them small.
  const PRICE_SCALE_MARGIN = 0.04;

  // Formatting helpers
  function trimNumber(value, decimals) {
    return String(Number(value.toFixed(decimals)));
  }

  // Compact dollar formatter: $0.10, $1, $100, $1K, $10K, $1M. fixedSmall forces 2 decimals under $1K.
  function formatDollar(value, fixedSmall) {
    if (value === null || value === undefined || !isFinite(value)) {
      return "-";
    }
    const abs = Math.abs(value);
    let text;
    if (abs >= BILLION) {
      text = trimNumber(value / BILLION, 2) + "B";
    } else if (abs >= MILLION) {
      text = trimNumber(value / MILLION, 2) + "M";
    } else if (abs >= THOUSAND) {
      text = trimNumber(value / THOUSAND, 2) + "K";
    } else if (fixedSmall) {
      text = value.toFixed(SMALL_PRICE_PRECISION);
    } else if (abs < 1) {
      text = value.toFixed(abs < TINY_PRICE_LIMIT ? TINY_PRICE_PRECISION : SMALL_PRICE_PRECISION);
    } else {
      text = trimNumber(value, SMALL_PRICE_PRECISION);
    }
    return "$" + text;
  }

  // Full-precision formatter for series value tags, e.g. 122362.40
  function formatFull(value) {
    return value.toFixed(SMALL_PRICE_PRECISION);
  }

  function escapeHtml(text) {
    return String(text).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  // Normalise a chart time (string or business-day object) to "YYYY-MM-DD"
  function timeKey(t) {
    if (typeof t === "string") {
      return t;
    }
    if (t && typeof t === "object" && t.year) {
      const mm = String(t.month).padStart(2, "0");
      const dd = String(t.day).padStart(2, "0");
      return t.year + "-" + mm + "-" + dd;
    }
    return null;
  }

  // "#RRGGBB" to "rgba(r,g,b,a)"
  function hexToRgba(hex, alpha) {
    const m = HEX_COLOR_PATTERN.exec(hex);
    const n = parseInt(m[1], HEX_RADIX);
    return "rgba(" + ((n >> 16) & 255) + "," + ((n >> 8) & 255) + "," + (n & 255) + "," + alpha + ")";
  }

  function arr(value) {
    return Array.isArray(value) ? value : [];
  }

  function toMap(data) {
    const map = new Map();
    data.forEach(function (p) { map.set(p.time, p.value); });
    return map;
  }

  // Chart setup
  const meta = PAYLOAD.meta || {};
  const golden = PAYLOAD.golden || {};
  const powerlaw = PAYLOAD.powerlaw || {};
  const rainbow = powerlaw.rainbow || { bands: [], edges: [] };
  const priceData = arr(PAYLOAD.price);
  const COLOR_PRICE = typeof meta.priceColor === "string" && HEX_COLOR_PATTERN.test(meta.priceColor)
    ? meta.priceColor : COLOR_PRICE_DEFAULT;
  const COLOR_AREA_TOP = hexToRgba(COLOR_PRICE, ALPHA_AREA_TOP);
  const COLOR_AREA_BOTTOM = hexToRgba(COLOR_PRICE, ALPHA_AREA_BOTTOM);
  let mode = meta.initialMode === MODE_POWERLAW ? MODE_POWERLAW : MODE_GOLDEN;

  document.getElementById("chart-title").textContent = document.title;

  const chart = LWC.createChart(document.getElementById("chart"), {
    autoSize: true,
    layout: { attributionLogo: false, background: { type: "solid", color: COLOR_BACKGROUND }, textColor: COLOR_TEXT, fontFamily: FONT_STACK },
    grid: { vertLines: { color: COLOR_GRID }, horzLines: { color: COLOR_GRID } },
    rightPriceScale: {
      mode: LWC.PriceScaleMode.Logarithmic,
      borderColor: COLOR_BORDER,
      scaleMargins: { top: PRICE_SCALE_MARGIN, bottom: PRICE_SCALE_MARGIN },
    },
    timeScale: { borderColor: COLOR_BORDER, rightOffset: 2, minBarSpacing: MIN_BAR_SPACING_PX },
    crosshair: {
      mode: LWC.CrosshairMode.Normal,
      vertLine: { labelVisible: true },
      horzLine: { labelVisible: true },
    },
    localization: { priceFormatter: function (v) { return formatDollar(v, false); } },
  });

  // Series factories: return null for empty data so callers can skip them
  function addLine(data, opts) {
    if (!data || !data.length) {
      return null;
    }
    const series = chart.addSeries(LWC.LineSeries, Object.assign({
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: false,
      priceFormat: { type: "custom", formatter: formatFull, minMove: MIN_MOVE },
    }, opts));
    series.setData(data);
    return series;
  }

  function addArea(data, opts) {
    if (!data || !data.length) {
      return null;
    }
    const series = chart.addSeries(LWC.AreaSeries, Object.assign({
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: false,
      priceFormat: { type: "custom", formatter: formatFull, minMove: MIN_MOVE },
    }, opts));
    series.setData(data);
    return series;
  }

  // Legend entries: one per toggleable row. setVisible applies the effective visibility.
  const entries = [];

  function addEntry(entry) {
    entry.hidden = false;
    entries.push(entry);
    return entry;
  }

  // Golden mode series
  const goldenPrice = addArea(priceData, {
    lineColor: COLOR_PRICE, topColor: COLOR_AREA_TOP, bottomColor: COLOR_AREA_BOTTOM,
    lineWidth: WIDTH_NORMAL, title: "Bitcoin Price",
  });
  addEntry({
    id: "golden-price", isPrice: true, mode: MODE_GOLDEN, label: "Bitcoin Price", color: COLOR_PRICE,
    values: toMap(priceData), setVisible: function (v) { if (goldenPrice) { goldenPrice.applyOptions({ visible: v }); } },
  });

  const ma = golden.ma;
  if (ma) {
    const maSeries = addLine(arr(ma.data), {
      color: ma.color, lineWidth: WIDTH_NORMAL, lineStyle: LWC.LineStyle.Dashed, title: ma.label,
    });
    addEntry({
      id: "golden-ma", mode: MODE_GOLDEN, label: ma.label, color: ma.color, values: toMap(arr(ma.data)),
      setVisible: function (v) { if (maSeries) { maSeries.applyOptions({ visible: v }); } },
    });
  }

  arr(golden.bands).forEach(function (band) {
    const isGolden = !!band.golden;
    const bandSeries = addLine(arr(band.data), {
      color: band.color,
      lineWidth: isGolden ? WIDTH_GOLDEN : WIDTH_THIN,
      lineStyle: isGolden ? LWC.LineStyle.Solid : LWC.LineStyle.Dashed,
      title: band.label,
    });
    addEntry({
      id: "golden-" + band.key, mode: MODE_GOLDEN, label: band.label, color: band.color,
      values: toMap(arr(band.data)),
      setVisible: function (v) { if (bandSeries) { bandSeries.applyOptions({ visible: v }); } },
    });
  });

  // Power law mode series
  const plPrice = addLine(priceData, { color: COLOR_PRICE, lineWidth: WIDTH_NORMAL, title: "Bitcoin Price" });
  addEntry({
    id: "pl-price", isPrice: true, mode: MODE_POWERLAW, label: "Bitcoin Price", color: COLOR_PRICE,
    values: toMap(priceData), setVisible: function (v) { if (plPrice) { plPrice.applyOptions({ visible: v }); } },
  });

  // Fair value is split in two series: the fitted past is dashed, the projection is dotted
  const fair = powerlaw.fairValue;
  const fairData = fair ? arr(fair.data) : [];
  const projectionStart = powerlaw.projectionStart || null;
  const fairPast = projectionStart ? fairData.filter(function (p) { return p.time <= projectionStart; }) : fairData;
  const fairProjected = projectionStart ? fairData.filter(function (p) { return p.time >= projectionStart; }) : [];
  let fairPastSeries = null;
  let fairProjectedSeries = null;
  if (fair) {
    fairPastSeries = addLine(fairPast, {
      color: fair.color, lineWidth: WIDTH_NORMAL, lineStyle: LWC.LineStyle.Dashed, lastValueVisible: false,
    });
    fairProjectedSeries = addLine(fairProjected, {
      color: fair.color, lineWidth: WIDTH_NORMAL, lineStyle: LWC.LineStyle.Dotted, title: fair.label,
    });
    addEntry({
      id: "pl-fair", mode: MODE_POWERLAW, label: fair.label, color: fair.color, values: toMap(fairData),
      setVisible: function (v) {
        if (fairPastSeries) { fairPastSeries.applyOptions({ visible: v }); }
        if (fairProjectedSeries) { fairProjectedSeries.applyOptions({ visible: v }); }
      },
    });
  }

  // Rainbow bands: Option A, a custom series primitive drawing one polygon per band.
  // Chosen over stacked AreaSeries because it fills exactly between two edges with true
  // translucency (no pre-blended colours), stays correct on a log axis, adds no series to
  // the legend or price scale, and one visibility flag toggles every band at once.
  class RainbowPrimitive {
    constructor(bands, edges, dates) {
      this._bands = bands;
      this._edges = edges;
      this._dates = dates;
      this._visible = true;
      const self = this;
      this._view = {
        zOrder: function () { return "bottom"; },
        renderer: function () { return { draw: function (target) { self._draw(target); } }; },
      };
    }

    attached(param) {
      this._chart = param.chart;
      this._series = param.series;
      this._requestUpdate = param.requestUpdate;
    }

    detached() {
      this._chart = null;
      this._series = null;
    }

    paneViews() { return [this._view]; }

    updateAllViews() {}

    // Price range of the bands over the visible time range, or null while they are hidden.
    // Called by the anchor series' autoscaleInfoProvider, not by the library.
    range() {
      if (!this._visible || !this._chart || !this._dates) { return null; }
      const visible = this._chart.timeScale().getVisibleRange();
      const range = visible ? { from: timeKey(visible.from), to: timeKey(visible.to) } : null;
      let min = Infinity;
      let max = -Infinity;
      for (let i = 0; i < this._dates.length; i++) {
        const t = this._dates[i];
        if (range && (t < range.from || t > range.to)) { continue; }
        for (let k = 0; k < this._edges.length; k++) {
          const p = arr(this._edges[k])[i];
          if (p && p.value > 0) {
            min = Math.min(min, p.value);
            max = Math.max(max, p.value);
          }
        }
      }
      return max >= min ? { priceRange: { minValue: min, maxValue: max } } : null;
    }

    setVisible(visible) {
      this._visible = visible;
      if (this._requestUpdate) { this._requestUpdate(); }
    }

    _draw(target) {
      if (!this._visible || !this._chart || !this._series) { return; }
      const dates = this._dates;
      if (!dates || !dates.length) { return; }
      const timeScale = this._chart.timeScale();
      const series = this._series;
      const self = this;
      target.useBitmapCoordinateSpace(function (scope) {
        const ctx = scope.context;
        const hpr = scope.horizontalPixelRatio;
        const vpr = scope.verticalPixelRatio;
        const width = scope.mediaSize.width;

        // Only points near the visible area are projected, to keep each frame cheap
        const idx = [];
        const xs = [];
        for (let i = 0; i < dates.length; i++) {
          const x = timeScale.timeToCoordinate(dates[i]);
          if (x === null) { continue; }
          if (x < -RAINBOW_CULL_MARGIN_PX || x > width + RAINBOW_CULL_MARGIN_PX) { continue; }
          idx.push(i);
          xs.push(x);
        }
        if (!idx.length) { return; }

        const ys = self._edges.map(function (edge) {
          return idx.map(function (i) { return arr(edge)[i] ? series.priceToCoordinate(arr(edge)[i].value) : null; });
        });

        ctx.save();
        ctx.globalAlpha = ALPHA_RAINBOW;
        for (let k = 0; k < self._bands.length; k++) {
          const lo = ys[k];
          const hi = ys[k + 1];
          if (!lo || !hi) { continue; }
          const px = [];
          const pLo = [];
          const pHi = [];
          for (let j = 0; j < xs.length; j++) {
            if (lo[j] === null || hi[j] === null) { continue; }
            px.push(xs[j] * hpr);
            pLo.push(lo[j] * vpr);
            pHi.push(hi[j] * vpr);
          }
          if (px.length < 2) { continue; }
          ctx.beginPath();
          ctx.moveTo(px[0], pHi[0]);
          for (let j = 1; j < px.length; j++) { ctx.lineTo(px[j], pHi[j]); }
          for (let j = px.length - 1; j >= 0; j--) { ctx.lineTo(px[j], pLo[j]); }
          ctx.closePath();
          ctx.fillStyle = self._bands[k].color;
          ctx.fill();
        }
        ctx.restore();
      });
    }
  }

  // Rainbow edge helpers: edges share the fair value dates
  const rainbowBands = arr(rainbow.bands);
  const rainbowEdges = arr(rainbow.edges);
  const rainbowReady = rainbowBands.length > 0 && rainbowEdges.length === rainbowBands.length + 1
    && rainbowEdges.every(function (e) { return arr(e).length > 0; });
  const rainbowDates = rainbowReady ? arr(rainbowEdges[0]).map(function (p) { return p.time; }) : [];
  const rainbowIndex = new Map();
  rainbowDates.forEach(function (t, i) { rainbowIndex.set(t, i); });

  // Primitives are only drawn while their host series is visible, so both the rainbow and the
  // halving lines live on a dedicated anchor series that is always visible, draws nothing and
  // never affects the price scale on its own.
  let rainbowPrimitive = null;
  const anchorDates = rainbowReady ? rainbowDates
    : (fairData.length ? fairData : priceData).map(function (p) { return p.time; });
  const anchorSeries = anchorDates.length ? chart.addSeries(LWC.LineSeries, {
    lineVisible: false, lastValueVisible: false, priceLineVisible: false, crosshairMarkerVisible: false,
    autoscaleInfoProvider: function () {
      return rainbowPrimitive && mode === MODE_POWERLAW ? rainbowPrimitive.range() : null;
    },
  }) : null;
  if (anchorSeries) {
    anchorSeries.setData(anchorDates.map(function (t) { return { time: t, value: ANCHOR_VALUE }; }));
  }

  if (rainbowReady && anchorSeries) {
    rainbowPrimitive = new RainbowPrimitive(rainbowBands, rainbowEdges, rainbowDates);
    anchorSeries.attachPrimitive(rainbowPrimitive);
    const gradient = "linear-gradient(to right, " + rainbowBands.map(function (b) { return b.color; }).join(", ") + ")";
    addEntry({
      id: "pl-rainbow", mode: MODE_POWERLAW, label: "Rainbow", color: gradient, values: null,
      setVisible: function (v) { rainbowPrimitive.setVisible(v); },
    });
  }

  // Name of the rainbow band that contains the price at a date, or null if unknown
  function rainbowBandAt(time, price) {
    if (!rainbowReady || price === null || price === undefined) { return null; }
    const i = rainbowIndex.get(time);
    if (i === undefined) { return null; }
    const last = rainbowBands.length - 1;
    // Outer edges are clamped: the payload is rounded, so extremes can sit just outside them
    for (let k = 0; k <= last; k++) {
      const lo = arr(rainbowEdges[k])[i];
      const hi = arr(rainbowEdges[k + 1])[i];
      if (!lo || !hi) { return null; }
      if (k === 0 && price < lo.value) { return rainbowBands[0]; }
      if (k === last && price >= hi.value) { return rainbowBands[last]; }
      if (price >= lo.value && price < hi.value) { return rainbowBands[k]; }
    }
    return null;
  }

  // Era high markers on both price series
  const eraMarkers = arr(PAYLOAD.eraHighs).map(function (h) {
    return {
      time: h.time, position: "atPriceTop", price: h.price, shape: "circle",
      color: COLOR_MARKER, size: 1, text: h.label,
    };
  }).sort(function (a, b) { return a.time < b.time ? -1 : a.time > b.time ? 1 : 0; });
  [goldenPrice, plPrice].forEach(function (s) {
    if (s && eraMarkers.length) { LWC.createSeriesMarkers(s, eraMarkers); }
  });

  // Halving lines: one primitive on the anchor series, shown in both modes
  class HalvingPrimitive {
    constructor(items) {
      this._items = items;
      const self = this;
      this._view = {
        zOrder: function () { return "normal"; },
        renderer: function () { return { draw: function (target) { self._draw(target); } }; },
      };
    }

    attached(param) { this._chart = param.chart; }

    detached() { this._chart = null; }

    paneViews() { return [this._view]; }

    updateAllViews() {}

    _draw(target) {
      const chartRef = this._chart;
      const items = this._items;
      if (!chartRef) { return; }
      target.useBitmapCoordinateSpace(function (scope) {
        const ctx = scope.context;
        const hpr = scope.horizontalPixelRatio;
        const vpr = scope.verticalPixelRatio;
        const height = scope.bitmapSize.height;
        const width = scope.bitmapSize.width;
        ctx.save();
        ctx.font = Math.round(HALVING_FONT_PX * vpr) + "px " + FONT_STACK;
        ctx.textBaseline = "bottom";
        items.forEach(function (item) {
          const xCss = chartRef.timeScale().timeToCoordinate(item.time);
          if (xCss === null) { return; }
          const x = Math.round(xCss * hpr);
          if (x < 0 || x > width) { return; }
          ctx.globalAlpha = ALPHA_HALVING;
          ctx.strokeStyle = COLOR_HALVING;
          ctx.lineWidth = Math.max(1, Math.round(hpr));
          ctx.setLineDash(item.dashed ? [HALVING_DASH_PX * hpr, HALVING_DASH_PX * hpr] : []);
          ctx.beginPath();
          ctx.moveTo(x + 0.5, 0);
          ctx.lineTo(x + 0.5, height);
          ctx.stroke();

          ctx.setLineDash([]);
          ctx.globalAlpha = 1;
          ctx.fillStyle = COLOR_HALVING_TEXT;
          const pad = HALVING_LABEL_PAD_PX * hpr;
          const textWidth = ctx.measureText(item.label).width;
          const fitsRight = x + pad + textWidth <= width;
          // Flip to the left of the line near the right edge, then clamp inside the pane
          const textX = Math.max(0, Math.min(fitsRight ? x + pad : x - pad - textWidth, width - textWidth));
          ctx.textAlign = "left";
          ctx.fillText(item.label, textX, height - pad);
        });
        ctx.restore();
      });
    }
  }

  const halvings = PAYLOAD.halvings || {};
  const halvingItems = arr(halvings.past).map(function (h) {
    return { time: h.time, label: h.label || ("Halving " + h.time), dashed: false };
  });
  if (halvings.next) {
    halvingItems.push({
      time: halvings.next.time, label: halvings.next.label || ("Next halving " + halvings.next.time), dashed: true,
    });
  }
  if (halvingItems.length && anchorSeries) {
    anchorSeries.attachPrimitive(new HalvingPrimitive(halvingItems));
  }

  // Legend
  const legendEl = document.getElementById("legend");
  const lastPriceTime = priceData.length ? priceData[priceData.length - 1].time : (meta.lastDate || null);
  let hoverTime = null;

  function entryVisible(entry) {
    return entry.mode === mode && !entry.hidden;
  }

  function renderLegend() {
    const time = hoverTime || lastPriceTime;
    if (!time) {
      legendEl.innerHTML = "";
      return;
    }
    const priceEntry = entries.find(function (e) { return e.mode === mode && e.isPrice; });
    const price = priceEntry ? priceEntry.values.get(time) : undefined;
    let html = '<div class="date">' + escapeHtml(time) + "</div>";
    entries.forEach(function (e) {
      if (e.mode !== mode) { return; }
      const value = e.values ? e.values.get(time) : undefined;
      const text = e.values ? formatDollar(value === undefined ? null : value, true) : "";
      html += '<div class="row' + (e.hidden ? " off" : "") + '" data-id="' + escapeHtml(e.id) + '">'
        + '<span class="swatch" style="background:' + escapeHtml(e.color) + '"></span>'
        + "<span>" + escapeHtml(e.label) + '</span><span class="val">' + escapeHtml(text) + "</span></div>";
    });
    if (mode === MODE_POWERLAW) {
      const band = rainbowBandAt(time, price);
      if (band) {
        html += '<div class="row static"><span class="swatch" style="background:' + escapeHtml(band.color)
          + '"></span><span>Band</span><span class="val">' + escapeHtml(band.name) + "</span></div>";
      }
    }
    legendEl.innerHTML = html;
  }

  legendEl.addEventListener("click", function (event) {
    const row = event.target.closest(".row[data-id]");
    if (!row) { return; }
    const entry = entries.find(function (e) { return e.id === row.getAttribute("data-id"); });
    if (!entry) { return; }
    entry.hidden = !entry.hidden;
    entry.setVisible(entryVisible(entry));
    renderLegend();
  });

  chart.subscribeCrosshairMove(function (param) {
    hoverTime = param && param.time ? timeKey(param.time) : null;
    renderLegend();
  });

  // Mode switching: only toggles visibility and refits the time scale
  const buttons = Array.prototype.slice.call(document.querySelectorAll("#toolbar button[data-mode]"));

  // "YYYY-MM-DD" plus a number of days, in UTC
  function addDays(dateText, days) {
    const ms = Date.parse(dateText + "T00:00:00Z") + days * MS_PER_DAY;
    return new Date(ms).toISOString().slice(0, 10);
  }

  // Golden mode shows only the price history (hidden series keep future dates on the shared
  // time scale); power law mode shows everything up to the end of the projection.
  function fitMode() {
    const timeScale = chart.timeScale();
    const lastDate = meta.lastDate || lastPriceTime;
    if (mode === MODE_GOLDEN && priceData.length && lastDate) {
      timeScale.setVisibleRange({
        from: priceData[0].time,
        to: addDays(lastDate, GOLDEN_RIGHT_MARGIN_DAYS),
      });
    } else {
      timeScale.fitContent();
    }
  }

  function applyMode() {
    entries.forEach(function (e) { e.setVisible(entryVisible(e)); });
    buttons.forEach(function (b) { b.classList.toggle("active", b.getAttribute("data-mode") === mode); });
    fitMode();
    renderLegend();
  }

  buttons.forEach(function (b) {
    b.addEventListener("click", function () {
      mode = b.getAttribute("data-mode") === MODE_POWERLAW ? MODE_POWERLAW : MODE_GOLDEN;
      applyMode();
    });
  });

  // Footer
  const fit = powerlaw.fit;
  let footer = "Generated " + (meta.generatedAt || "n/a");
  if (fit && isFinite(fit.slope) && isFinite(fit.intercept)) {
    footer += " | Power law fit: y = 10^" + fit.intercept.toFixed(3) + " * days^" + fit.slope.toFixed(3)
      + ", R^2 = " + (isFinite(fit.rSquared) ? fit.rSquared.toFixed(4) : "n/a");
  }
  document.getElementById("footer").textContent = footer;

  applyMode();
})();
