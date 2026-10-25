// Zusatzansichten: Portfolio-Sicht, Kalender, Backup, Analyse-Erweiterungen.
// Nutzt api(), toast(), ts(), fmt(), showSection() aus dashboard.html.
// Alle API-Strings sind bereits per api() escaped -> darf per innerHTML eingesetzt werden.

const $ = id => document.getElementById(id);
const pct = (v, d = 1) => v == null ? '–' : (v >= 0 ? '+' : '') + Number(v).toFixed(d) + ' %';
const plain = (v, d = 1) => v == null ? '–' : Number(v).toFixed(d);
const clr = v => v == null ? '#94a3b8' : v >= 0 ? '#4ade80' : '#f87171';
const card = (title, body, extra = '') =>
  `<div class="card"><div class="card-head">${title}${extra}</div>${body}</div>`;
const pad = (s) => `<div style="padding:1rem">${s}</div>`;
const btn = (label, attrs, kind = 'dark') =>
  `<button ${attrs} style="padding:.3rem .8rem;border:none;border-radius:6px;cursor:pointer;font-size:.8rem;font-weight:600;` +
  `background:${kind === 'primary' ? '#4f46e5' : kind === 'danger' ? '#450a0a' : '#2d3148'};` +
  `color:${kind === 'danger' ? '#f87171' : '#e2e8f0'}">${label}</button>`;
const inputCss = 'background:#0f1117;border:1px solid #2d3148;color:#e2e8f0;padding:.35rem .6rem;border-radius:6px;font-size:.85rem';

async function downloadFile(url, fallback) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  const name = ((r.headers.get('Content-Disposition') || '').match(/filename="?([^";]+)"?/) || [])[1] || fallback;
  const href = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement('a'), { href, download: name });
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(href);
}

// ── SVG-Liniendiagramm ────────────────────────────────────────
function lineChart(series, { height = 260, unit = '' } = {}) {
  const W = 900, H = height, L = 46, R = 14, T = 12, B = 26;
  const all = series.flatMap(s => s.data);
  if (all.length < 2) return '<div class="empty">Zu wenig Daten</div>';
  const dates = [...new Set(all.map(p => p[0]))].sort();
  const xi = Object.fromEntries(dates.map((d, i) => [d, i]));
  const vals = all.map(p => p[1]);
  let lo = Math.min(...vals), hi = Math.max(...vals);
  const padv = (hi - lo) * 0.08 || 1; lo -= padv; hi += padv;
  const x = d => L + xi[d] / Math.max(dates.length - 1, 1) * (W - L - R);
  const y = v => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  let g = '';
  for (let i = 0; i <= 4; i++) {
    const v = lo + (hi - lo) * i / 4, yy = y(v);
    g += `<line x1="${L}" x2="${W - R}" y1="${yy}" y2="${yy}" stroke="#2d3148" stroke-width="1"/>` +
         `<text x="${L - 6}" y="${yy + 4}" fill="#64748b" font-size="11" text-anchor="end">${v.toFixed(0)}${unit}</text>`;
  }
  const lab = [0, Math.floor(dates.length / 2), dates.length - 1];
  g += lab.map((i, k) => `<text x="${x(dates[i])}" y="${H - 6}" fill="#64748b" font-size="11" ` +
       `text-anchor="${k === 0 ? 'start' : k === 2 ? 'end' : 'middle'}">${dates[i]}</text>`).join('');
  const lines = series.map(s => `<polyline fill="none" stroke="${s.color}" stroke-width="2" stroke-linejoin="round" ` +
    `points="${s.data.map(p => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(' ')}"/>`).join('');
  const legend = series.map(s => `<span style="margin-right:1rem"><span style="display:inline-block;width:.8rem;height:.2rem;` +
    `background:${s.color};vertical-align:middle;margin-right:.3rem"></span>${s.name} <strong style="color:${s.color}">` +
    `${s.data.length ? s.data[s.data.length - 1][1].toFixed(1) : ''}</strong></span>`).join('');
  return `<svg viewBox="0 0 ${W} ${H}" style="width:100%;height:auto;display:block">${g}${lines}</svg>` +
         `<div style="font-size:.8rem;color:#94a3b8;margin-top:.4rem">${legend}</div>`;
}

function barRows(rows, color) {
  return rows.slice(0, 8).map(r => `<div style="margin:.35rem 0"><div style="display:flex;justify-content:space-between;font-size:.8rem">` +
    `<span>${r.name}</span><span style="color:#94a3b8">${r.pct.toFixed(1)} %</span></div>` +
    `<div style="background:#12151f;border-radius:4px;height:.55rem"><div style="width:${Math.min(r.pct, 100)}%;height:100%;` +
    `background:${color};border-radius:4px"></div></div></div>`).join('') || '<div class="empty">–</div>';
}

// ── Portfolio-Sicht ───────────────────────────────────────────
async function loadPView() {
  const box = $('pview-body');
  try {
    const o = await api('/api/portfolio-view/overview');
    if (o.empty) { box.innerHTML = card('Portfolio-Sicht', '<div class="empty">Noch keine Daten – zuerst einen Run starten.</div>'); return; }
    const k = (label, v, sub = '') => `<div class="kpi"><div class="label">${label}</div><div class="value">${v}</div>` +
      (sub ? `<div style="font-size:.72rem;color:#64748b;margin-top:.2rem">${sub}</div>` : '') + '</div>';
    const c = o.concentration, r = o.risk;
    const kpis = `<div class="kpi-grid">` +
      k('Depotwert', o.nav != null ? fmt(o.nav) : fmt(o.equity_value), `Cash ${o.cash_pct != null ? plain(o.cash_pct, 0) + ' %' : '–'}`) +
      k('Positionen', o.position_count, `effektiv ${plain(c.effective_positions, 1)}`) +
      k('Größte Position', `${plain(c.largest_pct, 0)} %`, c.largest) +
      k('Top 3 Anteil', `${plain(c.top3_pct, 0)} %`) +
      k('Volatilität p.a.', r.portfolio_vol != null ? plain(r.portfolio_vol, 1) + ' %' : '–', `Kursdaten ${r.covered}`) +
      k('Max. Rückgang (1 J.)', r.portfolio_drawdown != null ? plain(r.portfolio_drawdown, 1) + ' %' : '–', 'rückgerechnet') +
      k('Beta vs. ' + (o.history.benchmark || '–'), r.portfolio_beta != null ? plain(r.portfolio_beta, 2) : '–') + '</div>';

    const h = o.history;
    const ser = [];
    if (h.hypothetical.length) ser.push({ name: 'Aktuelles Depot (rückgerechnet)', color: '#818cf8', data: h.hypothetical });
    if (h.benchmark_hypothetical.length) ser.push({ name: h.benchmark || 'Benchmark', color: '#94a3b8', data: h.benchmark_hypothetical });
    let chart = ser.length ? lineChart(ser) : '<div class="empty">Keine Kurshistorie – beim nächsten Run werden Kurse geladen (IBKR-Marktdaten nötig).</div>';
    let navChart = '';
    if (h.stored_nav.length >= 2) {
      const base = h.stored_nav[0][1] || 1;
      navChart = card('Gespeicherter Depotwert (Index 100)', pad(lineChart([{ name: 'Depot', color: '#4ade80',
        data: h.stored_nav.map(p => [p[0], p[1] / base * 100]) }], { height: 200 })));
    }
    const hist = card('Verlauf vs. Benchmark (1 Jahr)', pad(chart +
      '<div style="font-size:.72rem;color:#64748b;margin-top:.5rem">Hypothetisch: Die heutigen Bestände mit festen Gewichten über das letzte Jahr gerechnet – keine tatsächliche Wertentwicklung deines Depots (Käufe/Verkäufe nicht berücksichtigt).</div>')) + navChart;

    const alloc = `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem;padding:1rem">` +
      `<div><div style="color:#94a3b8;font-size:.8rem;margin-bottom:.3rem">Branche</div>${barRows(o.allocation.sector, '#818cf8')}</div>` +
      `<div><div style="color:#94a3b8;font-size:.8rem;margin-bottom:.3rem">Währung</div>${barRows(o.allocation.currency, '#4ade80')}</div>` +
      `<div><div style="color:#94a3b8;font-size:.8rem;margin-bottom:.3rem">Land (Domizil laut ISIN)</div>${barRows(o.allocation.country, '#fbbf24')}</div></div>`;

    const rows = o.positions.map(p => `<tr><td><strong>${p.symbol}</strong><div style="font-size:.7rem;color:#64748b">${p.sector || ''}</div></td>` +
      `<td>${plain(p.weight, 1)} %</td><td style="color:${clr(p.ret_1m)}">${pct(p.ret_1m)}</td><td style="color:${clr(p.ret_3m)}">${pct(p.ret_3m)}</td>` +
      `<td style="color:${clr(p.ret_6m)}">${pct(p.ret_6m)}</td><td>${p.volatility != null ? plain(p.volatility, 0) + ' %' : '–'}</td>` +
      `<td>${p.beta != null ? plain(p.beta, 2) : '–'}</td></tr>`).join('');
    const tbl = `<table><thead><tr><th>Position</th><th>Gewicht</th><th>1 M</th><th>3 M</th><th>6 M</th><th>Volatilität</th><th>Beta</th></tr></thead><tbody>${rows}</tbody></table>`;

    const cm = o.correlation;
    let corr = '<div class="empty">Zu wenig Kursdaten für Korrelationen</div>';
    if (cm.symbols.length >= 2) {
      const cell = v => {
        if (v == null) return '<td style="color:#475569;text-align:center">–</td>';
        const a = Math.min(Math.abs(v), 1) * 0.75;
        const bg = v >= 0 ? `rgba(248,113,113,${a})` : `rgba(96,165,250,${a})`;
        return `<td style="background:${bg};text-align:center;font-size:.72rem;padding:.3rem .4rem">${v.toFixed(2)}</td>`;
      };
      corr = `<div style="overflow-x:auto;padding:1rem"><table style="width:auto"><thead><tr><th></th>${cm.symbols.map(s => `<th style="font-size:.72rem">${s}</th>`).join('')}</tr></thead><tbody>` +
        cm.symbols.map((s, i) => `<tr><th style="font-size:.72rem">${s}</th>${cm.matrix[i].map(cell).join('')}</tr>`).join('') + '</tbody></table>' +
        `<div style="font-size:.8rem;color:#94a3b8;margin-top:.7rem">Rot = bewegen sich gleich (wenig Streuung), blau = gegenläufig. ` +
        (cm.top_pairs.length ? `Ähnlichste Paare: ${cm.top_pairs.map(p => `${p.a}/${p.b} ${p.corr.toFixed(2)}`).join(', ')}.` : '') + '</div></div>';
    }

    const sectors = [...new Set(o.allocation.sector.map(s => s.name))];
    const stress = pad(`<div style="display:flex;gap:.8rem;flex-wrap:wrap;align-items:end">
      <label style="font-size:.8rem;color:#94a3b8">Marktschock %<br><input id="st-mkt" type="number" value="-20" min="-90" max="90" step="1" style="${inputCss};width:110px"></label>
      <label style="font-size:.8rem;color:#94a3b8">Zusätzlich Branche<br><select id="st-sec" style="${inputCss}"><option value="">– keine –</option>${sectors.map(s => `<option>${s}</option>`).join('')}</select></label>
      <label style="font-size:.8rem;color:#94a3b8">Branchenschock %<br><input id="st-secpct" type="number" value="-10" step="1" style="${inputCss};width:110px"></label>
      ${btn('Szenario rechnen', 'onclick="runStress()"', 'primary')}</div><div id="st-result" style="margin-top:1rem"></div>`);

    const fees = pad(`Gebühren aus ${o.fees.orders} echten Orders: <strong>${fmt(o.fees.total)}</strong>` +
      `<div style="font-size:.72rem;color:#64748b;margin-top:.3rem">Dry-Run-Orders zählen nicht. Dividenden und Steuern werden (noch) nicht erfasst.</div>`);

    box.innerHTML = kpis + hist + card('Verteilung', alloc) + card('Positionen &amp; Kennzahlen', tbl) +
      card('Korrelationen (Tagesrenditen, 1 Jahr)', corr) + card('Stresstest', stress) + card('Gebühren', fees);
  } catch (e) { box.innerHTML = `<div class="empty">Fehler: ${e.message}</div>`; }
}

async function runStress() {
  const mkt = parseFloat($('st-mkt').value), sec = $('st-sec').value, sp = parseFloat($('st-secpct').value);
  if (!isFinite(mkt)) return toast('Marktschock ungültig', 'error');
  const sectors = sec && isFinite(sp) ? { [sec]: sp } : {};
  try {
    const r = await api('/api/portfolio-view/stress', { method: 'POST', body: JSON.stringify({ market_pct: mkt, sectors }) });
    const rows = r.rows.map(x => `<tr><td><strong>${x.symbol}</strong><div style="font-size:.7rem;color:#64748b">${x.sector}</div></td>` +
      `<td>${plain(x.beta, 2)}${x.beta_assumed ? ' <span title="angenommen" style="color:#fbbf24">*</span>' : ''}</td>` +
      `<td style="color:${clr(x.impact_pct)}">${pct(x.impact_pct)}</td><td style="color:${clr(x.change)}">${fmt(x.change)}</td></tr>`).join('');
    $('st-result').innerHTML = `<div style="font-size:1.05rem;margin-bottom:.6rem">Gesamt: <strong style="color:${clr(r.total_change)}">${fmt(r.total_change)}</strong>` +
      ` (${pct(r.total_pct_of_nav)} vom Depot)</div><table><thead><tr><th>Position</th><th>Beta</th><th>Wirkung</th><th>Wert</th></tr></thead><tbody>${rows}</tbody></table>` +
      `<div style="font-size:.72rem;color:#64748b;margin-top:.5rem">${r.note} * = Beta 1,0 angenommen (keine Kursdaten).</div>`;
  } catch (e) { toast(e.message, 'error'); }
}

// ── Kalender ──────────────────────────────────────────────────
let _calMonth = new Date(); _calMonth.setDate(1);
let _calEvents = [];
const KIND = { earnings: ['#1e3a5f', '#60a5fa', 'Zahlen'], dividend: ['#14532d', '#4ade80', 'Dividende'],
               agm: ['#3b0764', '#c084fc', 'Hauptversammlung'], other: ['#2d3148', '#94a3b8', 'Sonstiges'] };
const dstr = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;

async function loadCalendar() {
  const first = new Date(_calMonth), startOffset = (first.getDay() + 6) % 7;
  const gridStart = new Date(first); gridStart.setDate(1 - startOffset);
  const gridEnd = new Date(gridStart); gridEnd.setDate(gridStart.getDate() + 41);
  try {
    const [grid, next] = await Promise.all([
      api(`/api/calendar?start=${dstr(gridStart)}&end=${dstr(gridEnd)}`),
      api(`/api/calendar?start=${dstr(new Date())}&end=${dstr(new Date(Date.now() + 90 * 864e5))}`)]);
    _calEvents = grid.concat(next);
    const byDay = {};
    grid.forEach(e => (byDay[e.date] ||= []).push(e));
    const todayS = dstr(new Date());
    let cells = '';
    for (let i = 0; i < 42; i++) {
      const d = new Date(gridStart); d.setDate(gridStart.getDate() + i);
      const ds = dstr(d), inMonth = d.getMonth() === first.getMonth();
      const chips = (byDay[ds] || []).slice(0, 3).map(e => { const [bg, fg] = KIND[e.kind] || KIND.other;
        return `<div data-id="${e.id}" onclick="showEvent(+this.dataset.id)" title="${e.title}" style="cursor:pointer;background:${bg};color:${fg};` +
          `font-size:.68rem;padding:.1rem .3rem;border-radius:3px;margin-top:.15rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${e.approx ? 'ca. ' : ''}${e.title}</div>`; }).join('');
      const more = (byDay[ds] || []).length > 3 ? `<div style="font-size:.65rem;color:#64748b">+${byDay[ds].length - 3} weitere</div>` : '';
      cells += `<div style="min-height:5.2rem;padding:.3rem;border:1px solid #2d3148;background:${ds === todayS ? '#1e2540' : inMonth ? '#12151f' : '#0d0f16'};` +
        `opacity:${inMonth ? 1 : .5}"><div style="font-size:.72rem;color:${ds === todayS ? '#818cf8' : '#64748b'}">${d.getDate()}</div>${chips}${more}</div>`;
    }
    const month = _calMonth.toLocaleDateString('de-DE', { month: 'long', year: 'numeric' });
    const legend = Object.values(KIND).map(([bg, fg, n]) => `<span style="background:${bg};color:${fg};font-size:.7rem;padding:.1rem .4rem;border-radius:3px;margin-right:.4rem">${n}</span>`).join('');
    const head = `<div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap">${btn('◀', 'onclick="calNav(-1)"')}` +
      `<strong style="min-width:9rem;text-align:center;text-transform:capitalize">${month}</strong>${btn('▶', 'onclick="calNav(1)"')}` +
      `${btn('Heute', 'onclick="calNav(0)"')}<span style="flex:1"></span>${legend}${btn('📥 .ics Export', 'onclick="exportIcs()"')}</div>`;
    const wd = ['Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa', 'So'].map(x => `<div style="font-size:.72rem;color:#64748b;text-align:center;padding:.3rem">${x}</div>`).join('');
    const upcoming = next.length ? `<table><thead><tr><th>Datum</th><th>Termin</th><th>Art</th><th>Quelle</th></tr></thead><tbody>` +
      next.map(e => { const [bg, fg, n] = KIND[e.kind] || KIND.other;
        return `<tr data-id="${e.id}" onclick="showEvent(+this.dataset.id)" style="cursor:pointer"><td>${e.approx ? 'ca. ' : ''}${new Date(e.date).toLocaleDateString('de-DE')}</td>` +
          `<td>${e.title}${e.isin ? `<div style="font-size:.7rem;color:#64748b">${e.isin}</div>` : ''}</td>` +
          `<td><span style="background:${bg};color:${fg};font-size:.7rem;padding:.1rem .4rem;border-radius:3px">${n}</span></td>` +
          `<td style="color:#64748b">${e.source === 'analysis' ? 'Analyse' : 'manuell'}</td></tr>`; }).join('') + '</tbody></table>'
      : '<div class="empty">Keine Termine in den nächsten 90 Tagen – Termine entstehen aus Analysen oder manuell.</div>';
    const add = pad(`<div style="display:flex;gap:.6rem;flex-wrap:wrap;align-items:end">
      <label style="font-size:.78rem;color:#94a3b8">Datum<br><input id="ce-date" type="date" style="${inputCss}"></label>
      <label style="font-size:.78rem;color:#94a3b8">Titel<br><input id="ce-title" maxlength="200" placeholder="z.B. Q3-Zahlen SAP" style="${inputCss};width:250px"></label>
      <label style="font-size:.78rem;color:#94a3b8">Art<br><select id="ce-kind" style="${inputCss}">${Object.entries(KIND).map(([k, v]) => `<option value="${k}">${v[2]}</option>`).join('')}</select></label>
      <label style="font-size:.78rem;color:#94a3b8">ISIN (optional)<br><input id="ce-isin" maxlength="12" style="${inputCss};width:130px;text-transform:uppercase"></label>
      ${btn('＋ Termin', 'onclick="addEvent()"', 'primary')}</div>`);
    $('cal-body').innerHTML = card('Kalender', pad(head) + `<div style="padding:0 1rem 1rem"><div style="display:grid;grid-template-columns:repeat(7,minmax(0,1fr))">${wd}</div>` +
      `<div style="display:grid;grid-template-columns:repeat(7,minmax(0,1fr))">${cells}</div></div><div id="cal-detail"></div>`) +
      card('Nächste 90 Tage', upcoming) + card('Termin hinzufügen', add);
  } catch (e) { $('cal-body').innerHTML = `<div class="empty">Fehler: ${e.message}</div>`; }
}

function calNav(d) {
  if (d === 0) { _calMonth = new Date(); _calMonth.setDate(1); }
  else _calMonth = new Date(_calMonth.getFullYear(), _calMonth.getMonth() + d, 1);
  loadCalendar();
}

function showEvent(id) {
  const e = _calEvents.find(x => x.id === id); if (!e) return;
  const [bg, fg, n] = KIND[e.kind] || KIND.other;
  $('cal-detail').innerHTML = `<div style="margin:0 1rem 1rem;padding:.9rem;border:1px solid #2d3148;border-radius:8px;background:#12151f">
    <div style="display:flex;justify-content:space-between;gap:1rem"><strong>${e.title}</strong>
    <span style="background:${bg};color:${fg};font-size:.72rem;padding:.1rem .5rem;border-radius:3px;height:fit-content">${n}</span></div>
    <div style="color:#94a3b8;font-size:.85rem;margin:.3rem 0">${e.approx ? 'ca. ' : ''}${new Date(e.date).toLocaleDateString('de-DE', { weekday: 'long', day: '2-digit', month: 'long', year: 'numeric' })}
      ${e.isin ? ' · ' + e.isin : ''} · ${e.source === 'analysis' ? 'aus Analyse' : 'manuell'}</div>
    ${e.note ? `<div style="font-size:.82rem;color:#cbd5e1">${e.note}</div>` : ''}
    <div style="margin-top:.6rem;display:flex;gap:.5rem">
      ${/^[A-Z]{2}[A-Z0-9]{10}$/.test(e.isin) ? btn('🏢 Analyse öffnen', `data-isin="${e.isin}" onclick="analyseIsin(this.dataset.isin)"`) : ''}
      ${btn('Löschen', `data-id="${e.id}" onclick="deleteEvent(+this.dataset.id)"`, 'danger')}</div></div>`;
}

async function addEvent() {
  const date = $('ce-date').value, title = $('ce-title').value.trim();
  if (!date || !title) return toast('Datum und Titel angeben', 'error');
  try {
    await api('/api/calendar', { method: 'POST', body: JSON.stringify({ date, title, kind: $('ce-kind').value, isin: $('ce-isin').value.trim().toUpperCase() }) });
    toast('Termin gespeichert'); loadCalendar();
  } catch (e) { toast(e.message, 'error'); }
}

async function deleteEvent(id) {
  if (!confirm('Termin löschen?')) return;
  try { await api(`/api/calendar/${id}`, { method: 'DELETE' }); loadCalendar(); } catch (e) { toast(e.message, 'error'); }
}

async function exportIcs() {
  try { await downloadFile('/api/calendar/export.ics', 'portfolio-termine.ics'); } catch (e) { toast(e.message, 'error'); }
}

// ── Backup ────────────────────────────────────────────────────
const KIND_LBL = { manual: 'manuell', auto: 'automatisch', 'pre-restore': 'vor Import' };
const sizeStr = n => n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(n / 1024)) + ' KB';

async function loadBackups() {
  try {
    const r = await api('/api/backup');
    const rows = r.backups.map(b => `<tr><td>${ts(b.created)}</td><td>${KIND_LBL[b.kind] || b.kind}</td><td>${sizeStr(b.size)}</td>` +
      `<td style="font-size:.72rem;color:#64748b">${b.name}</td><td style="white-space:nowrap">` +
      `${btn('⬇ Download', `data-name="${b.name}" onclick="dlBackup(this.dataset.name)"`)} ` +
      `${btn('Löschen', `data-name="${b.name}" onclick="delBackup(this.dataset.name)"`, 'danger')}</td></tr>`).join('');
    $('backup-body').innerHTML =
      card('Datenbank-Sicherung', pad(`<div style="display:flex;gap:.7rem;flex-wrap:wrap;align-items:center">
        ${btn('💾 Jetzt sichern', 'id="bk-create" onclick="createBackup()"', 'primary')}
        <label style="${inputCss};cursor:pointer">📤 Sicherung importieren…<input id="bk-file" type="file" accept=".db,.gz,.db.gz" style="display:none" onchange="importBackup(this)"></label>
        <span style="color:#94a3b8;font-size:.82rem">Automatisch: ${r.auto.enabled ? `täglich ab ${r.auto.hour}:00 Uhr, letzte ${r.auto.keep} behalten` : 'aus'} (Einstellungen → Backup)</span></div>
        <div style="margin-top:.8rem;font-size:.78rem;color:#64748b;line-height:1.5">${r.note}<br>
        Beim Import wird die <strong>gesamte Datenbank ersetzt</strong>. Vorher wird automatisch eine Sicherung des aktuellen Stands angelegt (Art „vor Import").</div>`)) +
      card('Vorhandene Sicherungen', r.backups.length ? `<table><thead><tr><th>Erstellt</th><th>Art</th><th>Größe</th><th>Datei</th><th></th></tr></thead><tbody>${rows}</tbody></table>`
        : '<div class="empty">Noch keine Sicherungen</div>');
  } catch (e) { $('backup-body').innerHTML = `<div class="empty">Fehler: ${e.message}</div>`; }
}

async function createBackup() {
  const b = $('bk-create'); b.disabled = true;
  try { const r = await api('/api/backup/create', { method: 'POST' }); toast(`Sicherung erstellt (${sizeStr(r.size)})`); loadBackups(); }
  catch (e) { toast(e.message, 'error'); b.disabled = false; }
}
async function dlBackup(name) { try { await downloadFile(`/api/backup/download/${encodeURIComponent(name)}`, name); } catch (e) { toast(e.message, 'error'); } }
async function delBackup(name) {
  if (!confirm('Sicherung endgültig löschen?')) return;
  try { await api(`/api/backup/${encodeURIComponent(name)}`, { method: 'DELETE' }); loadBackups(); } catch (e) { toast(e.message, 'error'); }
}

async function importBackup(input) {
  const f = input.files[0]; input.value = '';
  if (!f) return;
  if (!confirm(`⚠️ Import von „${f.name}"\n\nDie GESAMTE aktuelle Datenbank wird ersetzt.\nVorher wird automatisch eine Sicherung angelegt.\n\nFortfahren?`)) return;
  try {
    const r = await fetch('/api/backup/import', { method: 'POST', headers: { 'X-Confirm-Import': 'yes' }, body: f });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
    toast(`Import erfolgreich (${j.tables} Tabellen). API-Keys ggf. neu eintragen.`);
    loadBackups();
  } catch (e) { toast('Import fehlgeschlagen: ' + e.message, 'error'); }
}

// ── Analyse-Erweiterungen ─────────────────────────────────────
function analyseIsin(isin) {
  showSection('analysis', document.querySelector("[onclick*=\"'analysis'\"]"));
  $('an-isin').value = isin;
  startAnalysis();
}

async function addAnalysisToWatchlist(btnEl) {
  const isin = btnEl.dataset.isin;
  let sym = (btnEl.dataset.ticker || '').trim();
  if (!sym) { sym = (prompt('Ticker-Symbol für die Watchlist:') || '').trim(); if (!sym) return; }
  try { await api('/api/watchlist', { method: 'POST', body: JSON.stringify({ symbol: sym.toUpperCase(), isin }) }); toast(`${sym.toUpperCase()} zur Watchlist hinzugefügt`); }
  catch (e) { toast(e.message, 'error'); }
}

const ARROW = { up: ['↗', '#4ade80'], down: ['↘', '#f87171'], flat: ['→', '#94a3b8'] };
const arr = d => ARROW[(d || 'flat').toLowerCase()] || ARROW.flat;

async function afterAnalysisRender(d) {
  if (!d.id) return;
  try {
    const c = await api(`/api/analysis/${d.id}/compare`);
    if (!c.previous) return;
    const v = c.verdict, changed = v.was && v.now && v.was !== v.now;
    const hz = (c.horizons || []).map(h => { const [a1, c1] = arr(h.was), [a2, c2] = arr(h.now);
      return `<div style="display:inline-block;margin:.2rem 1rem .2rem 0;font-size:.82rem"><span style="color:#64748b">${h.period}:</span> ` +
        `<span style="color:${c1}">${a1} ${h.was_effect || ''}</span> → <span style="color:${c2}">${a2} ${h.now_effect || ''}</span></div>`; }).join('');
    const news = (c.new_news || []).map(n => `<li>${n.headline || ''}</li>`).join('');
    const html = `<div class="card" style="border-color:#4f46e5"><div class="card-head">🔄 Seit der letzten Analyse (${ts(c.previous.timestamp)})</div>
      <div style="padding:1rem;font-size:.87rem;line-height:1.6;color:#cbd5e1">
      <div>Tendenz: <strong style="color:${changed ? '#fbbf24' : '#94a3b8'}">${v.was || '–'} → ${v.now || '–'}</strong>${changed ? ' (geändert)' : ' (unverändert)'}
        ${c.confidence_delta != null ? ` · Datenlage ${c.confidence_delta >= 0 ? '+' : ''}${Math.round(c.confidence_delta * 100)} Pkt.` : ''}</div>
      ${c.market_cap.was !== c.market_cap.now ? `<div>Marktkapitalisierung: <span style="color:#94a3b8">${c.market_cap.was || '–'}</span> → ${c.market_cap.now || '–'}</div>` : ''}
      ${hz ? `<div style="margin-top:.4rem"><span style="color:#64748b">Ausblick damals → jetzt:</span><br>${hz}</div>` : ''}
      ${news ? `<div style="margin-top:.4rem;color:#64748b">Neue Meldungen:</div><ul style="margin-left:1.1rem">${news}</ul>` : '<div style="color:#64748b">Keine neuen Meldungen.</div>'}
      </div></div>`;
    $('an-result').insertAdjacentHTML('afterbegin', html);
  } catch (e) { /* Vergleich ist optional */ }
}

function anPickChanged() {
  const n = document.querySelectorAll('.an-pick:checked').length, b = $('an-cmp-btn');
  b.disabled = n !== 2; b.style.opacity = n === 2 ? 1 : .5;
  if (n > 2) { toast('Bitte genau zwei Analysen wählen', 'warn'); }
}

async function compareTwo() {
  const ids = [...document.querySelectorAll('.an-pick:checked')].map(x => x.value);
  if (ids.length !== 2) return;
  try {
    const [a, b] = await Promise.all(ids.map(i => api('/api/analysis/' + i)));
    const row = (label, fa, fb = fa) => {
      const va = fa(a) || '–', vb = fb(b) || '–';
      return `<tr><td style="color:#64748b;white-space:nowrap">${label}</td><td>${va}</td><td>${vb}</td></tr>`; };
    const hz = x => (x.outlook?.horizons || []).map(h => { const [ar, c] = arr(h.direction);
      return `<div><span style="color:#64748b">${h.period}</span> <strong style="color:${c}">${ar} ${h.price_effect || ''}</strong></div>`; }).join('');
    const list = k => x => (x[k] || []).map(i => `• ${i}`).join('<br>');
    const verdict = x => { const v = (x.outlook?.verdict || '').toUpperCase();
      return `<span class="tag ${v === 'BULLISH' ? 'buy' : v === 'BEARISH' ? 'sell' : 'neutral'}">${v || '–'}</span> ${x.outlook?.confidence != null ? Math.round(x.outlook.confidence * 100) + ' % Datenlage' : ''}`; };
    $('an-result').innerHTML = card('⚖️ Vergleich', `<table><thead><tr><th></th><th>${a.company?.name || a.isin}</th><th>${b.company?.name || b.isin}</th></tr></thead><tbody>` +
      row('ISIN / Ticker', x => `${x.isin} ${x.company?.ticker || ''}`) + row('Branche', x => x.company?.sector) +
      row('Stand', x => ts(x.timestamp)) + row('Tendenz', verdict) + row('Marktkapitalisierung', x => x.market?.market_cap) +
      row('Kurs', x => x.market?.price) + row('Entwicklung 1 Jahr', x => x.market?.change_1y) + row('Bewertung', x => x.market?.valuation) +
      row('Umsatz', x => x.reports?.revenue) + row('Gewinn', x => x.reports?.net_income) + row('Finanzlage', x => x.financial_health?.assessment) +
      row('Wettbewerbsvorteil', x => x.competition?.moat) + row('Ausblick', hz) + row('These', x => x.outlook?.thesis) +
      row('Katalysatoren', list('catalysts')) + row('Risiken', list('risks')) + '</tbody></table>');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  } catch (e) { toast(e.message, 'error'); }
}
