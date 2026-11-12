(function () {
  "use strict";

  const CFG = window.PHW_CONFIG;
  const ICONS = {
    clear: "☀️", "mostly-clear": "🌤️", "partly-cloudy": "⛅", overcast: "☁️", fog: "🌫️",
    drizzle: "🌦️", rain: "🌧️", "heavy-rain": "🌧️", showers: "🌦️", snow: "❄️", thunder: "⛈️",
  };
  const state = { cities: [], current: {}, reference: null, cityData: {}, selected: null };

  const $ = (id) => document.getElementById(id);
  const fmt1 = (v) => (v === null || v === undefined ? "--" : Number(v).toFixed(1));
  const fmt0 = (v) => (v === null || v === undefined ? "--" : Math.round(Number(v)).toString());

  // Data is republished hourly; bucket the cache-buster to 5 minutes so CDN caches still help.
  const bust = () => Math.floor(Date.now() / 300000);
  async function getJSON(path) {
    const res = await fetch(`${CFG.dataBase}/${path}?v=${bust()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`${path}: HTTP ${res.status}`);
    return res.json();
  }

  function manilaToday() {
    return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Manila" }).format(new Date());
  }
  function prettyLocal(ts) {
    // ts is "YYYY-MM-DDTHH:MM" in Manila local time
    const [d, t] = ts.split("T");
    const dt = new Date(`${d}T00:00:00Z`);
    const day = dt.toLocaleDateString("en-PH", { weekday: "short", month: "short", day: "numeric", timeZone: "UTC" });
    const [h, m] = t.split(":").map(Number);
    const hh = ((h + 11) % 12) + 1;
    return `${day}, ${hh}:${String(m).padStart(2, "0")} ${h < 12 ? "AM" : "PM"} PHT`;
  }
  function weekday(dateStr) {
    return new Date(`${dateStr}T00:00:00Z`).toLocaleDateString("en-PH", { weekday: "short", timeZone: "UTC" });
  }
  function shortDate(dateStr) {
    return new Date(`${dateStr}T00:00:00Z`).toLocaleDateString("en-PH", { month: "short", day: "numeric", timeZone: "UTC" });
  }
  function iconFor(code) {
    const wc = (state.reference?.weather_codes || []).find((w) => w.weather_code === code);
    return ICONS[wc?.weather_icon] || "🌡️";
  }
  function band(bands, value, minKey, maxKey) {
    if (value === null || value === undefined) return null;
    return bands.find((b) => value >= b[minKey] && value < b[maxKey]) || null;
  }
  function showError(msg) {
    const el = $("error");
    el.textContent = msg;
    el.hidden = false;
  }

  // ---------- city picker ----------
  function renderPicker() {
    const chips = $("city-chips");
    const select = $("city-select");
    chips.innerHTML = "";
    select.innerHTML = "";
    state.cities.forEach((c) => {
      const cur = state.current[c.city_id];
      const b = document.createElement("button");
      b.className = "chip";
      b.type = "button";
      b.setAttribute("role", "tab");
      b.dataset.city = c.city_id;
      b.innerHTML = `${c.city_name.replace(" (Metro Manila)", "")}<span class="chip-temp">${cur ? fmt0(cur.temperature_c) + "°" : ""}</span>`;
      b.addEventListener("click", () => selectCity(c.city_id));
      chips.appendChild(b);
      const o = document.createElement("option");
      o.value = c.city_id;
      o.textContent = c.city_name;
      select.appendChild(o);
    });
    select.addEventListener("change", (e) => selectCity(e.target.value));
  }

  async function selectCity(cityId) {
    state.selected = cityId;
    history.replaceState(null, "", `#city=${cityId}`);
    document.querySelectorAll(".chip").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.city === cityId)));
    $("city-select").value = cityId;
    renderCurrent();
    try {
      if (!state.cityData[cityId]) state.cityData[cityId] = await getJSON(`city/${cityId}.json`);
      if (state.selected !== cityId) return;
      renderForecast();
      renderCharts();
    } catch (err) {
      showError(`Could not load data for this city (${err.message}).`);
    }
  }

  // ---------- current conditions ----------
  function renderCurrent() {
    const c = state.cities.find((x) => x.city_id === state.selected);
    const cur = state.current[state.selected];
    if (!c || !cur) return;
    $("city-name").textContent = c.city_name;
    $("city-region").textContent = `${c.region} · ${c.island_group}`;
    $("obs-time").textContent = `Latest hour: ${prettyLocal(cur.observed_at_local)}`;
    $("wx-icon").textContent = iconFor(cur.weather_code);
    $("temp").textContent = `${fmt0(cur.temperature_c)}°C`;
    $("wx-desc").textContent = cur.weather_description || "";
    $("feels").textContent = `${fmt0(cur.apparent_temperature_c)}°C`;
    $("humidity").textContent = `${fmt0(cur.relative_humidity_pct)}%`;
    $("wind").textContent = `${fmt0(cur.wind_speed_kmh)} km/h`;
    $("precip").textContent = `${fmt1(cur.precipitation_mm)} mm`;

    const aqiBands = state.reference.aqi_bands;
    const ab = band(aqiBands, cur.us_aqi, "aqi_min", "aqi_max_exclusive");
    $("aqi-value").textContent = fmt0(cur.us_aqi);
    $("aqi-cat").textContent = ab ? ab.aqi_category : "No data";
    $("aqi-advice").textContent = ab ? ab.health_advice : "";
    $("aqi-dial").style.borderColor = ab ? ab.aqi_color : "#cfd8e6";
    $("pm25").textContent = fmt1(cur.pm2_5_ugm3);
    $("pm10").textContent = fmt1(cur.pm10_ugm3);
    renderScale("aqi-scale", aqiBands, "aqi_color", "aqi_category", ab && ab.aqi_category, "aqi_category");

    const hiBands = state.reference.heat_index_bands;
    const hb = band(hiBands, cur.heat_index_c, "heat_index_min_c", "heat_index_max_exclusive_c");
    $("hi-value").textContent = fmt0(cur.heat_index_c);
    $("hi-cat").textContent = hb ? hb.heat_category : "No data";
    $("hi-advice").textContent = hb ? hb.advice : "";
    $("hi-dial").style.borderColor = hb ? hb.heat_color : "#cfd8e6";
    renderScale("hi-scale", hiBands, "heat_color", "heat_category", hb && hb.heat_category, "heat_category");
    $("hi-peak").textContent = "--";
  }

  function renderScale(id, bands, colorKey, labelKey, active) {
    const el = $(id);
    el.innerHTML = "";
    bands.forEach((b) => {
      const s = document.createElement("span");
      s.style.background = b[colorKey];
      s.title = b[labelKey];
      if (b[labelKey] === active) s.className = "active";
      el.appendChild(s);
    });
  }

  // ---------- forecast ----------
  function renderForecast() {
    const d = state.cityData[state.selected].daily;
    const today = manilaToday();
    const wrap = $("forecast");
    wrap.innerHTML = "";
    const idx = d.observed_date_local.map((x, i) => [x, i]).filter(([x]) => x >= today).slice(0, 7);
    idx.forEach(([date, i]) => {
      const aqi = d.us_aqi_max[i];
      const ab = band(state.reference.aqi_bands, aqi, "aqi_min", "aqi_max_exclusive");
      const div = document.createElement("div");
      div.className = "day" + (date === today ? " today" : "");
      div.innerHTML = `
        <div class="dname">${date === today ? "Today" : weekday(date)}</div>
        <div class="ddate">${shortDate(date)}</div>
        <div class="dicon" title="${d.weather_description[i] || ""}">${iconFor(d.weather_code_max[i])}</div>
        <div class="dtemps"><span class="max">${fmt0(d.temp_max_c[i])}°</span><span class="min">${fmt0(d.temp_min_c[i])}°</span></div>
        <div class="dmeta">💧 ${fmt1(d.precipitation_total_mm[i])} mm</div>
        <div class="dmeta">${ab ? `<span class="aqi-dot" style="background:${ab.aqi_color}"></span>AQI ${aqi}` : "AQI n/a"}</div>`;
      wrap.appendChild(div);
      if (date === today) $("hi-peak").textContent = `${fmt0(d.heat_index_max_c[i])}°C (${d.heat_category_max[i] || "n/a"})`;
    });
  }

  // ---------- charts ----------
  const baseLayout = () => ({
    margin: { l: 44, r: 16, t: 8, b: 36 },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif", size: 12, color: "#33435e" },
    xaxis: { gridcolor: "#eef2f8", type: "date" },
    yaxis: { gridcolor: "#eef2f8", zeroline: false },
    legend: { orientation: "h", y: 1.12, x: 0 },
    hovermode: "x unified",
  });
  const plotCfg = { displayModeBar: false, responsive: true };

  function forecastShape(h) {
    const first = h.is_forecast.indexOf(true);
    if (first < 0) return [];
    return [{
      type: "rect", xref: "x", yref: "paper", x0: h.observed_at_local[first],
      x1: h.observed_at_local[h.observed_at_local.length - 1], y0: 0, y1: 1,
      fillcolor: "rgba(47,123,245,0.07)", line: { width: 0 }, layer: "below",
    }];
  }

  function renderCharts() {
    const h = state.cityData[state.selected].hourly;
    const d = state.cityData[state.selected].daily;
    const x = h.observed_at_local;
    const shapes = forecastShape(h);

    Plotly.react("chart-temp", [
      { x, y: h.temperature_c, name: "Temperature °C", mode: "lines", line: { color: "#2f7bf5", width: 2 } },
      { x, y: h.heat_index_c, name: "Heat index °C", mode: "lines", line: { color: "#f08c00", width: 2, dash: "dot" } },
      { x, y: h.apparent_temperature_c, name: "Feels like °C", mode: "lines", line: { color: "#9aa7bd", width: 1 }, visible: "legendonly" },
    ], Object.assign(baseLayout(), { shapes, yaxis: { gridcolor: "#eef2f8", title: { text: "°C" } } }), plotCfg);

    Plotly.react("chart-rain", [
      { x, y: h.precipitation_mm, type: "bar", name: "Rain mm", marker: { color: "#4f9cf9" } },
    ], Object.assign(baseLayout(), { shapes, showlegend: false }), plotCfg);

    const aqiColors = h.us_aqi.map((v) => {
      const b = band(state.reference.aqi_bands, v, "aqi_min", "aqi_max_exclusive");
      return b ? b.aqi_color : "#ccc";
    });
    Plotly.react("chart-aqi", [
      { x, y: h.us_aqi, name: "US AQI", type: "bar", marker: { color: aqiColors } },
      { x, y: h.pm2_5_ugm3, name: "PM2.5 µg/m³", mode: "lines", yaxis: "y2", line: { color: "#5b4bd6", width: 1.5 } },
    ], Object.assign(baseLayout(), {
      shapes,
      yaxis: { gridcolor: "#eef2f8", title: { text: "AQI" }, rangemode: "tozero" },
      yaxis2: { overlaying: "y", side: "right", showgrid: false, title: { text: "PM2.5" }, rangemode: "tozero" },
      margin: { l: 44, r: 48, t: 8, b: 36 },
    }), plotCfg);

    Plotly.react("chart-daily", [
      { x: d.observed_date_local, y: d.temp_max_c, name: "Max °C", mode: "lines+markers", line: { color: "#e8590c" } },
      { x: d.observed_date_local, y: d.temp_min_c, name: "Min °C", mode: "lines+markers", line: { color: "#1971c2" }, fill: "tonexty", fillcolor: "rgba(47,123,245,0.08)" },
      { x: d.observed_date_local, y: d.precipitation_total_mm, name: "Rain mm (day)", type: "bar", yaxis: "y2", marker: { color: "rgba(79,156,249,0.35)" } },
    ], Object.assign(baseLayout(), {
      yaxis: { gridcolor: "#eef2f8", title: { text: "°C" } },
      yaxis2: { overlaying: "y", side: "right", showgrid: false, title: { text: "mm" }, rangemode: "tozero" },
      margin: { l: 44, r: 48, t: 8, b: 36 },
      hovermode: "x unified",
    }), plotCfg);
  }

  // ---------- boot ----------
  async function init() {
    try {
      const [cities, current, reference] = await Promise.all([
        getJSON("cities.json"), getJSON("current.json"), getJSON("reference.json"),
      ]);
      state.cities = cities;
      current.forEach((c) => (state.current[c.city_id] = c));
      state.reference = reference;
    } catch (err) {
      showError(`Could not load weather data (${err.message}). Please try again in a minute.`);
      return;
    }
    renderPicker();
    const fromHash = (location.hash.match(/city=([a-z_]+)/) || [])[1];
    const first = state.cities.some((c) => c.city_id === fromHash) ? fromHash : (state.cities.find((c) => c.city_id === "quezon_city") || state.cities[0]).city_id;
    selectCity(first);
  }

  init();
})();
