// PeBrief: interfața. Fără framework: rute pe hash, randare cu template strings.
const $app = document.getElementById('app');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = t => { t = Math.max(0, t); return `${Math.floor(t/60)}:${(t%60).toFixed(1).padStart(4,'0')}`; };
const lei = n => `${Number(n||0).toLocaleString('ro-RO')} lei`;
let timer = null;

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch {}
    throw new Error(msg);
  }
  return r.json();
}

function statusPill(s) {
  const cls = {'aprobat':'ok','plătit':'ok','de refăcut':'bad','eroare':'bad','în verificare':'warn'}[s] || '';
  return `<span class="pill ${cls}">${esc(s)}</span>`;
}

function rulesHtml(r) {
  const chips = (a, no) => a.length ? a.map(x => `<span class="chip ${no?'no':''}">${esc(x)}</span>`).join('') : '<span class="mute small">—</span>';
  const dur = r.min_duration_s != null || r.max_duration_s != null
    ? `${r.min_duration_s ?? 0}–${r.max_duration_s ?? '∞'} s` : '—';
  return `<ul class="rules">
    <li><span class="k">Durată</span><span>${dur}</span></li>
    <li><span class="k">Logo vizibil</span><span>${r.logo_min_seconds != null ? `minim ${r.logo_min_seconds} s` : '—'}</span></li>
    <li><span class="k">Trebuie spus</span><span>${chips(r.must_say)}</span></li>
    <li><span class="k">Interzis în vorbire</span><span>${chips(r.must_not_say, true)}</span></li>
    <li><span class="k">Descriere: obligatoriu</span><span>${chips(r.caption_must_include)}</span></li>
    <li><span class="k">Descriere: interzis</span><span>${chips(r.caption_must_not_include, true)}</span></li>
    ${r.manual.length ? `<li><span class="k">Verifică un om</span><span class="small">${r.manual.map(esc).join('<br>')}</span></li>` : ''}
  </ul>`;
}

// ------------------------------------------------------------------ pagini

async function home() {
  const cs = await api('/api/campaigns');
  $app.innerHTML = `
    <div class="row" style="justify-content:space-between"><h1>Campanii</h1><a class="btn" href="#/new">Campanie nouă</a></div>
    <div class="grid g3">${cs.map(c => {
      const n = c.counts || {};
      return `<a class="card link" href="#/c/${c.id}">
        <h2>${esc(c.title)}</h2>
        <div class="small mute">${c.rules.must_say.length} fraze · logo ${c.rules.logo_min_seconds ?? '—'} s · ${lei(c.fee)} / creator</div>
        <div class="row small" style="margin-top:10px">
          <span class="pill ok">${(n['aprobat']||0)+(n['plătit']||0)} aprobate</span>
          <span class="pill bad">${n['de refăcut']||0} de refăcut</span>
        </div></a>`;}).join('') || '<p class="mute">Nicio campanie încă.</p>'}
    </div>`;
}

async function newCampaign() {
  const info = await api('/api/info');
  $app.innerHTML = `
    <h1>Campanie nouă</h1>
    <form id="f" class="card" style="max-width:720px">
      <label>Numele campaniei</label><input type="text" name="title" required placeholder="ex. Brisa Zero · vara 2027">
      <label>Brief-ul, așa cum l-a trimis brandul</label><textarea name="brief" required>${esc(info.template)}</textarea>
      <div class="small mute">Claude îl transformă în reguli verificabile. Ce nu se poate verifica automat ajunge la „Verifică un om”.</div>
      <label>Logo-ul (PNG, cât mai clar)</label><input type="file" name="logo" accept="image/*">
      <label>Onorariu per creator (lei)</label><input type="number" name="fee" value="1500" min="0">
      <label class="row" style="color:var(--ink)"><input type="checkbox" name="use_claude" checked> Citește brief-ul cu Claude (altfel, parser offline pe șablon)</label>
      <div class="row" style="margin-top:16px"><button id="go">Creează contractul</button><span id="st" class="mute small"></span></div>
      <div id="err" class="err"></div>
    </form>`;
  document.getElementById('f').onsubmit = async e => {
    e.preventDefault();
    const fd = new FormData(e.target);
    fd.set('use_claude', e.target.use_claude.checked ? 'true' : 'false');
    if (!fd.get('logo').size) fd.delete('logo');
    document.getElementById('go').disabled = true;
    document.getElementById('st').textContent = 'Citesc brief-ul…';
    try { const c = await api('/api/campaigns', {method:'POST', body:fd}); location.hash = `#/c/${c.id}`; }
    catch (x) { document.getElementById('err').textContent = x.message; document.getElementById('go').disabled = false; document.getElementById('st').textContent=''; }
  };
}

async function campaign(id) {
  const [c, info] = await Promise.all([api(`/api/campaigns/${id}`), api('/api/info')]);
  const url = `${info.lan}/#/u/${id}`;
  const reserved = c.ledger.filter(l => l.kind === 'blocat').reduce((a, l) => a + l.amount, 0);
  const paid = c.ledger.filter(l => l.kind === 'plătit').reduce((a, l) => a + l.amount, 0);
  const pending = c.submissions.some(s => s.status === 'în verificare');
  $app.innerHTML = `
    <div class="mute small"><a href="#/">Campanii</a> /</div>
    <h1>${esc(c.title)}</h1>
    <div class="grid g2">
      <div class="card">
        <div class="row" style="justify-content:space-between"><h2>Contractul (din brief)</h2>
          <span class="pill">${c.rules_source === 'claude' ? 'citit de Claude' : c.rules_source === 'editat' ? 'editat de mână' : 'parser offline'}</span></div>
        ${rulesHtml(c.rules)}
        <details style="margin-top:10px"><summary class="small mute" style="cursor:pointer">Editează regulile (JSON)</summary>
          <textarea id="rj">${esc(JSON.stringify(c.rules, null, 2))}</textarea>
          <button class="ghost" id="saveRules" style="margin-top:8px">Salvează</button> <span id="rerr" class="err"></span>
        </details>
      </div>
      <div class="grid" style="align-content:start">
        <div class="card row" style="align-items:flex-start;gap:16px">
          <img class="qr" src="/api/qr?url=${encodeURIComponent(url)}" alt="cod QR">
          <div><h2>Link pentru creatori</h2>
            <div class="small mute">Creatorul scanează codul cu telefonul, filmează și primește verdictul în câteva secunde.</div>
            <div style="margin-top:8px"><a href="#/u/${id}">${esc(url)}</a></div>
            ${c.has_logo ? `<img src="/api/campaigns/${id}/logo" style="max-width:140px;margin-top:10px;border-radius:8px">` : '<div class="err small">Fără logo: verificarea de logo e oprită.</div>'}
          </div>
        </div>
        <div class="card"><h2>Bani</h2>
          <div class="row" style="gap:28px"><div><div class="money">${lei(reserved - paid)}</div><div class="small mute">rezervați (drafturi aprobate, nepublicate)</div></div>
          <div><div class="money">${lei(paid)}</div><div class="small mute">plătiți după publicare</div></div></div>
        </div>
      </div>
    </div>
    <div class="card" style="margin-top:18px"><h2>Drafturi primite</h2>
      ${c.submissions.length ? `<table><tr><th>Creator</th><th>Încercarea</th><th>Status</th><th>Probleme</th><th>Timp verificare</th><th></th></tr>
      ${c.submissions.map(s => {
        const bad = s.verdict?.checks?.filter(x => !x.pass).map(x => x.label) || [];
        return `<tr><td>${esc(s.creator)}</td><td>#${s.attempt}</td><td>${statusPill(s.status)}</td>
          <td class="small">${bad.length ? bad.map(esc).join('<br>') : (s.verdict ? '—' : esc(s.progress?.msg || ''))}</td>
          <td class="small mute">${s.verdict?.seconds ? s.verdict.seconds + ' s' : ''}</td>
          <td><a href="#/s/${s.id}">vezi</a></td></tr>`;}).join('')}</table>` : '<p class="mute">Niciun draft încă. Trimite linkul de mai sus creatorilor.</p>'}
    </div>`;
  document.getElementById('saveRules').onclick = async () => {
    try { await api(`/api/campaigns/${id}/rules`, {method:'PUT', headers:{'content-type':'application/json'}, body: document.getElementById('rj').value}); route(); }
    catch (x) { document.getElementById('rerr').textContent = x.message; }
  };
  if (pending) { timer = setTimeout(route, 2000); return; }
  // Agenția ține pagina deschisă cât creatorii încarcă de pe telefon: verificăm la 3 s dacă a
  // venit un draft nou sau o plată și redesenăm doar atunci, ca să nu stricăm editarea regulilor.
  const sig = campaignSig(c);
  timer = setTimeout(async function watch() {
    try {
      const now = await api(`/api/campaigns/${id}`);
      if (location.hash.slice(1) !== `/c/${id}`) return;
      if (campaignSig(now) !== sig) return route();
    } catch {}
    timer = setTimeout(watch, 3000);
  }, 3000);
}

const campaignSig = c => JSON.stringify([c.submissions.map(s => [s.id, s.status]), c.ledger.length]);

async function upload(id) {
  const c = await api(`/api/campaigns/${id}`);
  const name = localStorage.getItem('pebrief.creator') || '';
  $app.innerHTML = `
    <div class="grid g2">
      <form id="f" class="card">
        <h1 style="font-size:22px">${esc(c.title)}</h1>
        <div class="small mute">Încarcă draftul înainte să-l postezi. Primești pe loc ce trebuie refăcut, cu secunda exactă.</div>
        <label>Numele tău</label><input type="text" name="creator" required value="${esc(name)}" placeholder="@contul_tau">
        <label>Clipul</label><input type="file" name="video" accept="video/*" required>
        <label>Descrierea pe care o vei posta</label><input type="text" name="caption" placeholder="text + hashtag-uri">
        <div style="margin-top:16px"><button id="go">Verifică draftul</button></div>
        <div id="pg" hidden><div class="bar"><div id="pb" style="width:0"></div></div><div id="pm" class="small mute"></div></div>
        <div id="err" class="err"></div>
      </form>
      <div class="card"><h2>După ce vei fi verificat</h2>${rulesHtml(c.rules)}</div>
    </div>`;
  document.getElementById('f').onsubmit = e => {
    e.preventDefault();
    const fd = new FormData(e.target);
    localStorage.setItem('pebrief.creator', fd.get('creator'));
    document.getElementById('go').disabled = true;
    document.getElementById('pg').hidden = false;
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `/api/campaigns/${id}/submissions`);
    xhr.upload.onprogress = ev => {
      if (!ev.lengthComputable) return;
      document.getElementById('pb').style.width = (ev.loaded / ev.total * 100) + '%';
      document.getElementById('pm').textContent = `Se încarcă… ${Math.round(ev.loaded / ev.total * 100)}%`;
    };
    xhr.onload = () => {
      if (xhr.status >= 300) { document.getElementById('err').textContent = xhr.responseText; document.getElementById('go').disabled = false; return; }
      location.hash = `#/s/${JSON.parse(xhr.responseText).id}`;
    };
    xhr.onerror = () => { document.getElementById('err').textContent = 'Încărcarea a eșuat.'; document.getElementById('go').disabled = false; };
    xhr.send(fd);
  };
}

async function submission(id) {
  const s = await api(`/api/submissions/${id}`);
  const v = s.verdict;
  if (!v) {
    const p = s.progress || {p: 0, msg: 'În coadă'};
    $app.innerHTML = `<div class="card" style="max-width:560px;margin:40px auto">
      <h2>Verific draftul lui ${esc(s.creator)}</h2>
      <div class="bar"><div style="width:${p.p * 100}%"></div></div><div class="small mute">${esc(p.msg)}</div></div>`;
    timer = setTimeout(route, 700);
    return;
  }
  if (v.error) {
    $app.innerHTML = `<div class="card"><h2>Clipul nu a putut fi verificat</h2><div class="err">${esc(v.error)}</div>
      <p><a href="#/u/${s.campaign}">Încearcă din nou</a></p></div>`;
    return;
  }
  const fails = v.checks.filter(c => !c.pass);
  const d = v.timeline.duration || v.video.duration;
  const pct = t => (100 * t / d).toFixed(3) + '%';
  const seg = (cls, a, b, title) => `<div class="seg ${cls}" title="${esc(title)}" style="left:${pct(a)};width:max(3px, ${pct(b - a)})"></div>`;
  $app.innerHTML = `
    <div class="mute small"><a href="#/c/${s.campaign}">Campania</a> / ${esc(s.creator)} · încercarea #${s.attempt}</div>
    <div class="verdict-head ${v.pass ? 'ok' : 'bad'}">
      <div class="big">${v.pass ? 'Trece. Poți posta.' : `De refăcut: ${fails.length} ${fails.length === 1 ? 'problemă' : 'probleme'}`}</div>
      <div class="small">verificat în ${v.seconds} s · ${statusPill(s.status)}</div>
    </div>
    <div class="grid g2">
      <div>
        <div class="player"><video id="vid" src="/api/submissions/${id}/video" controls playsinline preload="metadata"></video><canvas id="ov"></canvas></div>
        <div class="tl" id="tl">
          <div class="lane" style="top:4px">${v.timeline.logo.map(i => seg('logo', i.t0, i.t1, `logo ${fmt(i.t0)}–${fmt(i.t1)}`)).join('')}</div>
          <div class="lane" style="top:21px">${v.timeline.said.map(i => seg('say' + (i.partial ? ' partial' : ''), i.t0, i.t1, i.text)).join('')}</div>
          <div class="lane" style="top:38px">${v.timeline.forbidden.map(i => seg('forb', i.t0, i.t1, i.text)).join('')}</div>
          <div class="head" id="hd"></div>
        </div>
        <div class="legend"><span><i style="background:var(--logo)"></i>logo vizibil</span><span><i style="background:var(--say)"></i>frază cerută</span>
          <span><i style="background:var(--warn)"></i>spusă pe jumătate</span><span><i style="background:var(--forb)"></i>cuvânt interzis</span></div>
        ${v.words?.length ? `<div class="transcript">${v.words.map(w => `<span data-t="${w.start}">${esc(w.w)}</span>`).join('')}</div>` : ''}
      </div>
      <div class="card">
        ${v.checks.map(c => `<div class="check"><div class="mark ${c.pass ? 'ok' : 'bad'}">${c.pass ? '✓' : '✗'}</div><div>
          <div><b>${esc(c.label)}</b></div><div class="small">${esc(c.detail)}</div>
          ${c.evidence.length ? `<div class="ev">${c.evidence.map(e => `<figure data-t="${e.t}"><img loading="lazy" src="/api/submissions/${id}/frame/${Math.round(e.t * 1000)}" onerror="this.style.display='none'"><figcaption>${fmt(e.t)} ${esc(e.text)}</figcaption></figure>`).join('')}</div>` : ''}
        </div></div>`).join('')}
        ${v.manual.length ? `<div class="check"><div class="mark warn">?</div><div><b>Verifică un om</b><div class="small">${v.manual.map(esc).join('<br>')}</div></div></div>` : ''}
        <div style="margin-top:14px">${s.status === 'aprobat' ? `
          <form id="pub" class="row"><input type="url" name="link" required placeholder="https://www.tiktok.com/@…/video/…" style="flex:1">
          <button>Am postat: eliberează plata</button></form><div id="perr" class="err"></div>` :
          s.status === 'plătit' ? `<div class="pill ok">Plătit</div> <a class="small" href="${esc(s.link)}" target="_blank" rel="noopener">${esc(s.link)}</a>` :
          `<a class="btn" href="#/u/${s.campaign}">Refilmează și încarcă din nou</a>`}</div>
      </div>
    </div>`;
  const vid = document.getElementById('vid'), tl = document.getElementById('tl'), hd = document.getElementById('hd'), ov = document.getElementById('ov');
  const seek = t => { vid.currentTime = Math.max(0, t - 0.2); vid.play().catch(() => {}); };
  tl.onclick = e => { const r = tl.getBoundingClientRect(); seek((e.clientX - r.left) / r.width * d); };
  document.querySelectorAll('[data-t]').forEach(el => el.onclick = () => seek(+el.dataset.t));
  const samples = v.timeline.logo_samples || [];
  const draw = () => {
    hd.style.left = pct(vid.currentTime || 0);
    const r = vid.getBoundingClientRect(), pr = vid.parentElement.getBoundingClientRect();
    ov.width = r.width; ov.height = r.height; ov.style.left = (r.left - pr.left) + 'px'; ov.style.top = (r.top - pr.top) + 'px';
    const g = ov.getContext('2d'); g.clearRect(0, 0, ov.width, ov.height);
    let best = null;
    for (const smp of samples) if (Math.abs(smp.t - vid.currentTime) <= 0.2 && (!best || Math.abs(smp.t - vid.currentTime) < Math.abs(best.t - vid.currentTime))) best = smp;
    if (best && best.q) {
      // videoclipul e încadrat cu "contain"; calculăm zona efectivă
      const vw = vid.videoWidth, vh = vid.videoHeight, s = Math.min(r.width / vw, r.height / vh);
      const ox = (r.width - vw * s) / 2, oy = (r.height - vh * s) / 2;
      g.strokeStyle = '#22c55e'; g.lineWidth = 3; g.beginPath();
      best.q.forEach(([x, y], i) => { const X = ox + x * vw * s, Y = oy + y * vh * s; i ? g.lineTo(X, Y) : g.moveTo(X, Y); });
      g.closePath(); g.stroke();
    }
    if (document.body.contains(vid)) requestAnimationFrame(draw);
  };
  requestAnimationFrame(draw);
  const pub = document.getElementById('pub');
  if (pub) pub.onsubmit = async e => {
    e.preventDefault();
    try { await api(`/api/submissions/${id}/publish`, {method:'POST', body:new FormData(pub)}); route(); }
    catch (x) { document.getElementById('perr').textContent = x.message; }
  };
}

// ------------------------------------------------------------------ rute

async function route() {
  clearTimeout(timer);
  const h = location.hash.slice(1) || '/';
  const [, page, id] = h.split('/');
  try {
    if (!page) await home();
    else if (page === 'new') await newCampaign();
    else if (page === 'c') await campaign(id);
    else if (page === 'u') await upload(id);
    else if (page === 's') await submission(id);
    else $app.innerHTML = '<p>Pagina nu există.</p>';
  } catch (e) {
    $app.innerHTML = `<div class="card err">${esc(e.message)}</div>`;
  }
}
addEventListener('hashchange', route);
route();
