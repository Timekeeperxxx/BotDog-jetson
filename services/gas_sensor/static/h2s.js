const $ = (selector) => document.querySelector(selector);

const DEVICE = {
  id: "GT-01",
  name: "固定式磷化氢浓度检测仪",
  location: "原料入口",
};

const DUST_DEVICE = {
  id: "GT-01 DUST",
  name: "地址1粉尘通道",
  location: "原料入口",
};

const CLIMATE_DEVICE = {
  id: "GT-01 ENV",
  name: "PH₃模组环境寄存器",
  location: "原料入口",
};

const gases = [
  {
    id: "ph3", formula: "PH₃", name: "磷化氢", unit: "ppm", decimals: 1,
    value: null, minimum: 0, maximum: 100,
    chartMin: 0, chartMax: 100, rangeText: "等待设备量程", color: "#83f28f",
    status: "连接中", statusCode: null, address: 4,
  },
  {
    id: "co2", formula: "CO₂", name: "二氧化碳", unit: "ppm", decimals: 0,
    value: null, minimum: 0, maximum: 10000,
    chartMin: 0, chartMax: 10000, rangeText: "等待设备量程", color: "#75a7ff",
    status: "连接中", statusCode: null, address: 3,
  },
  {
    id: "o2", formula: "O₂", name: "氧气", unit: "% vol", decimals: 1,
    value: null, minimum: 0, maximum: 30,
    chartMin: 0, chartMax: 30, rangeText: "等待设备量程", color: "#6de1dd",
    status: "连接中", statusCode: null, address: 2,
  },
];

const environmentChannels = [
  {
    id: "dust", formula: "DUST", name: "粉尘浓度", unit: "mg/m³", decimals: 3,
    value: null, minimum: 0, maximum: 1,
    chartMin: 0, chartMax: 1, rangeText: "等待设备量程", color: "#f1c56b",
    status: "连接中", statusCode: null, address: 1,
  },
  {
    id: "temperature", formula: "TEMP", name: "仓内温度", unit: "°C", decimals: 1,
    value: null, minimum: -20, maximum: 60,
    chartMin: 20, chartMax: 26, rangeText: "20.0 – 26.0 °C", color: "#ff9177",
  },
  {
    id: "humidity", formula: "RH", name: "相对湿度", unit: "% RH", decimals: 1,
    value: null, minimum: 0, maximum: 100,
    chartMin: 45, chartMax: 70, rangeText: "45 – 70% RH", color: "#6db9ff",
  },
];

const state = {
  paused: false,
  selectedRange: 30,
  tick: 0,
  records: [],
  histories: new Map(),
  environmentHistories: new Map(),
  toastTimer: null,
  requestInFlight: false,
  lastApiError: null,
};

const elements = {
  ph3Reading: $("#ph3Reading"),
  co2Reading: $("#co2Reading"),
  o2Reading: $("#o2Reading"),
  ph3Track: $("#ph3Track"),
  co2Track: $("#co2Track"),
  o2Track: $("#o2Track"),
  multiTrend: $("#multiTrend"),
  dustTrend: $("#dustTrend"),
  climateTrend: $("#climateTrend"),
  recordsBody: $("#recordsBody"),
  dustRecordsBody: $("#dustRecordsBody"),
  climateRecordsBody: $("#climateRecordsBody"),
  dustReading: $("#dustReading"),
  dustStatus: $("#dustStatus"),
  temperatureReading: $("#temperatureReading"),
  humidityReading: $("#humidityReading"),
  lastUpdated: $("#lastUpdated"),
  monitorStatus: $("#monitorStatus"),
  pauseMonitorButton: $("#pauseMonitorButton"),
  pauseIconPath: $("#pauseIconPath"),
  exportButton: $("#exportButton"),
  toast: $("#toast"),
  dataSourceBadge: $("#dataSourceBadge"),
  sourceConnection: $("#sourceConnection"),
  gasOnlineStatus: $("#gasOnlineStatus"),
  overallTitle: $("#overallTitle"),
  overallDetail: $("#overallDetail"),
};

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function gasById(id) {
  return gases.find((gas) => gas.id === id);
}

function environmentById(id) {
  return environmentChannels.find((channel) => channel.id === id);
}

function formatValue(gas, value = gas.value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return "—";
  return Number(value).toFixed(gas.decimals);
}

function formatHtmlValue(gas, value = gas.value) {
  return formatValue(gas, value).replace("<", "&lt;");
}

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("visible");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => elements.toast.classList.remove("visible"), 2600);
}

function timeLabel(date = new Date()) {
  return date.toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function renderSummary() {
  gases.forEach((gas) => {
    elements[`${gas.id}Reading`].textContent = formatValue(gas);
    const statusElement = $(`#${gas.id}Status`);
    if (statusElement) statusElement.textContent = gas.status;
  });
  gases.forEach((gas) => {
    const track = elements[`${gas.id}Track`];
    const percentage = gas.value === null ? 0 : (gas.value / gas.maximum) * 100;
    track.style.width = `${clamp(percentage, 0, 100)}%`;
  });
}

function renderEnvironmentSummary() {
  environmentChannels.forEach((channel) => {
    elements[`${channel.id}Reading`].textContent = formatValue(channel);
  });
  elements.dustStatus.textContent = environmentById("dust").status;
}

function chartPoints(gas, values) {
  const left = 10;
  const right = 790;
  const top = 10;
  const bottom = 88;
  const span = Math.max(0.000001, gas.chartMax - gas.chartMin);
  return values.map((value, index) => ({
    x: values.length === 1 ? right : left + (index / (values.length - 1)) * (right - left),
    y: bottom - clamp((value - gas.chartMin) / span, 0, 1) * (bottom - top),
    value,
  }));
}

function smoothPath(points) {
  if (!points.length) return "";
  let path = `M ${points[0].x.toFixed(2)} ${points[0].y.toFixed(2)}`;
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const current = points[index];
    const midpoint = (previous.x + current.x) / 2;
    path += ` C ${midpoint.toFixed(2)} ${previous.y.toFixed(2)}, ${midpoint.toFixed(2)} ${current.y.toFixed(2)}, ${current.x.toFixed(2)} ${current.y.toFixed(2)}`;
  }
  return path;
}

function trendRowsMarkup(channels, histories) {
  const sampleCount = state.selectedRange === 30 ? 20 : state.selectedRange === 60 ? 30 : 48;
  return channels.map((channel) => {
    const values = (histories.get(channel.id) || []).slice(-sampleCount);
    const points = chartPoints(channel, values);
    const line = smoothPath(points);
    const visibleDots = points.filter((_, index) => index % Math.max(1, Math.floor(points.length / 6)) === 0 || index === points.length - 1);
    const dots = visibleDots.map((point) => `<circle class="trend-dot" cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="3"><title>${formatHtmlValue(channel, point.value)} ${channel.unit}</title></circle>`).join("");
    return `
      <section class="trend-row" style="--trend-color:${channel.color}" aria-label="${channel.name}趋势">
        <div class="trend-meta">
          <span class="trend-name"><i></i>${channel.formula} · ${channel.name}</span>
          <span class="trend-current"><strong>${formatHtmlValue(channel)}</strong><span>${channel.unit}</span></span>
          <span class="trend-range">独立量程 ${channel.rangeText}</span>
        </div>
        <svg class="trend-svg" viewBox="0 0 800 100" preserveAspectRatio="none" role="img">
          <line class="grid-line" x1="10" y1="25" x2="790" y2="25" />
          <line class="grid-line" x1="10" y1="50" x2="790" y2="50" />
          <line class="grid-line" x1="10" y1="75" x2="790" y2="75" />
          <path class="trend-area" d="${line ? `${line} L 790 88 L 10 88 Z` : ""}" />
          <path class="trend-line" d="${line}" />
          ${dots}
        </svg>
      </section>`;
  }).join("");
}

function renderTrends() {
  elements.multiTrend.innerHTML = trendRowsMarkup(gases, state.histories);
}

function renderEnvironmentTrends() {
  elements.dustTrend.innerHTML = trendRowsMarkup(
    [environmentById("dust")],
    state.environmentHistories,
  );
  elements.climateTrend.innerHTML = trendRowsMarkup(
    [environmentById("temperature"), environmentById("humidity")],
    state.environmentHistories,
  );
}

function recordFromCurrent(readAt) {
  return {
    time: timeLabel(readAt),
    device: DEVICE.id,
    location: DEVICE.location,
    values: Object.fromEntries(gases.map((gas) => [gas.id, gas.value])),
    statuses: Object.fromEntries(gases.map((gas) => [gas.id, gas.status])),
    environmentValues: Object.fromEntries(environmentChannels.map((channel) => [channel.id, channel.value])),
    environmentStatuses: Object.fromEntries(environmentChannels.map((channel) => [channel.id, channel.status || "模组上报"])),
  };
}

function addRecord(readAt) {
  state.records.unshift(recordFromCurrent(readAt));
  state.records = state.records.slice(0, 20);
}

function renderRecords() {
  if (!state.records.length) {
    elements.recordsBody.innerHTML = '<tr><td colspan="7">正在等待第一组串口数据…</td></tr>';
    return;
  }
  elements.recordsBody.innerHTML = state.records.slice(0, 8).map((record) => `
    <tr>
      <td>${record.time}</td>
      <td>${record.device}</td>
      <td>${record.location}</td>
      <td><span class="record-value ph3">${formatHtmlValue(gasById("ph3"), record.values.ph3)}<small>ppm</small></span></td>
      <td><span class="record-value co2">${formatHtmlValue(gasById("co2"), record.values.co2)}<small>ppm</small></span></td>
      <td><span class="record-value o2">${formatHtmlValue(gasById("o2"), record.values.o2)}<small>% vol</small></span></td>
      <td><span class="record-status">${Object.values(record.statuses).every((status) => status === "正常") ? "正常" : "请检查"}</span></td>
    </tr>
  `).join("");
}

function renderEnvironmentRecords() {
  if (!state.records.length) {
    elements.dustRecordsBody.innerHTML = '<tr><td colspan="5">正在等待第一组粉尘串口数据…</td></tr>';
    elements.climateRecordsBody.innerHTML = '<tr><td colspan="6">正在等待模组环境数据…</td></tr>';
    return;
  }
  elements.dustRecordsBody.innerHTML = state.records.slice(0, 8).map((record) => `
    <tr>
      <td>${record.time}</td>
      <td>${DUST_DEVICE.id}</td>
      <td>${DUST_DEVICE.location}</td>
      <td><span class="record-value dust">${formatHtmlValue(environmentById("dust"), record.environmentValues.dust)}<small>mg/m³</small></span></td>
      <td><span class="record-status dust-status">${record.environmentStatuses.dust}</span></td>
    </tr>
  `).join("");
  elements.climateRecordsBody.innerHTML = state.records.slice(0, 8).map((record) => `
    <tr>
      <td>${record.time}</td>
      <td>${CLIMATE_DEVICE.id}</td>
      <td>${CLIMATE_DEVICE.location}</td>
      <td><span class="record-value temperature">${formatHtmlValue(environmentById("temperature"), record.environmentValues.temperature)}<small>°C</small></span></td>
      <td><span class="record-value humidity">${formatHtmlValue(environmentById("humidity"), record.environmentValues.humidity)}<small>% RH</small></span></td>
      <td><span class="record-status climate-status">模组上报</span></td>
    </tr>
  `).join("");
}

function pushHistory(histories, id, value) {
  if (!Number.isFinite(Number(value))) return;
  const history = histories.get(id) || [];
  history.push(Number(value));
  if (history.length > 48) history.shift();
  histories.set(id, history);
}

function formatCacheAge(seconds) {
  const age = Math.max(0, Number(seconds) || 0);
  if (age < 60) return `${Math.round(age)} 秒`;
  if (age < 3600) return `${Math.round(age / 60)} 分钟`;
  return `${(age / 3600).toFixed(1)} 小时`;
}

function applyGasReading(gas, reading) {
  gas.value = Number(reading.value);
  gas.decimals = Number(reading.decimals);
  gas.unit = reading.unit === "%VOL" ? "% vol" : reading.unit;
  gas.minimum = 0;
  gas.maximum = Number(reading.full_scale);
  gas.chartMin = 0;
  gas.chartMax = Math.max(gas.maximum, 0.1);
  gas.rangeText = `0 – ${formatValue(gas, gas.maximum)} ${gas.unit}`;
  gas.status = reading.cached
    ? `${reading.status} · 缓存 ${formatCacheAge(reading.age_seconds)}`
    : reading.status;
  gas.statusCode = reading.status_code;
  gas.address = reading.address;
  pushHistory(state.histories, gas.id, gas.value);
}

function applyEnvironmentReading(ph3Reading) {
  const temperature = Number(ph3Reading.temperature);
  const humidity = Number(ph3Reading.humidity);
  if (temperature >= -20 && temperature <= 60) {
    const channel = environmentById("temperature");
    channel.value = temperature;
    channel.chartMin = Math.floor(temperature - 5);
    channel.chartMax = Math.ceil(temperature + 5);
    channel.rangeText = `${channel.chartMin.toFixed(1)} – ${channel.chartMax.toFixed(1)} °C`;
    pushHistory(state.environmentHistories, channel.id, channel.value);
  }
  if (humidity >= 0 && humidity <= 100) {
    const channel = environmentById("humidity");
    channel.value = humidity;
    channel.chartMin = Math.max(0, Math.floor(humidity - 15));
    channel.chartMax = Math.min(100, Math.ceil(humidity + 15));
    channel.rangeText = `${channel.chartMin} – ${channel.chartMax}% RH`;
    pushHistory(state.environmentHistories, channel.id, channel.value);
  }
}

function applyDustReading(reading) {
  const channel = environmentById("dust");
  channel.value = Number(reading.value);
  channel.decimals = Number(reading.decimals);
  channel.maximum = Number(reading.full_scale);
  channel.chartMin = 0;
  channel.chartMax = Math.max(channel.maximum, 0.001);
  channel.rangeText = `0 – ${formatValue(channel, channel.maximum)} mg/m³`;
  channel.status = reading.cached
    ? `${reading.status} · 缓存 ${formatCacheAge(reading.age_seconds)}`
    : reading.status;
  channel.statusCode = reading.status_code;
  channel.address = reading.address;
  pushHistory(state.environmentHistories, channel.id, channel.value);
}

function updateConnectionSummary(payload) {
  const freshChannels = new Set(payload.fresh_channels || []);
  const environmentCount = ["temperature", "humidity"]
    .filter((id) => freshChannels.has("ph3") && Number.isFinite(Number(environmentById(id).value))).length;
  const onlineCount = freshChannels.size + environmentCount;
  elements.gasOnlineStatus.textContent = `${onlineCount} / 6 数据项在线`;
  elements.sourceConnection.textContent = `${payload.port} · Modbus-RTU 9600 8N1`;
  const cachedCount = (payload.cached_channels || []).length;
  elements.dataSourceBadge.innerHTML = cachedCount
    ? `<i></i>真实串口数据 · ${cachedCount} 项缓存`
    : "<i></i>真实串口数据";
  const dust = environmentById("dust");
  const allFresh = freshChannels.size === 4 && cachedCount === 0;
  const allNormal = allFresh && gases.every((gas) => Number(gas.statusCode) === 1)
    && Number(dust.statusCode) === 1;
  elements.overallTitle.textContent = cachedCount
    ? "传感器通信异常"
    : (allNormal ? "环境监测正常" : "存在传感器告警");
  elements.overallDetail.textContent = cachedCount
    ? `${cachedCount} 个串口通道没有新回包，当前显示最后一次实测值`
    : (allNormal
      ? "粉尘、三路气体与温湿度状态正常"
      : [`DUST ${dust.status}`, ...gases.map((gas) => `${gas.formula} ${gas.status}`)].join(" · "));
}

async function updateLiveReadings() {
  if (state.paused || state.requestInFlight) return;
  state.requestInFlight = true;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5_000);
  try {
    const response = await fetch("/api/gases", { cache: "no-store", signal: controller.signal });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || `读取失败（HTTP ${response.status}）`);
    if (state.paused) return;

    gases.forEach((gas) => {
      const reading = payload.gases?.[gas.id];
      if (reading) {
        applyGasReading(gas, reading);
      } else {
        gas.status = "离线";
      }
    });
    if (payload.dust) {
      applyDustReading(payload.dust);
    } else {
      environmentById("dust").status = "离线";
    }
    if (payload.gases?.ph3) applyEnvironmentReading(payload.gases.ph3);
    const readAt = new Date(payload.read_at);
    addRecord(readAt);
    updateConnectionSummary(payload);
    const sampleTimes = Object.values(payload.gases).map((reading) => Date.parse(reading.sampled_at));
    if (payload.dust) sampleTimes.push(Date.parse(payload.dust.sampled_at));
    const latestSample = Math.max(...sampleTimes);
    if (Number.isFinite(latestSample)) elements.lastUpdated.textContent = timeLabel(new Date(latestSample));
    elements.monitorStatus.textContent = payload.status === "ok"
      ? "真实数据监测中"
      : (payload.fresh_channels.length ? "部分通道在线" : "监测数据未更新");
    state.lastApiError = null;

    renderSummary();
    renderEnvironmentSummary();
    renderTrends();
    renderEnvironmentTrends();
    renderRecords();
    renderEnvironmentRecords();
  } catch (error) {
    if (state.paused) return;
    const message = controller.signal.aborted ? "读取气体数据超时" : error.message;
    elements.monitorStatus.textContent = "监测数据未更新";
    elements.dataSourceBadge.innerHTML = "<i></i>连接异常 · 正在重试";
    elements.gasOnlineStatus.textContent = "0 / 6 数据项在线";
    elements.overallTitle.textContent = "监测数据未更新";
    elements.overallDetail.textContent = `${message}，正在重试`;
    for (const channel of [...gases, environmentById("dust")]) {
      channel.status = channel.value === null ? "离线" : "上次读数";
    }
    renderSummary();
    renderEnvironmentSummary();
    if (state.lastApiError !== message) showToast(message);
    state.lastApiError = message;
  } finally {
    clearTimeout(timeout);
    state.requestInFlight = false;
  }
}

function toggleMonitoring() {
  state.paused = !state.paused;
  elements.pauseMonitorButton.querySelector("span").textContent = state.paused ? "继续监测" : "暂停监测";
  elements.pauseIconPath.setAttribute("d", state.paused ? "M8 5l11 7-11 7z" : "M8 5v14M16 5v14");
  elements.monitorStatus.textContent = state.paused ? "监测已暂停" : "实时监测中";
  document.querySelectorAll(".live-reading i, .auto-refresh i, .environment-live i, .climate-live i").forEach((dot) => {
    dot.style.animationPlayState = state.paused ? "paused" : "running";
  });
  showToast(state.paused ? "已暂停三路监测数据刷新" : "已继续读取三台设备数据");
  if (!state.paused) updateLiveReadings();
}

function exportRecords() {
  const rows = [
    ["时间", "气体仪器", "粉尘设备", "温湿度设备", "安装位置", "PH3 (ppm)", "CO2 (ppm)", "O2 (% vol)", "粉尘 (mg/m³)", "温度 (°C)", "相对湿度 (% RH)", "状态"],
    ...state.records.map((record) => [
      record.time, record.device, DUST_DEVICE.id, CLIMATE_DEVICE.id, record.location,
      formatValue(gasById("ph3"), record.values.ph3),
      formatValue(gasById("co2"), record.values.co2),
      formatValue(gasById("o2"), record.values.o2),
      formatValue(environmentById("dust"), record.environmentValues.dust),
      formatValue(environmentById("temperature"), record.environmentValues.temperature),
      formatValue(environmentById("humidity"), record.environmentValues.humidity),
      Object.values(record.statuses).every((status) => status === "正常") ? "正常" : "请检查",
    ]),
  ];
  const csv = `\ufeff${rows.map((row) => row.map((cell) => `"${String(cell).replaceAll('"', '""')}"`).join(",")).join("\n")}`;
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = `warehouse-monitoring-${new Date().toISOString().slice(0, 10)}.csv`;
  link.click();
  URL.revokeObjectURL(url);
  showToast("气体与环境监测记录已导出");
}

gases.forEach((gas) => state.histories.set(gas.id, []));
environmentChannels.forEach((channel) => state.environmentHistories.set(channel.id, []));
renderSummary();
renderEnvironmentSummary();
renderTrends();
renderEnvironmentTrends();
renderRecords();
renderEnvironmentRecords();

elements.pauseMonitorButton.addEventListener("click", toggleMonitoring);
elements.exportButton.addEventListener("click", exportRecords);
document.querySelectorAll("[data-range]").forEach((button) => {
  button.addEventListener("click", () => {
    state.selectedRange = Number(button.dataset.range);
    document.querySelectorAll("[data-range]").forEach((item) => item.classList.toggle("active", item === button));
    renderTrends();
    renderEnvironmentTrends();
  });
});

updateLiveReadings();
setInterval(updateLiveReadings, 2_000);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden) updateLiveReadings();
});
