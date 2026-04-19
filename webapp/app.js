/* SplitBot — Telegram Mini App frontend logic */
"use strict";

const tg = window.Telegram.WebApp;

// Tell Telegram the app is ready and expand to full height
tg.ready();
tg.expand();

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------

const API_BASE = window.__SPLITBOT_API_BASE || "";
const startParam = tg.initDataUnsafe?.start_param || "";
const GROUP_ID = startParam || new URLSearchParams(window.location.search).get("group_id") || "";
const AUTH_HEADER = tg.initData ? { Authorization: "tma " + tg.initData } : {};
const DEMO_MODE = new URLSearchParams(window.location.search).get("demo") === "1" || !GROUP_ID || !tg.initData;

// Current user from Telegram
const CURRENT_USER_ID = tg.initDataUnsafe?.user?.id || null;

const DEMO_BALANCES_DATA = {
  group_id: 999001,
  base_currency: "USD",
  balances: [
    { user_id: 101, display_name: "@alice", net_balance: "210.00" },
    { user_id: 102, display_name: "@bob", net_balance: "-130.00" },
    { user_id: 103, display_name: "@charlie", net_balance: "-80.00" },
  ],
  settlements: [
    { from_id: 102, from_name: "@bob", to_id: 101, to_name: "@alice", amount: "130.00" },
    { from_id: 103, from_name: "@charlie", to_id: 101, to_name: "@alice", amount: "80.00" },
  ],
};

const DEMO_EXPENSES_DATA = {
  group_id: 999001,
  expenses: [
    {
      payer_id: 101,
      payer_name: "@alice",
      total_amount: "240.00",
      original_amount: "240.00",
      currency: "USD",
      original_currency: "USD",
      description: "Dinner at Pasta House",
      is_settlement: false,
      created_at: "2026-04-19T17:00:00Z",
      split_count: 3,
    },
    {
      payer_id: 102,
      payer_name: "@bob",
      total_amount: "90.00",
      original_amount: "90.00",
      currency: "USD",
      original_currency: "USD",
      description: "Cab to venue",
      is_settlement: false,
      created_at: "2026-04-19T15:45:00Z",
      split_count: 3,
    },
    {
      payer_id: 103,
      payer_name: "@charlie",
      total_amount: "60.00",
      original_amount: "60.00",
      currency: "USD",
      original_currency: "USD",
      description: "Snacks",
      is_settlement: false,
      created_at: "2026-04-19T14:30:00Z",
      split_count: 3,
    },
  ],
};

// ---------------------------------------------------------------------------
// TON Connect
// ---------------------------------------------------------------------------

let tonConnector = null;
let connectedWallet = null;
let cachedTonPrice = null;
let lastBalancesData = null;
let lastExpensesData = null;
let selectedStreakDays = 7;
let financeTipIndex = 0;

const DUMMY_FINANCE_TIPS = [
  "Start with the 50/30/20 rule: 50% needs, 30% wants, 20% savings.",
  "Track every shared expense right away to avoid end-of-month confusion.",
  "Build an emergency fund goal equal to 3-6 months of fixed expenses.",
  "Pay high-interest debt first, even while making minimum payments elsewhere.",
  "Review subscriptions monthly; small recurring cuts improve cash flow quickly.",
];

// TON Connect manifest — hosted alongside the app
const TON_MANIFEST_URL = (window.location.origin || API_BASE) + "/tonconnect-manifest.json";

function initTonConnect() {
  if (typeof TonConnectSDK === "undefined") {
    console.warn("TonConnect SDK not loaded");
    return;
  }

  tonConnector = new TonConnectSDK.TonConnect({ manifestUrl: TON_MANIFEST_URL });

  tonConnector.onStatusChange((wallet) => {
    connectedWallet = wallet;
    updateWalletUI();
    if (wallet && GROUP_ID) {
      saveWalletToServer(wallet.account.address);
    }
  });

  // Restore existing session
  tonConnector.restoreConnection().then(() => {
    updateWalletUI();
  });

  // Show the wallet bar
  const bar = document.getElementById("wallet-bar");
  if (bar) bar.style.display = "flex";
}

function updateWalletUI() {
  const label = document.getElementById("wallet-label");
  const addr = document.getElementById("wallet-addr");
  const btn = document.getElementById("wallet-btn");

  if (connectedWallet) {
    const rawAddr = connectedWallet.account.address;
    const short = rawAddr.slice(0, 6) + "..." + rawAddr.slice(-4);
    label.textContent = "TON Wallet Connected";
    addr.textContent = short;
    btn.textContent = "Disconnect";
    btn.className = "btn btn-disconnect";
  } else {
    label.textContent = "Connect wallet to settle on-chain";
    addr.textContent = "";
    btn.textContent = "Connect Wallet";
    btn.className = "btn btn-primary";
  }
}

async function toggleWallet() {
  if (!tonConnector) return;

  if (connectedWallet) {
    await tonConnector.disconnect();
    connectedWallet = null;
    updateWalletUI();
    showToast("Wallet disconnected");
  } else {
    // Get available wallets and open the connection modal
    const walletsList = await tonConnector.getWallets();
    // Prefer Tonkeeper, then first available
    const tonkeeper = walletsList.find(w => w.appName === "tonkeeper");
    const target = tonkeeper || walletsList[0];

    if (target) {
      const universalLink = tonConnector.connect({
        universalLink: target.universalUrl,
        bridgeUrl: target.bridgeUrl,
      });
      // Open the wallet link
      if (universalLink) {
        window.open(universalLink, "_blank");
      }
    }
  }
}
// Expose to onclick
window.toggleWallet = toggleWallet;

async function saveWalletToServer(address) {
  try {
    await fetch(API_BASE + "/api/ton/wallet", {
      method: "POST",
      headers: { ...AUTH_HEADER, "Content-Type": "application/json" },
      body: JSON.stringify({ group_id: GROUP_ID, wallet_address: address }),
    });
  } catch (e) {
    console.warn("Failed to save wallet:", e);
  }
}

// ---------------------------------------------------------------------------
// TON Settlement
// ---------------------------------------------------------------------------

async function getTonPrice() {
  if (cachedTonPrice) return cachedTonPrice;
  try {
    const data = await apiFetch("/api/ton/price");
    cachedTonPrice = parseFloat(data.price_usd);
    // Cache for 60s
    setTimeout(() => { cachedTonPrice = null; }, 60000);
    return cachedTonPrice;
  } catch (e) {
    console.error("Failed to fetch TON price:", e);
    return null;
  }
}

async function settleOnTon(fromId, toId, amountUsd, currency, toName) {
  if (!tonConnector || !connectedWallet) {
    showToast("Please connect your wallet first");
    return;
  }

  const btn = document.querySelector(`[data-settle-to="${toId}"]`);
  if (btn) {
    btn.disabled = true;
    btn.textContent = "Processing...";
  }

  try {
    // 1. Get creditor's wallet
    const walletData = await apiFetch(
      "/api/ton/wallet?group_id=" + encodeURIComponent(GROUP_ID) +
      "&user_id=" + encodeURIComponent(toId)
    );

    if (!walletData.wallet_address) {
      showToast(toName + " hasn't connected a wallet yet");
      return;
    }

    // 2. Convert amount to TON
    const tonPrice = await getTonPrice();
    if (!tonPrice) {
      showToast("Could not fetch TON price");
      return;
    }

    const amountTon = parseFloat(amountUsd) / tonPrice;
    const nanotons = Math.round(amountTon * 1e9).toString();

    // 3. Build and send the transaction
    const tx = {
      validUntil: Math.floor(Date.now() / 1000) + 600, // 10 min
      messages: [{
        address: walletData.wallet_address,
        amount: nanotons,
        payload: "", // simple TON transfer
      }],
    };

    showToast("Confirm in your wallet...");

    const result = await tonConnector.sendTransaction(tx);
    const txHash = result.boc || "";

    // 4. Verify on backend
    showToast("Verifying on-chain...");

    const verifyResp = await fetch(API_BASE + "/api/ton/verify", {
      method: "POST",
      headers: { ...AUTH_HEADER, "Content-Type": "application/json" },
      body: JSON.stringify({
        group_id: parseInt(GROUP_ID),
        to_user_id: toId,
        amount: amountUsd,
        currency: currency,
        tx_hash: txHash,
        sender_wallet: connectedWallet.account.address,
        receiver_wallet: walletData.wallet_address,
        amount_ton: amountTon.toFixed(9),
      }),
    });

    const verifyData = await verifyResp.json();

    if (verifyData.verified) {
      showToast("Settlement recorded on-chain! ✅");
      // Refresh balances
      loadBalances();
      loadExpenses();
    } else {
      // Even if on-chain verification is pending, the tx was sent
      showToast("Transaction sent! Verification may take a moment.");
      setTimeout(() => { loadBalances(); loadExpenses(); }, 5000);
    }
  } catch (e) {
    if (e.message && e.message.includes("User rejected")) {
      showToast("Transaction cancelled");
    } else {
      console.error("Settlement error:", e);
      showToast("Settlement failed: " + (e.message || "unknown error"));
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "⛓ Settle on TON";
    }
  }
}
// Expose for onclick
window.settleOnTon = settleOnTon;

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

function showToast(msg) {
  const el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg;
  el.classList.add("visible");
  setTimeout(() => el.classList.remove("visible"), 3000);
}

function addDummyFinanceReply(questionText) {
  const chatLog = $("#finance-chat-log");
  if (!chatLog) return;

  if (questionText) {
    chatLog.innerHTML +=
      '<div class="chat-bubble user"><b>You:</b> ' + esc(questionText) + "</div>";
  }

  const tip = DUMMY_FINANCE_TIPS[financeTipIndex % DUMMY_FINANCE_TIPS.length];
  financeTipIndex += 1;
  chatLog.innerHTML +=
    '<div class="chat-bubble bot"><b>Finance Coach:</b> ' + esc(tip) + "</div>";

  chatLog.scrollTop = chatLog.scrollHeight;
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
  lastBalancesData = data;

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

  // Settlements section with "Settle on TON" buttons
  if (data.settlements.length) {
    html += '<div class="section-title" style="margin-top:20px">Suggested Settlements</div>';
    for (const s of data.settlements) {
      const isCurrentUserDebtor = (s.from_id === CURRENT_USER_ID);
      html +=
        '<div class="settlement-card">' +
          '<span class="arrow">→</span>' +
          '<div class="details">' +
            '<div class="names">' + esc(s.from_name) + " pays " + esc(s.to_name) + "</div>" +
            '<div class="amt">' + esc(s.amount) + " " + esc(data.base_currency) + "</div>" +
            (isCurrentUserDebtor
              ? '<div class="settle-actions">' +
                  '<button class="btn btn-ton" data-settle-to="' + s.to_id + '" ' +
                    'onclick="settleOnTon(' + s.from_id + ',' + s.to_id + ',\'' +
                    esc(s.amount) + '\',\'' + esc(data.base_currency) + '\',\'' +
                    esc(s.to_name) + '\')">' +
                    '⛓ Settle on TON' +
                  '</button>' +
                '</div>'
              : '') +
          "</div>" +
        "</div>";
    }
  }

  container.innerHTML = html;
}

function renderExpenses(data) {
  const container = $("#expenses-content");
  lastExpensesData = data;

  if (!data.expenses.length) {
    container.innerHTML =
      '<div class="state-msg"><div class="icon">🧾</div>No expenses recorded yet.</div>';
    return;
  }

  let html = '<div class="section-title">Recent Transactions</div>';

  for (const e of data.expenses) {
    const isSettlement = e.is_settlement;
    const isBlockchain = e.description === "blockchain_settlement";
    const desc = isBlockchain ? "⛓ On-chain Settlement" : isSettlement ? "💸 Settlement" : esc(e.description);
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

function renderInsights() {
  const container = $("#insights-content");
  if (!container) return;

  if (!lastBalancesData || !lastExpensesData) {
    container.innerHTML = '<div class="loader"></div>';
    return;
  }

  const expenses = (lastExpensesData.expenses || []).filter((e) => !e.is_settlement);
  const totalSpend = expenses.reduce((sum, e) => sum + (parseFloat(e.total_amount) || 0), 0);
  const avgSpend = expenses.length ? totalSpend / expenses.length : 0;

  const payerTotals = {};
  for (const e of expenses) {
    const key = e.payer_name || "Unknown";
    payerTotals[key] = (payerTotals[key] || 0) + (parseFloat(e.total_amount) || 0);
  }
  const topSpender = Object.entries(payerTotals).sort((a, b) => b[1] - a[1])[0];

  container.innerHTML =
    '<div class="section-title">Group Analytics</div>' +
    '<div class="insight-grid">' +
      '<div class="insight-card"><div class="insight-label">Total Spend</div><div class="insight-value">' +
        totalSpend.toFixed(2) + " " + esc(lastBalancesData.base_currency || "USD") +
      "</div></div>" +
      '<div class="insight-card"><div class="insight-label">Avg Expense</div><div class="insight-value">' +
        avgSpend.toFixed(2) + " " + esc(lastBalancesData.base_currency || "USD") +
      "</div></div>" +
      '<div class="insight-card"><div class="insight-label">Top Spender</div><div class="insight-value">' +
        esc(topSpender ? topSpender[0] : "N/A") +
      "</div></div>" +
      '<div class="insight-card"><div class="insight-label">Tracked Transactions</div><div class="insight-value">' +
        String(expenses.length) +
      "</div></div>" +
    "</div>" +
    '<div class="section-title">Expense Streaks</div>' +
    '<div class="streak-row">' +
      '<button class="btn btn-streak" data-streak-days="3">🔥 3-day streak</button>' +
      '<button class="btn btn-streak" data-streak-days="7">💪 7-day streak</button>' +
      '<button class="btn btn-streak" data-streak-days="14">🏆 14-day streak</button>' +
    "</div>" +
    '<div class="state-msg" style="padding:8px 0 14px;font-size:13px">Current streak goal: <b>' +
      String(selectedStreakDays) +
      " days</b></div>" +
    '<div class="section-title">Learn More About Finance</div>' +
    '<div class="finance-chat">' +
      '<div id="finance-chat-log" class="chat-log">' +
        '<div class="chat-bubble bot"><b>Finance Coach:</b> Ask me anything about budgeting, debt, or saving. (Demo chatbot)</div>' +
      "</div>" +
      '<button id="learn-finance-btn" class="btn btn-primary" style="width:100%">Learn more about finance</button>' +
    "</div>";

  $$("[data-streak-days]").forEach((btn) => {
    btn.addEventListener("click", () => {
      selectedStreakDays = Number(btn.dataset.streakDays || "7");
      showToast("Streak goal set to " + selectedStreakDays + " days");
      renderInsights();
    });
  });

  const learnBtn = $("#learn-finance-btn");
  if (learnBtn) {
    learnBtn.addEventListener("click", () => {
      addDummyFinanceReply("Teach me one practical finance tip.");
    });
  }
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
  if (DEMO_MODE) {
    renderBalances(DEMO_BALANCES_DATA);
    renderInsights();
    return;
  }
  try {
    const data = await apiFetch("/api/balances?group_id=" + encodeURIComponent(GROUP_ID));
    renderBalances(data);
    renderInsights();
  } catch (err) {
    showError(container, err.message || "Failed to load balances");
  }
}

async function loadExpenses() {
  const container = $("#expenses-content");
  if (DEMO_MODE) {
    renderExpenses(DEMO_EXPENSES_DATA);
    renderInsights();
    return;
  }
  try {
    const data = await apiFetch("/api/expenses?group_id=" + encodeURIComponent(GROUP_ID));
    renderExpenses(data);
    renderInsights();
  } catch (err) {
    showError(container, err.message || "Failed to load expenses");
  }
}

// ---------------------------------------------------------------------------
// Bootstrap
// ---------------------------------------------------------------------------

loadBalances();
loadExpenses();

if (DEMO_MODE) {
  showToast("Demo mode: showing sample balances and expenses");
} else {
  initTonConnect();
}
