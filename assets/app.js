const data = window.STOCK_DATA;
const ALL = "\uc804\uccb4";
const LISTED = "\uc0c1\uc7a5";
const WATCHLIST_KEY = "sector-dashboard-watchlist-v1";
const CUSTOM_STOCKS_KEY = "sector-dashboard-custom-stocks-v1";
const OVERRIDES_KEY = "sector-dashboard-stock-overrides-v1";
const MEMOS_KEY = "sector-dashboard-stock-memos-v1";

const state = {
  part: ALL,
  theme: ALL,
  status: ALL,
  query: "",
  treeQuery: "",
  watchOnly: false,
  sort: "d1",
  selectedKey: null,
  apiOnline: false,
  aiStatus: null,
  newsMode: "all",
  newsScope: "market",
  heatmapStockSort: "marketCap",
  partFlowMode: "ytd",
  weights: {
    value: 0.25,
    quality: 0.3,
    momentum: 0.25,
    growth: 0.1,
    stability: 0.1,
  },
};

const $ = (selector) => document.querySelector(selector);
const tickerKey = (stock) => stock.gfKey || stock.ticker || stock.nameKr;
const pct = (value) => (typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "-");
const signedClass = (value) => (value > 0 ? "positive" : value < 0 ? "negative" : "neutral");
const formatNumber = (value, digits = 2) =>
  typeof value === "number" ? new Intl.NumberFormat("ko-KR", { maximumFractionDigits: digits }).format(value) : "-";
const formatMoney = (value, currency = "") =>
  typeof value === "number" ? `${formatNumber(value)}${currency ? ` ${currency}` : ""}` : "-";
const escapeHtml = (value = "") =>
  String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");

let watchlist = loadSet(WATCHLIST_KEY);
let stockOverrides = loadOverrides();
let stockMemos = loadObject(MEMOS_KEY);
let lookupCache = new Map();
let lookupRequestSeq = 0;
let lookupDebounceTimer = null;
let lookupAbortController = null;
let marketIndicatorsRequested = false;

function loadSet(key) {
  try {
    return new Set(JSON.parse(localStorage.getItem(key) || "[]"));
  } catch {
    return new Set();
  }
}


function loadObject(key) {
  try { return JSON.parse(localStorage.getItem(key) || "{}"); } catch { return {}; }
}

function loadOverrides() { return loadObject(OVERRIDES_KEY); }
function loadCustomStocks() { try { return JSON.parse(localStorage.getItem(CUSTOM_STOCKS_KEY) || "[]"); } catch { return []; } }
function saveOverrides() { localStorage.setItem(OVERRIDES_KEY, JSON.stringify(stockOverrides)); }
function saveStockMemos() { localStorage.setItem(MEMOS_KEY, JSON.stringify(stockMemos)); }
function saveCustomStocks(stocks) { localStorage.setItem(CUSTOM_STOCKS_KEY, JSON.stringify(stocks)); }
function saveWatchlist() { localStorage.setItem(WATCHLIST_KEY, JSON.stringify([...watchlist])); }

function hydrateCustomStocks() {
  const existing = new Set(data.stocks.map(tickerKey));
  loadCustomStocks().forEach((stock) => { if (!existing.has(tickerKey(stock))) data.stocks.push(stock); });
}

function applyOverrides() {
  data.stocks.forEach((stock) => { if (stockOverrides[tickerKey(stock)]) Object.assign(stock, stockOverrides[tickerKey(stock)]); });
}

function unique(items) { return [...new Set(items.filter(Boolean))].sort(); }
function cleanPartLabel(value) {
  return String(value || "")
    .replace(/^\s*Part\s*\d+\)\s*/i, "")
    .trim() || "\uBBF8\uBD84\uB958";
}
function comparePartLabel(a, b) {
  return cleanPartLabel(a).localeCompare(cleanPartLabel(b), "ko-KR", { numeric: true, sensitivity: "base" });
}
function sortedPartValues(items) {
  return unique(items.map(cleanPartLabel)).sort(comparePartLabel);
}
function normalizeText(value) {
  return String(value || "").replace(/\s+/g, " ").trim();
}
function normalizeThemeLabel(value) {
  return normalizeText(value) || "일반";
}
function themeLooseKey(value) {
  return normalizeThemeLabel(value).replace(/\s+/g, "").toLowerCase();
}
function compareThemeLabel(a, b) {
  return normalizeThemeLabel(a).localeCompare(normalizeThemeLabel(b), "ko-KR", { numeric: true, sensitivity: "base" });
}
function sortedThemeValues(items) {
  const byKey = new Map();
  items.map(normalizeThemeLabel).forEach((label) => {
    const key = themeLooseKey(label);
    if (!byKey.has(key)) byKey.set(key, label);
  });
  return [...byKey.values()].sort(compareThemeLabel);
}
function allThemeValues(part = "") {
  const cleanPart = part ? cleanPartLabel(part) : "";
  const source = cleanPart ? data.stocks.filter((stock) => cleanPartLabel(stock.part) === cleanPart) : data.stocks;
  return sortedThemeValues(source.map((stock) => stock.theme));
}
function canonicalThemeLabel(value, part = "") {
  const normalized = normalizeThemeLabel(value);
  const key = themeLooseKey(normalized);
  const match = allThemeValues(part).find((theme) => themeLooseKey(theme) === key);
  return match || normalized;
}
function normalizeStockTaxonomy(stock) {
  if (!stock) return;
  stock.part = cleanPartLabel(stock.part);
  stock.theme = normalizeThemeLabel(stock.theme || stock.industry || "일반");
}
function normalizeAllTaxonomy() {
  data.stocks.forEach(normalizeStockTaxonomy);
}
function partThemeLabel(stock) {
  const part = cleanPartLabel(stock?.part);
  const theme = normalizeThemeLabel(stock?.theme);
  return theme ? `${part} / ${theme}` : part;
}
function marketOf(stock) { return stock.exchange || stock.market || (stock.gfKey || "").split(":")[0] || "-"; }
function averageOf(stocks, key) { const values = stocks.map((s) => s[key]).filter((v) => typeof v === "number"); return values.length ? values.reduce((a,b)=>a+b,0)/values.length : null; }
function metricValue(stock, key) { if (key === "targetAvg") return stock.targetPriceAvg ?? stock.targetPrice ?? null; if (key === "forwardPe") return stock.forwardPe ?? null; return stock[key] ?? null; }
function rangePosition(stock) { if (typeof stock.price !== "number" || typeof stock.low52 !== "number" || typeof stock.high52 !== "number" || stock.high52 === stock.low52) return null; return Math.max(0, Math.min(1, (stock.price - stock.low52) / (stock.high52 - stock.low52))); }
function isWatched(stock) { return watchlist.has(tickerKey(stock)); }
function toggleWatch(stock) { const key=tickerKey(stock); if (watchlist.has(key)) watchlist.delete(key); else watchlist.add(key); saveWatchlist(); render(); }

function stockPrimaryName(stock) {
  if (!stock) return "-";
  const ticker = String(stock.ticker || stock.gfKey || "").trim();
  const name = String(stock.nameKr || stock.name || stock.nameEn || ticker || "-").trim();
  return name || ticker || "-";
}

function stockDisplayLabel(stock, compact = false) {
  if (!stock) return "-";
  const ticker = String(stock.ticker || stock.gfKey || "").trim();
  const name = stockPrimaryName(stock);
  if (!ticker || name === ticker) return name;
  return compact ? `${ticker} · ${name}` : `${name} (${ticker})`;
}

function stockSecondaryLabel(stock) {
  if (!stock) return "";
  const ticker = String(stock.ticker || stock.gfKey || "").trim();
  const nameEn = String(stock.nameEn || "").trim();
  const market = marketOf(stock);
  return [ticker, nameEn && nameEn !== stockPrimaryName(stock) ? nameEn : "", market && market !== "-" ? market : ""].filter(Boolean).join(" · ");
}

function stockShortName(stock) {
  const name = stockPrimaryName(stock);
  return name.length > 11 ? `${name.slice(0, 10)}...` : name;
}

function findStockByTicker(raw) {
  const key = String(raw || "").trim();
  if (!key) return null;
  const normalized = key.toUpperCase();
  return data.stocks.find((stock) => {
    const candidates = [tickerKey(stock), stock.ticker, stock.gfKey, stock.nameKr, stock.nameEn].filter(Boolean).map((value) => String(value).toUpperCase());
    return candidates.includes(normalized);
  }) || null;
}

function relatedTickerLabels(item, limit = 8) {
  const related = [...new Set(item.related_tickers || [])].filter(Boolean);
  if (!related.length) return ["시장공통"];
  return related.slice(0, limit).map((ticker) => {
    if (ticker === "시장공통" || ticker === "공통") return "시장공통";
    const stock = findStockByTicker(ticker);
    return stock ? stockDisplayLabel(stock, true) : ticker;
  });
}

function populateFilters() {
  const parts = sortedPartValues(data.stocks.map((s) => s.part));
  $("#partFilter").innerHTML = [ALL, ...parts].map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join("");
  const addPart = $("#newPart");
  if (addPart) {
    const current = cleanPartLabel(addPart.value);
    addPart.innerHTML = [`<option value="미분류">미분류</option>`, ...parts.map((item) => `<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`)].join("");
    if (current && ["미분류", ...parts].includes(current)) addPart.value = current;
  }
  populateThemeFilter();
  ensureThemeDatalist();
  updateThemeSuggestions();
}

function populateThemeFilter() {
  const source = state.part === ALL ? data.stocks : data.stocks.filter((s) => cleanPartLabel(s.part) === state.part);
  const themes = [ALL, ...sortedThemeValues(source.map((s) => s.theme))];
  const selected = themes.find((theme) => themeLooseKey(theme) === themeLooseKey(state.theme));
  state.theme = state.theme === ALL || !selected ? ALL : selected;
  $("#themeFilter").innerHTML = themes.map((item) => `<option value="${escapeHtml(item)}" ${item === state.theme ? "selected" : ""}>${escapeHtml(item)}</option>`).join("");
}

function ensureThemeDatalist() {
  const input = $("#newTheme");
  if (!input) return;
  input.setAttribute("list", "themeSuggestions");
  if (!$("#themeSuggestions")) input.insertAdjacentHTML("afterend", `<datalist id="themeSuggestions"></datalist>`);
}

function updateThemeSuggestions() {
  const list = $("#themeSuggestions");
  const input = $("#newTheme");
  if (!list || !input) return;
  const part = cleanPartLabel($("#newPart")?.value || "");
  const themes = allThemeValues(part).length ? allThemeValues(part) : allThemeValues();
  list.innerHTML = themes.map((theme) => `<option value="${escapeHtml(theme)}"></option>`).join("");
}

function normalizeThemeInput() {
  const input = $("#newTheme");
  if (!input) return;
  input.value = canonicalThemeLabel(input.value, $("#newPart")?.value || "");
  updateThemeSuggestions();
}
function filteredStocks() {
  const q = state.query.trim().toLowerCase();
  return data.stocks.filter((stock) => {
    const text = `${stock.nameKr || ""} ${stock.nameEn || ""} ${stock.ticker || ""} ${stock.gfKey || ""} ${stock.theme || ""} ${stock.part || ""} ${cleanPartLabel(stock.part)}`.toLowerCase();
    return (state.part === ALL || cleanPartLabel(stock.part) === state.part) &&
      (state.theme === ALL || themeLooseKey(stock.theme) === themeLooseKey(state.theme)) &&
      (state.status === ALL || stock.status === state.status) &&
      (!state.watchOnly || isWatched(stock)) &&
      (!q || text.includes(q));
  });
}

function buildQuantScores() {
  const listed = data.stocks.filter((s) => s.status === LISTED);
  const maxPer = Math.max(...listed.map((s) => s.per).filter((v) => typeof v === "number" && v > 0), 1);
  data.stocks.forEach((stock) => {
    const valueScore = typeof stock.per === "number" ? Math.max(0, 100 - (stock.per / maxPer) * 100) : 50;
    const qualityScore = typeof stock.roe === "number" ? Math.max(0, Math.min(100, stock.roe)) : 50;
    const momentumScore = typeof stock.ytd === "number" ? Math.max(0, Math.min(100, 50 + stock.ytd * 50)) : 50;
    const stabilityScore = rangePosition(stock) === null ? 50 : Math.max(0, Math.min(100, (1 - Math.abs(rangePosition(stock) - 0.5)) * 100));
    const growthScore = typeof stock.m1 === "number" ? Math.max(0, Math.min(100, 50 + stock.m1 * 50)) : 50;
    stock.quant = { valueScore, qualityScore, momentumScore, stabilityScore, growthScore, totalScore: valueScore*state.weights.value + qualityScore*state.weights.quality + momentumScore*state.weights.momentum + growthScore*state.weights.growth + stabilityScore*state.weights.stability };
  });
}

async function checkApiStatus() {
  try {
    const res = await fetch("http://127.0.0.1:8787/api/health", { cache: "no-store" });
    state.apiOnline = res.ok;
  } catch {
    state.apiOnline = false;
  }
  const el = $("#apiStatus");
  if (el) el.textContent = state.apiOnline ? "\u0041\u0050\u0049 \uc5f0\uacb0\ub428" : "\u0041\u0050\u0049 \uaebc\uc9d0";
}

async function recalculateQuantFromApi() { return false; }
function normalizeWeightsFromInputs() {
  document.querySelectorAll(".weight-input").forEach((input) => {
    state.weights[input.dataset.weight] = Number(input.value || 0) / 100;
  });
  const total = Object.values(state.weights).reduce((a, b) => a + b, 0);
  const el = $("#weightTotal");
  if (el) el.textContent = `\ud569\uacc4 ${(total * 100).toFixed(0)}%`;
}

function renderTerminalTicker() {
  const stock = state.selectedKey ? findStock(state.selectedKey) : null;
  const el = $("#terminalTicker");
  if (!el) return;
  if (!stock) {
    el.innerHTML = `<div class="terminal-placeholder">\uc885\ubaa9\uc744 \uc120\ud0dd\ud558\uba74 \ud604\uc7ac\uac00, 1D, YTD\uac00 \ud45c\uc2dc\ub429\ub2c8\ub2e4.</div>`;
    return;
  }
  el.innerHTML = `<strong>${escapeHtml(stock.nameKr || stock.nameEn || stock.ticker)}</strong><span>${escapeHtml(stock.ticker || stock.gfKey || "")}</span><b class="terminal-price">${formatMoney(stock.price, stock.currency)}</b><span class="${signedClass(stock.d1)}">1D ${pct(stock.d1)}</span><span class="${signedClass(stock.ytd)}">YTD ${pct(stock.ytd)}</span>`;
}

function sourceLabel(source) {
  const raw = String(source || "").toLowerCase();
  if (raw.includes("financial_modeling_prep")) return "FMP";
  if (raw.includes("yahoo")) return "Yahoo Finance";
  if (raw.includes("finnhub")) return "Finnhub";
  if (raw.includes("alpha")) return "Alpha Vantage";
  if (raw.includes("sqlite") || raw.includes("sample")) return "초기 데이터";
  if (raw.includes("price_history")) return "가격 이력";
  return source || "초기 데이터";
}

function renderMarketTickerTape(stocks) {
  const el = $("#marketTickerTape");
  if (!el) return;
  const preferred = ["SPY", "QQQ", "VOO", "AAPL", "NVDA", "MSFT", "GOOGL", "AMZN", "TSLA", "AMD", "PLTR", "AVGO"];
  const byTicker = new Map(stocks.map((s) => [String(s.ticker || s.gfKey || "").toUpperCase(), s]));
  const picks = preferred.map((ticker) => byTicker.get(ticker)).filter(Boolean);
  const picked = new Set(picks.map(tickerKey));
  const rest = [...stocks]
    .filter((s) => typeof s.price === "number" && !picked.has(tickerKey(s)))
    .sort((a, b) => (b.marketCap || 0) - (a.marketCap || 0) || Math.abs(b.d1 || 0) - Math.abs(a.d1 || 0))
    .slice(0, 28);
  const rows = [...picks, ...rest].slice(0, 36);
  if (!rows.length) {
    el.innerHTML = `<span>시장 티커 대기 · 가격 데이터 수집 후 표시됩니다.</span>`;
    return;
  }
  const itemHtml = rows.map((stock) => `<button class="market-tape-item row-button" data-stock="${escapeHtml(tickerKey(stock))}" type="button" title="${escapeHtml(stockDisplayLabel(stock))}"><strong>${escapeHtml(stock.ticker || stock.gfKey || stockPrimaryName(stock))}</strong><span>${formatMoney(stock.price, stock.currency)}</span><b class="${signedClass(stock.d1)}">${pct(stock.d1)}</b></button>`).join("");
  el.innerHTML = `<div class="market-tape-track">${itemHtml}${itemHtml}</div>`;
  bindStockButtons();
}


function renderMarketIndicators(items = null) {
  const headerActions = document.querySelector(".header-actions");
  const wrap = document.querySelector(".header-search-wrap") || document.querySelector(".search-wrap");
  if (!headerActions && !wrap) return;
  let box = $("#marketIndicators");
  if (!box) {
    const html = `<div id="marketIndicators" class="market-indicators"></div>`;
    if (headerActions) headerActions.insertAdjacentHTML("beforebegin", html);
    else wrap.insertAdjacentHTML("beforeend", html);
    box = $("#marketIndicators");
  }
  const rows = items && items.length ? items : [
    { label: "VIX", value: "연동 대기", changePct: null },
    { label: "USD/KRW", value: "연동 대기", changePct: null },
  ];
  box.innerHTML = rows.map((item) => `<span class="market-indicator"><b>${escapeHtml(item.label)}</b><strong>${escapeHtml(item.value ?? "-")}</strong>${typeof item.changePct === "number" ? `<em class="${signedClass(item.changePct)}">${pct(item.changePct)}</em>` : ""}</span>`).join("");
}

async function hydrateMarketIndicators() {
  if (marketIndicatorsRequested || !state.apiOnline) return;
  marketIndicatorsRequested = true;
  try {
    const res = await fetch("http://127.0.0.1:8787/api/market/indicators", { cache: "no-store" });
    if (!res.ok) return;
    const payload = await res.json();
    const items = (payload.items || []).map((item) => ({ label: item.label, value: item.value, changePct: item.change_pct }));
    if (items.length) renderMarketIndicators(items);
  } catch {}
}
function renderMarketHeatmap(stocks) {
  const el = $("#marketHeatmap");
  if (!el) return;
  const listed = stocks.filter((s) => s.status === LISTED && typeof s.d1 === "number");
  const rows = listed.length ? listed : stocks.filter((s) => s.status === LISTED);
  updateHeatmapControls();
  if (!rows.length) {
    el.innerHTML = `<p class="empty-state">히트맵을 표시할 가격 데이터가 없습니다.</p>`;
    return;
  }
  const groups = new Map();
  rows.forEach((stock) => {
    const key = cleanPartLabel(stock.part);
    groups.set(key, [...(groups.get(key) || []), stock]);
  });
  const groupRows = [...groups.entries()]
    .map(([part, group]) => {
      const values = group.map((stock) => stock.d1).filter((value) => typeof value === "number");
      const avg = values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
      return { part, group, avg };
    })
    .sort((a, b) => (b.avg ?? -999) - (a.avg ?? -999));
  el.innerHTML = groupRows.map(({ part, group, avg }) => {
    const sorted = [...group].sort(compareHeatmapStocks).slice(0, 24);
    return `<section class="heatmap-group"><div class="heatmap-title"><strong>${escapeHtml(cleanPartLabel(part))}</strong><span class="${signedClass(avg)}">평균 ${pct(avg)} · ${group.length}개</span></div><div class="heatmap-tiles">${sorted.map(heatmapTile).join("")}</div></section>`;
  }).join("");
  bindStockButtons();
}

function compareHeatmapStocks(a, b) {
  if (state.heatmapStockSort === "move") {
    return Math.abs(b.d1 || 0) - Math.abs(a.d1 || 0) || (b.marketCap || 0) - (a.marketCap || 0);
  }
  return (b.marketCap || 0) - (a.marketCap || 0) || Math.abs(b.d1 || 0) - Math.abs(a.d1 || 0);
}

function updateHeatmapControls() {
  document.querySelectorAll("[data-heatmap-sort]").forEach((button) => {
    button.classList.toggle("active", button.dataset.heatmapSort === state.heatmapStockSort);
  });
}

function heatmapTile(stock) {
  const value = typeof stock.d1 === "number" ? stock.d1 : 0;
  const strength = Math.min(1, Math.abs(value) / 0.05);
  const alpha = 0.22 + strength * 0.68;
  const color = value > 0 ? `rgba(0, 128, 77, ${alpha})` : value < 0 ? `rgba(220, 38, 38, ${alpha})` : "#cbd5e1";
  const flex = Math.max(1, Math.min(3.5, Math.log10((stock.marketCap || stock.price || 10) + 10) / 2.5));
  return `<button class="heatmap-tile row-button" data-stock="${escapeHtml(tickerKey(stock))}" type="button" title="${escapeHtml(stockDisplayLabel(stock))}" style="background:${color}; flex-grow:${flex}"><strong>${escapeHtml(stock.ticker || stock.gfKey || stockPrimaryName(stock))}</strong><small>${escapeHtml(stockShortName(stock))}</small><span>${pct(stock.d1)}</span></button>`;
}

function renderKpis(stocks) {
  const el = $("#overview");
  if (!el) return;
  const listed = stocks.filter((s) => s.status === LISTED);
  const filledCore = listed.filter((s) => typeof s.per === "number" && typeof s.pbr === "number" && typeof s.roe === "number").length;
  const rows = [
    ["\uD45C\uC2DC \uC885\uBAA9", stocks.length, `${listed.length}\uAC1C \uC0C1\uC7A5`],
    ["\uAD00\uC2EC \uC885\uBAA9", watchlist.size, "\uBE0C\uB77C\uC6B0\uC800 \uC800\uC7A5"],
    ["\uD3C9\uADE0 1D", pct(averageOf(listed, "d1")), "\uB2F9\uC77C \uD750\uB984"],
    ["\uD575\uC2EC \uC9C0\uD45C \uCC44\uC6C0", `${filledCore}/${listed.length}`, "PER/PBR/ROE"],
  ];
  el.innerHTML = rows.map(([a, b, c]) => `<article class="kpi-card"><span>${a}</span><strong>${b}</strong><em>${c}</em></article>`).join("");
}
function renderPartBars(stocks) {
  const el = $("#partBars");
  if (!el) return;
  const mode = state.partFlowMode === "d1" ? "d1" : "ytd";
  const label = mode === "d1" ? "1D" : "YTD";
  const title = $("#partFlowTitle");
  if (title) title.textContent = `Part\uBCC4 ${label} \uD750\uB984`;
  document.querySelectorAll("[data-part-flow-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.partFlowMode === mode);
  });
  const map = new Map();
  stocks.forEach((stock) => {
    const key = cleanPartLabel(stock.part);
    map.set(key, [...(map.get(key) || []), stock]);
  });
  const rows = [...map.entries()].map(([part, rows]) => {
    const values = rows.map((stock) => stock[mode]).filter((value) => typeof value === "number");
    const average = values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
    return { part, count: rows.length, filled: values.length, average };
  }).sort((a, b) => (b.average ?? -999) - (a.average ?? -999));
  el.innerHTML = `<div class="part-summary-list">${rows.map((row) => {
    const tone = row.average > 0 ? "positive" : row.average < 0 ? "negative" : "neutral";
    const value = typeof row.average === "number" ? pct(row.average) : `${label} \uB370\uC774\uD130 \uC5C6\uC74C`;
    return `<article class="part-summary-item"><strong>${escapeHtml(cleanPartLabel(row.part))}</strong><span>${row.count}\uAC1C \uC885\uBAA9 \u00B7 ${label} ${row.filled}/${row.count}</span><b class="${tone}">${value}</b></article>`;
  }).join("")}</div>`;
  const c = $("#filteredCount");
  if (c) c.textContent = `${stocks.length}\uAC1C \uC885\uBAA9 \uD45C\uC2DC`;
}
function renderQuantRank() {}

function renderTree() {
  const el = $("#treeView");
  if (!el) return;
  const q = state.treeQuery.trim().toLowerCase();
  const rows = filteredStocks().filter((s) => !q || `${s.part || ""} ${cleanPartLabel(s.part)} ${s.theme || ""} ${s.nameKr || ""} ${s.nameEn || ""} ${s.name || ""} ${s.ticker || ""} ${s.gfKey || ""}`.toLowerCase().includes(q)).slice(0, 80);
  el.innerHTML = rows.map((s) => `<div class="tree-stock-row ${isWatched(s) ? "watched" : ""}"><button class="watch-star ${isWatched(s) ? "active" : ""}" data-watch="${escapeHtml(tickerKey(s))}" type="button" title="관심 종목">${isWatched(s) ? "★" : "☆"}</button><button class="tree-stock row-button" data-stock="${escapeHtml(tickerKey(s))}" type="button"><strong>${escapeHtml(stockPrimaryName(s))}</strong><small>${escapeHtml(stockSecondaryLabel(s))}</small></button><span>${escapeHtml(s.theme || s.part || "")}</span></div>`).join("");
  bindWatchButtons();
  bindStockButtons();
}

function renderMetricCoverage(stocks) {
  const host = $("#metricCoveragePanel");
  if (!host) return;
  const listed = stocks.filter((s) => s.status === LISTED);
  const total = Math.max(listed.length, 1);
  const defs = [["\ud604\uc7ac\uac00", "price"], ["PER", "per"], ["PBR", "pbr"], ["ROE", "roe"], ["\ubaa9\ud45c\uac00", "targetAvg"]];
  const sourceCounts = new Map();
  listed.forEach((s) => sourceCounts.set(sourceLabel(s._metricsSource || s.source), (sourceCounts.get(sourceLabel(s._metricsSource || s.source)) || 0) + 1));
  const sources = [...sourceCounts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 4).map(([name, count]) => `${name} ${count}`).join(" · ");
  const missingCore = listed.filter((s) => typeof s.per !== "number" || typeof s.pbr !== "number" || typeof s.roe !== "number").length;
  host.innerHTML = `<div class="coverage-head"><strong>\uc9c0\ud45c \ucc44\uc6c0 \ud604\ud669</strong><span>${listed.length}\uac1c \ud45c\uc2dc \uc885\ubaa9 \uae30\uc900</span></div><div class="coverage-grid">${defs.map(([label, key]) => { const count = listed.filter((s) => typeof metricValue(s, key) === "number").length; const p = Math.round((count / total) * 100); return `<div class="coverage-item"><span>${label}</span><strong>${count}/${listed.length}</strong><b><i style="width:${p}%"></i></b></div>`; }).join("")}</div><div class="coverage-source-note"><strong>데이터 출처</strong><span>${escapeHtml(sources || "초기 데이터")}</span><em>조회 순서: 한국 가격/차트 pykrx→FinanceDataReader, 지표 FMP→Yahoo→Finnhub→Alpha Vantage. PER/PBR/ROE 핵심 누락 ${missingCore}개 · 목표가는 무료 제공처에서 비는 종목이 많습니다.</em></div>`;
}

function renderRows(stocks) {
  const el = $("#stockRows");
  if (!el) return;
  const sorted = [...stocks].sort((a, b) => {
    const av = metricValue(a, state.sort) ?? a[state.sort] ?? -999;
    const bv = metricValue(b, state.sort) ?? b[state.sort] ?? -999;
    return bv - av;
  });
  el.innerHTML = sorted.map((stock) => `<tr><td><button class="watch-star ${isWatched(stock) ? "active" : ""}" data-watch="${escapeHtml(tickerKey(stock))}" type="button" title="관심 종목">${isWatched(stock) ? "★" : "☆"}</button></td><td><button class="stock-link row-button" data-stock="${escapeHtml(tickerKey(stock))}" type="button"><strong>${escapeHtml(stockPrimaryName(stock))}</strong><span>${escapeHtml(stockSecondaryLabel(stock))}</span></button></td><td>${escapeHtml(partThemeLabel(stock))}</td><td>${escapeHtml(marketOf(stock))}</td><td>${formatMoney(stock.price, stock.currency)}</td><td>${formatNumber(stock.per, 2)}</td><td>${formatNumber(stock.pbr, 2)}</td><td>${typeof stock.roe === "number" ? pct(stock.roe / 100) : "-"}</td><td>${formatNumber(stock.forwardPe, 2)}</td><td>${formatMoney(metricValue(stock, "targetAvg"), stock.currency)}</td><td class="${signedClass(stock.d1)}">${pct(stock.d1)}</td><td class="${signedClass(stock.ytd)}">${pct(stock.ytd)}</td></tr>`).join("");
  bindWatchButtons();
  bindStockButtons();
  updateSortStatus();
}
function findStock(key) { return data.stocks.find(s=>tickerKey(s)===key || s.ticker===key || s.gfKey===key) || data.stocks[0]; }
function renderDetail() {
  const stock = state.selectedKey ? findStock(state.selectedKey) : null;
  const body = $("#detailBody");
  if (!body) return;
  if (!stock) {
    $("#detailTitle").textContent = "\uC885\uBAA9\uC744 \uC120\uD0DD\uD558\uC138\uC694";
    body.innerHTML = `<p class="empty-state">\uC885\uBAA9\uC744 \uC120\uD0DD\uD558\uC138\uC694.</p>`;
    return;
  }
  state.selectedKey = tickerKey(stock);
  $("#detailTitle").textContent = stockDisplayLabel(stock);
  const wb = $("#detailWatchButton");
  if (wb) {
    wb.textContent = isWatched(stock) ? "\uAD00\uC2EC \uD574\uC81C" : "\uAD00\uC2EC \uB4F1\uB85D";
    wb.onclick = () => toggleWatch(stock);
  }
  const pos = rangePosition(stock);
  const targetAvg = metricValue(stock, "targetAvg");
  const upside = typeof targetAvg === "number" && typeof stock.price === "number" ? targetAvg / stock.price - 1 : null;
  const coreFilled = ["per", "pbr", "roe"].filter((key) => typeof metricValue(stock, key) === "number").length;
  body.innerHTML = `${refreshStatusCard(stock)}${priceHistoryChart(stock)}${priceChart(stock, pos, targetAvg)}<section class="metric-quality-card"><div><span>Data Quality</span><strong>\uD575\uC2EC \uC9C0\uD45C ${coreFilled}/3</strong></div><p>PER, PBR, ROE\uB294 \uC22B\uC790\uAC00 \uC788\uC73C\uBA74 \uB9C8\uC774\uB108\uC2A4\uB77C\uB3C4 \uCC44\uC6C0\uC73C\uB85C \uBCF4\uBA70, \uC5C6\uB294 \uAC12\uB9CC \uB370\uC774\uD130 \uC5C6\uC74C\uC73C\uB85C \uD45C\uC2DC\uD569\uB2C8\uB2E4.</p></section><div class="metric-grid">${metricCard("\uD604\uC7AC\uAC00", formatMoney(stock.price, stock.currency), "\uB370\uC774\uD130 \uC5C6\uC74C", "price", metricFillStatus(stock, "price"))}${metricCard("1D", pct(stock.d1), "\uB370\uC774\uD130 \uC5C6\uC74C", "d1", metricFillStatus(stock, "d1"))}${metricCard("PER", formatNumber(stock.per, 2), "\uB370\uC774\uD130 \uC5C6\uC74C", "per", metricFillStatus(stock, "per"))}${metricCard("PBR", formatNumber(stock.pbr, 2), "\uB370\uC774\uD130 \uC5C6\uC74C", "pbr", metricFillStatus(stock, "pbr"))}${metricCard("ROE", typeof stock.roe === "number" ? pct(stock.roe / 100) : "-", "\uB370\uC774\uD130 \uC5C6\uC74C", "roe", metricFillStatus(stock, "roe"))}${metricCard("Forward PE", formatNumber(stock.forwardPe, 2), "\uB370\uC774\uD130 \uC5C6\uC74C", "forwardPe", metricFillStatus(stock, "forwardPe"))}${metricCard("\uBAA9\uD45C\uAC00 \uD3C9\uADE0", formatMoney(targetAvg, stock.currency), "\uB370\uC774\uD130 \uC5C6\uC74C", "targetAvg", metricFillStatus(stock, "targetAvg"))}${metricCard("\uBAA9\uD45C\uAC00 \uC5EC\uB825", pct(upside), "\uB370\uC774\uD130 \uC5C6\uC74C")}${metricCard("52\uC8FC \uC704\uCE58", pos === null ? "-" : `${(pos * 100).toFixed(0)}%`, "\uB370\uC774\uD130 \uC5C6\uC74C", "rangePosition", pos === null ? "\uB370\uC774\uD130 \uC5C6\uC74C" : "\uCC44\uC6C0")}</div>${stockNewsCard(stock)}${researchLinks(stock)}`;
  bindStockNewsButtons();
  bindDetailSortCards();
  bindChartControls(stock);
  hydratePriceHistoryFromApi(stock);
  hydrateStockNews(stock);
  hydrateMetricsFromApi(stock);
}
function saveMemo(stock){ const input=$("#memoInput"); const key=tickerKey(stock); if(input?.value) stockMemos[key]=input.value; else delete stockMemos[key]; saveStockMemos(); renderWatchNews(); }

function priceHistoryChart(stock) {
  const period = stock._pricePeriod || "1mo";
  const historyPayload = stock._priceHistory?.[period] || null;
  const history = historyPayload?.items || [];
  const current = history.length ? history[history.length - 1] : null;
  const hover = stock._chartHover || current;
  const periods = [["1d", "1\uC77C"], ["1mo", "1\uAC1C\uC6D4"], ["3mo", "3\uAC1C\uC6D4"], ["6mo", "6\uAC1C\uC6D4"], ["1y", "1\uB144"]];
  const chartMarkup = history.length >= 2
    ? `${historySvg(history, stock)}<div class="history-chart-range-tooltip" data-chart-range-tooltip></div>`
    : `<div class="chart-empty">\uAC00\uACA9 \uC774\uB825\uC744 \uBD88\uB7EC\uC624\uB294 \uC911\uC774\uAC70\uB098 \uC218\uC9D1\uB41C \uB370\uC774\uD130\uAC00 \uC5C6\uC2B5\uB2C8\uB2E4.</div>`;
  return `
    <section class="history-chart-card">
      <div class="history-chart-head">
        <div><span>Price Chart</span><strong>${periodLabel(period)} \uCC28\uD2B8</strong></div>
        <div class="history-chart-actions">${periods.map(([key, label]) => `<button class="${period === key ? "active" : ""}" data-chart-period="${key}" type="button">${label}</button>`).join("")}</div>
      </div>
      <div class="history-chart-hover"><b>${hover?.date || "-"}</b><span>\uC885\uAC00 ${formatMoney(hover?.close, stock.currency)}</span></div>
      <div class="history-chart-body">${chartMarkup}</div>
      ${chartAnalysisCard(history, stock, period)}
      ${historySourceNote(historyPayload)}${historyFoot(history, stock)}
    </section>`;
}

function chartAnalysisCard(items, stock, period) {
  const closes = items.map((item) => item.close).filter((value) => typeof value === "number");
  if (closes.length < 3) return "";
  const first = closes[0];
  const last = closes[closes.length - 1];
  const prev = closes.length > 1 ? closes[closes.length - 2] : null;
  const high = Math.max(...closes);
  const low = Math.min(...closes);
  const change = first ? last / first - 1 : null;
  const highGap = high ? last / high - 1 : null;
  const lowBounce = low ? last / low - 1 : null;
  const recentWindow = closes.slice(-Math.min(6, closes.length));
  const recentFirst = recentWindow[0];
  const recentChange = recentFirst ? last / recentFirst - 1 : null;
  const basisWindow = closes.slice(-Math.min(20, closes.length));
  const avg20 = basisWindow.reduce((a, b) => a + b, 0) / basisWindow.length;
  const avgGap = avg20 ? last / avg20 - 1 : null;
  const support = Math.min(...basisWindow);
  const resistance = Math.max(...basisWindow);
  const supportGap = support ? last / support - 1 : null;
  const resistanceGap = resistance ? last / resistance - 1 : null;
  const dayChange = typeof stock.d1 === "number" ? stock.d1 : prev ? last / prev - 1 : null;
  const monthItems = stock._priceHistory?.["1mo"]?.items || [];
  const monthCloses = monthItems.map((item) => item.close).filter((value) => typeof value === "number");
  const monthChange = typeof stock.m1 === "number" ? stock.m1 : monthCloses.length >= 2 ? monthCloses[monthCloses.length - 1] / monthCloses[0] - 1 : period === "1mo" ? change : null;
  const returns = closes.slice(1).map((value, index) => closes[index] ? Math.abs(value / closes[index] - 1) : 0);
  const volatility = returns.length ? returns.reduce((a, b) => a + b, 0) / returns.length : null;
  const rangePositionValue = high !== low ? (last - low) / (high - low) : null;
  const rangeLabel = rangePositionValue === null ? "\uC704\uCE58 \uBD80\uC871" : rangePositionValue >= 0.75 ? "\uC0C1\uB2E8\uAD8C" : rangePositionValue <= 0.35 ? "\uD558\uB2E8\uAD8C" : "\uC911\uB2E8\uAD8C";
  let toneClass = "neutral";
  let trend = "\uC911\uB9BD\u00B7\uBC15\uC2A4\uAD8C";
  let summary = "\uB2E8\uAE30 \uBC29\uD5A5\uC131\uC774 \uD06C\uAC8C \uC6B0\uC138\uD558\uC9C0 \uC54A\uC544, \uC9C0\uC9C0\uC120\uACFC \uC800\uD56D\uC120 \uC774\uD0C8 \uC5EC\uBD80\uB97C \uAC19\uC774 \uBCF4\uB294 \uAD6C\uAC04\uC785\uB2C8\uB2E4.";
  if ((recentChange ?? 0) > 0.015 && (avgGap ?? 0) > 0) {
    toneClass = "positive";
    trend = "\uC0C1\uC2B9 \uC6B0\uC704";
    summary = "\uCD5C\uADFC \uD750\uB984\uC774 20\uAC1C \uD3C9\uADE0 \uC704\uC5D0\uC11C \uC720\uC9C0\uB418\uACE0 \uC788\uC5B4 \uB2E8\uAE30 \uBAA8\uBA58\uD140\uC740 \uC6B0\uD638\uC801\uC785\uB2C8\uB2E4.";
  } else if ((recentChange ?? 0) < -0.015 && (avgGap ?? 0) < 0) {
    toneClass = "negative";
    trend = "\uC57D\uC138 \uC8FC\uC758";
    summary = "\uCD5C\uADFC \uD750\uB984\uC774 20\uAC1C \uD3C9\uADE0 \uC544\uB798\uB85C \uAE30\uC6B0\uB294 \uBAA8\uC591\uC774\uB77C \uCD94\uAC00 \uC774\uD0C8 \uC5EC\uBD80\uB97C \uC8FC\uC758\uD574\uC57C \uD569\uB2C8\uB2E4.";
  } else if ((lowBounce ?? 0) > 0.04 && (recentChange ?? 0) > 0) {
    toneClass = "positive";
    trend = "\uBC18\uB4F1 \uC2DC\uB3C4";
    summary = "\uAE30\uAC04 \uC800\uC810\uC5D0\uC11C \uBC18\uB4F1\uC774 \uB098\uC624\uACE0 \uC788\uC9C0\uB9CC, \uC800\uD56D\uC120 \uB3CC\uD30C \uC5EC\uBD80\uAC00 \uD544\uC694\uD55C \uAD6C\uAC04\uC785\uB2C8\uB2E4.";
  } else if ((highGap ?? 0) < -0.08) {
    toneClass = "negative";
    trend = "\uACE0\uC810 \uD558\uB77D\uAD8C";
    summary = "\uCD5C\uADFC \uACE0\uC810\uB300\uBE44 \uC544\uB798\uC5D0 \uC788\uC5B4 \uCD94\uC138 \uD68C\uBCF5\uC774 \uD655\uC778\uB418\uAE30 \uC804\uAE4C\uC9C0\uB294 \uC8FC\uC758\uAC00 \uD544\uC694\uD569\uB2C8\uB2E4.";
  }
  const volLabel = (volatility ?? 0) > 0.035 ? "\uBCC0\uB3D9\uC131 \uD07C" : (volatility ?? 0) > 0.018 ? "\uBCC0\uB3D9\uC131 \uBCF4\uD1B5" : "\uBCC0\uB3D9\uC131 \uB0AE\uC74C";
  const oneMonthLabel = typeof monthChange === "number" ? pct(monthChange) : "\uB370\uC774\uD130 \uC5C6\uC74C";
  return `<section class="chart-analysis-card chart-${toneClass}">
    <div class="chart-analysis-head"><div><span>\uCC28\uD2B8\uBD84\uC11D\uD615</span><strong>${trend}</strong></div><em>${periodLabel(period)} \uAE30\uC900</em></div>
    <p>${summary}</p>
    <div class="chart-analysis-grid">
      <article><span>\uB2E8\uAE30 \uCD94\uC138</span><strong>${trend}</strong><small>20\uAC1C \uD3C9\uADE0 \uB300\uBE44 ${pct(avgGap)}</small></article>
      <article><span>\uC9C0\uC9C0\uC120</span><strong>${formatMoney(support, stock.currency)}</strong><small>\uD604\uC7AC\uAC00\uB294 \uC9C0\uC9C0\uC120 \uB300\uBE44 ${pct(supportGap)}</small></article>
      <article><span>\uC800\uD56D\uC120</span><strong>${formatMoney(resistance, stock.currency)}</strong><small>\uC800\uD56D\uC120\uAE4C\uC9C0 ${pct(resistanceGap)}</small></article>
      <article><span>\uACE0\uC810 \uB300\uBE44</span><strong>${rangeLabel}</strong><small>\uAE30\uAC04 \uACE0\uC810 \uB300\uBE44 ${pct(highGap)}</small></article>
    </div>
    <div class="chart-analysis-pills"><span>1D ${pct(dayChange)}</span><span>1M ${oneMonthLabel}</span><span>\uAE30\uAC04 ${pct(change)}</span><span>${volLabel}</span></div>
    <small>\uC571\uC5D0 \uC800\uC7A5\uB41C \uAC00\uACA9 \uC774\uB825\uB9CC \uAE30\uC900\uC73C\uB85C \uBCF8 \uCC28\uD2B8 \uD574\uC11D\uC785\uB2C8\uB2E4. \uB9E4\uC218\u00B7\uB9E4\uB3C4 \uC9C0\uC2DC\uAC00 \uC544\uB2D9\uB2C8\uB2E4.</small>
  </section>`;
}
function fallbackHistory(stock, period) {
  if (typeof stock.price !== "number") return [];
  const count = { "1d": 24, "1mo": 22, "3mo": 66, "6mo": 126, "1y": 252 }[period] || 252;
  const startBase = typeof stock.ytd === "number" ? stock.price / Math.max(0.1, 1 + stock.ytd) : stock.price * 0.85;
  const items = [];
  const today = new Date();
  for (let i = 0; i < count; i += 1) {
    const ratio = count === 1 ? 1 : i / (count - 1);
    const wave = Math.sin(ratio * Math.PI * 4) * 0.035 + Math.sin(ratio * Math.PI * 9) * 0.018;
    const close = startBase + (stock.price - startBase) * ratio + stock.price * wave;
    const date = new Date(today);
    date.setDate(today.getDate() - (count - i));
    items.push({ date: date.toISOString().slice(0, 10), close: Math.max(0.01, close), volume: null });
  }
  return items;
}

function periodLabel(period) { return { "1d": "1\uC77C", "1mo": "1\uAC1C\uC6D4", "3mo": "3\uAC1C\uC6D4", "6mo": "6\uAC1C\uC6D4", "1y": "1\uB144" }[period] || period; }
function historySourceNote(payload) {
  if (!payload) return `<div class="history-source-note loading">\uc2e4\uc81c \uac00\uaca9 \uc774\ub825\uc744 \ubd88\ub7ec\uc624\ub294 \uc911\uc785\ub2c8\ub2e4.</div>`;
  if (payload.source === "local_chart_fallback") return `<div class="history-source-note warning">\uc2e4\uc81c \uac00\uaca9 \uc774\ub825\uc774 \uc5c6\uc5b4 \ucc28\ud2b8\ub97c \ud45c\uc2dc\ud558\uc9c0 \uc54a\uc2b5\ub2c8\ub2e4.</div>`;
  return `<div class="history-source-note">\uc2e4\uc81c \uac00\uaca9 \uc774\ub825: ${escapeHtml(payload.source || "cache")}</div>`;
}

function historySvg(items, stock) {
  const width = 920, height = 270;
  const pad = { top: 20, right: 58, bottom: 34, left: 58 };
  const closes = items.map((item) => item.close).filter((value) => typeof value === "number");
  const min = Math.min(...closes), max = Math.max(...closes);
  const span = max === min ? 1 : max - min;
  const xOf = (idx) => pad.left + (idx / Math.max(1, items.length - 1)) * (width - pad.left - pad.right);
  const yOf = (value) => pad.top + (1 - (value - min) / span) * (height - pad.top - pad.bottom);
  const points = items.map((item, idx) => `${xOf(idx).toFixed(1)},${yOf(item.close).toFixed(1)}`).join(" ");
  const area = `${pad.left},${height - pad.bottom} ${points} ${width - pad.right},${height - pad.bottom}`;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
    const value = min + span * (1 - ratio);
    const y = pad.top + ratio * (height - pad.top - pad.bottom);
    return `<line class="history-chart-grid" x1="${pad.left}" x2="${width - pad.right}" y1="${y}" y2="${y}"></line><text class="history-chart-axis" x="${width - pad.right + 8}" y="${y + 4}">${formatNumber(value, 2)}</text>`;
  }).join("");
  const dateLabels = [0, Math.floor((items.length - 1) / 2), items.length - 1].map((idx) => `<text class="history-chart-axis" x="${xOf(idx)}" y="${height - 10}" text-anchor="middle">${items[idx].date}</text>`).join("");
  const pointData = JSON.stringify(items.map((item, idx) => ({ date: item.date, close: item.close, volume: item.volume, x: xOf(idx), y: yOf(item.close) })));
  return `<svg class="history-chart-svg" viewBox="0 0 ${width} ${height}" data-chart-svg="1" data-points='${escapeHtml(pointData)}'>${ticks}<polygon class="history-chart-area" points="${area}"></polygon><polyline class="history-chart-line" points="${points}"></polyline><line class="history-crosshair-x" x1="0" x2="0" y1="${pad.top}" y2="${height - pad.bottom}"></line><line class="history-crosshair-y" x1="${pad.left}" x2="${width - pad.right}" y1="0" y2="0"></line><circle class="history-chart-dot" cx="0" cy="0" r="4"></circle><line class="history-range-line start" x1="0" x2="0" y1="${pad.top}" y2="${height - pad.bottom}"></line><line class="history-range-line end" x1="0" x2="0" y1="${pad.top}" y2="${height - pad.bottom}"></line><circle class="history-range-dot start" cx="0" cy="0" r="5"></circle><circle class="history-range-dot end" cx="0" cy="0" r="5"></circle>${dateLabels}</svg>`;
}

function historyFoot(items, stock) {
  if (!items.length) return "";
  const closes = items.map((item) => item.close).filter((value) => typeof value === "number");
  const first = closes[0], last = closes[closes.length - 1], min = Math.min(...closes), max = Math.max(...closes);
  const change = first ? last / first - 1 : null;
  return `<div class="history-chart-foot"><span>\uae30\uac04 \uc218\uc775\ub960 <b class="${signedClass(change)}">${pct(change)}</b></span><span>\uc800\uc810 <b>${formatMoney(min, stock.currency)}</b></span><span>\uace0\uc810 <b>${formatMoney(max, stock.currency)}</b></span><span>\ucd5c\uadfc \uc885\uac00 <b>${formatMoney(last, stock.currency)}</b></span></div>`;
}

async function hydratePriceHistoryFromApi(stock) {
  if (!state.apiOnline) return;
  const ticker = stock.ticker || stock.gfKey;
  const period = stock._pricePeriod || "1mo";
  if (!ticker) return;
  stock._priceHistory = stock._priceHistory || {};
  stock._priceHistoryLoading = stock._priceHistoryLoading || {};
  if (stock._priceHistory[period]?.items?.length || stock._priceHistoryLoading[period]) return;
  stock._priceHistoryLoading[period] = true;
  try {
    const res = await fetch(`http://127.0.0.1:8787/api/stocks/${encodeURIComponent(ticker)}/prices?period=${encodeURIComponent(period)}&t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) return;
    const payload = await res.json();
    stock._priceHistory[period] = payload.source === "local_chart_fallback" ? { ...payload, items: [] } : payload;
    stock._chartHover = payload.items?.[payload.items.length - 1] || null;
    if (state.selectedKey === tickerKey(stock)) renderDetail();
  } catch {}
  finally { stock._priceHistoryLoading[period] = false; }
}

function bindChartControls(stock) {
  document.querySelectorAll("[data-chart-period]").forEach((button) => {
    button.addEventListener("click", () => {
      stock._pricePeriod = button.dataset.chartPeriod;
      stock._chartHover = null;
      stock._chartRange = null;
      renderDetail();
      hydratePriceHistoryFromApi(stock);
    });
  });
  const svg = document.querySelector("[data-chart-svg]");
  if (!svg) return;
  let points = [];
  try { points = JSON.parse(svg.dataset.points || "[]"); } catch { points = []; }
  const crossX = svg.querySelector(".history-crosshair-x");
  const crossY = svg.querySelector(".history-crosshair-y");
  const dot = svg.querySelector(".history-chart-dot");
  const rangeStartLine = svg.querySelector(".history-range-line.start");
  const rangeEndLine = svg.querySelector(".history-range-line.end");
  const rangeStartDot = svg.querySelector(".history-range-dot.start");
  const rangeEndDot = svg.querySelector(".history-range-dot.end");
  const tooltip = document.querySelector("[data-chart-range-tooltip]");

  const nearestFromEvent = (event) => {
    const rect = svg.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * 920;
    return points.reduce((best, item) => Math.abs(item.x - x) < Math.abs(best.x - x) ? item : best, points[0]);
  };
  const setCrosshair = (point) => {
    crossX.setAttribute("x1", point.x); crossX.setAttribute("x2", point.x);
    crossY.setAttribute("y1", point.y); crossY.setAttribute("y2", point.y);
    dot.setAttribute("cx", point.x); dot.setAttribute("cy", point.y);
    crossX.classList.add("active"); crossY.classList.add("active"); dot.classList.add("active");
  };
  const updateRangeMarker = (line, marker, point) => {
    if (!line || !marker || !point) return;
    line.setAttribute("x1", point.x); line.setAttribute("x2", point.x);
    marker.setAttribute("cx", point.x); marker.setAttribute("cy", point.y);
    line.classList.add("active"); marker.classList.add("active");
  };
  const clearRangeMarker = (line, marker) => {
    line?.classList.remove("active"); marker?.classList.remove("active");
  };
  const orderedRange = (a, b) => a.x <= b.x ? [a, b] : [b, a];
  const showRangeTooltip = (event, start, end, fixed = false) => {
    if (!tooltip || !start) return;
    const body = document.querySelector(".history-chart-body");
    const rect = body.getBoundingClientRect();
    const left = Math.max(10, Math.min(rect.width - 230, event.clientX - rect.left + 14));
    const top = Math.max(10, Math.min(rect.height - 88, event.clientY - rect.top + 12));
    tooltip.style.left = `${left}px`;
    tooltip.style.top = `${top}px`;
    tooltip.classList.add("active");
    if (!end) {
      tooltip.innerHTML = `<b>시작점 선택</b><span>${escapeHtml(start.date)} · ${formatMoney(start.close, stock.currency)}</span><em>다음 지점을 클릭하세요</em>`;
      return;
    }
    const [from, to] = orderedRange(start, end);
    const change = from.close ? to.close / from.close - 1 : null;
    const diff = typeof from.close === "number" && typeof to.close === "number" ? to.close - from.close : null;
    tooltip.innerHTML = `<b class="${signedClass(change)}">${pct(change)}</b><span>${escapeHtml(from.date)} → ${escapeHtml(to.date)}</span><em>${formatMoney(from.close, stock.currency)} → ${formatMoney(to.close, stock.currency)} · ${formatMoney(diff, stock.currency)}</em>${fixed ? "<small>다시 클릭하면 새 시작점</small>" : ""}`;
  };
  const syncRange = (event, hoverPoint = null) => {
    const range = stock._chartRange;
    if (!range?.start) {
      clearRangeMarker(rangeStartLine, rangeStartDot);
      clearRangeMarker(rangeEndLine, rangeEndDot);
      tooltip?.classList.remove("active");
      return;
    }
    updateRangeMarker(rangeStartLine, rangeStartDot, range.start);
    const end = range.end || hoverPoint;
    if (end) updateRangeMarker(rangeEndLine, rangeEndDot, end);
    else clearRangeMarker(rangeEndLine, rangeEndDot);
    if (event) showRangeTooltip(event, range.start, end, Boolean(range.end));
  };

  svg.addEventListener("mousemove", (event) => {
    if (!points.length) return;
    const nearest = nearestFromEvent(event);
    stock._chartHover = { date: nearest.date, close: nearest.close, volume: nearest.volume };
    setCrosshair(nearest);
    const hover = document.querySelector(".history-chart-hover");
    if (hover) hover.innerHTML = `<b>${escapeHtml(nearest.date)}</b><span>종가 ${formatMoney(nearest.close, stock.currency)}</span>`;
    syncRange(event, nearest);
  });
  svg.addEventListener("click", (event) => {
    if (!points.length) return;
    const nearest = nearestFromEvent(event);
    if (!stock._chartRange?.start || stock._chartRange?.end) stock._chartRange = { start: nearest, end: null };
    else stock._chartRange.end = nearest;
    syncRange(event, nearest);
  });
  svg.addEventListener("mouseleave", () => {
    crossX.classList.remove("active"); crossY.classList.remove("active"); dot.classList.remove("active");
  });
}

function metricCoverageNeedsRefresh(stock) {
  return typeof stock.price !== "number" ||
    typeof stock.per !== "number" ||
    typeof stock.pbr !== "number" ||
    typeof stock.roe !== "number" ||
    typeof stock.forwardPe !== "number" ||
    typeof metricValue(stock, "targetAvg") !== "number";
}

function refreshCoverageViews() {
  const stocks = filteredStocks();
  renderMetricCoverage(stocks);
  renderRows(stocks);
  renderKpis(stocks);
}
async function hydrateVisibleMetrics(stocks){ if(!state.apiOnline) return; const targets=stocks.filter(s=>!s._metricsHydrated).slice(0,8); await Promise.all(targets.map(s=>hydrateMetricsFromApi(s))); }
function updateMetricsRefreshStatus(message){ const el=$("#metricsRefreshStatus"); if(el) el.textContent=message; }
async function refreshWatchMetrics() {
  const allTargets = data.stocks.filter((s) => s.status === LISTED && (s.ticker || s.gfKey));
  const missing = allTargets.filter(metricCoverageNeedsRefresh);
  const filled = allTargets.filter((s) => !metricCoverageNeedsRefresh(s));
  const targets = [...missing, ...filled];
  const batchSize = 8;
  updateMetricsRefreshStatus(`0/${targets.length} 전체 갱신 준비`);
  for (let i = 0; i < targets.length; i += batchSize) {
    const batch = targets.slice(i, i + batchSize);
    updateMetricsRefreshStatus(`${i + 1}-${Math.min(i + batchSize, targets.length)}/${targets.length} 전체 갱신 중`);
    await Promise.all(batch.map((s) => hydrateMetricsFromApi(s, { force: metricCoverageNeedsRefresh(s), quiet: true })));
    refreshCoverageViews();
  }
  updateMetricsRefreshStatus(`완료 · 미채움 ${data.stocks.filter((s) => s.status === LISTED && metricCoverageNeedsRefresh(s)).length}/${allTargets.length}`);
  renderDetail();
}

function setRefreshStatus(stock,stateName,message,steps=[]){ stock._refreshStatus={state:stateName,message,steps}; if(state.selectedKey===tickerKey(stock)) renderDetail(); }
function refreshStatusCard(stock){ const s=stock._refreshStatus; if(!s) return ""; return `<section class="refresh-status-card ${s.state||"idle"}"><div><span>Data Refresh</span><strong>${escapeHtml(s.message||"")}</strong></div><div class="refresh-steps">${(s.steps||[]).map(step=>`<span class="${step.state}">${escapeHtml(step.label)}</span>`).join("")}</div></section>`; }
function priceChart(stock, pos, targetAvg) {
  const hasRange = typeof pos === "number";
  const currentX = hasRange ? pos * 100 : 50;
  let targetX = null;
  if (typeof targetAvg === "number" && typeof stock.low52 === "number" && typeof stock.high52 === "number" && stock.high52 !== stock.low52) {
    targetX = Math.max(0, Math.min(100, ((targetAvg - stock.low52) / (stock.high52 - stock.low52)) * 100));
  }
  return `<section class="price-chart-card"><div class="price-chart-head"><div><span>Price Range</span><strong>${formatMoney(stock.price, stock.currency)}</strong></div><div class="small-muted">52\uc8fc \ubc94\uc704\uc640 \ubaa9\ud45c\uac00 \uc704\uce58</div></div><div class="price-track"><div class="price-band"></div>${hasRange ? `<b class="price-marker current" style="left:${currentX}%"></b>` : ""}${targetX !== null ? `<b class="price-marker target" style="left:${targetX}%"></b>` : ""}</div><div class="price-chart-labels"><span>\uc800\uac00 ${formatMoney(stock.low52, stock.currency)}</span><span>\ud604\uc7ac\uac00</span><span>\ubaa9\ud45c\uac00 ${formatMoney(targetAvg, stock.currency)}</span><span>\uace0\uac00 ${formatMoney(stock.high52, stock.currency)}</span></div></section>`;
}

async function hydrateMetricsFromApi(stock, options = {}) {
  const force = Boolean(options.force);
  if (!state.apiOnline || (stock._metricsHydrated && !force)) return;
  const ticker = stock.ticker || stock.gfKey;
  if (!ticker) return;
  stock._metricsHydrated = true;
  try {
    const refreshParam = force ? "?refresh=1" : "";
    const res = await fetch(`http://127.0.0.1:8787/api/stocks/${encodeURIComponent(ticker)}/metrics${refreshParam}`, {
      cache: "no-store",
    });
    if (!res.ok) return;
    const payload = await res.json();
    const metrics = payload.metrics || {};
    if (typeof metrics.price === "number") stock.price = metrics.price;
    if (typeof metrics.per === "number") stock.per = metrics.per;
    if (typeof metrics.pbr === "number") stock.pbr = metrics.pbr;
    if (typeof metrics.roe === "number") stock.roe = metrics.roe;
    if (typeof metrics.forward_pe === "number") stock.forwardPe = metrics.forward_pe;
    if (typeof metrics.target_price_avg === "number") stock.targetPriceAvg = metrics.target_price_avg;
    if (typeof metrics.high52 === "number") stock.high52 = metrics.high52;
    if (typeof metrics.low52 === "number") stock.low52 = metrics.low52;
    if (typeof metrics.d1 === "number") stock.d1 = metrics.d1;
    if (typeof metrics.m1 === "number") stock.m1 = metrics.m1;
    if (typeof metrics.ytd === "number") stock.ytd = metrics.ytd;
    stock._metricsSource = metrics.source || payload.stock?.source || "API";
    stock._metricsCollectedAt = metrics.collected_at || null;
    stock._metricsMissing = ["PBR", "ROE", "Forward PE", "\ubaa9\ud45c\uac00"].filter((label) => {
      if (label === "PBR") return typeof stock.pbr !== "number";
      if (label === "ROE") return typeof stock.roe !== "number";
      if (label === "Forward PE") return typeof stock.forwardPe !== "number";
      return typeof stock.targetPriceAvg !== "number" && typeof stock.targetPrice !== "number";
    });
    buildQuantScores();
    renderRows(filteredStocks());
    if (state.selectedKey === tickerKey(stock)) renderDetail();
  } catch {
    // Missing external metrics should never break the dashboard.
  }
}


function multiAgentInsightCard(stock, pos, upside, coreFilled) {
  const news = stock._stockNewsSummary || null;
  const missing = [
    ["PER", stock.per],
    ["PBR", stock.pbr],
    ["ROE", stock.roe],
    ["Forward PE", stock.forwardPe],
    ["목표가", metricValue(stock, "targetAvg")],
  ].filter(([, value]) => typeof value !== "number").map(([label]) => label);
  const bull = [];
  const bear = [];
  const risks = [];
  const checks = [];

  if (typeof stock.roe === "number") {
    if (stock.roe >= 15) bull.push(`ROE ${formatNumber(stock.roe, 1)}%로 수익성 지표가 우호적입니다.`);
    else if (stock.roe < 0) { bear.push(`ROE ${formatNumber(stock.roe, 1)}%로 수익성이 마이너스입니다.`); risks.push("ROE가 음수라 이익 안정성 확인이 필요합니다."); }
  } else checks.push("ROE 데이터 확인");

  if (typeof stock.per === "number") {
    if (stock.per > 80) { bear.push(`PER ${formatNumber(stock.per, 1)}배로 밸류 부담이 큽니다.`); risks.push("고PER 종목은 실적 기대가 흔들릴 때 변동성이 커질 수 있습니다."); }
    else if (stock.per > 0 && stock.per <= 25) bull.push(`PER ${formatNumber(stock.per, 1)}배로 과도한 부담은 제한적입니다.`);
  } else checks.push("PER 데이터 확인");

  if (typeof stock.pbr === "number") {
    if (stock.pbr > 10) bear.push(`PBR ${formatNumber(stock.pbr, 1)}배로 자산가치 대비 프리미엄이 높습니다.`);
    else if (stock.pbr > 0 && stock.pbr <= 3) bull.push(`PBR ${formatNumber(stock.pbr, 1)}배로 자산가치 부담은 비교적 낮습니다.`);
  } else checks.push("PBR 데이터 확인");

  if (typeof upside === "number") {
    if (upside >= 0.15) bull.push(`목표가 여력이 ${pct(upside)}로 남아 있습니다.`);
    else if (upside < 0) bear.push(`현재가가 목표가 평균보다 높아 목표가 여력은 제한적입니다.`);
  } else checks.push("목표가 평균 확인");

  if (typeof stock.d1 === "number") {
    if (stock.d1 >= 0.04) bull.push(`1D ${pct(stock.d1)}로 단기 모멘텀이 강합니다.`);
    else if (stock.d1 <= -0.04) bear.push(`1D ${pct(stock.d1)}로 단기 하락 압력이 있습니다.`);
  }
  if (typeof stock.ytd === "number") {
    if (stock.ytd >= 0.2) bull.push(`YTD ${pct(stock.ytd)}로 중기 추세가 강합니다.`);
    else if (stock.ytd <= -0.2) bear.push(`YTD ${pct(stock.ytd)}로 중기 흐름이 약합니다.`);
  }
  if (typeof pos === "number") {
    if (pos >= 0.9) risks.push("52주 고점권에 가까워 추격 진입 리스크가 있습니다.");
    else if (pos <= 0.2) risks.push("52주 저점권이라 반등 전환 확인이 필요합니다.");
  }

  if (news?.sentiment === "positive") bull.push("최근 뉴스 흐름은 긍정 쪽으로 분류됩니다.");
  if (news?.sentiment === "negative") { bear.push("최근 뉴스 흐름은 부정 쪽으로 분류됩니다."); risks.push("뉴스 이벤트 영향이 가격에 반영되는지 확인해야 합니다."); }
  if (!news || news.source === "empty") checks.push("최근 2일 뉴스 없음 또는 수집 대기");

  if (missing.length >= 3) risks.push(`핵심 지표 누락이 많습니다: ${missing.slice(0, 4).join(", ")}`);
  if (!bull.length) bull.push("명확한 강세 근거가 부족합니다. 추가 데이터 확인이 필요합니다.");
  if (!bear.length) bear.push("뚜렷한 약세 근거는 제한적입니다.");
  if (!risks.length) risks.push("큰 경고 신호는 제한적이지만 실적/뉴스 이벤트는 계속 확인하세요.");
  if (!checks.length) checks.push("최근 차트 고점·저점 확인", "실적 발표 일정 확인", "뉴스 원문 확인");

  const score = bull.length - bear.length - Math.max(0, risks.length - 1) - Math.max(0, 3 - coreFilled);
  const verdict = score >= 3 ? "우호적" : score >= 1 ? "중립 우호" : score <= -3 ? "고위험" : score <= -1 ? "주의" : "중립";
  const tone = verdict === "우호적" || verdict === "중립 우호" ? "positive" : verdict === "주의" || verdict === "고위험" ? "negative" : "neutral";
  const confidence = coreFilled >= 3 && missing.length <= 1 ? "보통 이상" : coreFilled >= 2 ? "보통" : "낮음";

  const agentCards = [
    ["펀더멘털", coreFilled >= 2 ? "분석 가능" : "보류", coreFilled >= 2 ? `핵심 지표 ${coreFilled}/3개 채움` : `핵심 지표 ${coreFilled}/3개만 채움`],
    ["차트", typeof stock.d1 === "number" || typeof stock.ytd === "number" ? "확인 가능" : "보류", `1D ${pct(stock.d1)} · YTD ${pct(stock.ytd)}`],
    ["뉴스·매크로", news ? sentimentLabel(news.sentiment) : "대기", news?.headline || "최근 뉴스 요약 대기"],
    ["리스크", risks.length >= 3 ? "주의" : "점검", risks[0]],
  ];

  return `<section class="multi-agent-card"><div class="coverage-head"><strong>멀티 관점 분석</strong><span class="verdict-pill ${tone}">${verdict}</span></div><p>TradingAgents 구조를 가볍게 적용한 규칙 기반 점검입니다. 매수·매도 추천이 아니라 확인용 리포트입니다.</p><div class="agent-card-grid">${agentCards.map(([title, status, body]) => `<article><span>${escapeHtml(title)}</span><strong>${escapeHtml(status)}</strong><p>${escapeHtml(body)}</p></article>`).join("")}</div><div class="debate-grid"><div><strong>강세 근거</strong>${bull.slice(0, 4).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div><div><strong>약세 근거</strong>${bear.slice(0, 4).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div><div><strong>리스크 매니저</strong>${risks.slice(0, 4).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div><div><strong>체크리스트</strong>${checks.slice(0, 4).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div></div><div class="portfolio-verdict"><strong>최종 점검</strong><span>${verdict}</span><em>판단 신뢰도: ${confidence}</em></div></section>`;
}
function stockNewsCard(stock) {
  const ticker = stock.ticker || stock.gfKey;
  const summary = stock._stockNewsSummary;
  if (stock._stockNewsLoading) {
    return `<section class="detail-news-card"><div class="coverage-head"><strong>AI \uc885\ubaa9 \ub274\uc2a4 \uc694\uc57d</strong><span>\ubd84\uc11d \uc911</span></div><p class="empty-state">\ucd5c\uadfc \ub274\uc2a4\ub97c \ubd88\ub7ec\uc640 AI\uac00 \ud575\uc2ec\ub9cc \uc815\ub9ac\ud558\ub294 \uc911\uc785\ub2c8\ub2e4.</p></section>`;
  }
  if (!summary) {
    return `<section class="detail-news-card"><div class="coverage-head"><strong>AI \uc885\ubaa9 \ub274\uc2a4 \uc694\uc57d</strong><span>${escapeHtml(ticker || "")}</span></div><p class="empty-state">\uc544\uc9c1 \ub274\uc2a4 \uc694\uc57d\uc774 \uc5c6\uc2b5\ub2c8\ub2e4.</p><button class="ghost-button" data-stock-news-refresh="${escapeHtml(ticker || "")}" type="button">AI \ub274\uc2a4 \uc694\uc57d</button></section>`;
  }
  const articles = summary.articles || [];
  const sentimentLabel = { positive: "\uae0d\uc815", negative: "\ubd80\uc815", neutral: "\uc911\ub9bd", mixed: "\ud63c\uc7ac" }[summary.sentiment] || "\uc911\ub9bd";
  return `<section class="detail-news-card ai-news-summary"><div class="coverage-head"><strong>AI \uc885\ubaa9 \ub274\uc2a4 \uc694\uc57d</strong><span>${sentimentLabel} · ${escapeHtml(summary.source || "AI")}</span></div><h3>${escapeHtml(summary.headline || "\ub370\uc774\ud130 \ubd80\uc871")}</h3><p>${escapeHtml(summary.reason || "")}</p><div class="ai-news-columns"><div><strong>\ud575\uc2ec \uc774\uc288</strong>${(summary.key_issues || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div><div><strong>\ud655\uc778\ud560 \uc810</strong>${(summary.watch_points || []).map((item) => `<span>${escapeHtml(item)}</span>`).join("")}</div></div>${articles.length ? `<div class="ai-news-links"><strong>\uc6d0\ubb38</strong>${articles.slice(0, 5).map((item) => `<a href="${escapeHtml(item.url || "#")}" target="_blank" rel="noreferrer">${escapeHtml(item.publisher || "News")} · ${escapeHtml(item.title || "\uae30\uc0ac")}</a>`).join("")}</div>` : ""}<button class="ghost-button" data-stock-news-refresh="${escapeHtml(ticker || "")}" type="button">\ub2e4\uc2dc \uc694\uc57d</button></section>`;
}

async function hydrateStockNews(stock, force = false) {
  if (!state.apiOnline || !stock) return;
  const ticker = stock.ticker || stock.gfKey;
  if (!ticker) return;
  if (stock._stockNewsLoading || (!force && stock._stockNewsLoaded)) return;
  stock._stockNewsLoading = true;
  if (state.selectedKey === tickerKey(stock)) renderDetail();
  try {
    const res = await fetch(`http://127.0.0.1:8787/api/stocks/${encodeURIComponent(ticker)}/news-summary?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error("news summary api failed");
    const payload = await res.json();
    stock._stockNewsSummary = payload.summary;
    stock._stockNewsLoaded = true;
  } catch {
    stock._stockNewsSummary = null;
    stock._stockNewsLoaded = true;
  } finally {
    stock._stockNewsLoading = false;
    if (state.selectedKey === tickerKey(stock)) renderDetail();
  }
}

function bindStockNewsButtons() {
  document.querySelectorAll("[data-stock-news-refresh]").forEach((button) => {
    button.addEventListener("click", () => {
      const stock = findStock(state.selectedKey || button.dataset.stockNewsRefresh);
      if (stock) hydrateStockNews(stock, true);
    });
  });
}


function researchLinks(stock) {
  const ticker = stock.ticker || stock.gfKey || stock.nameKr;
  const name = stock.nameEn || stock.nameKr || ticker;
  const query = encodeURIComponent(`${name} ${ticker} analyst report target price PDF`);
  const koreanQuery = encodeURIComponent(`${stock.nameKr || name} ${ticker} \uc99d\uad8c\uc0ac \ub9ac\ud3ec\ud2b8 \ubaa9\ud45c\uac00`);
  const yahooSymbol = encodeURIComponent(ticker);
  const links = [
    ["\uc560\ub110\ub9ac\uc2a4\ud2b8 \ub9ac\ud3ec\ud2b8", `https://www.google.com/search?q=${query}`],
    ["\uad6d\ub0b4 \ub9ac\ud3ec\ud2b8", `https://www.google.com/search?q=${koreanQuery}`],
    ["Yahoo Analysis", `https://finance.yahoo.com/quote/${yahooSymbol}/analysis`],
    ["SEC \uacf5\uc2dc", `https://www.sec.gov/edgar/search/#/q=${encodeURIComponent(ticker)}`],
  ];
  return `<section class="research-links-card"><div><span>Research Links</span><strong>\ub9ac\ud3ec\ud2b8\u00b7\uacf5\uc2dc \ub9c1\ud06c</strong></div><div class="research-links">${links.map(([label, url]) => `<a href="${url}" target="_blank" rel="noreferrer">${label}</a>`).join("")}</div></section>`;
}
function metricCard(label, value, emptyReason = "", sortKey = "", status = "") {
  const reason = value === "-" && emptyReason ? `<em>${emptyReason}</em>` : "";
  const statusText = status ? `<small>${escapeHtml(status)}</small>` : "";
  return `<div class="mini-metric"><span>${label}</span><strong>${value}</strong>${reason}${statusText}</div>`;
}

function metricFillStatus(stock, key) {
  const value = metricValue(stock, key);
  if (typeof value === "number") return value < 0 ? "\ucc44\uc6c0\u00b7\uc74c\uc218" : "\ucc44\uc6c0";
  return stock._metricsSource ? "\ub370\uc774\ud130 \uc5c6\uc74c" : "\ud655\uc778 \uc804";
}

function bindDetailSortCards() {}

function sortStatusText() {
  const labels = {
    d1: "1D \ub4f1\ub77d\ub960",
    ytd: "YTD \ub4f1\ub77d\ub960",
    price: "\ud604\uc7ac\uac00",
    per: "PER",
    pbr: "PBR",
    roe: "ROE",
    forwardPe: "Forward PE",
    targetAvg: "\ubaa9\ud45c\uac00 \ud3c9\uade0",
    rangePosition: "52\uc8fc \uc704\uce58",
  };
  return `\uc885\ubaa9 \ubaa9\ub85d \uc815\ub82c \uae30\uc900: ${labels[state.sort] || state.sort}`;
}

function updateSortStatus() {
  const status = $("#detailSortStatus");
  if (status) status.textContent = sortStatusText();
  document.querySelectorAll("[data-table-sort]").forEach((button) => {
    button.classList.toggle("active", button.dataset.tableSort === state.sort);
  });
}

function setTableSort(sortKey) {
  state.sort = sortKey;
  renderRows(filteredStocks());
}

function factorBar(label, value) {
  const width = Math.max(0, Math.min(100, value || 0));
  return `
    <div class="factor-row">
      <span>${label}</span>
      <div class="factor-track"><b style="width:${width}%"></b></div>
      <strong>${formatNumber(value, 1)}</strong>
    </div>
  `;
}

function newsForStock(stock) {
  const query = encodeURIComponent(`${stockPrimaryName(stock)} ${stock.ticker || ""} 최신 뉴스`);
  const naverQuery = encodeURIComponent(`${stockPrimaryName(stock)} ${stock.ticker || ""}`);
  return {
    title: `${stockPrimaryName(stock)} 최신 뉴스 검색`,
    publisher: stock.ticker || stock.gfKey || marketOf(stock),
    url: `https://www.google.com/search?tbm=nws&q=${query}`,
    naverUrl: `https://search.naver.com/search.naver?where=news&query=${naverQuery}`,
    summary: stockMemos[tickerKey(stock)] || "\uc9c1\uc811 \uc791\uc131\ud55c \uba54\ubaa8\uac00 \uc5c6\uc2b5\ub2c8\ub2e4.",
    related_tickers: [stock.ticker || stock.gfKey || stock.nameKr],
    sentiment: stockMemos[tickerKey(stock)] ? "neutral" : "neutral",
    tags: stockMemos[tickerKey(stock)] ? ["\ub0b4 \uba54\ubaa8"] : ["\uc77c\ubc18"],
  };
}

function renderNewsItem(item) {
  const sentiment = effectiveSentiment(item);
  const tags = item.tags?.length ? item.tags : ["일반"];
  const labels = relatedTickerLabels(item, 10);
  const dateLabel = formatNewsDate(item.published_at || item.created_at);
  const sourceLabel = item.publisher || item.source || "뉴스";
  const actions = [
    item.url ? `<a href="${item.url}" target="_blank" rel="noreferrer">기사 열기</a>` : "",
    item.naverUrl ? `<a href="${item.naverUrl}" target="_blank" rel="noreferrer">네이버 검색</a>` : "",
  ].join("");
  return `
    <article class="news-item news-board-item news-${sentiment}">
      <div class="news-meta-row">
        <span>${escapeHtml(sourceLabel)}</span>
        <b>${sentimentLabel(sentiment)}</b>
      </div>
      <strong>${escapeHtml(item.title || "제목 없음")}</strong>
      <p>${escapeHtml(readableNewsSummary(item))}</p>
      <div class="news-tags">${tags.map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div>
      <div class="news-board-bottom">
        <div class="impact-labels"><em>영향 가능</em>${labels.map((label) => `<span>${escapeHtml(label)}</span>`).join("")}</div>
        <div class="news-date">${escapeHtml(dateLabel)}</div>
      </div>
      <div class="news-actions">${actions}</div>
    </article>
  `;
}

function readableNewsSummary(item) {
  const title = String(item.title || "").replace(/\s+/g, " ").trim();
  let text = String(item.ai_summary || item.summary || item.title || "제목 없음").replace(/\s+/g, " ").trim();
  if (title && text.toLowerCase().startsWith(title.toLowerCase())) {
    text = text.slice(title.length).replace(/^\s*[-:|?]+\s*/, "").trim();
  }
  text = text
    .replace(/\s+-\s+[A-Za-z0-9 .]+$/, "")
    .replace(/([.!?])\s*\1+/g, "$1")
    .trim();
  const cleaned = uniqueSentences(text).join(" ").trim();
  const candidate = cleaned && cleaned.toLowerCase() !== title.toLowerCase() ? cleaned : "";
  if (hasKorean(candidate)) return truncateText(candidate, 190);
  return ruleBasedKoreanNewsSummary(item, candidate || title);
}

function uniqueSentences(text) {
  const sentences = String(text || "").split(/(?<=[.!?。！？])\s+/).filter(Boolean);
  const unique = [];
  const seen = new Set();
  sentences.forEach((sentence) => {
    const key = sentence.toLowerCase().replace(/[^가-힣a-z0-9]+/g, "");
    if (!key || seen.has(key)) return;
    seen.add(key);
    unique.push(sentence.trim());
  });
  return unique;
}

function hasKorean(text) {
  return /[가-힣]/.test(String(text || ""));
}

function truncateText(text, max = 190) {
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  return clean.length > max ? `${clean.slice(0, max - 3).trim()}...` : clean;
}

function ruleBasedKoreanNewsSummary(item, rawText = "") {
  const labels = relatedTickerLabels(item, 2).filter((label) => label !== "시장공통");
  const subject = labels[0] || item.topic || "시장 전체";
  const tags = item.tags || [];
  const lower = `${item.title || ""} ${item.summary || ""} ${rawText}`.toLowerCase();
  let topic = "일반 이슈";
  if (tags.includes("실적") || /earnings|revenue|eps|guidance|quarter/.test(lower)) topic = "실적·가이던스";
  else if (tags.includes("목표가") || /target|rating|upgrade|downgrade|analyst/.test(lower)) topic = "투자의견·목표가";
  else if (tags.includes("수주") || /contract|order|supply/.test(lower)) topic = "수주·계약";
  else if (tags.includes("규제") || /lawsuit|probe|regulation|sanction|tariff/.test(lower)) topic = "규제·정책";
  else if (tags.includes("신제품") || /product|launch|ai|chip|semiconductor/.test(lower)) topic = "제품·기술";
  const tone = sentimentLabel(effectiveSentiment(item));
  return `${subject} 관련 ${topic} 뉴스입니다. 제목과 제공 요약 기준으로 ${tone} 요인으로 분류했으며, 원문에서 금액·가이던스·계약 규모 같은 숫자를 확인해야 합니다.`;
}

function effectiveSentiment(item) {
  if (["positive", "negative", "mixed"].includes(item.sentiment)) return item.sentiment;
  const text = `${item.title || ""} ${item.ai_summary || ""} ${item.summary || ""}`.toLowerCase();
  const positives = ["beat", "beats", "strong", "upbeat", "surge", "soaring", "raise", "raised", "growth", "profit", "contract", "buyback", "upgrade", "호조", "상향", "강세", "성장", "수주", "흑자"];
  const negatives = ["miss", "weak", "drop", "drops", "fall", "falls", "cut", "cuts", "downgrade", "loss", "concern", "cancel", "probe", "lawsuit", "부진", "하향", "약세", "적자", "소송", "규제", "취소"];
  const score = positives.filter((word) => text.includes(word)).length - negatives.filter((word) => text.includes(word)).length;
  return score > 0 ? "positive" : score < 0 ? "negative" : "neutral";
}

function formatNewsDate(value) {
  if (!value) return "날짜 없음";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 16);
  return date.toLocaleString("ko-KR", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

async function renderAiStatus() {
  const box = $("#aiStatusBanner");
  if (!box) return;
  if (!state.apiOnline) {
    box.innerHTML = "";
    return;
  }
  try {
    const res = await fetch("http://127.0.0.1:8787/api/ai/status", { cache: "no-store" });
    state.aiStatus = res.ok ? await res.json() : { enabled: false };
  } catch {
    state.aiStatus = { enabled: false };
  }
  box.innerHTML = `<div class="ai-status ${state.aiStatus.enabled ? "active" : "inactive"}"><strong>AI \uc694\uc57d ${state.aiStatus.enabled ? "\uc5f0\uacb0\ub428" : "\ub300\uae30\uc911"}</strong><span>${state.aiStatus.enabled ? `${state.aiStatus.model}\ub85c \ub274\uc2a4 \uc694\uc57d\uc744 \ubcf4\uac15\ud569\ub2c8\ub2e4.` : ".env\uc5d0 OPENAI_API_KEY\ub97c \ub123\uc73c\uba74 \ub354 \uc790\uc5f0\uc2a4\ub7ec\uc6b4 \uc694\uc57d\uc744 \uc0ac\uc6a9\ud569\ub2c8\ub2e4."}</span></div>`;
}

async function renderEconomicCalendar() {
  const box = $("#economicCalendarList");
  if (!box) return;
  if (!state.apiOnline) {
    box.innerHTML = "";
    return;
  }
  try {
    const res = await fetch("http://127.0.0.1:8787/api/economic-calendar", { cache: "no-store" });
    if (!res.ok) throw new Error("calendar api failed");
    const payload = await res.json();
    const items = (payload.items || []).slice(0, 6);
    box.innerHTML = `
      <div class="briefing-head">
        <span>US Economic Calendar</span>
        <strong>\ubbf8\uad6d \uc8fc\uc694 \uacbd\uc81c\uc9c0\ud45c \uc77c\uc815</strong>
      </div>
      <div class="economic-grid">
        ${items.map((item) => `
          <article class="economic-card">
            <div class="economic-date"><b>${escapeHtml(item.date)}</b><span>${escapeHtml(item.time_et)} ET</span></div>
            <strong>${escapeHtml(item.label)}</strong>
            <p>${escapeHtml(item.impact)}</p>
            <div class="news-tags"><span>${escapeHtml(item.category)}</span><span>${escapeHtml(item.source)}</span></div>
          </article>
        `).join("")}
      </div>
    `;
  } catch {
    box.innerHTML = "";
  }
}
async function renderMarketBriefing() {
  const box = $("#marketBriefingList");
  if (!box) return;
  if (!state.apiOnline) {
    box.innerHTML = "";
    return;
  }
  try {
    const res = await fetch("http://127.0.0.1:8787/api/market/news", { cache: "no-store" });
    if (!res.ok) throw new Error("market news api failed");
    const payload = await res.json();
    const items = dedupeNewsItems(payload.items || []).slice(0, 4);
    if (!items.length) {
      box.innerHTML = "";
      return;
    }
    box.innerHTML = `
      <div class="briefing-head">
        <span>Market Briefing</span>
        <strong>\uc804\uccb4 \uc2dc\uc7a5 \uacf5\ud1b5 \uc774\uc288</strong>
      </div>
      <div class="briefing-grid">
        ${items
          .map(
            (item) => `
              <article class="briefing-card news-${item.sentiment || "neutral"}">
                <div class="news-meta-row">
                  <span>${escapeHtml(item.topic || item.publisher || "\ub274\uc2a4")}</span>
                  <b>${sentimentLabel(item.sentiment)}</b>
                </div>
                <strong>${escapeHtml(item.title || "\uc81c\ubaa9 \uc5c6\uc74c")}</strong>
                <p>${escapeHtml(readableNewsSummary(item))}</p>
                <div class="news-tags">${(item.tags || ["\uc77c\ubc18"]).map((tag) => `<span>${escapeHtml(tag)}</span>`).join("")}</div>
                <div class="news-actions"><a href="${item.url}" target="_blank" rel="noreferrer">\uae30\uc0ac \uc5f4\uae30</a></div>
              </article>
            `,
          )
          .join("")}
      </div>
    `;
  } catch {
    box.innerHTML = "";
  }
}

function renderNewsDecisionBrief(items, watchedStocks) {
  const box = $("#newsDecisionBrief");
  if (!box) return;
  const real = dedupeNewsItems(items || []).filter(isRealNewsItem);
  if (!real.length) {
    box.innerHTML = `<section class="decision-brief-card empty"><div><span>Decision Brief</span><strong>판단 보류</strong></div><p>최근 2일 내 실제 기사로 확인된 뉴스가 부족합니다. 뉴스 없는 종목은 가격/지표 중심으로만 보세요.</p></section>`;
    return;
  }
  const counts = real.reduce((acc, item) => {
    const key = effectiveSentiment(item);
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const negative = counts.negative || 0;
  const positive = counts.positive || 0;
  const neutral = counts.neutral || 0;
  const verdict = negative >= positive + 2 ? "주의" : positive >= negative + 2 ? "우호적" : "중립";
  const tone = verdict === "우호적" ? "positive" : verdict === "주의" ? "negative" : "neutral";
  const tags = topNewsTags(real).slice(0, 6);
  const tickers = [...new Set(real.flatMap((item) => relatedTickerLabels(item, 6)))].filter((label) => label !== "시장공통").slice(0, 8);
  box.innerHTML = `<section class="decision-brief-card"><div class="decision-brief-head"><div><span>Decision Brief</span><strong>뉴스 활용 요약</strong></div><b class="verdict-pill ${tone}">${verdict}</b></div><div class="decision-stats"><span>실제 기사 ${real.length}건</span><span>긍정 ${positive}</span><span>부정 ${negative}</span><span>중립 ${neutral}</span></div><div class="decision-focus"><article><span>많이 나온 주제</span><strong>${escapeHtml(tags.join(" · ") || "일반")}</strong></article><article><span>영향 가능 종목</span><strong>${escapeHtml(tickers.join(" · ") || "시장공통")}</strong></article><article><span>활용 방법</span><strong>중복 기사는 하나의 이슈로 보고, 실적·가이던스·계약 규모 같은 숫자를 원문에서 확인하세요.</strong></article></div></section>`;
}

function topNewsTags(items) {
  const counts = new Map();
  items.forEach((item) => (item.tags || ["일반"]).forEach((tag) => counts.set(tag, (counts.get(tag) || 0) + 1)));
  return [...counts.entries()].sort((a, b) => b[1] - a[1]).map(([tag]) => tag);
}

function renderStockIssues(items, watchedStocks) {
  const box = $("#stockIssueList");
  if (!box) return;
  const important = prioritizeInvestmentNews(clusterNewsEvents(dedupeNewsItems(items || []).filter(isRealNewsItem))).slice(0, 8);
  if (!important.length) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = `
    <div class="briefing-head">
      <span>\uD575\uC2EC \uC774\uC288</span>
      <strong>\uC774\uBCA4\uD2B8 \uAE30\uC900 \uD22C\uC790 \uB274\uC2A4</strong>
    </div>
    <div class="investment-news-grid">
      ${important.map((item) => `
        <article class="investment-news-card news-${effectiveSentiment(item)}">
          <div class="news-meta-row">
            <span>${escapeHtml(primaryNewsTag(item))}</span>
            <b>${item._clusterCount > 1 ? `관련 기사 ${item._clusterCount}건` : sentimentLabel(effectiveSentiment(item))}</b>
          </div>
          <strong>${escapeHtml(clusterDisplayTitle(item))}</strong>
          <p>${escapeHtml(investmentNewsTakeaway(item))}</p>
          <div class="impact-labels"><em>영향 가능</em>${relatedTickerLabels(item, 7).map((label) => `<span>${escapeHtml(label)}</span>`).join("")}</div>
          <div class="news-check-pills">${newsWatchPoints(item).map((point) => `<span>${escapeHtml(point)}</span>`).join("")}</div>
        </article>
      `).join("")}
    </div>
  `;
}

function prioritizeInvestmentNews(items) {
  return [...items].sort((a, b) => newsImportanceScore(b) - newsImportanceScore(a));
}

function newsImportanceScore(item) {
  const tags = item.tags || [];
  let score = 0;
  if (effectiveSentiment(item) !== "neutral") score += 3;
  if (relatedTickerLabels(item, 3).some((label) => label !== "시장공통")) score += 2;
  if (tags.some((tag) => ["실적", "목표가", "수주", "규제", "신제품"].includes(tag))) score += 3;
  if (isMacroNews(item)) score += 1;
  const text = `${item.title || ""} ${item.summary || ""}`.toLowerCase();
  if (/earnings|guidance|revenue|contract|lawsuit|probe|upgrade|downgrade|실적|가이던스|계약|수주|소송|규제|상향|하향/.test(text)) score += 2;
  return score;
}

function primaryNewsTag(item) {
  const tags = item.tags || [];
  return tags.find((tag) => tag !== "일반") || item.topic || "일반";
}

function investmentNewsTakeaway(item) {
  const tag = primaryNewsTag(item);
  const sentiment = sentimentLabel(effectiveSentiment(item));
  const targets = relatedTickerLabels(item, 3).join(" · ");
  const base = readableNewsSummary(item);
  return `${targets}에 ${sentiment} 가능성이 있는 ${tag} 뉴스입니다. ${base}`;
}

function newsWatchPoints(item) {
  const tag = primaryNewsTag(item);
  const points = [];
  if (["실적", "실적·가이던스"].includes(tag)) points.push("매출·EPS·가이던스 확인");
  if (["목표가", "투자의견·목표가"].includes(tag)) points.push("목표가 변경 폭 확인");
  if (["수주", "수주·계약"].includes(tag)) points.push("계약 규모·기간 확인");
  if (["규제", "규제·정책"].includes(tag)) points.push("일회성인지 구조적 리스크인지 확인");
  if (isMacroNews(item)) points.push("금리·달러·업종 영향 확인");
  points.push("주가 반응 확인");
  return [...new Set(points)].slice(0, 4);
}

function isRealNewsItem(item) {
  const url = String(item.url || "").toLowerCase();
  const publisher = String(item.publisher || "").toLowerCase();
  const tags = item.tags || [];
  if (!url || url.includes("google.com/search") || url.includes("search.naver.com")) return false;
  if (publisher.includes("fallback") || publisher.includes("\uc911\ub9bd")) return false;
  if (tags.includes("\uc911\ub9bd")) return false;
  return true;
}
function issueLine(item) {
  const tags = (item.tags || []).filter((tag) => !["\uc911\ub9bd", "\uc911\ub9bd"].includes(tag));
  const prefix = tags[0] ? `${tags[0]}: ` : "";
  return `${prefix}${readableNewsSummary(item)}`;
}
function renderHotTopics(items) {
  const box = $("#hotTopicList");
  if (!box) return;
  const topics = extractHotTopics(dedupeNewsItems(items));
  if (!topics.length) {
    box.innerHTML = "";
    return;
  }
  box.innerHTML = topics
    .map(
      (topic) => `
        <article class="hot-topic-card hot-${topic.sentiment}">
          <div class="hot-topic-top">
            <span>Hot Topic</span>
            <b>${topic.count}건</b>
          </div>
          <strong>${escapeHtml(topic.label)}</strong>
          <p>${escapeHtml(topic.summary)}</p>
          <div class="hot-topic-meta">
            <span>${sentimentLabel(topic.sentiment)}</span>
            <span>${escapeHtml(topic.tickers.join(", ") || "\uc694\uc57d \uc5c6\uc74c")}</span>
          </div>
        </article>
      `,
    )
    .join("");
}

function dedupeNewsItems(items) {
  const result = [];
  const seen = new Set();
  items.forEach((item) => {
    const key = newsFingerprint(item);
    if (seen.has(key)) return;
    const duplicate = result.find((existing) => {
      const left = newsFingerprint(existing);
      return left === key || left.includes(key.slice(0, 48)) || key.includes(left.slice(0, 48));
    });
    if (duplicate) {
      mergeNewsDuplicate(duplicate, item);
      return;
    }
    seen.add(key);
    result.push({ ...item });
  });
  return result;
}

function mergeNewsDuplicate(target, source) {
  target.related_tickers = [...new Set([...(target.related_tickers || []), ...(source.related_tickers || [])])];
  target.tags = [...new Set([...(target.tags || []), ...(source.tags || [])])];
  const titles = [target.title, ...(target._clusterTitles || []), source.title, ...(source._clusterTitles || [])].filter(Boolean);
  target._clusterTitles = [...new Set(titles)].slice(0, 8);
  target._clusterCount = Math.max(target._clusterCount || 1, target._clusterTitles.length);
}

function clusterNewsEvents(items) {
  const groups = new Map();
  items.forEach((item) => {
    const key = newsEventFingerprint(item);
    if (!groups.has(key)) {
      groups.set(key, { ...item, _clusterCount: 1, _clusterTitles: [item.title].filter(Boolean) });
      return;
    }
    const existing = groups.get(key);
    if (newsImportanceScore(item) > newsImportanceScore(existing)) {
      const merged = { ...item, _clusterCount: existing._clusterCount || 1, _clusterTitles: existing._clusterTitles || [existing.title].filter(Boolean) };
      mergeNewsDuplicate(merged, existing);
      groups.set(key, merged);
    } else {
      mergeNewsDuplicate(existing, item);
    }
  });
  return [...groups.values()].map((item) => ({ ...item, _clusterCount: Math.max(item._clusterCount || 1, (item._clusterTitles || []).length) }));
}

function newsEventFingerprint(item) {
  const tickers = [...new Set(item.related_tickers || ["시장공통"])].filter(Boolean).sort().slice(0, 4).join("+") || "시장공통";
  const text = `${item.title || ""} ${item.ai_summary || ""} ${item.summary || ""} ${(item.tags || []).join(" ")}`.toLowerCase();
  const event = newsEventType(text, item.tags || []);
  const quarter = (text.match(/\bq[1-4]\b|\b[1-4]q\b|[1-4]분기|[1-4]분기|1분기|2분기|3분기|4분기/) || [""])[0].toLowerCase();
  const year = (text.match(/20\d{2}/) || [""])[0];
  if (event !== "general") return `${tickers}|${event}|${quarter}|${year}`;
  return `${tickers}|${event}|${newsFingerprint(item).slice(0, 46)}`;
}

function newsEventType(text, tags = []) {
  if (tags.includes("실적") || /earnings|revenue|eps|guidance|quarter|results|transcript|call highlights|estimates|실적|매출|가이던스/.test(text)) return "earnings";
  if (tags.includes("목표가") || /target|rating|upgrade|downgrade|analyst|목표가|투자의견|상향|하향/.test(text)) return "rating";
  if (tags.includes("수주") || /contract|order|supply|deal|deals|수주|계약|공급/.test(text)) return "contract";
  if (tags.includes("규제") || /lawsuit|probe|regulation|tariff|sanction|규제|소송|조사|관세/.test(text)) return "policy";
  if (tags.includes("신제품") || /launch|product|ai|chip|semiconductor|신제품|출시|반도체/.test(text)) return "product";
  return "general";
}

function clusterDisplayTitle(item) {
  if ((item._clusterCount || 1) <= 1) return item.title || "제목 없음";
  const tickers = relatedTickerLabels(item, 2).join(" · ");
  const tag = primaryNewsTag(item);
  const text = `${item.title || ""} ${item.summary || ""}`.toLowerCase();
  const quarter = (text.match(/\bq[1-4]\b|[1-4]분기/) || [""])[0].toUpperCase();
  return `${tickers} ${quarter ? `${quarter} ` : ""}${tag} 이슈 묶음`;
}

function newsFingerprint(item) {
  return String(item.title || item.ai_summary || item.summary || item.url || "")
    .toLowerCase()
    .replace(/https?:\/\/\S+/g, "")
    .replace(/\b(?:com|inc|corp|ltd|plc|co|llc)\b/g, "")
    .replace(/[^가-힣a-z0-9]+/g, "")
    .slice(0, 100);
}

function compactSummary(text) {
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  return clean.length > 125 ? `${clean.slice(0, 122).trim()}...` : clean;
}

function topicAliases() {
  const aliases = new Map();
  data.stocks.forEach((stock) => {
    const ticker = String(stock.ticker || stock.gfKey || "").toLowerCase();
    const names = [stock.nameKr, stock.nameEn, ticker].filter(Boolean);
    names.forEach((name) => aliases.set(String(name).toLowerCase(), stock.ticker || stock.gfKey || stock.nameKr));
  });
  return aliases;
}

function extractHotTopics(items) {
  const topicMap = new Map();
  const addTopic = (label, item, weight = 1) => {
    const clean = String(label || "").trim();
    if (!clean || clean.length < 2 || clean === "일반") return;
    const key = clean.toLowerCase();
    if (!topicMap.has(key)) topicMap.set(key, { label: clean, score: 0, items: [], tickers: new Set(), sentiments: { positive: 0, negative: 0, neutral: 0, mixed: 0 } });
    const topic = topicMap.get(key);
    topic.score += weight;
    if (!topic.items.includes(item)) topic.items.push(item);
    relatedTickerLabels(item, 4).forEach((label) => topic.tickers.add(label));
    const sentiment = effectiveSentiment(item);
    topic.sentiments[sentiment] = (topic.sentiments[sentiment] || 0) + 1;
  };
  dedupeNewsItems(items).forEach((item) => {
    (item.tags || []).forEach((tag) => addTopic(tag, item, 3));
    const lower = `${item.title || ""} ${item.summary || ""}`.toLowerCase();
    if (/fed|fomc|interest rate|cpi|pce|inflation|jobs|payroll|금리|연준|물가|고용/.test(lower)) addTopic("경제·정책", item, 5);
    if (/ai|semiconductor|chip|반도체|인공지능/.test(lower)) addTopic("AI·반도체", item, 4);
    if (/earnings|revenue|guidance|실적|매출|가이던스/.test(lower)) addTopic("실적·가이던스", item, 4);
  });
  return [...topicMap.values()]
    .filter((topic) => topic.items.length >= 1)
    .sort((a, b) => b.score - a.score || b.items.length - a.items.length)
    .slice(0, 4)
    .map((topic) => {
      const sentiment = topic.sentiments.positive > topic.sentiments.negative && topic.sentiments.positive >= topic.sentiments.neutral ? "positive" : topic.sentiments.negative > topic.sentiments.positive && topic.sentiments.negative >= topic.sentiments.neutral ? "negative" : "neutral";
      const first = topic.items[0] || {};
      return {
        label: topic.label,
        count: topic.items.length,
        sentiment,
        tickers: [...topic.tickers].slice(0, 4),
        summary: readableNewsSummary(first),
      };
    });
}

function renderWatchNews() {
  const watchedStocks = data.stocks.filter(isWatched);
  const listedCount = data.stocks.filter((stock) => stock.status === LISTED).length;
  const countLabel = state.newsScope === "watch" ? `${watchedStocks.length}개 관심 종목 · 최근 2일` : state.newsScope === "macro" ? "미국 경제·정책 · 최근 2일" : `${listedCount}개 종목 기준 · 최근 2일`;
  $("#newsCount").textContent = countLabel;
  updateNewsToolbar();
  renderAiStatus();
  renderEconomicCalendar();
  const marketBriefing = $("#marketBriefingList");
  if (marketBriefing) marketBriefing.innerHTML = "";
  if (state.apiOnline) {
    renderWatchNewsFromApi(watchedStocks);
    return;
  }
  const items = [];
  if (state.newsScope === "watch") items.push(...watchedStocks.slice(0, 12).map(newsForStock));
  const realItems = dedupeNewsItems(items).filter(isRealNewsItem);
  renderNewsSections(realItems, watchedStocks);
}

async function fetchJsonSafe(url) {
  try {
    const res = await fetch(url, { cache: "no-store" });
    if (!res.ok) return { items: [], error: res.statusText };
    return await res.json();
  } catch (error) {
    return { items: [], error: String(error) };
  }
}

async function renderWatchNewsFromApi(watchedStocks) {
  const tickers = watchedStocks.map((stock) => stock.ticker || stock.gfKey || stock.nameKr).filter(Boolean);
  const requests = [];
  if (state.newsScope === "market" || state.newsScope === "macro") {
    requests.push(fetchJsonSafe("http://127.0.0.1:8787/api/market/news"));
  }
  if ((state.newsScope === "market" || state.newsScope === "watch") && tickers.length) {
    requests.push(fetchJsonSafe(`http://127.0.0.1:8787/api/watchlist/news?tickers=${encodeURIComponent(tickers.join(","))}`));
  }
  const payloads = await Promise.all(requests);
  const items = payloads.flatMap((payload) => payload.items || []);
  renderNewsSections(items, watchedStocks);
}

function renderNewsSections(items, watchedStocks) {
  const deduped = dedupeNewsItems(items || []).filter(isRealNewsItem);
  const scoped = state.newsScope === "macro" ? deduped.filter(isMacroNews) : deduped;
  const filtered = scoped.filter(newsModeFilter);
  const clustered = clusterNewsEvents(filtered.length ? filtered : scoped);
  const visible = clustered.slice(0, state.newsScope === "market" ? 30 : 18);
  renderNewsDecisionBrief(visible, watchedStocks);
  renderHotTopics([]);
  renderStockIssues(visible, watchedStocks);
  if (!visible.length) {
    const message = state.newsScope === "watch" && !watchedStocks.length ? "관심 종목을 등록하면 관련 뉴스가 표시됩니다." : "최근 2일 내 수집된 실제 기사가 없거나 조회 중입니다.";
    $("#newsList").innerHTML = `<p class="empty-state">${message}</p>`;
    return;
  }
  const rawVisible = visible.slice(0, 12);
  $("#newsList").innerHTML = `<div class="raw-news-head"><strong>\uC6D0\uBB38 \uAE30\uC0AC</strong><span>\uC911\uBCF5 \uC774\uBCA4\uD2B8 \uBB36\uC74C \u00B7 \uC0C1\uC704 ${rawVisible.length}\uAC74</span></div>${rawVisible.map(renderNewsItem).join("")}`;
}

function isMacroNews(item) {
  const text = `${item.title || ""} ${item.ai_summary || ""} ${item.summary || ""} ${(item.tags || []).join(" ")} ${item.topic || ""}`.toLowerCase();
  return ["경제", "정책", "fed", "fomc", "cpi", "pce", "jobs", "payroll", "tariff", "rate", "inflation", "gdp", "treasury", "yield", "dollar", "oil", "금리", "물가", "고용", "연준", "관세", "국채", "달러", "유가"].some((word) => text.includes(word));
}
function newsModeFilter(item) {
  const text = `${item.title || ""} ${item.ai_summary || ""} ${item.summary || ""} ${(item.tags || []).join(" ")}`.toLowerCase();
  if (state.newsMode === "all") return true;
  if (state.newsMode === "memo") return (item.tags || []).includes("내 메모") || Boolean(stockMemos[(item.related_tickers || [])[0]]);
  if (state.newsMode === "breaking") return ["breaking", "urgent", "속보", "급등", "급락", "surge", "falls", "drops"].some((word) => text.includes(word));
  if (state.newsMode === "report") return ["실적", "리포트", "목표가", "투자의견", "가이던스", "earnings", "revenue", "eps", "target", "rating", "guidance"].some((word) => text.includes(word));
  if (state.newsMode === "macro") return ["경제", "정책", "fed", "fomc", "cpi", "pce", "jobs", "payroll", "tariff", "rate", "inflation", "gdp", "금리", "물가", "고용", "연준", "관세", "국채", "달러"].some((word) => text.includes(word));
  return true;
}

function sentimentLabel(sentiment) {
  if (sentiment === "positive") return "\uae0d\uc815";
  if (sentiment === "negative") return "\ubd80\uc815";
  if (sentiment === "mixed") return "\ud63c\uc7ac";
  return "\uc911\ub9bd";
}

function updateNewsToolbar() {
  document.querySelectorAll("[data-heatmap-sort]").forEach((button) => {
    button.addEventListener("click", () => {
      state.heatmapStockSort = button.dataset.heatmapSort;
      renderMarketHeatmap(filteredStocks());
    });
  });
  document.querySelectorAll("[data-news-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.newsMode === state.newsMode);
  });
  document.querySelectorAll("[data-news-scope]").forEach((button) => {
    button.classList.toggle("active", button.dataset.newsScope === state.newsScope);
  });
}

function inferManualStock(query) {
  const raw = String(query || "").trim();
  const ticker = raw.replace(/\s+/g, "").toUpperCase();
  const isKoreanTicker = /^\d{6}$/.test(ticker);
  return { nameKr: ticker || raw, nameEn: "", ticker, gfKey: ticker, exchange: isKoreanTicker ? "KRX" : "NASDAQ", part: "미분류", theme: "일반", status: LISTED, source: "manual" };
}

function fillAddForm(stock) {
  if (!stock) return;
  const part = cleanPartLabel(stock.part || "미분류");
  const theme = canonicalThemeLabel(stock.theme || stock.industry || "일반", part);
  $("#newName").value = stock.nameKr || stock.name || stock.nameEn || stock.ticker || "";
  $("#newTicker").value = stock.ticker || stock.gfKey || "";
  $("#newMarket").value = stock.exchange || stock.market || "";
  $("#newPart").value = part;
  $("#newTheme").value = theme;
  updateThemeSuggestions();
}

function closeLookupResults() {
  const box = $("#stockLookupResults");
  if (!box) return;
  box.innerHTML = "";
  box.hidden = true;
}

function isDerivativeTicker(ticker) {
  return /[A-Z]{1,8}\d{6}[CP]\d{8}/i.test(String(ticker || ""));
}

function lookupMarketScore(stock) {
  const market = String(stock.exchange || stock.market || "").toUpperCase();
  const ticker = String(stock.ticker || stock.gfKey || "").toUpperCase();
  if (["NASDAQ", "NYSE", "AMEX", "NYSEARCA", "US"].some((key) => market.includes(key))) return 0;
  if (["KRX", "KOSPI", "KOSDAQ"].some((key) => market.includes(key))) return 1;
  if (market === "OPR" || isDerivativeTicker(ticker)) return 20;
  if (/\.[A-Z]{2,4}$/.test(ticker)) return 8;
  return 4;
}

function lookupSourceScore(stock) {
  const source = String(stock.source || "");
  if (source === "financial_modeling_prep" || source === "yahoo_finance" || source === "finnhub") return 0;
  if (source === "direct_ticker") return 2;
  return 4;
}

function lookupRank(stock, query) {
  const q = String(query || "").toLowerCase();
  const ticker = String(stock.ticker || stock.gfKey || "").toLowerCase();
  const name = `${stock.nameKr || ""} ${stock.nameEn || ""} ${stock.name || ""}`.toLowerCase();
  let base = 9;
  if (ticker === q) base = 0;
  else if (ticker.startsWith(q)) base = 1;
  else if (name.includes(q)) base = 2;
  else if (`${ticker} ${name}`.includes(q)) base = 3;
  const derivativePenalty = isDerivativeTicker(ticker) ? 20 : 0;
  return base * 100 + lookupMarketScore(stock) * 10 + lookupSourceScore(stock) + derivativePenalty;
}

function cleanLookupMatches(matches, query) {
  const q = String(query || "").toUpperCase();
  const hasExactStock = matches.some((stock) => String(stock.ticker || stock.gfKey || "").toUpperCase() === q && !isDerivativeTicker(stock.ticker || stock.gfKey));
  return matches.filter((stock) => !hasExactStock || !isDerivativeTicker(stock.ticker || stock.gfKey));
}

function lookupSourceLabel(source) {
  return ({ financial_modeling_prep: "FMP", yahoo_finance: "Yahoo", finnhub: "Finnhub", alpha_vantage: "Alpha Vantage", finance_datareader: "FDR", pykrx: "pykrx", direct_ticker: "직접 후보", manual: "직접 입력" })[source] || source || "";
}

function renderLookupBox(query, matches, loading = false) {
  const box = $("#stockLookupResults");
  if (!box) return;
  const manual = inferManualStock(query);
  lookupCache = new Map(matches.map((stock) => [tickerKey(stock), stock]));
  box.hidden = false;
  const list = matches.map((stock) => `
    <button class="lookup-item" data-lookup="${escapeHtml(tickerKey(stock))}" type="button">
      <strong>${escapeHtml(stockPrimaryName(stock))}</strong>
      <span>${escapeHtml(stock.ticker || stock.gfKey || "-")} · ${escapeHtml(marketOf(stock))} · ${escapeHtml(cleanPartLabel(stock.part))} / ${escapeHtml(stock.theme || "일반")}${stock.source ? ` · ${escapeHtml(lookupSourceLabel(stock.source))}` : ""}</span>
    </button>`).join("");
  box.innerHTML = `
    <div class="lookup-head"><strong>${loading ? "검색 중" : "검색 결과"}</strong><button data-lookup-close type="button">닫기</button></div>
    ${list || `<div class="lookup-empty">일치하는 종목을 찾지 못했습니다. 아래 버튼으로 직접 추가할 수 있습니다.</div>`}
    <button class="lookup-manual" data-lookup-manual type="button"><strong>${escapeHtml(manual.ticker)} 직접 추가</strong><span>이름/시장/테마는 아래 입력칸에서 바꿀 수 있어요.</span></button>`;
  box.querySelector("[data-lookup-close]")?.addEventListener("click", closeLookupResults);
  box.querySelector("[data-lookup-manual]")?.addEventListener("click", () => { fillAddForm(manual); closeLookupResults(); });
  box.querySelectorAll("[data-lookup]").forEach((button) => {
    button.addEventListener("click", () => {
      const stock = lookupCache.get(button.dataset.lookup) || findStock(button.dataset.lookup);
      fillAddForm(stock);
      closeLookupResults();
      $("#stockLookup").value = `${stockPrimaryName(stock)} ${stock.ticker || ""}`.trim();
    });
  });
}

function renderLookupResults() {
  const input = $("#stockLookup");
  const query = input.value.trim();
  const queryLower = query.toLowerCase();
  const requestId = ++lookupRequestSeq;
  if (lookupDebounceTimer) clearTimeout(lookupDebounceTimer);
  if (lookupAbortController) lookupAbortController.abort();
  if (!query) { closeLookupResults(); lookupCache = new Map(); return; }
  const manual = inferManualStock(query);
  if (/^[a-z0-9.\-]{1,10}$/i.test(query)) {
    if (!$("#newTicker").value.trim()) $("#newTicker").value = manual.ticker;
    if (!$("#newName").value.trim()) $("#newName").value = manual.ticker;
    if (!$("#newMarket").value.trim()) $("#newMarket").value = manual.exchange;
  }
  let matches = data.stocks
    .map((stock) => ({ stock, rank: lookupRank(stock, queryLower) }))
    .filter((item) => item.rank < 900)
    .sort((a, b) => a.rank - b.rank || (b.stock.marketCap || 0) - (a.stock.marketCap || 0))
    .map((item) => item.stock);
  matches = cleanLookupMatches(matches, query).slice(0, 8);
  renderLookupBox(query, matches, state.apiOnline);
  if (!state.apiOnline) return;
  lookupDebounceTimer = setTimeout(() => fetchLookupResults(query, queryLower, matches, requestId), 350);
}

async function fetchLookupResults(query, queryLower, baseMatches, requestId) {
  lookupAbortController = new AbortController();
  try {
    const res = await fetch(`http://127.0.0.1:8787/api/search/stocks?q=${encodeURIComponent(query)}`, { cache: "no-store", signal: lookupAbortController.signal });
    if (!res.ok || requestId !== lookupRequestSeq) return;
    const payload = await res.json();
        const apiMatches = (payload.results || []).map((item) => {
      const part = cleanPartLabel(item.sector || "미분류");
      return { nameKr: item.name || item.ticker, nameEn: "", ticker: item.ticker, gfKey: item.ticker, exchange: item.market || "", part, theme: canonicalThemeLabel(item.theme || item.industry || "일반", part), status: LISTED, source: item.source };
    });
    const seen = new Set(baseMatches.map(tickerKey));
    let matches = [...baseMatches, ...apiMatches.filter((item) => !seen.has(tickerKey(item)))]
      .map((stock) => ({ stock, rank: lookupRank(stock, queryLower) }))
      .filter((item) => item.rank < 900 || String(item.stock.ticker || "").toLowerCase() === queryLower)
      .sort((a, b) => a.rank - b.rank)
      .map((item) => item.stock);
    matches = cleanLookupMatches(matches, query).slice(0, 10);
    renderLookupBox(query, matches, false);
  } catch (error) {
    if (error?.name === "AbortError") return;
    if (requestId === lookupRequestSeq) renderLookupBox(query, baseMatches, false);
  }
}
function bindWatchButtons() {
  document.querySelectorAll("[data-watch]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const stock = findStock(button.dataset.watch);
      toggleWatch(stock);
    });
  });
}

function bindStockButtons() {
  document.querySelectorAll("[data-stock]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedKey = button.dataset.stock;
      const stock = findStock(state.selectedKey);
      renderDetail();
      if (stock) hydrateMetricsFromApi(stock, { force: true });
    });
  });
}

function addCustomStock(form) {
  const name = $("#newName").value.trim();
  const ticker = $("#newTicker").value.trim().toUpperCase();
  if (!name || !ticker) return;

  const existing = data.stocks.find((item) => tickerKey(item) === ticker || item.ticker === ticker);
  if (existing) {
    const part = cleanPartLabel($("#newPart").value || existing.part || "미분류");
    const theme = canonicalThemeLabel($("#newTheme").value || existing.theme || "일반", part);
    existing.part = part;
    existing.theme = theme;
    existing.exchange = normalizeText($("#newMarket").value) || existing.exchange || "직접 입력";
    stockOverrides[tickerKey(existing)] = { ...(stockOverrides[tickerKey(existing)] || {}), part, theme, exchange: existing.exchange };
    saveOverrides();
    watchlist.add(tickerKey(existing));
    saveWatchlist();
    state.selectedKey = tickerKey(existing);
    form.reset();
    populateFilters();
    render();
    refreshStockData(existing);
    return;
  }

  const stock = {
    no: Date.now(),
    part: cleanPartLabel($("#newPart").value || "미분류"),
    theme: canonicalThemeLabel($("#newTheme").value || "일반", $("#newPart").value || "미분류"),
    nameKr: name,
    nameEn: "",
    status: LISTED,
    exchange: normalizeText($("#newMarket").value) || "직접 입력",
    ticker,
    gfKey: ticker,
    currency: "",
    price: null,
    d1: null,
    m1: null,
    ytd: null,
    high52: null,
    low52: null,
    marketCap: null,
    per: null,
    pbr: null,
    roe: null,
    forwardPe: null,
    targetPriceAvg: null,
    memo: "\uc0ac\uc6a9\uc790 \ucd94\uac00 \uc885\ubaa9",
  };

  const customStocks = loadCustomStocks().filter((item) => tickerKey(item) !== tickerKey(stock));
  customStocks.push(stock);
  saveCustomStocks(customStocks);
  data.stocks = data.stocks.filter((item) => tickerKey(item) !== tickerKey(stock));
  data.stocks.push(stock);
  watchlist.add(tickerKey(stock));
  saveWatchlist();
  state.selectedKey = tickerKey(stock);
  form.reset();
  buildQuantScores();
  populateFilters();
  render();
  refreshStockData(stock);
}

async function refreshStockData(stock) {
  if (!state.apiOnline) {
    setRefreshStatus(stock, "error", "API\uac00 \uaebc\uc838 \uc788\uc5b4 \ub370\uc774\ud130\ub97c \ubd88\ub7ec\uc624\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4.", [
      { label: "\uc9c0\ud45c", state: "pending" },
      { label: "\ucc28\ud2b8", state: "pending" },
      { label: "\ub274\uc2a4", state: "pending" },
    ]);
    return;
  }
  stock._metricsHydrated = false;
  stock._priceHistory = {};
  stock._pricePeriod = stock._pricePeriod || "1mo";
  setRefreshStatus(stock, "loading", "\uc0c8 \uc885\ubaa9 \ub370\uc774\ud130\ub97c \ubd88\ub7ec\uc624\ub294 \uc911\uc785\ub2c8\ub2e4.", [
    { label: "\uc9c0\ud45c/PER", state: "loading" },
    { label: "\ucc28\ud2b8", state: "loading" },
    { label: "\ub274\uc2a4", state: "loading" },
  ]);
  try {
    await Promise.all([hydrateMetricsFromApi(stock, { force: true }), hydratePriceHistoryFromApi(stock)]);
    await renderWatchNewsFromApi(data.stocks.filter(isWatched));
    setRefreshStatus(stock, "done", "\ud604\uc7ac\uac00, \ucc28\ud2b8, \ub274\uc2a4 \uac31\uc2e0\uc744 \uc2dc\ub3c4\ud588\uc2b5\ub2c8\ub2e4.", [
      { label: "\uc9c0\ud45c/PER", state: "done" },
      { label: "\ucc28\ud2b8", state: "done" },
      { label: "\ub274\uc2a4", state: "done" },
    ]);
  } catch {
    setRefreshStatus(stock, "error", "\uc77c\ubd80 \ub370\uc774\ud130\ub97c \ubd88\ub7ec\uc624\uc9c0 \ubabb\ud588\uc2b5\ub2c8\ub2e4. \uc7a0\uc2dc \ud6c4 \ub2e4\uc2dc \uc2dc\ub3c4\ud558\uc138\uc694.", [
      { label: "\uc9c0\ud45c/PER", state: typeof stock.price === "number" ? "done" : "error" },
      { label: "\ucc28\ud2b8", state: stock._priceHistory?.[stock._pricePeriod]?.items?.length ? "done" : "error" },
      { label: "\ub274\uc2a4", state: "error" },
    ]);
  }
  renderTerminalTicker();
  renderRows(filteredStocks());
}

function render() {
  const stocks = filteredStocks();
  renderTerminalTicker();
  renderKpis(stocks);
  renderMarketTickerTape(stocks);
  renderMarketIndicators();
  renderMarketHeatmap(stocks);
  renderPartBars(stocks);
  renderTree();
  renderMetricCoverage(stocks);
  renderRows(stocks);
  renderDetail();
  hydrateVisibleMetrics(stocks);
  renderWatchNews();
}

function attachEvents() {
  $("#partFilter").addEventListener("change", (event) => {
    state.part = event.target.value;
    populateThemeFilter();
    render();
  });
  $("#themeFilter").addEventListener("change", (event) => {
    state.theme = event.target.value;
    render();
  });
  $("#statusFilter").addEventListener("change", (event) => {
    state.status = event.target.value;
    render();
  });
  $("#watchOnlyToggle").addEventListener("change", (event) => {
    state.watchOnly = event.target.checked;
    render();
  });
  $("#searchInput").addEventListener("input", (event) => {
    state.query = event.target.value;
    render();
  });
  $("#treeSearch").addEventListener("input", (event) => {
    state.treeQuery = event.target.value;
    renderTree();
  });
  $("#stockLookup").addEventListener("input", renderLookupResults);
  $("#newPart")?.addEventListener("change", updateThemeSuggestions);
  $("#newTheme")?.addEventListener("change", normalizeThemeInput);
  $("#newTheme")?.addEventListener("blur", normalizeThemeInput);
  $("#stockLookup").addEventListener("keydown", (event) => { if (event.key === "Escape") closeLookupResults(); });
  $("#addStockForm").addEventListener("submit", (event) => {
    event.preventDefault();
    addCustomStock(event.currentTarget);
    closeLookupResults();
  });
  document.querySelectorAll("[data-table-sort]").forEach((button) => {
    button.addEventListener("click", () => setTableSort(button.dataset.tableSort));
  });
  $("#refreshWatchMetricsButton")?.addEventListener("click", refreshWatchMetrics);
  document.querySelectorAll("[data-heatmap-sort]").forEach((button) => {
    button.addEventListener("click", () => {
      state.heatmapStockSort = button.dataset.heatmapSort;
      renderMarketHeatmap(filteredStocks());
    });
  });
  document.querySelectorAll("[data-news-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.newsMode = button.dataset.newsMode;
      renderWatchNews();
    });
  });
  document.querySelectorAll("[data-news-scope]").forEach((button) => {
    button.addEventListener("click", () => {
      state.newsScope = button.dataset.newsScope;
      renderWatchNews();
    });
  });
  document.querySelectorAll("[data-part-flow-mode]").forEach((button) => {
    button.addEventListener("click", () => {
      state.partFlowMode = button.dataset.partFlowMode === "d1" ? "d1" : "ytd";
      renderPartBars(filteredStocks());
    });
  });
}
hydrateCustomStocks();
applyOverrides();
normalizeAllTaxonomy();
buildQuantScores();
populateFilters();
attachEvents();
checkApiStatus().then(() => {
  render();
  hydrateMarketIndicators();
});
























































