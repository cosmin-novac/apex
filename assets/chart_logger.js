(function () {
  'use strict';

  var TARGET_ID = 'main-portfolio-chart-v2';
  var DONUT_ID = 'holdings-donut-chart';
  var POLL_MS = 500;
  var lastSignature = null;

  function isChartDebugEnabled() {
    try {
      if (typeof window === 'undefined') return false;
      if (window.location && window.location.search && window.location.search.indexOf('debugCharts=1') !== -1) return true;
      var v = window.localStorage ? window.localStorage.getItem('debugCharts') : null;
      return v === '1' || v === 'true';
    } catch (e) {
      return false;
    }
  }

  function isFiniteNumber(v) {
    return typeof v === 'number' && isFinite(v);
  }

  function isArrayLike(v) {
    return v != null && typeof v !== 'string' && typeof v.length === 'number';
  }

  function isBinaryArrayObject(v) {
    return v && typeof v === 'object' && typeof v.bdata === 'string' && typeof v.dtype === 'string';
  }

  function base64ToArrayBuffer(b64) {
    var binary = atob(b64);
    var len = binary.length;
    var bytes = new Uint8Array(len);
    for (var i = 0; i < len; i++) bytes[i] = binary.charCodeAt(i);
    return bytes.buffer;
  }

  function decodeBinaryArrayObject(v) {
    // Dash/Plotly sometimes serializes numpy arrays as {dtype, bdata, shape}
    // dtype examples: 'f8' (float64), 'f4' (float32), 'i4' (int32), 'i2' (int16)
    try {
      if (!isBinaryArrayObject(v)) return null;
      var buf = base64ToArrayBuffer(v.bdata);
      switch (v.dtype) {
        case 'f8': return new Float64Array(buf);
        case 'f4': return new Float32Array(buf);
        case 'i4': return new Int32Array(buf);
        case 'i2': return new Int16Array(buf);
        case 'u4': return new Uint32Array(buf);
        case 'u2': return new Uint16Array(buf);
        case 'u1': return new Uint8Array(buf);
        default:
          // Unknown dtype; return bytes so we still get a length.
          return new Uint8Array(buf);
      }
    } catch (e) {
      return null;
    }
  }

  function getSeries(t) {
    if (!t) return [];
    var y = t.y;
    // Plotly may store typed arrays (Float64Array, etc). They are not Array.isArray.
    if (isArrayLike(y)) return y;
    // Or it may store binary-encoded arrays as objects.
    if (isBinaryArrayObject(y)) {
      var decoded = decodeBinaryArrayObject(y);
      if (decoded && isArrayLike(decoded)) return decoded;
    }
    return [];
  }

  function summarizeTrace(t) {
    t = t || {};
    var y = getSeries(t);
    var yLen = y && typeof y.length === 'number' ? y.length : 0;
    var firstY = yLen ? y[0] : null;
    var lastY = yLen ? y[yLen - 1] : null;

    var minY = null;
    var maxY = null;
    for (var i = 0; i < yLen; i++) {
      var v = y[i];
      if (!isFiniteNumber(v)) {
        if (v == null) continue;
        v = Number(v);
      }
      if (!isFiniteNumber(v)) continue;
      if (minY === null || v < minY) minY = v;
      if (maxY === null || v > maxY) maxY = v;
    }

    return {
      name: t.name,
      n: yLen,
      first_y: firstY,
      last_y: lastY,
      min_y: minY,
      max_y: maxY,
      y_type: yLen ? typeof y[yLen - 1] : null,
      y_container_type: (t.y == null) ? null : (Object.prototype.toString.call(t.y)),
      y_object_keys: (t.y && typeof t.y === 'object' && !isArrayLike(t.y)) ? Object.keys(t.y).slice(0, 10) : null
    };
  }

  function signatureFromTraces(traces) {
    try {
      if (!traces || !traces.length) return 'empty';
      // Keep signature cheap: names + last_y (stringified) + lengths.
      var parts = [];
      for (var i = 0; i < traces.length; i++) {
        var t = traces[i] || {};
        var y = getSeries(t);
        var yLen = y && typeof y.length === 'number' ? y.length : 0;
        var lastY = yLen ? y[yLen - 1] : null;
        parts.push(String(t.name || ''));
        parts.push(String(yLen));
        parts.push(String(lastY));
      }
      return parts.join('|');
    } catch (e) {
      return 'sig_error';
    }
  }

  function logFromGraphDiv(gd) {
    try {
      var figData = (gd && gd.data) ? gd.data : [];
      var sig = signatureFromTraces(figData);
      if (sig === lastSignature) return;
      lastSignature = sig;

      var summaries = [];
      for (var i = 0; i < figData.length; i++) summaries.push(summarizeTrace(figData[i]));

      console.groupCollapsed('[ChartAsset] main-portfolio-chart updated');
      console.log('[ChartAsset] fired @', new Date().toISOString());
      if (gd && gd.layout) {
        console.log('[ChartAsset] layout:', {
          title: gd.layout.title,
          yaxis: gd.layout.yaxis,
          xaxis: gd.layout.xaxis
        });
      }
      if (console.table) console.table(summaries);
      else console.log('[ChartAsset] traces:', summaries);

      // If Plotly has richer data elsewhere, surface it too.
      try {
        if (gd && gd._fullData && gd._fullData.length) {
          var fullSummaries = [];
          for (var k = 0; k < gd._fullData.length; k++) fullSummaries.push(summarizeTrace(gd._fullData[k]));
          if (console.table) {
            console.log('[ChartAsset] _fullData:');
            console.table(fullSummaries);
          } else {
            console.log('[ChartAsset] _fullData:', fullSummaries);
          }
        }
      } catch (e2) {
        console.log('[ChartAsset] _fullData log failed:', e2);
      }
      console.groupEnd();
    } catch (e) {
      console.error('[ChartAsset] Failed to log figure:', e);
    }
  }

  function getGraphDivById(elementId) {
    var container = document.getElementById(elementId);
    if (!container) return null;
    var plots = container.getElementsByClassName('js-plotly-plot');
    return plots && plots.length ? plots[0] : null;
  }

  function formatCurrency(value) {
    var n = Number(value);
    if (!isFiniteNumber(n)) return '€0.00';
    try {
      return '€' + n.toLocaleString('de-DE', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    } catch (e) {
      return '€' + n.toFixed(2);
    }
  }

  function attachMainLogger() {
    if (!isChartDebugEnabled()) return false;
    var gd = getGraphDivById(TARGET_ID);
    if (!gd) return false;

    if (gd.__chartLoggerAttached) return true;
    gd.__chartLoggerAttached = true;

    // Log immediately if data exists
    logFromGraphDiv(gd);

    // Attach Plotly events
    if (typeof gd.on === 'function') {
      gd.on('plotly_afterplot', function () { logFromGraphDiv(gd); });
      gd.on('plotly_relayout', function () { logFromGraphDiv(gd); });
      gd.on('plotly_redraw', function () { logFromGraphDiv(gd); });
    }

    console.log('[ChartAsset] Attached logger to', TARGET_ID);
    return true;
  }

  function attachDonutHover() {
    var gd = getGraphDivById(DONUT_ID);
    if (!gd) return false;

    if (gd.__donutHoverAttached) return true;
    gd.__donutHoverAttached = true;

    function getThemeColors() {
      var container = document.getElementById(DONUT_ID);
      var scope = (container && container.closest && container.closest('.portfolio-top-summary')) || document.documentElement;
      var styles = scope ? window.getComputedStyle(scope) : null;
      var textPrimary = styles ? styles.getPropertyValue('--text-primary').trim() : '';
      var textSecondary = styles ? styles.getPropertyValue('--text-secondary').trim() : '';
      var cardBg = styles ? styles.getPropertyValue('--card-bg').trim() : '';
      return {
        textPrimary: textPrimary || '#111827',
        textSecondary: textSecondary || '#6b7280',
        cardBg: cardBg || '#ffffff'
      };
    }

    function applyTheme() {
      if (typeof Plotly === 'undefined' || !Plotly.relayout) return;

      // Avoid event recursion: Plotly.relayout can trigger plotly_afterplot.
      if (gd.__donutThemeApplying) return;

      var theme = getThemeColors();
      var sig = theme.cardBg + '|' + theme.textPrimary + '|' + theme.textSecondary;

      // Skip if already applied.
      if (gd.__donutThemeSig === sig) return;
      gd.__donutThemeSig = sig;

      gd.__donutThemeApplying = true;
      try {
        var p = Plotly.relayout(gd, {
          paper_bgcolor: theme.cardBg,
          plot_bgcolor: theme.cardBg,
          'annotations[0].font.color': theme.textSecondary,
          'annotations[1].font.color': theme.textPrimary
        });
        // Clear flag after plot settles (promise if available; fallback timeout).
        if (p && typeof p.then === 'function') {
          p.then(function () { setTimeout(function () { gd.__donutThemeApplying = false; }, 0); })
           .catch(function () { gd.__donutThemeApplying = false; });
        } else {
          setTimeout(function () { gd.__donutThemeApplying = false; }, 0);
        }
      } catch (e) {
        gd.__donutThemeApplying = false;
      }
    }

    function getDefaultCenter() {
      var ann = (gd.layout && gd.layout.annotations) ? gd.layout.annotations : [];
      return {
        name: (ann[0] && ann[0].text) ? ann[0].text : 'Portfolio',
        value: (ann[1] && ann[1].text) ? ann[1].text : '€0.00'
      };
    }

    function setCenterText(nameText, valueText) {
      if (typeof Plotly !== 'undefined' && Plotly.relayout) {
        Plotly.relayout(gd, {
          'annotations[0].text': nameText,
          'annotations[1].text': valueText
        });
      }
    }

    var defaults = getDefaultCenter();
    applyTheme();

    if (typeof gd.on === 'function') {
      gd.on('plotly_hover', function (eventData) {
        try {
          var pt = eventData && eventData.points ? eventData.points[0] : null;
          if (!pt) return;
          var label = pt.label || (pt.data && pt.data.name) || 'Position';
          var value = (pt.value != null) ? pt.value : (pt.y != null ? pt.y : null);
          setCenterText(String(label).slice(0, 24), formatCurrency(value));
        } catch (e) {}
      });

      gd.on('plotly_unhover', function () {
        defaults = getDefaultCenter();
        setCenterText(defaults.name, defaults.value);
      });

      gd.on('plotly_afterplot', function () {
        if (gd.__donutThemeApplying) return;
        defaults = getDefaultCenter();
        applyTheme();
      });
    }

    console.log('[ChartAsset] Attached donut hover to', DONUT_ID);
    return true;
  }

  // Poll until the graph exists (Dash mounts it asynchronously)
  var poll = setInterval(function () {
    var donutOk = attachDonutHover();
    var mainOk = attachMainLogger();
    // If debug is off, mainOk stays false; don't keep polling once donut is attached.
    if (donutOk && (!isChartDebugEnabled() || mainOk)) {
      clearInterval(poll);
    }
  }, POLL_MS);
})();
