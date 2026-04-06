/* ═══════════════════════════════════════════════════════
   OSINT Monitor — Main Dashboard Logic
   ═══════════════════════════════════════════════════════ */

// ── Helpers ─────────────────────────────────────────────

function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
  const tab = document.querySelector(`.tab[data-tab="${name}"]`);
  if (tab) tab.classList.add('active');
  const content = document.getElementById('tab-' + name);
  if (content) content.classList.add('active');
}

function toggleSwitch(el) {
  el.classList.toggle('on');
  el.setAttribute('aria-checked', el.classList.contains('on'));
}

// ── Tab Navigation ──────────────────────────────────────

let logAutoRefreshInterval = null;
let feedAutoRefreshInterval = null;

document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    switchTab(tab.dataset.tab);

    // Auto-refresh for logs
    if (tab.dataset.tab === 'logs') {
      loadLogs();
      if (document.getElementById('log-auto-refresh').checked && !logAutoRefreshInterval) {
        logAutoRefreshInterval = setInterval(loadLogs, 5000);
      }
    } else {
      if (logAutoRefreshInterval) { clearInterval(logAutoRefreshInterval); logAutoRefreshInterval = null; }
    }

    // Auto-refresh for feed
    if (tab.dataset.tab === 'feed') {
      loadFeed();
      if (!feedAutoRefreshInterval) feedAutoRefreshInterval = setInterval(loadFeed, 10000);
    } else {
      if (feedAutoRefreshInterval) { clearInterval(feedAutoRefreshInterval); feedAutoRefreshInterval = null; }
    }

    // Load analytics on tab open
    if (tab.dataset.tab === 'analytics') loadAnalytics();
  });
});

// ── Health (updated via loadAnalytics) ──────────────────

// ── Config Loading ──────────────────────────────────────

let _lastLoadedConfig = null;

async function loadConfig() {
  const cfg = await api('GET', 'config');
  if (!cfg) return;
  _lastLoadedConfig = cfg;
  const src = cfg.sources || {};

  // Telegram
  if (src.telegram) renderTags('tg-channels', src.telegram.channels || []);

  // Twitter
  if (src.twitter) {
    renderTags('tw-accounts', src.twitter.accounts || []);
    renderTags('tw-nitter', src.twitter.nitter_instances || ['https://nitter.net/']);
  } else {
    renderTags('tw-nitter', ['https://nitter.net/']);
  }

  // RSS feeds (accept both keys)
  const rssData = src.rss_feeds || src.aws_health;
  if (rssData) renderRSSFeeds(rssData.feeds || []);

  // Polling
  const poll = cfg.polling || {};
  document.getElementById('poll-telegram').value = poll.telegram_interval_seconds || 30;
  document.getElementById('poll-twitter').value = poll.twitter_interval_seconds || 300;
  document.getElementById('poll-rss').value = poll.rss_feeds_interval_seconds || poll.aws_health_interval_seconds || 120;
  document.getElementById('poll-radar').value = poll.radar_interval_seconds || 300;

  // Radar
  const radar = src.radar || {};
  if (radar.enabled) document.getElementById('radar-toggle').classList.add('on');
  if (radar.countries) {
    const countryTags = Object.entries(radar.countries).map(([code, name]) => `${code}:${name}`);
    renderTags('radar-countries', countryTags);
  }

  // Notifiers
  const ntf = cfg.notifiers || {};
  if (ntf.whatsapp) {
    if (ntf.whatsapp.enabled) document.getElementById('wa-toggle').classList.add('on');
    document.getElementById('wa-api-url').value = ntf.whatsapp.api_url || 'http://whatsapp-api:3000';
    document.getElementById('wa-session').value = ntf.whatsapp.session_name || 'default';
    renderTags('wa-chats', ntf.whatsapp.chat_ids || []);
  }
  if (ntf.signal) {
    if (ntf.signal.enabled) document.getElementById('sig-toggle').classList.add('on');
    document.getElementById('sig-api-url').value = ntf.signal.api_url || '';
    document.getElementById('sig-sender').value = ntf.signal.sender || '';
    renderTags('sig-recipients', ntf.signal.recipients || []);
  }
  if (ntf.discord) {
    if (ntf.discord.enabled) document.getElementById('discord-toggle').classList.add('on');
    renderTags('discord-webhooks', ntf.discord.webhook_urls || []);
  }
  if (ntf.slack) {
    if (ntf.slack.enabled) document.getElementById('slack-toggle').classList.add('on');
    renderTags('slack-webhooks', ntf.slack.webhook_urls || []);
  }
  if (ntf.email) {
    if (ntf.email.enabled) document.getElementById('email-toggle').classList.add('on');
    document.getElementById('email-smtp-host').value = ntf.email.smtp_host || '';
    document.getElementById('email-smtp-port').value = ntf.email.smtp_port || 587;
    document.getElementById('email-from').value = ntf.email.from_address || '';
    renderTags('email-to', ntf.email.to_addresses || []);
    if (ntf.email.use_tls !== false) document.getElementById('email-tls-toggle').classList.add('on');
  }
  if (ntf.webhook) {
    if (ntf.webhook.enabled) document.getElementById('webhook-toggle').classList.add('on');
    renderWebhookEndpoints(ntf.webhook.urls || []);
  }

  // Database + Logging
  const db = cfg.database || {};
  document.getElementById('db-retention').value = db.retention_days || 90;
  const logging = cfg.logging || {};
  document.getElementById('log-level').value = logging.level || 'INFO';

  // Filters
  const flt = cfg.filters || {};
  renderTags('filter-default-include', flt.include_keywords || []);
  renderTags('filter-default-exclude', flt.exclude_keywords || []);
  const tgf = flt.telegram || {};
  renderTags('filter-telegram-include', tgf.include_keywords || []);
  renderTags('filter-telegram-exclude', tgf.exclude_keywords || []);
  const twf = flt.twitter || {};
  renderTags('filter-twitter-include', twf.include_keywords || []);
  renderTags('filter-twitter-exclude', twf.exclude_keywords || []);
  const rssf = flt.rss || flt.rss_feeds || flt.aws_health || {};
  renderTags('filter-rss-include', rssf.include_keywords || []);
  renderTags('filter-rss-exclude', rssf.exclude_keywords || []);

  // Translation
  const trans = cfg.translation || {};
  if (trans.enabled) document.getElementById('translate-toggle').classList.add('on');
  if (trans.api_url) document.getElementById('translate-api-url').value = trans.api_url;
  if (trans.target_language) document.getElementById('translate-target').value = trans.target_language;
}

async function loadCredentials() {
  const c = await api('GET', 'credentials');
  if (!c) return;
  document.getElementById('cred-telegram-api-id').value = c.TELEGRAM_API_ID || '';
  document.getElementById('cred-telegram-api-hash').value = c.TELEGRAM_API_HASH || '';
  document.getElementById('cred-signal-sender').value = c.SIGNAL_SENDER || '';
  document.getElementById('cred-radar-token').value = c.CLOUDFLARE_RADAR_TOKEN || '';
  document.getElementById('cred-smtp-username').value = c.SMTP_USERNAME || '';
  document.getElementById('cred-smtp-password').value = c.SMTP_PASSWORD || '';
  document.getElementById('cred-webhook-token').value = c.WEBHOOK_TOKEN || '';
}

// ── Logs ────────────────────────────────────────────────

let logFilter = 'all';

async function loadLogs() {
  const data = await api('GET', 'logs?lines=300');
  if (!data) return;
  const v = document.getElementById('log-viewer');
  const filterMap = {
    'all': () => true,
    'error': l => l.includes('[ERROR]'),
    'warning': l => l.includes('[WARNING]') || l.includes('[ERROR]'),
    'info': l => l.includes('[INFO]') || l.includes('[WARNING]') || l.includes('[ERROR]'),
    'telegram': l => l.includes('[TELEGRAM]'),
    'twitter': l => l.includes('[TWITTER]'),
    'rss': l => l.includes('[RSS]') || l.includes('[STATUS]'),
    'radar': l => l.includes('[RADAR]'),
    'whatsapp': l => l.toLowerCase().includes('whatsapp') || l.includes('WAHA'),
    'translate': l => l.includes('Translation:') || l.includes('translation'),
  };
  const filterFn = filterMap[logFilter] || filterMap['all'];
  const lines = data.lines.filter(filterFn);
  v.innerHTML = lines.map(l => {
    let c = '';
    if (l.includes('[ERROR]')) c = 'error';
    else if (l.includes('[WARNING]')) c = 'warning';
    else if (l.includes('[INFO]')) c = 'info';
    return `<div class="${c}">${esc(l)}</div>`;
  }).join('');
  v.scrollTop = v.scrollHeight;
}

function setLogFilter(f) {
  logFilter = f;
  document.querySelectorAll('#tab-logs .filter-bar .btn-sm').forEach(b => b.classList.remove('active'));
  const btn = document.querySelector(`#tab-logs .filter-bar [data-filter="${f}"]`);
  if (btn) btn.classList.add('active');
  loadLogs();
}

function toggleLogAutoRefresh() {
  const on = document.getElementById('log-auto-refresh').checked;
  if (on) {
    if (!logAutoRefreshInterval) logAutoRefreshInterval = setInterval(loadLogs, 5000);
  } else {
    if (logAutoRefreshInterval) { clearInterval(logAutoRefreshInterval); logAutoRefreshInterval = null; }
  }
}

async function clearLogs() { await api('POST', 'logs/clear'); toast('Logs cleared'); loadLogs(); }

// ── Feed ────────────────────────────────────────────────

let feedSource = 'all';

function setFeedSource(src) {
  feedSource = src;
  document.querySelectorAll('#tab-feed .filter-bar .btn-sm').forEach(b => b.classList.remove('active'));
  const btn = document.querySelector(`#tab-feed .filter-bar [data-filter="${src}"]`);
  if (btn) btn.classList.add('active');
  loadFeed();
}

function _timeAgo(dateStr) {
  if (!dateStr) return '';
  try {
    const d = new Date(dateStr.replace(' ', 'T') + (dateStr.includes('+') || dateStr.includes('Z') ? '' : 'Z'));
    const now = Date.now();
    const secs = Math.floor((now - d.getTime()) / 1000);
    if (secs < 0) return 'just now';
    if (secs < 60) return secs + 's ago';
    if (secs < 3600) return Math.floor(secs / 60) + 'm ago';
    if (secs < 86400) return Math.floor(secs / 3600) + 'h ago';
    if (secs < 604800) return Math.floor(secs / 86400) + 'd ago';
    return d.toLocaleDateString();
  } catch (e) { return dateStr.substring(0, 16); }
}

let _feedMessages = [];

function filterFeedSearch() {
  const q = (document.getElementById('feed-search')?.value || '').toLowerCase().trim();
  renderFeedMessages(q);
}

function renderFeedMessages(query) {
  const el = document.getElementById('feed-list');
  const countEl = document.getElementById('feed-count');
  let msgs = _feedMessages;
  if (query) {
    msgs = msgs.filter(m =>
      (m.content || '').toLowerCase().includes(query) ||
      (m.author || '').toLowerCase().includes(query)
    );
  }
  if (countEl) countEl.textContent = `Showing ${msgs.length} of ${_feedMessages.length} messages`;
  if (!msgs.length) {
    el.innerHTML = query
      ? '<div class="feed-empty">No messages match your search.</div>'
      : '<div class="feed-empty">No messages yet.<br>Once sources are configured and polling, messages will appear here.</div>';
    return;
  }
  el.innerHTML = msgs.map(m => {
    const ts = m.timestamp || m.created_at || '';
    const ago = _timeAgo(ts);
    const content = esc((m.content || '').substring(0, 600));
    const src = (m.source || '').toLowerCase();
    const srcLabel = esc((m.source || '').toUpperCase());
    const author = esc(m.author || 'Unknown');
    const url = m.url ? `<a class="feed-link" href="${esc(m.url)}" target="_blank" rel="noopener">${esc(m.url)}</a>` : '';
    const keywords = m.matched_keywords ? `<div class="feed-keywords">Flagged: ${esc(m.matched_keywords)}</div>` : '';
    const translation = m.translation ? `<div class="feed-translation">${esc(m.translation.substring(0, 600))}</div><div class="feed-original-label">Original:</div>` : '';
    return `<div class="feed-card">
      <div class="feed-card-header">
        <span class="feed-badge ${src}">${srcLabel}</span>
        <span class="feed-author">${author}</span>
        <span class="feed-time">${esc(ago)}</span>
      </div>
      ${keywords}
      ${translation}
      <div class="feed-body">${content}</div>
      ${url}
    </div>`;
  }).join('');
}

async function loadFeed() {
  const data = await api('GET', `messages/recent?limit=100&source=${feedSource}`);
  if (!data || !data.messages) return;
  _feedMessages = data.messages;
  const el = document.getElementById('feed-list');
  if (!data.messages.length) {
    document.getElementById('feed-count').textContent = '';
    el.innerHTML = '<div class="feed-empty">No messages yet.<br>Once sources are configured and polling, messages will appear here.</div>';
    return;
  }
  const query = (document.getElementById('feed-search')?.value || '').toLowerCase().trim();
  renderFeedMessages(query);
}


// ── Export ───────────────────────────────────────────────

function exportData(format) {
  const params = new URLSearchParams({ format, source: feedSource });
  window.open('/api/export?' + params.toString(), '_blank');
  toast(`Exporting as ${format.toUpperCase()}...`);
}

// ── Updates ─────────────────────────────────────────────

async function checkForUpdates() {
  const statusEl = document.getElementById('update-status');
  const btn = document.getElementById('update-check-btn');
  if (!statusEl) return;
  btn.disabled = true;
  btn.textContent = 'Checking...';
  statusEl.innerHTML = '';

  const data = await api('GET', 'update/check');
  btn.disabled = false;
  btn.textContent = 'Check for updates';

  if (!data || data.error) {
    statusEl.innerHTML = `<span style="color:var(--red,#ef4444);font-size:12px">${esc(data?.error || 'Cannot reach GitHub')}</span>`;
    return;
  }

  if (data.up_to_date) {
    statusEl.innerHTML = `<span style="color:var(--green,#22c55e);font-size:12px">Up to date (${esc(data.local_commit)})</span>`;
  } else {
    statusEl.innerHTML = `
      <div style="font-size:12px;margin-bottom:6px">
        <span style="color:var(--warning,#f59e0b)">Update available</span>
        <span style="color:var(--text2)"> — ${esc(data.remote_commit)}: ${esc(data.remote_message)}</span>
      </div>
      <button class="btn btn-sm" style="background:var(--accent);color:#fff;width:100%" onclick="applyUpdate()">Update &amp; Restart</button>
    `;
  }
}

async function applyUpdate() {
  if (!confirm('This will pull the latest code from GitHub, rebuild the container, and restart. Your config and data are preserved. Continue?')) return;

  // Show update modal
  const modal = document.getElementById('update-modal');
  modal.classList.remove('hidden');
  updateStep('step-pull', 'active');
  updateStep('step-build', 'pending');
  updateStep('step-restart', 'pending');
  updateStep('step-done', 'pending');
  document.getElementById('update-error').classList.add('hidden');

  const data = await api('POST', 'update/apply');
  if (!data || data.error) {
    updateStep('step-pull', 'error');
    const errEl = document.getElementById('update-error');
    errEl.textContent = data?.error || 'Update failed';
    errEl.classList.remove('hidden');
    return;
  }

  // Pull succeeded, now rebuilding
  updateStep('step-pull', 'done');
  updateStep('step-build', 'active');

  // Poll for the container to come back with new version
  const startTime = Date.now();
  const maxWait = 300000; // 5 minutes
  let buildShown = false;

  const poll = setInterval(async () => {
    if (Date.now() - startTime > maxWait) {
      clearInterval(poll);
      updateStep('step-build', 'error');
      const errEl = document.getElementById('update-error');
      errEl.textContent = 'Update is taking longer than expected. Check Docker logs on the host.';
      errEl.classList.remove('hidden');
      return;
    }

    try {
      const resp = await fetch('/api/health');
      if (resp.ok) {
        if (!buildShown) {
          updateStep('step-build', 'done');
          updateStep('step-restart', 'active');
          buildShown = true;
        }
        // App is back — wait a moment then mark done
        clearInterval(poll);
        updateStep('step-restart', 'done');
        updateStep('step-done', 'done');
        setTimeout(() => location.reload(), 3000);
      }
    } catch (e) {
      // Connection refused = container is restarting, expected
      if (!buildShown && Date.now() - startTime > 10000) {
        updateStep('step-build', 'done');
        updateStep('step-restart', 'active');
        buildShown = true;
      }
    }
  }, 3000);
}

function updateStep(id, state) {
  const el = document.getElementById(id);
  if (!el) return;
  const icon = el.querySelector('.step-icon');
  el.className = 'update-step ' + state;
  if (state === 'active') icon.innerHTML = '<div class="spinner-sm"></div>';
  else if (state === 'done') icon.textContent = '\u2713';
  else if (state === 'error') icon.textContent = '\u2717';
  else icon.textContent = '\u2022';
}

// ── Gather & Save ───────────────────────────────────────

function gatherSources() {
  // Start from existing config to preserve keys the UI doesn't edit (e.g. radar.countries)
  const s = Object.assign({}, _lastLoadedConfig?.sources || {});

  const tg = getTags('tg-channels');
  if (tg.length) {
    const existing = s.telegram || {};
    s.telegram = { ...existing, api_id: existing.api_id || '${TELEGRAM_API_ID}', api_hash: existing.api_hash || '${TELEGRAM_API_HASH}', session_name: existing.session_name || 'osint_monitor', channels: tg };
  } else {
    delete s.telegram;
  }

  const tw = getTags('tw-accounts');
  if (tw.length) s.twitter = { method: 'nitter_rss', nitter_instances: getTags('tw-nitter'), accounts: tw };
  else delete s.twitter;

  const rss = getRSSFeeds();
  if (rss.length) { s.rss_feeds = { feeds: rss }; delete s.aws_health; }
  else { delete s.rss_feeds; delete s.aws_health; }

  return s;
}

function gatherPolling() {
  return {
    telegram_interval_seconds: parseInt(document.getElementById('poll-telegram').value) || 30,
    twitter_interval_seconds: parseInt(document.getElementById('poll-twitter').value) || 300,
    rss_feeds_interval_seconds: parseInt(document.getElementById('poll-rss').value) || 120,
    radar_interval_seconds: parseInt(document.getElementById('poll-radar').value) || 300,
  };
}

function gatherRadar() {
  const countries = {};
  getTags('radar-countries').forEach(t => {
    const parts = t.split(':');
    if (parts.length === 2) countries[parts[0].trim()] = parts[1].trim();
  });
  return {
    enabled: document.getElementById('radar-toggle').classList.contains('on'),
    countries,
  };
}

const COUNTRIES = [
  "AF:Afghanistan","AL:Albania","DZ:Algeria","AO:Angola","AR:Argentina","AM:Armenia",
  "AU:Australia","AT:Austria","AZ:Azerbaijan","BH:Bahrain","BD:Bangladesh","BY:Belarus",
  "BE:Belgium","BA:Bosnia and Herzegovina","BR:Brazil","BG:Bulgaria","KH:Cambodia",
  "CM:Cameroon","CA:Canada","CF:Central African Republic","TD:Chad","CL:Chile","CN:China",
  "CO:Colombia","CD:DR Congo","HR:Croatia","CU:Cuba","CY:Cyprus","CZ:Czech Republic",
  "DK:Denmark","DJ:Djibouti","EG:Egypt","ER:Eritrea","EE:Estonia","ET:Ethiopia",
  "FI:Finland","FR:France","GE:Georgia","DE:Germany","GH:Ghana","GR:Greece",
  "HN:Honduras","HK:Hong Kong","HU:Hungary","IN:India","ID:Indonesia","IR:Iran",
  "IQ:Iraq","IE:Ireland","IL:Israel","IT:Italy","JP:Japan","JO:Jordan","KZ:Kazakhstan",
  "KE:Kenya","KW:Kuwait","KG:Kyrgyzstan","LA:Laos","LV:Latvia","LB:Lebanon","LY:Libya",
  "LT:Lithuania","MG:Madagascar","MY:Malaysia","ML:Mali","MX:Mexico","MD:Moldova",
  "MN:Mongolia","MA:Morocco","MZ:Mozambique","MM:Myanmar","NA:Namibia","NP:Nepal",
  "NL:Netherlands","NZ:New Zealand","NE:Niger","NG:Nigeria","KP:North Korea","NO:Norway",
  "OM:Oman","PK:Pakistan","PS:Palestine","PA:Panama","PH:Philippines","PL:Poland",
  "PT:Portugal","QA:Qatar","RO:Romania","RU:Russia","RW:Rwanda","SA:Saudi Arabia",
  "SN:Senegal","RS:Serbia","SG:Singapore","SK:Slovakia","SI:Slovenia","SO:Somalia",
  "ZA:South Africa","KR:South Korea","ES:Spain","SD:Sudan","SE:Sweden","CH:Switzerland",
  "SY:Syria","TW:Taiwan","TJ:Tajikistan","TZ:Tanzania","TH:Thailand","TN:Tunisia",
  "TR:Turkey","TM:Turkmenistan","UA:Ukraine","AE:United Arab Emirates","GB:United Kingdom",
  "US:United States","UZ:Uzbekistan","VE:Venezuela","VN:Vietnam","YE:Yemen","ZM:Zambia",
  "ZW:Zimbabwe"
];

function filterRadarCountries() {
  const input = document.getElementById('radar-country-input');
  const dropdown = document.getElementById('radar-country-dropdown');
  const query = input.value.toLowerCase().trim();
  const existing = getTags('radar-countries');

  const matches = COUNTRIES.filter(c => {
    const name = c.split(':')[1].toLowerCase();
    const code = c.split(':')[0].toLowerCase();
    return (!query || name.includes(query) || code.includes(query)) && !existing.includes(c);
  }).slice(0, 10);

  if (!matches.length) {
    dropdown.classList.add('hidden');
    return;
  }

  dropdown.innerHTML = matches.map(c => {
    const [code, name] = c.split(':');
    return `<div class="autocomplete-item" onmousedown="selectRadarCountry('${c}')">${esc(name)} <span style="color:var(--text2)">(${esc(code)})</span></div>`;
  }).join('');
  dropdown.classList.remove('hidden');
}

function selectRadarCountry(value) {
  const input = document.getElementById('radar-country-input');
  const dropdown = document.getElementById('radar-country-dropdown');
  input.value = value;
  addTag('radar-countries', 'radar-country-input');
  input.value = '';
  dropdown.classList.add('hidden');
}

// Close dropdown when clicking outside
document.addEventListener('click', (e) => {
  if (!e.target.closest('#radar-country-input') && !e.target.closest('#radar-country-dropdown')) {
    const dd = document.getElementById('radar-country-dropdown');
    if (dd) dd.classList.add('hidden');
  }
});

function renderWebhookEndpoints(endpoints) {
  const el = document.getElementById('webhook-endpoints');
  if (!el) return;
  el.innerHTML = '';
  (endpoints || []).forEach(ep => {
    const url = typeof ep === 'string' ? ep : ep.url;
    const method = typeof ep === 'string' ? 'POST' : (ep.method || 'POST');
    const tag = document.createElement('div');
    tag.className = 'tag';
    tag.dataset.url = url;
    tag.dataset.method = method;
    tag.style.marginBottom = '4px';
    const text = document.createElement('span');
    text.className = 'tag-text';
    text.textContent = `${method} ${url}`;
    tag.appendChild(text);
    const remove = document.createElement('span');
    remove.className = 'remove';
    remove.textContent = '\u00d7';
    remove.addEventListener('click', () => tag.remove());
    tag.appendChild(remove);
    el.appendChild(tag);
  });
}

function addWebhookEndpoint() {
  const url = document.getElementById('webhook-url-input').value.trim();
  const method = document.getElementById('webhook-method-input').value;
  if (!url) return;
  const el = document.getElementById('webhook-endpoints');
  const tag = document.createElement('div');
  tag.className = 'tag'; tag.dataset.url = url; tag.dataset.method = method; tag.style.marginBottom = '4px';
  const text = document.createElement('span');
  text.className = 'tag-text';
  text.textContent = `${method} ${url}`;
  tag.appendChild(text);
  const remove = document.createElement('span');
  remove.className = 'remove';
  remove.textContent = '\u00d7';
  remove.addEventListener('click', () => tag.remove());
  tag.appendChild(remove);
  el.appendChild(tag);
  document.getElementById('webhook-url-input').value = '';
}

function getWebhookEndpoints() {
  return Array.from(document.querySelectorAll('#webhook-endpoints .tag')).map(t => ({
    url: t.dataset.url,
    method: t.dataset.method || 'POST',
  }));
}

function gatherNotifiers() {
  // Start from existing config to preserve notifiers the UI hasn't loaded yet
  const n = Object.assign({}, _lastLoadedConfig?.notifiers || {});

  const waOn = document.getElementById('wa-toggle').classList.contains('on');
  const waC = getTags('wa-chats');
  if (waOn || waC.length) n.whatsapp = { enabled: waOn, api_url: document.getElementById('wa-api-url').value, session_name: document.getElementById('wa-session').value, chat_ids: waC };
  else delete n.whatsapp;

  const sigOn = document.getElementById('sig-toggle').classList.contains('on');
  const sigR = getTags('sig-recipients');
  if (sigOn || sigR.length) n.signal = { enabled: sigOn, api_url: document.getElementById('sig-api-url').value, sender: document.getElementById('sig-sender').value || '', recipients: sigR };
  else delete n.signal;

  const dcOn = document.getElementById('discord-toggle').classList.contains('on');
  const dcW = getTags('discord-webhooks');
  if (dcOn || dcW.length) n.discord = { enabled: dcOn, webhook_urls: dcW };
  else delete n.discord;

  const slOn = document.getElementById('slack-toggle').classList.contains('on');
  const slW = getTags('slack-webhooks');
  if (slOn || slW.length) n.slack = { enabled: slOn, webhook_urls: slW };
  else delete n.slack;

  const emOn = document.getElementById('email-toggle').classList.contains('on');
  const emTo = getTags('email-to');
  if (emOn || emTo.length) n.email = {
    enabled: emOn,
    smtp_host: document.getElementById('email-smtp-host').value,
    smtp_port: parseInt(document.getElementById('email-smtp-port').value) || 587,
    use_tls: document.getElementById('email-tls-toggle').classList.contains('on'),
    from_address: document.getElementById('email-from').value,
    to_addresses: emTo,
  };
  else delete n.email;

  const whOn = document.getElementById('webhook-toggle').classList.contains('on');
  const whEps = getWebhookEndpoints();
  if (whOn || whEps.length) n.webhook = { enabled: whOn, urls: whEps };
  else delete n.webhook;

  return n;
}

function gatherFilters() {
  const f = {
    include_keywords: getTags('filter-default-include'),
    exclude_keywords: getTags('filter-default-exclude'),
  };
  const tgi = getTags('filter-telegram-include'), tge = getTags('filter-telegram-exclude');
  if (tgi.length || tge.length) f.telegram = { include_keywords: tgi, exclude_keywords: tge };
  const twi = getTags('filter-twitter-include'), twe = getTags('filter-twitter-exclude');
  if (twi.length || twe.length) f.twitter = { include_keywords: twi, exclude_keywords: twe };
  const ri = getTags('filter-rss-include'), re = getTags('filter-rss-exclude');
  if (ri.length || re.length) f.rss = { include_keywords: ri, exclude_keywords: re };
  return f;
}

function gatherTranslation() {
  return {
    enabled: document.getElementById('translate-toggle').classList.contains('on'),
    api_url: document.getElementById('translate-api-url').value,
    target_language: document.getElementById('translate-target').value || 'en',
  };
}

async function saveAndRestart(section) {
  if (!confirm('Save and restart the monitor?\n\nMonitoring will pause while the container restarts. This can take up to 30 seconds.')) return;

  const c = (await api('GET', 'config')) || {};

  if (section === 'sources' || section === 'all') {
    c.sources = gatherSources();
    const existingRadar = _lastLoadedConfig?.sources?.radar || {};
    c.sources.radar = { ...existingRadar, ...gatherRadar() };
    c.polling = gatherPolling();
    c.translation = gatherTranslation();
    // Database + logging
    c.database = c.database || {};
    c.database.retention_days = parseInt(document.getElementById('db-retention').value) || 90;
    c.logging = { level: document.getElementById('log-level').value || 'INFO' };
  }

  if (section === 'notifiers' || section === 'all') {
    c.notifiers = gatherNotifiers();
  }

  if (section === 'filters' || section === 'all') {
    c.filters = gatherFilters();
  }

  await api('PUT', 'config', c);
  _lastLoadedConfig = c;

  if (section === 'credentials' || section === 'all') {
    const d = {};
    const a = document.getElementById('cred-telegram-api-id').value; if (a) d.TELEGRAM_API_ID = a;
    const h = document.getElementById('cred-telegram-api-hash').value; if (h) d.TELEGRAM_API_HASH = h;
    const s = document.getElementById('cred-signal-sender').value; if (s) d.SIGNAL_SENDER = s;
    const r = document.getElementById('cred-radar-token').value; if (r) d.CLOUDFLARE_RADAR_TOKEN = r;
    const su = document.getElementById('cred-smtp-username').value; if (su) d.SMTP_USERNAME = su;
    const sp = document.getElementById('cred-smtp-password').value; if (sp) d.SMTP_PASSWORD = sp;
    const wt = document.getElementById('cred-webhook-token').value; if (wt) d.WEBHOOK_TOKEN = wt;
    await api('PUT', 'credentials', d);
  }

  toast('Saved — restarting...');
  await api('POST', 'restart');

  // Show restart overlay and poll until the app is back
  const overlay = document.getElementById('restart-overlay');
  const title = document.getElementById('restart-title');
  const subtitle = document.getElementById('restart-subtitle');
  overlay.classList.remove('hidden');

  let attempts = 0;
  const maxAttempts = 30; // 60 seconds max
  const poll = setInterval(async () => {
    attempts++;
    try {
      const resp = await fetch('/api/health', { signal: AbortSignal.timeout(2000) });
      if (resp.ok) {
        clearInterval(poll);
        title.textContent = 'Back online!';
        subtitle.textContent = 'Reloading...';
        setTimeout(() => location.reload(), 500);
      }
    } catch (e) {
      // Still restarting
      subtitle.textContent = `Waiting for monitor to restart... (${attempts * 2}s)`;
    }
    if (attempts >= maxAttempts) {
      clearInterval(poll);
      title.textContent = 'Restart is taking longer than expected.';
      subtitle.innerHTML = 'Try <a href="/" style="color:var(--accent)">refreshing the page</a> manually.';
    }
  }, 2000);
}

async function testNotification() {
  toast('Sending test...');
  const r = await api('POST', 'test-notification');
  if (!r || !r.results) { toast('Failed to send test', 'error'); return; }
  const ok = r.results.every(x => x.success);
  if (ok) toast('Test notification sent!');
  else toast('Failed: ' + r.results.filter(x => !x.success).map(x => x.notifier).join(', '), 'error');
}

async function testSource(type) {
  toast('Sending test ' + type + '...');
  const r = await api('POST', 'test-source', { type });
  if (r && r.status === 'ok') toast('Test sent!');
  else toast(r?.message || 'Failed to send test', 'error');
}

// ── Dashboard / Analytics ────────────────────────────────

const SOURCE_COLORS = {
  telegram: '#3b82f6',
  twitter: '#8b5cf6',
  rss: '#f59e0b',
  radar: '#22c55e',
  status: '#f59e0b',
};

let _charts = {};
let _analyticsData = null;
let _volumeRange = '7d';
let _analyticsInterval = null;

function getOrCreateChart(id, config) {
  if (_charts[id]) { _charts[id].destroy(); }
  const ctx = document.getElementById(id);
  if (!ctx) return null;
  _charts[id] = new Chart(ctx, config);
  return _charts[id];
}

const _chartStyle = {
  color: '#94a3b8',
  grid: '#1e293b',
  tick: '#64748b',
};

function setVolumeRange(range) {
  _volumeRange = range;
  document.querySelectorAll('#tab-analytics [data-range]').forEach(b => b.classList.remove('active'));
  const btn = document.querySelector(`#tab-analytics [data-range="${range}"]`);
  if (btn) btn.classList.add('active');
  if (_analyticsData) renderVolumeChart(_analyticsData);
}

function renderVolumeChart(data) {
  const allSources = [...new Set([
    ...Object.keys(data.by_source || {}),
    ...Object.values(data.hourly || {}).flatMap(h => Object.keys(h)),
  ])];

  let timeData, labelFn;
  if (_volumeRange === '24h') {
    timeData = data.hourly_24h || {};
    labelFn = h => h.slice(11, 16); // HH:MM
  } else if (_volumeRange === '30d') {
    timeData = data.daily || {};
    labelFn = d => d.slice(5); // MM-DD
  } else {
    timeData = data.hourly || {};
    labelFn = h => h.slice(5, 13); // MM-DD HH
  }

  const keys = Object.keys(timeData).sort();
  if (!keys.length) return;

  const datasets = allSources.map(src => ({
    label: src,
    data: keys.map(k => (timeData[k] || {})[src] || 0),
    backgroundColor: (SOURCE_COLORS[src] || '#6366f1') + '33',
    borderColor: SOURCE_COLORS[src] || '#6366f1',
    borderWidth: 1.5,
    fill: true,
    tension: 0.3,
    pointRadius: 0,
  }));

  const maxTicks = _volumeRange === '24h' ? 24 : _volumeRange === '30d' ? 15 : 14;

  getOrCreateChart('chart-volume', {
    type: 'line',
    data: { labels: keys.map(labelFn), datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: _chartStyle.color } } },
      scales: {
        x: { ticks: { color: _chartStyle.tick, maxTicksLimit: maxTicks, font: { size: 10 } }, grid: { color: _chartStyle.grid } },
        y: { ticks: { color: _chartStyle.tick, font: { size: 10 } }, grid: { color: _chartStyle.grid }, beginAtZero: true },
      },
      interaction: { intersect: false, mode: 'index' },
    },
  });
}

async function loadAnalytics() {
  const data = await api('GET', 'analytics');
  if (!data) return;
  _analyticsData = data;

  const health = data.health || {};
  const upHrs = Math.floor((health.uptime_seconds || 0) / 3600);
  const upMin = Math.floor(((health.uptime_seconds || 0) % 3600) / 60);

  // KPI summary cards
  const lastMsg = data.last_message_at ? data.last_message_at.substring(11, 16) + ' UTC' : 'none';
  const sourceCount = (health.connectors || []).filter(c => c.type === 'source').length;
  document.getElementById('analytics-summary').innerHTML = `
    <div class="status-chip"><div class="dot green"></div><div><div class="value">${data.today || 0}</div><div class="meta">Messages today</div></div></div>
    <div class="status-chip"><div class="dot green"></div><div><div class="value">${data.this_week || 0}</div><div class="meta">This week</div></div></div>
    <div class="status-chip"><div class="dot ${sourceCount > 0 ? 'green' : 'gray'}"></div><div><div class="value">${sourceCount}</div><div class="meta">Sources active</div></div></div>
    <div class="status-chip"><div class="dot ${health.connectors_healthy === health.connectors_total ? 'green' : 'red'}"></div><div><div class="value">${health.connectors_healthy || 0}/${health.connectors_total || 0}</div><div class="meta">Connectors</div></div></div>
    <div class="status-chip"><div class="dot green"></div><div><div class="value">${upHrs}h ${upMin}m</div><div class="meta">Uptime</div></div></div>
    <div class="status-chip"><div class="dot green"></div><div><div class="value">${lastMsg}</div><div class="meta">Last message</div></div></div>
  `;

  // Connector health bar
  const connectors = health.connectors || [];
  document.getElementById('status-bar').innerHTML = connectors.map(c => {
    let ago = 'never';
    if (c.last_success) {
      const secs = Math.round(Date.now() / 1000 - c.last_success);
      if (secs < 60) ago = secs + 's ago';
      else if (secs < 3600) ago = Math.floor(secs / 60) + 'm ago';
      else ago = Math.floor(secs / 3600) + 'h ' + Math.floor((secs % 3600) / 60) + 'm ago';
    }
    return `<div class="status-chip">
      <div class="dot ${c.healthy ? 'green' : 'red'}"></div>
      <div>
        <div class="value">${esc(c.name)}</div>
        <div class="meta">${esc(c.type)} &middot; ${c.messages_processed} msgs &middot; ${ago}</div>
        ${c.last_error ? `<div class="meta" style="color:var(--red)">${esc(c.last_error)}</div>` : ''}
      </div>
    </div>`;
  }).join('');

  // All sources for chart coloring
  const allSources = [...new Set([
    ...Object.keys(data.by_source || {}),
    ...Object.values(data.hourly || {}).flatMap(h => Object.keys(h)),
  ])];

  // Volume chart
  renderVolumeChart(data);

  // Source donut
  const srcLabels = Object.keys(data.by_source || {});
  const srcValues = Object.values(data.by_source || {});
  if (srcLabels.length) {
    getOrCreateChart('chart-sources', {
      type: 'doughnut',
      data: {
        labels: srcLabels,
        datasets: [{
          data: srcValues,
          backgroundColor: srcLabels.map(s => SOURCE_COLORS[s] || '#6366f1'),
          borderColor: '#0f172a',
          borderWidth: 2,
        }],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        cutout: '65%',
        plugins: {
          legend: { position: 'bottom', labels: { color: '#a1adc0', padding: 8, font: { size: 10 }, boxWidth: 12, boxHeight: 12 } },
        },
      },
    });
  }

  // Daily stacked bar (30 days)
  const days = Object.keys(data.daily || {}).sort();
  if (days.length) {
    const dailyDatasets = allSources.map(src => ({
      label: src,
      data: days.map(d => (data.daily[d] || {})[src] || 0),
      backgroundColor: SOURCE_COLORS[src] || '#6366f1',
      borderRadius: 2,
    }));
    getOrCreateChart('chart-daily', {
      type: 'bar',
      data: { labels: days.map(d => d.slice(5)), datasets: dailyDatasets },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: { legend: { labels: { color: _chartStyle.color } } },
        scales: {
          x: { stacked: true, ticks: { color: _chartStyle.tick, maxTicksLimit: 15, font: { size: 10 } }, grid: { display: false } },
          y: { stacked: true, ticks: { color: _chartStyle.tick, font: { size: 10 } }, grid: { color: _chartStyle.grid }, beginAtZero: true },
        },
      },
    });
  }

  // Top authors
  const authorsEl = document.getElementById('analytics-authors');
  if (authorsEl && data.top_authors && data.top_authors.length) {
    authorsEl.innerHTML = data.top_authors.map(a => `
      <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);align-items:center">
        <div>
          <span style="color:${SOURCE_COLORS[a.source] || 'var(--accent)'};font-weight:600;font-size:10px;text-transform:uppercase">${esc(a.source)}</span>
          <span style="margin-left:6px">${esc(a.author || '')}</span>
        </div>
        <span style="font-family:'Fira Code',monospace;color:var(--text2)">${a.count}</span>
      </div>
    `).join('');
  } else if (authorsEl) {
    authorsEl.innerHTML = '<div style="color:var(--text2);padding:20px;text-align:center">No data yet. <a href="#" onclick="switchTab(\'sources\');return false" style="color:var(--accent)">Add sources</a> to start monitoring.</div>';
  }

  // System info
  const sysEl = document.getElementById('dashboard-system');
  if (sysEl) {
    const srcCount = Object.keys(data.by_source || {}).length;
    const notifierCount = connectors.filter(c => c.type === 'notifier').length;
    const sourceCount = connectors.filter(c => c.type === 'source').length;
    sysEl.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:8px">
        <div style="display:flex;justify-content:space-between"><span style="color:var(--text2)">Sources active</span><span>${sourceCount}</span></div>
        <div style="display:flex;justify-content:space-between"><span style="color:var(--text2)">Notifiers active</span><span>${notifierCount}</span></div>
        <div style="display:flex;justify-content:space-between"><span style="color:var(--text2)">Source types seen</span><span>${srcCount}</span></div>
        <div style="display:flex;justify-content:space-between"><span style="color:var(--text2)">Retention</span><span>${_lastLoadedConfig?.database?.retention_days || 90} days</span></div>
        <div style="display:flex;justify-content:space-between"><span style="color:var(--text2)">Uptime</span><span>${upHrs}h ${upMin}m</span></div>
        <div style="display:flex;justify-content:space-between;border-top:1px solid var(--border);padding-top:8px;margin-top:4px">
          <button class="btn btn-sm btn-outline" onclick="exportData('csv')" style="flex:1">Export CSV</button>
          <button class="btn btn-sm btn-outline" onclick="exportData('json')" style="flex:1;margin-left:6px">Export JSON</button>
        </div>
        <div id="update-section" style="border-top:1px solid var(--border);padding-top:8px;margin-top:4px">
          <div style="display:flex;justify-content:space-between;align-items:center">
            <span style="color:var(--text2)">Updates</span>
            <button class="btn btn-sm btn-outline" onclick="checkForUpdates()" id="update-check-btn">Check for updates</button>
          </div>
          <div id="update-status" style="margin-top:6px"></div>
        </div>
      </div>
    `;
  }

  // Recent activity feed (last 10 messages)
  await loadDashboardFeed();
}

async function loadDashboardFeed() {
  const data = await api('GET', 'messages/recent?limit=10&source=all');
  const el = document.getElementById('dashboard-feed');
  if (!el || !data || !data.messages) return;
  if (!data.messages.length) {
    el.innerHTML = '<div style="color:var(--text2);padding:16px;text-align:center">No messages yet. <a href="#" onclick="switchTab(\'sources\');return false" style="color:var(--accent)">Configure sources</a> to start monitoring.</div>';
    return;
  }
  el.innerHTML = data.messages.map(m => {
    const ts = m.timestamp || m.created_at || '';
    const time = ts ? ts.substring(11, 16) : '';
    const date = ts ? ts.substring(0, 10) : '';
    const content = esc((m.content || '').substring(0, 120)).replace(/\n/g, ' ');
    const src = esc((m.source || '').toUpperCase());
    const color = SOURCE_COLORS[m.source] || 'var(--accent)';
    return `<div style="padding:6px 0;border-bottom:1px solid var(--border)">
      <div style="display:flex;justify-content:space-between;align-items:center">
        <span style="color:${color};font-weight:600;font-size:10px">${src}</span>
        <span style="color:var(--text2);font-size:10px;font-family:'Fira Code',monospace">${esc(date)} ${esc(time)}</span>
      </div>
      <div style="margin-top:2px;color:var(--text)">${content}</div>
    </div>`;
  }).join('');
}

// ── LibreTranslate Management ────────────────────────────

const LT_ALL_LANGUAGES = {
  en:'English',ar:'Arabic',az:'Azerbaijani',bn:'Bengali',bg:'Bulgarian',
  ca:'Catalan',zh:'Chinese',cs:'Czech',da:'Danish',nl:'Dutch',eo:'Esperanto',
  et:'Estonian',fi:'Finnish',fr:'French',de:'German',el:'Greek',he:'Hebrew',
  hi:'Hindi',hu:'Hungarian',id:'Indonesian',ga:'Irish',it:'Italian',
  ja:'Japanese',ko:'Korean',lv:'Latvian',lt:'Lithuanian',ms:'Malay',
  fa:'Persian',pl:'Polish',pt:'Portuguese',ro:'Romanian',ru:'Russian',
  sk:'Slovak',sl:'Slovenian',es:'Spanish',sv:'Swedish',tl:'Tagalog',
  th:'Thai',tr:'Turkish',uk:'Ukrainian',ur:'Urdu',vi:'Vietnamese',
};

let _loadedLangs = new Set();

function renderLangPicker(configured) {
  const el = document.getElementById('translate-lang-picker');
  if (!el) return;
  const selected = new Set(configured ? configured.split(',') : ['en']);
  selected.add('en'); // English always included

  el.innerHTML = Object.entries(LT_ALL_LANGUAGES).map(([code, name]) => {
    const checked = selected.has(code) ? 'checked' : '';
    const loaded = _loadedLangs.has(code);
    const dot = loaded ? '<span style="color:var(--green);margin-left:2px">&#9679;</span>' : '';
    const disabled = code === 'en' ? 'disabled' : '';
    return `<label class="preset-label" style="min-width:140px">
      <input type="checkbox" ${checked} ${disabled} value="${code}" onchange="updateLangSelection()"> ${esc(name)} (${code})${dot}
    </label>`;
  }).join('');
}

function updateLangSelection() {
  // Visual only — actual save happens on Save & Rebuild click
}

function getSelectedLangs() {
  const checks = document.querySelectorAll('#translate-lang-picker input[type="checkbox"]:checked');
  return Array.from(checks).map(c => c.value).sort().join(',');
}

async function checkTranslateStatus() {
  const statusEl = document.getElementById('translate-status');
  statusEl.textContent = 'Checking...';

  const r = await api('GET', 'translate/status');
  if (!r) { statusEl.innerHTML = '<span style="color:var(--red)">Failed to check</span>'; return; }

  // Render language picker with configured languages
  renderLangPicker(r.configured || 'en');

  if (r.ok) {
    _loadedLangs = new Set((r.languages || []).map(l => l.code || l));
    const count = _loadedLangs.size;
    statusEl.innerHTML = `<span style="color:var(--green)">Online</span> — ${count} language${count !== 1 ? 's' : ''} loaded <span style="color:var(--green)">&#9679;</span>`;
    // Re-render to show green dots
    renderLangPicker(r.configured || Array.from(_loadedLangs).join(','));
  } else {
    statusEl.innerHTML = `<span style="color:var(--red)">Offline</span> — ${esc(r.error || 'Unreachable')}`;
    if (r.error && (r.error.includes('Cannot connect') || r.error.includes('Connect call failed'))) {
      statusEl.innerHTML += '<br><span style="font-size:11px">LibreTranslate may still be downloading language models. This can take several minutes on first start.</span>';
    }
  }
}

let _translatePollInterval = null;

async function saveTranslateLanguages() {
  const langs = getSelectedLangs();
  if (!langs) { toast('Select at least one language', 'error'); return; }

  if (!confirm(`Rebuild translation service with: ${langs}?\n\nThis will restart the translate container and download any new language models.`)) return;

  const statusEl = document.getElementById('translate-status');
  statusEl.innerHTML = '<span style="color:var(--orange)">Rebuilding...</span> — Stopping old container...';

  const r = await api('POST', 'translate/configure', { languages: langs });
  if (r && r.status === 'ok') {
    toast(r.message);
    const requested = new Set(langs.split(','));
    statusEl.innerHTML = `<span style="color:var(--orange)">Rebuilding...</span> — Container restarting, downloading ${requested.size} language model${requested.size > 1 ? 's' : ''}...`;

    // Poll until all requested languages are loaded
    let attempts = 0;
    if (_translatePollInterval) clearInterval(_translatePollInterval);
    _translatePollInterval = setInterval(async () => {
      attempts++;
      const s = await api('GET', 'translate/status');
      if (s && s.ok) {
        const loaded = new Set((s.languages || []).map(l => l.code));
        const pending = [...requested].filter(l => !loaded.has(l));
        if (pending.length === 0) {
          clearInterval(_translatePollInterval);
          _translatePollInterval = null;
          statusEl.innerHTML = `<span style="color:var(--green)">Online</span> — All ${loaded.size} languages loaded`;
          _loadedLangs = loaded;
          renderLangPicker(langs);
          toast('All languages loaded!');
        } else {
          statusEl.innerHTML = `<span style="color:var(--orange)">Loading...</span> — ${loaded.size}/${requested.size} languages ready, waiting for: ${pending.join(', ')}`;
          _loadedLangs = loaded;
          renderLangPicker(langs);
        }
      } else {
        statusEl.innerHTML = `<span style="color:var(--orange)">Starting...</span> — Translate service not ready yet (${attempts * 5}s)`;
      }
      if (attempts > 60) { // 5 min timeout
        clearInterval(_translatePollInterval);
        _translatePollInterval = null;
        statusEl.innerHTML = '<span style="color:var(--red)">Timeout</span> — Language download is taking longer than expected. Check Logs tab for details.';
      }
    }, 5000);
  } else {
    toast(r?.message || 'Failed to save', 'error');
    statusEl.innerHTML = `<span style="color:var(--red)">Error</span> — ${esc(r?.message || 'Failed to rebuild')}`;
  }
}

// ── Telegram Auth (inline in Sources tab) ───────────────

function tgAuthStatus(msg, type) {
  document.getElementById('tg-auth-status').innerHTML = `<div class="status-msg ${type}" style="margin-top:10px">${esc(msg)}</div>`;
}

async function tgAuthStart() {
  const phone = document.getElementById('tg-phone').value.trim();
  if (!phone) { tgAuthStatus('Phone number is required.', 'err'); return; }
  // Read creds from Credentials tab fields (which loadCredentials populated)
  const apiId = document.getElementById('cred-telegram-api-id').value.trim();
  const apiHash = document.getElementById('cred-telegram-api-hash').value.trim();
  if (!apiId || !apiHash) { document.getElementById('tg-auth-status').innerHTML = '<div class="status-msg err" style="margin-top:10px">Telegram API ID and Hash are required. <a href="#" onclick="switchTab(\'credentials\');return false" style="color:var(--accent)">Go to Credentials tab</a></div>'; return; }
  tgAuthStatus('Sending verification code...', 'info');
  const result = await api('POST', 'telegram-auth/start', { api_id: parseInt(apiId), api_hash: apiHash, phone });
  if (result && result.status === 'awaiting_code') {
    tgAuthStatus(result.message, 'ok');
    document.getElementById('tg-auth-controls').classList.add('hidden');
    document.getElementById('tg-code-section').classList.remove('hidden');
  } else {
    tgAuthStatus(result ? result.message : 'Failed to start auth.', 'err');
  }
}

async function tgAuthCode() {
  const code = document.getElementById('tg-code').value.trim();
  if (!code) return;
  tgAuthStatus('Verifying...', 'info');
  const result = await api('POST', 'telegram-auth/code', { code });
  if (!result) { tgAuthStatus('Verification failed.', 'err'); return; }
  if (result.status === 'authenticated') {
    tgAuthStatus('Telegram authenticated!', 'ok');
    document.getElementById('tg-code-section').classList.add('hidden');
  } else if (result.status === 'awaiting_2fa') {
    tgAuthStatus(result.message, 'info');
    document.getElementById('tg-code-section').classList.add('hidden');
    document.getElementById('tg-2fa-section').classList.remove('hidden');
  } else {
    tgAuthStatus(result.message, 'err');
  }
}

async function tgAuth2fa() {
  const pw = document.getElementById('tg-2fa').value.trim();
  if (!pw) return;
  const result = await api('POST', 'telegram-auth/2fa', { password: pw });
  if (result && result.status === 'authenticated') {
    tgAuthStatus('Telegram authenticated!', 'ok');
    document.getElementById('tg-2fa-section').classList.add('hidden');
  } else {
    tgAuthStatus(result ? result.message : 'Failed.', 'err');
  }
}

// ── WhatsApp QR Pairing (modal) ─────────────────────────

function waStatus(msg, type) {
  document.getElementById('wa-pair-status').innerHTML = `<div class="status-msg ${type}" style="margin-top:10px">${esc(msg)}</div>`;
}

async function showWhatsAppQR() {
  document.getElementById('qr-modal').classList.remove('hidden');
  document.getElementById('wa-pair-status').innerHTML = '';
  // Automatically start the session flow
  await waStartSession();
}

async function waStartSession() {
  waStatus('Starting WhatsApp service — this may take a moment if the container needs to start...', 'info');
  const result = await api('POST', 'whatsapp/start');
  if (!result) {
    waStatus('Cannot reach the OSINT Monitor API.', 'err');
    return;
  }
  if (result.status === 'error') {
    waStatus(result.message || 'Failed to start WAHA.', 'err');
    return;
  }
  if (result.status === 'SCAN_QR_CODE') {
    waStatus('Ready — scan the QR code below with your phone.', 'ok');
    await loadModalQR();
  } else if (result.status === 'WORKING') {
    waStatus('WhatsApp is already connected!', 'ok');
  } else {
    waStatus(`Status: ${esc(result.status || 'unknown')}. Loading QR...`, 'info');
    await loadModalQR();
  }
}

async function loadModalQR() {
  const c = document.getElementById('modal-qr-container');
  c.innerHTML = '<p style="color:var(--text2)">Loading...</p>';
  try {
    const resp = await fetch('/api/whatsapp/qr');
    if (resp.ok) {
      const d = await resp.json();
      if (d.data) { c.innerHTML = `<img src="data:${esc(d.mimetype || 'image/png')};base64,${d.data}" style="max-width:260px;border-radius:8px;background:white;padding:12px">`; }
      else { c.innerHTML = `<p style="color:var(--text2)">${esc(d.message || 'Click "Start Session" first.')}</p>`; }
    } else {
      const d = await resp.json().catch(() => ({}));
      c.innerHTML = `<p style="color:var(--text2)">${esc(d.message || 'Click "Start Session" first.')}</p>`;
    }
  } catch (e) { c.innerHTML = `<p style="color:var(--red)">Cannot reach WhatsApp API.</p>`; }
}

async function waCheckStatus() {
  waStatus('Checking connection...', 'info');
  const result = await api('GET', 'whatsapp/status');
  if (result && result.status === 'WORKING') {
    waStatus('WhatsApp connected!', 'ok');
  } else {
    waStatus(`Status: ${result?.status || 'unknown'}. Scan the QR code and try again.`, 'err');
  }
}

// ── Init ────────────────────────────────────────────────

async function init() {
  const setup = await api('GET', 'setup-status');

  // Show welcome banner on first run (no sources or notifiers yet)
  if (!setup || !setup.setup_complete) {
    document.getElementById('welcome-overlay').classList.remove('hidden');
  }

  // Show Telegram auth status in both tabs
  if (setup) {
    const badge = document.getElementById('tg-auth-badge');
    const sourceStatus = document.getElementById('tg-auth-section');
    if (setup.telegram_authed) {
      if (badge) badge.innerHTML = '<span style="color:var(--green)">Authenticated</span>';
      if (sourceStatus) sourceStatus.innerHTML = '<p class="help" style="color:var(--green);margin-bottom:8px">Telegram authenticated. Manage credentials in the Credentials tab.</p>';
      // Hide the auth controls since already authed
      const controls = document.getElementById('tg-auth-controls');
      if (controls) controls.innerHTML = '<p class="help">Already authenticated. To re-authenticate, delete the session file and restart.</p>';
    } else if (setup.telegram_creds) {
      if (badge) badge.innerHTML = '<span style="color:var(--orange)">Not authenticated</span>';
      if (sourceStatus) sourceStatus.innerHTML = '<p class="help" style="color:var(--orange);margin-bottom:8px">Telegram credentials set but not authenticated. Go to Credentials tab to authenticate.</p>';
    } else {
      if (badge) badge.innerHTML = '<span style="color:var(--text2)">No credentials</span>';
      if (sourceStatus) sourceStatus.innerHTML = '<p class="help" style="margin-bottom:8px">Set Telegram API credentials and authenticate in the Credentials tab.</p>';
    }
  }

  await loadAnalytics();
  await loadConfig();
  await loadCredentials();

  // Ensure RSS presets render even if no feeds are configured yet
  if (!document.getElementById('feed-presets').children.length) {
    renderFeedPresets([]);
  }

  // Auto-refresh dashboard every 15 seconds when visible
  _analyticsInterval = setInterval(() => {
    const dashTab = document.getElementById('tab-analytics');
    if (dashTab && dashTab.classList.contains('active')) {
      loadAnalytics();
    }
  }, 15000);
}

init();
