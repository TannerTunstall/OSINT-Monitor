/* ═══════════════════════════════════════════════════════
   OSINT Monitor — API Client & UI Helpers
   ═══════════════════════════════════════════════════════ */

// ── Toast Notifications ─────────────────────────────────

function toast(msg, type = 'success') {
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), type === 'error' ? 6000 : 3000);
}

// ── API Client ──────────────────────────────────────────

async function api(method, path, body) {
  try {
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body) opts.body = JSON.stringify(body);
    const res = await fetch('/api/' + path, opts);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ message: res.statusText }));
      if (err.errors) toast(err.errors[0], 'error');
      return null;
    }
    return await res.json();
  } catch (e) {
    toast('Network error — check your connection', 'error');
    return null;
  }
}

// ── HTML Escaping ───────────────────────────────────────

function esc(text) {
  const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  return String(text).replace(/[&<>"']/g, m => map[m]);
}

// ── Tag Input System ────────────────────────────────────

function getTags(id) {
  return Array.from(document.querySelectorAll(`#${id} .tag`)).map(t => t.dataset.value);
}

function _createTag(value) {
  const tag = document.createElement('span');
  tag.className = 'tag';
  tag.dataset.value = value;
  const text = document.createElement('span');
  text.className = 'tag-text';
  text.textContent = value;
  tag.appendChild(text);
  const remove = document.createElement('span');
  remove.className = 'remove';
  remove.textContent = '\u00d7';
  remove.addEventListener('click', () => tag.remove());
  tag.appendChild(remove);
  return tag;
}

function renderTags(id, vals) {
  const el = document.getElementById(id);
  if (!el) return;
  el.innerHTML = '';
  vals.forEach(v => el.appendChild(_createTag(v)));
}

function addTag(containerId, inputId) {
  const input = document.getElementById(inputId);
  const val = input.value.trim();
  if (!val) return;
  document.getElementById(containerId).appendChild(_createTag(val));
  input.value = '';
  input.focus();
}

// Allow Enter key to add tags
document.addEventListener('keydown', (e) => {
  if (e.key !== 'Enter') return;
  const input = e.target;
  if (input.tagName !== 'INPUT' || input.type === 'checkbox') return;
  const addRow = input.closest('.add-row');
  if (addRow) {
    e.preventDefault();
    const btn = addRow.querySelector('.btn');
    if (btn) btn.click();
  }
});

// ── RSS Feed Helpers ────────────────────────────────────

const FEED_PRESETS = [
  { label: "AWS (Global)", url: "https://status.aws.amazon.com/rss/all.rss", content_filter: [] },
  { label: "Cloudflare Status", url: "https://www.cloudflarestatus.com/history.rss", content_filter: [] },
  { label: "Google Cloud", url: "https://status.cloud.google.com/feed.atom", content_filter: [] },
  { label: "Azure Status", url: "https://azurestatuscdn.azureedge.net/en-us/status/feed/", content_filter: [] },
  { label: "GitHub Status", url: "https://www.githubstatus.com/history.atom", content_filter: [] },
  { label: "Oracle Cloud", url: "https://ocistatus.oraclecloud.com/history.rss", content_filter: [] },
];

function renderFeedPresets(activeFeeds) {
  const urls = activeFeeds.map(f => f.url);
  const el = document.getElementById('feed-presets');
  if (!el) return;
  el.innerHTML = FEED_PRESETS.map(p => {
    const on = urls.includes(p.url);
    return `<label class="preset-label">
      <input type="checkbox" ${on ? 'checked' : ''} onchange="togglePreset('${p.url}',this.checked)"> ${p.label}
    </label>`;
  }).join('');
}

function _createFeedTag(url, label, contentFilter) {
  const tag = document.createElement('div');
  tag.className = 'tag'; tag.dataset.url = url; tag.dataset.label = label;
  tag.dataset.contentFilter = JSON.stringify(contentFilter || []);
  tag.style.marginBottom = '4px';
  const text = document.createElement('span');
  text.className = 'tag-text';
  text.textContent = label || url;
  tag.appendChild(text);
  const remove = document.createElement('span');
  remove.className = 'remove';
  remove.textContent = '\u00d7';
  remove.addEventListener('click', () => { tag.remove(); renderFeedPresets(getRSSFeeds()); });
  tag.appendChild(remove);
  return tag;
}

function togglePreset(url, on) {
  const preset = FEED_PRESETS.find(p => p.url === url);
  if (!preset) return;
  if (on) {
    document.getElementById('rss-feeds').appendChild(_createFeedTag(preset.url, preset.label, preset.content_filter));
  } else {
    document.querySelectorAll('#rss-feeds .tag').forEach(t => { if (t.dataset.url === url) t.remove(); });
  }
}

function renderRSSFeeds(feeds) {
  const el = document.getElementById('rss-feeds');
  if (!el) return;
  el.innerHTML = '';
  feeds.forEach(f => el.appendChild(_createFeedTag(f.url, f.label, f.content_filter || f.region_filter)));
  renderFeedPresets(feeds);
}

function getRSSFeeds() {
  return Array.from(document.querySelectorAll('#rss-feeds .tag')).map(t => {
    const f = { url: t.dataset.url, label: t.dataset.label };
    try {
      const cf = JSON.parse(t.dataset.contentFilter || '[]');
      if (cf.length) f.content_filter = cf;
    } catch (e) { }
    return f;
  });
}

function addRSSFeed() {
  const url = document.getElementById('rss-url-input').value.trim();
  const label = document.getElementById('rss-label-input').value.trim();
  if (!url) return;
  document.getElementById('rss-feeds').appendChild(_createFeedTag(url, label || url, []));
  document.getElementById('rss-url-input').value = '';
  document.getElementById('rss-label-input').value = '';
  renderFeedPresets(getRSSFeeds());
}
