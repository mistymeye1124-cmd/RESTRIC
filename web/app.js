/* ==========================================================================
   RESTRICTED FORWARD BOT PRO — CLIENT CONTROLLER & MINI APP STUDIO
   ========================================================================== */

document.addEventListener("DOMContentLoaded", () => {
  initTelegramWebApp();
  initTabs();
  initWatermarkSimulator();
  initTelegramCardSimulator();
  initClonerControls();
  initStatsPolling();
  initUsersTable();
  initTransactionsTable();
  initLogsPolling();
});

// ==========================================================================
// 1. TELEGRAM WEBAPP SDK INTEGRATION
// ==========================================================================
function initTelegramWebApp() {
  if (window.Telegram && window.Telegram.WebApp) {
    const tg = window.Telegram.WebApp;
    try {
      tg.ready();
      tg.expand();
      document.getElementById("appModeBadge").style.display = "inline-flex";
      document.getElementById("appModeText").textContent = "Telegram Mini App Active";
      
      // If user info is available from Telegram Mini App initDataUnsafe
      if (tg.initDataUnsafe && tg.initDataUnsafe.user) {
        const u = tg.initDataUnsafe.user;
        const name = u.first_name || "Harvester";
        showToast(`Welcome to Studio, ${name}!`, "info");
      }
    } catch (e) {
      console.log("[Telegram WebApp init error]", e);
    }
  }
}

// ==========================================================================
// 2. TAB CONTROLLER
// ==========================================================================
function initTabs() {
  const tabs = document.querySelectorAll(".tab-btn");
  const contents = document.querySelectorAll(".tab-content");

  tabs.forEach(tab => {
    tab.addEventListener("click", () => {
      const targetId = tab.dataset.tab;
      
      tabs.forEach(t => t.classList.remove("active"));
      contents.forEach(c => c.classList.remove("active"));

      tab.classList.add("active");
      const targetContent = document.getElementById(targetId);
      if (targetContent) {
        targetContent.classList.add("active");
      }
    });
  });
}

// ==========================================================================
// 3. INTERACTIVE TELEGRAM CARD SIMULATOR
// ==========================================================================
let simPct = 52.0;
let simInterval = null;

function initTelegramCardSimulator() {
  const blocksEl = document.getElementById("tgSimBlocks");
  const pctEl = document.getElementById("tgSimPct");
  const speedEl = document.getElementById("tgSimSpeed");
  const etaEl = document.getElementById("tgSimEta");
  const doneEl = document.getElementById("tgSimDone");
  const totalMB = 237.1;

  if (simInterval) clearInterval(simInterval);

  simInterval = setInterval(() => {
    simPct += 1.8;
    if (simPct > 99) {
      simPct = 12.0;
    }

    const pctInt = Math.floor(simPct);
    const totalBlocks = 8;
    const filledCount = Math.round((pctInt / 100) * totalBlocks);
    const filled = "▰".repeat(filledCount);
    const empty = "▱".repeat(totalBlocks - filledCount);

    if (blocksEl) blocksEl.textContent = `${filled}${empty}`;
    if (pctEl) pctEl.textContent = `${simPct.toFixed(1)}%`;

    const doneMB = ((simPct / 100) * totalMB).toFixed(1);
    if (doneEl) doneEl.textContent = `${doneMB} MB`;

    const speed = (34.0 + Math.random() * 8.5).toFixed(1);
    if (speedEl) speedEl.textContent = `${speed} MB/s`;

    const remainingMB = totalMB - parseFloat(doneMB);
    const etaSec = Math.max(1, Math.round(remainingMB / parseFloat(speed)));
    if (etaEl) etaEl.textContent = `${etaSec}s`;
  }, 1000);
}

function openTgModalAlert() {
  const bodyText = `⬇️ <b>Downloading from Telegram:</b> ${simPct.toFixed(1)}%<br>` +
    `⚡ <b>Speed:</b> ${document.getElementById("tgSimSpeed").textContent}<br>` +
    `⏱️ <b>ETA:</b> ${document.getElementById("tgSimEta").textContent}<br>` +
    `📦 <b>Progress:</b> ${document.getElementById("tgSimDone").textContent} / 237.1 MB<br>` +
    `🛡️ <b>Engine:</b> MTProto Turbo Sockets`;

  if (window.Telegram && window.Telegram.WebApp && window.Telegram.WebApp.showPopup) {
    window.Telegram.WebApp.showPopup({
      title: "Active Task Progress ⚡",
      message: `Downloading: ${simPct.toFixed(1)}%\nSpeed: ${document.getElementById("tgSimSpeed").textContent}\nETA: ${document.getElementById("tgSimEta").textContent}`,
      buttons: [{ type: "ok", text: "Close" }]
    });
  } else {
    document.getElementById("tgModalBody").innerHTML = bodyText;
    document.getElementById("tgModalAlert").style.display = "flex";
  }
}

function closeTgModalAlert() {
  document.getElementById("tgModalAlert").style.display = "none";
}

function simCancelTask() {
  if (confirm("Cancel this simulated restricted download task?")) {
    simPct = 0;
    showToast("Task cancelled cleanly by user.", "info");
  }
}

// ==========================================================================
// 4. FORWARD DISPATCH PIPELINE
// ==========================================================================
async function triggerForward() {
  const linkInput = document.getElementById("targetLink");
  const formatSelect = document.getElementById("targetFormat");
  const destSelect = document.getElementById("targetDestination");
  const stripHeader = document.getElementById("chkStripHeader").checked;
  const btn = document.getElementById("btnDispatch");

  const link = linkInput.value.trim();
  if (!link) return;

  btn.disabled = true;
  btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Dispatching...`;

  try {
    const res = await fetch("/api/forward", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        link: link,
        format: formatSelect.value,
        destination: destSelect.value,
        strip_header: stripHeader,
      }),
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Restricted post #${data.job_id} dispatched to ${destSelect.value}!`, "success");
      // Update simulated card with this filename
      const simName = document.getElementById("tgSimFileName");
      if (simName) {
        simName.textContent = link.includes("/") ? link.split("/").pop() : "Extracted_Media.mp4";
      }
      simPct = 5.0; // restart progress simulation
    } else {
      showToast(data.error || "Dispatch failed", "error");
    }
  } catch (e) {
    showToast("Server communication error. Check local server.", "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i class="fa-solid fa-bolt"></i> Launch Forward Pipeline`;
  }
}

// ==========================================================================
// 5. CHANNEL CLONER CONTROLS
// ==========================================================================
function initClonerControls() {
  const startEl = document.getElementById("clonerStartId");
  const endEl = document.getElementById("clonerEndId");
  const batchEl = document.getElementById("clonerTotalBatch");

  function updateBatch() {
    const s = parseInt(startEl.value, 10) || 1;
    const e = parseInt(endEl.value, 10) || 1;
    const count = Math.max(1, e - s + 1);
    if (batchEl) {
      batchEl.textContent = `${count} Posts in Range`;
    }
  }

  if (startEl && endEl) {
    startEl.addEventListener("input", updateBatch);
    endEl.addEventListener("input", updateBatch);
  }
}

async function launchClonerTask() {
  const src = document.getElementById("clonerSource").value.trim();
  const dst = document.getElementById("clonerDestination").value.trim();
  const s = parseInt(document.getElementById("clonerStartId").value, 10) || 1;
  const e = parseInt(document.getElementById("clonerEndId").value, 10) || 50;
  const btn = document.getElementById("btnLaunchCloner");

  btn.disabled = true;
  btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Initializing Cloner...`;

  try {
    const res = await fetch("/api/cloner/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        source: src,
        destination: dst,
        start_id: s,
        end_id: e,
      }),
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Channel Cloner #${data.clone_id} launched for ${data.total_posts} posts!`, "success");
    } else {
      showToast(data.error || "Failed to launch cloner", "error");
    }
  } catch (err) {
    showToast("Cloner API unreachable", "error");
  } finally {
    btn.disabled = false;
    btn.innerHTML = `<i class="fa-solid fa-play"></i> Launch Channel Mirror Task`;
  }
}

// ==========================================================================
// 6. LIVE WATERMARK SIMULATOR
// ==========================================================================
let bounceAnimationId = null;
let bounceAngle = 0;

function initWatermarkSimulator() {
  const textInput = document.getElementById("wmTextInput");
  const headlineInput = document.getElementById("wmHeadlineInput");
  const styleSelect = document.getElementById("wmStyleSelect");
  const posSelect = document.getElementById("wmPositionSelect");
  const opacityRange = document.getElementById("wmOpacityRange");
  const fontRange = document.getElementById("wmFontSizeRange");
  const bounceRange = document.getElementById("wmBounceRange");
  const bounceGroup = document.getElementById("bounceSpeedGroup");

  const badge = document.getElementById("simWatermarkBadge");
  const headline = document.getElementById("simHeadlineBanner");

  function updateSimulator() {
    badge.textContent = textInput.value || "@Channel";

    if (headlineInput.value && headlineInput.value.trim().length > 0) {
      headline.textContent = headlineInput.value.trim();
      headline.style.display = "block";
    } else {
      headline.style.display = "none";
    }

    badge.className = `live-watermark-overlay ${styleSelect.value}`;

    const opVal = opacityRange.value / 100;
    badge.style.opacity = opVal;
    document.getElementById("wmOpacityVal").textContent = `${opacityRange.value}%`;

    badge.style.fontSize = `${fontRange.value}px`;
    document.getElementById("wmFontSizeVal").textContent = `${fontRange.value}px`;

    const pos = posSelect.value;
    if (pos === "moving") {
      bounceGroup.style.display = "block";
      startBounceAnimation();
    } else {
      bounceGroup.style.display = "none";
      stopBounceAnimation();
      applyStaticPosition(pos);
    }
  }

  function applyStaticPosition(pos) {
    badge.style.transform = "none";
    badge.style.top = "auto";
    badge.style.bottom = "auto";
    badge.style.left = "auto";
    badge.style.right = "auto";

    switch(pos) {
      case "bottom_right":
        badge.style.bottom = "20px";
        badge.style.right = "20px";
        break;
      case "bottom_left":
        badge.style.bottom = "20px";
        badge.style.left = "20px";
        break;
      case "top_right":
        badge.style.top = headline.style.display === "block" ? "50px" : "20px";
        badge.style.right = "20px";
        break;
      case "top_left":
        badge.style.top = headline.style.display === "block" ? "50px" : "20px";
        badge.style.left = "20px";
        break;
      case "center":
        badge.style.top = "50%";
        badge.style.left = "50%";
        badge.style.transform = "translate(-50%, -50%)";
        break;
      default:
        badge.style.bottom = "20px";
        badge.style.right = "20px";
    }
  }

  function startBounceAnimation() {
    if (bounceAnimationId) return;
    const preview = document.getElementById("videoPreviewBox");
    function step() {
      const speed = parseInt(bounceRange.value, 10) || 3;
      document.getElementById("wmBounceVal").textContent = `${speed}x Speed`;
      
      bounceAngle += 0.02 * speed;
      const rect = preview.getBoundingClientRect();
      const badgeRect = badge.getBoundingClientRect();

      const maxX = (rect.width - badgeRect.width) / 2 - 20;
      const maxY = (rect.height - badgeRect.height) / 2 - 30;

      const posX = Math.sin(bounceAngle) * maxX;
      const posY = Math.cos(bounceAngle * 0.75) * maxY;

      badge.style.top = "50%";
      badge.style.left = "50%";
      badge.style.transform = `translate(calc(-50% + ${posX}px), calc(-50% + ${posY}px))`;

      bounceAnimationId = requestAnimationFrame(step);
    }
    bounceAnimationId = requestAnimationFrame(step);
  }

  function stopBounceAnimation() {
    if (bounceAnimationId) {
      cancelAnimationFrame(bounceAnimationId);
      bounceAnimationId = null;
    }
  }

  [textInput, headlineInput, styleSelect, posSelect, opacityRange, fontRange, bounceRange].forEach(input => {
    if (input) input.addEventListener("input", updateSimulator);
  });

  updateSimulator();

  // Save Settings
  const btnSave = document.getElementById("btnSaveWmConfig");
  if (btnSave) {
    btnSave.addEventListener("click", async () => {
      btnSave.disabled = true;
      btnSave.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> Saving...`;
      try {
        const payload = {
          watermark_text: textInput.value.trim(),
          headline_text: headlineInput.value.trim(),
          style: styleSelect.value,
          position: posSelect.value,
          opacity: opacityRange.value / 100,
          font_size: parseInt(fontRange.value, 10),
          bounce_speed: parseInt(bounceRange.value, 10),
        };
        const res = await fetch("/api/watermark", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.success) {
          showToast("Watermark profile saved to database!", "success");
        } else {
          showToast(data.error || "Save error", "error");
        }
      } catch (e) {
        showToast("Watermark save failed.", "error");
      } finally {
        btnSave.disabled = false;
        btnSave.innerHTML = `<i class="fa-solid fa-floppy-disk"></i> Save Studio Preset`;
      }
    });
  }

  // Free Watermark Master Switch
  const btnFreeWm = document.getElementById("btnToggleFreeWm");
  if (btnFreeWm) {
    btnFreeWm.addEventListener("click", async () => {
      try {
        const res = await fetch("/api/toggle_freewm", { method: "POST" });
        const data = await res.json();
        const lbl = document.getElementById("freeWmStateLabel");
        if (lbl) {
          lbl.textContent = `Free Watermark: ${data.enabled ? "ON" : "OFF"}`;
        }
        showToast(`Free User Watermark is now ${data.enabled ? "ENABLED" : "DISABLED"}!`, "info");
      } catch (e) {
        showToast("Failed to toggle free watermark", "error");
      }
    });
  }
}

// ==========================================================================
// 7. THUMBNAILS & CAPTION SMART TAGS
// ==========================================================================
function previewThumbnailFile(input) {
  if (input.files && input.files[0]) {
    const reader = new FileReader();
    reader.onload = function(e) {
      const box = document.getElementById("thumbPreviewBox");
      box.innerHTML = `<img src="${e.target.result}" style="width: 100%; height: 100%; object-fit: cover;">`;
      showToast("Custom cover loaded for preview!", "info");
    };
    reader.readAsDataURL(input.files[0]);
  }
}

function insertTag(tag) {
  const ta = document.getElementById("captionTemplate");
  if (ta) {
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const text = ta.value;
    ta.value = text.substring(0, start) + tag + text.substring(end);
    ta.focus();
    ta.selectionStart = ta.selectionEnd = start + tag.length;
  }
}

// ==========================================================================
// 8. TELEMETRY & STATS POLLING
// ==========================================================================
function initStatsPolling() {
  fetchStats();
  setInterval(fetchStats, 10000);

  const refreshBtn = document.getElementById("refreshStatsBtn");
  if (refreshBtn) {
    refreshBtn.addEventListener("click", () => {
      fetchStats();
      fetchUsers();
      fetchTransactions();
      fetchSystemLogs();
      showToast("Dashboard telemetry refreshed!", "info");
    });
  }
}

async function fetchStats() {
  try {
    const res = await fetch("/api/status");
    if (!res.ok) return;
    const data = await res.json();

    document.getElementById("statTotalUsers").textContent = data.users_count.toLocaleString();
    document.getElementById("statTotalDownloads").textContent = data.downloads_count.toLocaleString();
    document.getElementById("statVipUsers").textContent = data.vip_count.toLocaleString();

    const pendingBadge = document.getElementById("pendingTrxBadge");
    if (pendingBadge) {
      pendingBadge.textContent = `${data.pending_trx_count} Pending Transactions`;
    }

    const badge = document.getElementById("botStatusBadge");
    const text = document.getElementById("botStatusText");
    if (data.bot_online) {
      badge.style.color = "var(--accent-green)";
      badge.style.borderColor = "rgba(0, 255, 163, 0.3)";
      text.textContent = "MTProto Engine Active";
    } else {
      badge.style.color = "var(--accent-red)";
      badge.style.borderColor = "rgba(255, 51, 102, 0.3)";
      text.textContent = "Offline";
    }
  } catch (e) {
    console.log("[Status Poll Failed]", e);
  }
}

// ==========================================================================
// 9. USERS DATABASE TABLE & SEARCH
// ==========================================================================
let allUsersData = [];

function initUsersTable() {
  fetchUsers();
}

async function fetchUsers() {
  const tbody = document.getElementById("usersTableBody");
  try {
    const res = await fetch("/api/users");
    if (!res.ok) return;
    allUsersData = await res.json();
    renderUsersTable(allUsersData);
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--accent-red);">Failed to connect to database.</td></tr>`;
  }
}

function renderUsersTable(users) {
  const tbody = document.getElementById("usersTableBody");
  if (!users || users.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align: center; color: var(--text-dim); padding: 30px;">No registered harvesters yet.</td></tr>`;
    return;
  }

  tbody.innerHTML = users.map(u => {
    const isVip = u.is_premium === 1;
    const badgeHtml = isVip 
      ? `<span class="badge-vip"><i class="fa-solid fa-crown"></i> VIP PASS</span>`
      : `<span class="badge-free">FREE TIER</span>`;

    const btnClass = isVip ? "btn-cyber-danger" : "btn-cyber-success";
    const btnText = isVip ? "Revoke VIP" : "Grant VIP";
    const newTargetState = isVip ? 0 : 1;

    return `
      <tr>
        <td style="font-family: var(--font-mono); color: var(--accent-cyan); font-weight: 600;">${u.user_id}</td>
        <td>
          <div style="font-weight: 600; color: var(--text-main);">${escapeHtml(u.first_name || "Harvester")}</div>
          <div style="font-size: 0.78rem; color: var(--text-dim);">${u.username ? '@' + u.username : 'No handle'}</div>
        </td>
        <td>${badgeHtml}</td>
        <td style="font-family: var(--font-mono); font-weight: 600;">${u.daily_downloads_used || 0} files</td>
        <td style="font-family: var(--font-mono); font-weight: 600; color: var(--accent-gold);">${u.total_downloads || 0}</td>
        <td>
          <button class="${btnClass}" onclick="toggleUserVip(${u.user_id}, ${newTargetState})">
            ${btnText}
          </button>
        </td>
      </tr>
    `;
  }).join("");
}

function filterUsersTable() {
  const q = document.getElementById("userSearchInput").value.toLowerCase();
  const filtered = allUsersData.filter(u => 
    String(u.user_id).includes(q) || 
    (u.first_name && u.first_name.toLowerCase().includes(q)) ||
    (u.username && u.username.toLowerCase().includes(q))
  );
  renderUsersTable(filtered);
}

async function toggleUserVip(userId, newState) {
  try {
    const res = await fetch("/api/user_vip", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId, is_premium: newState })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`User ${userId} VIP status updated!`, "success");
      fetchUsers();
      fetchStats();
    } else {
      showToast(data.error || "Update failed", "error");
    }
  } catch (e) {
    showToast("Failed to update VIP status", "error");
  }
}

// ==========================================================================
// 10. TRANSACTIONS & PAYMENT APPROVAL
// ==========================================================================
function initTransactionsTable() {
  fetchTransactions();
}

async function fetchTransactions() {
  const tbody = document.getElementById("transactionsTableBody");
  try {
    const res = await fetch("/api/transactions");
    if (!res.ok) return;
    const trxs = await res.json();
    renderTransactionsTable(trxs);
  } catch (e) {
    console.log("[Transactions fetch failed]", e);
  }
}

function renderTransactionsTable(trxs) {
  const tbody = document.getElementById("transactionsTableBody");
  if (!trxs || trxs.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" style="text-align: center; color: var(--text-dim); padding: 30px;">No pending transactions in queue.</td></tr>`;
    return;
  }

  tbody.innerHTML = trxs.map(t => {
    const isPending = t.status === "pending";
    const statusBadge = isPending 
      ? `<span class="badge-pending">PENDING</span>`
      : (t.status === "approved" ? `<span class="badge-vip">APPROVED</span>` : `<span class="badge-free">REJECTED</span>`);

    const actionHtml = isPending ? `
      <div style="display: flex; gap: 8px;">
        <button class="btn-cyber-success" style="padding: 4px 10px; font-size: 0.75rem;" onclick="processTrx(${t.id}, 'approve')">
          <i class="fa-solid fa-check"></i> Approve
        </button>
        <button class="btn-cyber-danger" style="padding: 4px 10px; font-size: 0.75rem;" onclick="processTrx(${t.id}, 'reject')">
          <i class="fa-solid fa-xmark"></i> Reject
        </button>
      </div>
    ` : `<span style="font-size: 0.8rem; color: var(--text-dim);">Processed</span>`;

    return `
      <tr>
        <td style="font-family: var(--font-mono); font-size: 0.8rem;">#${t.id}</td>
        <td style="font-family: var(--font-mono); color: var(--accent-cyan); font-weight: 600;">${t.user_id}</td>
        <td><b>${escapeHtml(t.plan_key || "VIP")}</b></td>
        <td style="font-family: var(--font-mono); color: var(--accent-green); font-weight: 700;">${t.amount || 0} ৳</td>
        <td><span class="badge-free">${escapeHtml(t.method || "bKash")}</span></td>
        <td style="font-family: var(--font-mono); font-size: 0.82rem; color: var(--accent-gold);">${escapeHtml(t.trx_id || "--")}</td>
        <td style="font-family: var(--font-mono); font-size: 0.82rem;">${escapeHtml(t.sender_number || "--")}</td>
        <td>${statusBadge}</td>
        <td>${actionHtml}</td>
      </tr>
    `;
  }).join("");
}

async function processTrx(id, action) {
  try {
    const res = await fetch("/api/transaction_action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: id, action: action })
    });
    const data = await res.json();
    if (data.success) {
      showToast(`Transaction #${id} ${action}d successfully!`, "success");
      fetchTransactions();
      fetchUsers();
      fetchStats();
    } else {
      showToast(data.error || "Action failed", "error");
    }
  } catch (e) {
    showToast("Failed to process transaction", "error");
  }
}

// ==========================================================================
// 11. LIVE TELEMETRY LOGS
// ==========================================================================
function initLogsPolling() {
  fetchSystemLogs();
  setInterval(fetchSystemLogs, 8000);
}

async function fetchSystemLogs() {
  const terminal = document.getElementById("terminalBox");
  if (!terminal) return;

  try {
    const res = await fetch("/api/logs");
    if (!res.ok) return;
    const logs = await res.json();

    terminal.innerHTML = logs.map(l => `
      <div class="terminal-line ${l.level}">
        <span class="time">[${l.time}]</span>
        <span class="text">${escapeHtml(l.msg)}</span>
      </div>
    `).join("");

    terminal.scrollTop = terminal.scrollHeight;
  } catch (e) {
    // silently catch log poll error
  }
}

// ==========================================================================
// 12. UTILITY FUNCTIONS
// ==========================================================================
function showToast(message, type = "info") {
  const container = document.getElementById("toastContainer");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  
  let icon = "fa-circle-info";
  if (type === "success") icon = "fa-circle-check";
  if (type === "error") icon = "fa-triangle-exclamation";

  toast.innerHTML = `<i class="fa-solid ${icon}"></i> <span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(100%)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
