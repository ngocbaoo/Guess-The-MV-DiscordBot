/* ══════════════════════════════════════════════════════════════
   MV Search Tool — Frontend Logic
   ══════════════════════════════════════════════════════════════ */

let searchResults = [];
let selectedSet = new Set(); // video_ids that are selected

// ── Init ────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  loadStats();

  // Enter key triggers search
  document.getElementById("artist-input").addEventListener("keydown", (e) => {
    if (e.key === "Enter") searchArtist();
  });
});

// ── Load Stats ──────────────────────────────────────────────
async function loadStats() {
  try {
    const res = await fetch("/api/songs");
    const data = await res.json();
    document.getElementById("stat-filled").textContent = data.songs.length;
    document.getElementById("stat-empty").textContent = data.empty_slots;
  } catch (e) {
    console.error("Failed to load stats:", e);
  }
}

// ── Search ──────────────────────────────────────────────────
async function searchArtist() {
  const input = document.getElementById("artist-input");
  const artist = input.value.trim();
  if (!artist) {
    showToast("Nhập tên nghệ sĩ trước!", "error");
    input.focus();
    return;
  }

  // Show loading
  document.getElementById("loading-section").style.display = "block";
  document.getElementById("results-section").style.display = "none";
  document.getElementById("search-btn").disabled = true;

  // Animate progress
  const progressFill = document.getElementById("progress-fill");
  progressFill.style.width = "0%";
  let progress = 0;
  const progressInterval = setInterval(() => {
    progress += Math.random() * 8 + 2;
    if (progress > 90) progress = 90;
    progressFill.style.width = progress + "%";
  }, 500);

  try {
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ artist }),
    });

    clearInterval(progressInterval);
    progressFill.style.width = "100%";

    const data = await res.json();

    if (data.error) {
      showToast(data.error, "error");
      return;
    }

    searchResults = data.results;
    selectedSet.clear();
    renderResults(artist);

    if (searchResults.length === 0) {
      showToast("Không tìm thấy MV nào. Thử tên khác?", "info");
    } else {
      showToast(`Tìm được ${searchResults.length} MV!`, "success");
    }
  } catch (e) {
    clearInterval(progressInterval);
    showToast("Lỗi kết nối server!", "error");
    console.error(e);
  } finally {
    document.getElementById("loading-section").style.display = "none";
    document.getElementById("search-btn").disabled = false;
  }
}

// ── Render Results ──────────────────────────────────────────
function renderResults(artist) {
  const section = document.getElementById("results-section");
  const grid = document.getElementById("results-grid");
  const countBadge = document.getElementById("results-count");
  const title = document.getElementById("results-title");

  section.style.display = "block";
  title.textContent = `Kết quả cho "${artist}"`;
  countBadge.textContent = searchResults.length;

  grid.innerHTML = searchResults
    .map((r, i) => createCardHTML(r, i))
    .join("");

  updateAddButton();
}

function createCardHTML(r, index) {
  const existsClass = r.exists ? "exists" : "";
  const selectedClass = selectedSet.has(r.video_id) ? "selected" : "";
  const views = formatViews(r.view_count);
  const duration = formatDuration(r.duration);
  const thumbUrl = r.thumbnail || `https://i.ytimg.com/vi/${r.video_id}/mqdefault.jpg`;

  return `
    <div class="result-card glass ${existsClass} ${selectedClass}"
         data-id="${r.video_id}" data-index="${index}"
         onclick="toggleCard('${r.video_id}')">
      <div class="card-checkbox">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
      </div>
      <div class="card-inner">
        <div class="card-thumbnail">
          <img src="${thumbUrl}" alt="" loading="lazy"
               onerror="this.src='data:image/svg+xml,%3Csvg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 16 9%22%3E%3Crect fill=%22%23222%22 width=%2216%22 height=%229%22/%3E%3C/svg%3E'">
          <span class="card-duration">${duration}</span>
        </div>
        <div class="card-info">
          <div class="card-original-title" title="${escapeHTML(r.original_title)}">${escapeHTML(r.original_title)}</div>
          <div class="card-channel">${escapeHTML(r.channel)}</div>
          <div class="card-views">${views} lượt xem</div>
        </div>
      </div>
      <div class="card-url" onclick="event.stopPropagation()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/>
          <polyline points="15 3 21 3 21 9"/>
          <line x1="10" y1="14" x2="21" y2="3"/>
        </svg>
        <a href="${escapeAttr(r.url)}" target="_blank" rel="noopener">${escapeHTML(r.url)}</a>
      </div>
      <div class="card-editable-fields" onclick="event.stopPropagation()">
        <div class="editable-field" style="flex: 1.5;">
          <label>Tên bài hát</label>
          <input type="text" class="field-title" data-vid="${r.video_id}"
                 value="${escapeAttr(r.clean_title)}"
                 onfocus="ensureSelected('${r.video_id}')"
                 placeholder="Nhập tên bài hát...">
        </div>
        <div class="editable-field">
          <label>Nghệ sĩ</label>
          <input type="text" class="field-artist" data-vid="${r.video_id}"
                 value="${escapeAttr(r.artist)}"
                 onfocus="ensureSelected('${r.video_id}')"
                 placeholder="Tên nghệ sĩ...">
        </div>
      </div>
    </div>
  `;
}

// ── Card Interactions ───────────────────────────────────────
function toggleCard(videoId) {
  const r = searchResults.find((x) => x.video_id === videoId);
  if (!r || r.exists) return;

  if (selectedSet.has(videoId)) {
    selectedSet.delete(videoId);
  } else {
    selectedSet.add(videoId);
  }

  const card = document.querySelector(`[data-id="${videoId}"]`);
  if (card) card.classList.toggle("selected", selectedSet.has(videoId));

  updateAddButton();
}

function ensureSelected(videoId) {
  const r = searchResults.find((x) => x.video_id === videoId);
  if (!r || r.exists) return;

  if (!selectedSet.has(videoId)) {
    selectedSet.add(videoId);
    const card = document.querySelector(`[data-id="${videoId}"]`);
    if (card) card.classList.add("selected");
    updateAddButton();
  }
}

function selectAll() {
  searchResults.forEach((r) => {
    if (!r.exists) {
      selectedSet.add(r.video_id);
      const card = document.querySelector(`[data-id="${r.video_id}"]`);
      if (card) card.classList.add("selected");
    }
  });
  updateAddButton();
}

function deselectAll() {
  selectedSet.clear();
  document.querySelectorAll(".result-card.selected").forEach((c) => {
    c.classList.remove("selected");
  });
  updateAddButton();
}

function updateAddButton() {
  const btn = document.getElementById("add-btn");
  const text = document.getElementById("add-btn-text");
  const count = selectedSet.size;

  btn.disabled = count === 0;
  text.textContent = count > 0
    ? `Thêm ${count} bài vào songs.json`
    : "Thêm vào songs.json";
}

// ── Add Selected ────────────────────────────────────────────
async function addSelected() {
  if (selectedSet.size === 0) return;

  const items = [];
  selectedSet.forEach((videoId) => {
    const r = searchResults.find((x) => x.video_id === videoId);
    if (!r) return;

    // Read current values from the input fields
    const titleInput = document.querySelector(`.field-title[data-vid="${videoId}"]`);
    const artistInput = document.querySelector(`.field-artist[data-vid="${videoId}"]`);

    items.push({
      title: titleInput ? titleInput.value.trim() : r.clean_title,
      artist: artistInput ? artistInput.value.trim() : r.artist,
      url: r.url,
    });
  });

  const addBtn = document.getElementById("add-btn");
  addBtn.disabled = true;
  addBtn.innerHTML = `
    <div class="spinner" style="width:16px;height:16px;border-width:2px;margin:0;"></div>
    <span>Đang lưu...</span>
  `;

  try {
    const res = await fetch("/api/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    });

    const data = await res.json();

    if (data.error) {
      showToast(data.error, "error");
      return;
    }

    showToast(`✅ Đã thêm ${data.count} bài vào songs.json!`, "success");

    // Mark added cards as exists
    selectedSet.forEach((videoId) => {
      const r = searchResults.find((x) => x.video_id === videoId);
      if (r) r.exists = true;
      const card = document.querySelector(`[data-id="${videoId}"]`);
      if (card) {
        card.classList.remove("selected");
        card.classList.add("exists");
      }
    });

    selectedSet.clear();
    updateAddButton();
    loadStats();
  } catch (e) {
    showToast("Lỗi khi lưu!", "error");
    console.error(e);
  } finally {
    addBtn.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/>
        <polyline points="17 21 17 13 7 13 7 21"/>
        <polyline points="7 3 7 8 15 8"/>
      </svg>
      <span id="add-btn-text">Thêm vào songs.json</span>
    `;
    updateAddButton();
  }
}

// ── Toast ────────────────────────────────────────────────────
function showToast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;

  const icons = {
    success: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`,
    error: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>`,
    info: `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`,
  };

  toast.innerHTML = `${icons[type] || icons.info} ${escapeHTML(message)}`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.classList.add("toast-fade-out");
    setTimeout(() => toast.remove(), 300);
  }, 4000);
}

// ── Formatters ──────────────────────────────────────────────
function formatViews(n) {
  if (n == null) return "N/A";
  if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
  if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
  return n.toString();
}

function formatDuration(s) {
  if (!s) return "?:??";
  const m = Math.floor(s / 60);
  const sec = s % 60;
  return `${m}:${sec.toString().padStart(2, "0")}`;
}

function escapeHTML(str) {
  if (!str) return "";
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function escapeAttr(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/'/g, "&#39;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}
