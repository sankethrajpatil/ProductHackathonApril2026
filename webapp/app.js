/* SplitBot — Telegram Mini App frontend logic */
"use strict";

const tg = window.Telegram.WebApp;

// Tell Telegram the app is ready and expand to full height
tg.ready();
tg.expand();

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

// The API base URL is relative when served from the same aiohttp server.
// Override via a global if the webapp is hosted elsewhere.
const API_BASE = window.__SPLITBOT_API_BASE || "";

// Extract group_id from the start_param (set when the WebAppInfo button is
// pressed — we encode the group chat ID there).
const startParam = tg.initDataUnsafe?.start_param || "";
const GROUP_ID = startParam || new URLSearchParams(window.location.search).get("group_id") || "";

// Auth header — pass raw initData for server-side HMAC validation
const AUTH_HEADER = tg.initData ? { Authorization: "tma " + tg.initData } : {};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function $(sel) { return document.querySelector(sel); }
function $$(sel) { return document.querySelectorAll(sel); }

function esc(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

function formatAmount(amount, currency) {
  const n = parseFloat(amount);
  const sign = n >= 0 ? "+" : "";
  return sign + n.toFixed(2) + " " + (currency || "");
}

function relativeTime(isoString) {
  if (!isoString) return "";
  const date = new Date(isoString);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "just now";
  if (diffMins < 60) return diffMins + "m ago";
  const diffHrs = Math.floor(diffMins / 60);
  if (diffHrs < 24) return diffHrs + "h ago";
  const diffDays = Math.floor(diffHrs / 24);
  if (diffDays < 7) return diffDays + "d ago";
  return date.toLocaleDateString();
}

async function apiFetch(endpoint) {
  const url = API_BASE + endpoint;
  const resp = await fetch(url, { headers: AUTH_HEADER });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new Error(body.error || "API error " + resp.status);
  }
  return resp.json();
}

// ---------------------------------------------------------------------------
// Tab switching
// ---------------------------------------------------------------------------

$$(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    $$(".tab").forEach((t) => t.classList.remove("active"));
    $$(".panel").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    const panel = document.getElementById(tab.dataset.panel);
    if (panel) panel.classList.add("active");
  });
});

// ---------------------------------------------------------------------------
// Render functions
// ---------------------------------------------------------------------------

function renderBalances(data) {
  const container = $("#balances-content");

  if (!data.balances.length && !data.settlements.length) {
    container.innerHTML =
      '<div class="state-msg"><div class="icon">📊</div>No balances yet.<br>Start adding expenses in the group chat!</div>';
    return;
  }

  let html = "";

  // Net balances section
  if (data.balances.length) {
    html += '<div class="section-title">Net Balances (' + esc(data.base_currency) + ")</div>";
    for (const b of data.balances) {
      const n = parseFloat(b.net_balance);
      const cls = n > 0 ? "positive" : n < 0 ? "negative" : "";
      html +=
        '<div class="balance-card">' +
          '<span class="name">' + esc(b.display_name) + "</span>" +
          '<span class="amount ' + cls + '">' + formatAmount(b.net_balance, data.base_currency) + "</span>" +
        "</div>";
    }
  }

  // Settlements section
  if (data.settlements.length) {
    html += '<div class="section-title" style="margin-top:20px">Suggested Settlements</div>';
    for (const s of data.settlements) {
      html +=
        '<div class="settlement-card">' +
          '<span class="arrow">→</span>' +
          '<div class="details">' +
            '<div class="names">' + esc(s.from_name) + " pays " + esc(s.to_name) + "</div>" +
            '<div class="amt">' + esc(s.amount) + " " + esc(data.base_currency) + "</div>" +
          "</div>" +
        "</div>";
    }
  }

  container.innerHTML = html;
}

function renderExpenses(data) {
  const container = $("#expenses-content");

  if (!data.expenses.length) {
    container.innerHTML =
      '<div class="state-msg"><div class="icon">🧾</div>No expenses recorded yet.</div>';
    return;
  }

  let html = '<div class="section-title">Recent Transactions</div>';

  for (const e of data.expenses) {
    const isSettlement = e.is_settlement;
    const desc = isSettlement ? "💸 Settlement" : esc(e.description);
    const cls = isSettlement ? " settlement" : "";

    let conversionNote = "";
    if (e.original_currency && e.currency && e.original_currency !== e.currency) {
      conversionNote =
        " (orig: " + esc(e.original_amount) + " " + esc(e.original_currency) + ")";
    }

    html +=
      '<div class="expense-item' + cls + '">' +
        '<div class="top">' +
          '<span class="desc">' + desc + "</span>" +
          '<span class="amt">' + esc(e.total_amount) + " " + esc(e.currency) + "</span>" +
        "</div>" +
        '<div class="meta">' +
          "Paid by " + esc(e.payer_name) +
          " · Split " + e.split_count + " way" + (e.split_count !== 1 ? "s" : "") +
          conversionNote +
          " · " + relativeTime(e.created_at) +
        "</div>" +
      "</div>";
  }

  container.innerHTML = html;
}

function showError(container, message) {
  container.innerHTML =
    '<div class="state-msg"><div class="icon">⚠️</div>' + esc(message) + "</div>";
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------

async function loadBalances() {
  const container = $("#balances-content");
  try {
    const data = await apiFetch("/api/balances?group_id=" + encodeURIComponent(GROUP_ID));
    renderBalances(data);
  } catch (err) {
    showError(container, err.message || "Failed to load balances");
  }
}

async function loadExpenses() {
  const container = $("#expenses-content");
  try {
    const data = await apiFetch("/api/expenses?group_id=" + encodeURIComponent(GROUP_ID));
    renderExpenses(data);
  } catch (err) {
    showError(container, err.message || "Failed to load expenses");
  }
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

if (!GROUP_ID) {
  showError(
    $("#balances-content"),
    "No group context. Please open this dashboard from a group chat."
  );
  showError(
    $("#expenses-content"),
    "No group context. Please open this dashboard from a group chat."
  );
} else {
  // Load both panels in parallel
  loadBalances();
  loadExpenses();
}
