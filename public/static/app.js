/* StudyAI front end - plain JavaScript, no build step. Every control calls a real /api endpoint. */
(() => {
'use strict';
const $ = id => document.getElementById(id);
const S = { user: null, profile: null, docs: [], authMode: 'login', quiz: null, deck: { cards: [], i: 0, flip: false }, busy: new Set() };
const TITLES = { dashboard: 'Dashboard', library: 'My Library', tutor: 'AI Tutor', notes: 'AI Notes', quiz: 'Practice Quiz', flash: 'AI Flashcards', planner: 'Study Planner', tracker: 'Study Tracker', coach: 'AI Study Coach', profile: 'Learning Profile' };

/* ---------- helpers ---------- */
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
function md(src) { // escape first, then add a small safe subset of Markdown
  const lines = esc(src).split('\n'); const out = []; let list = null;
  const inline = t => t.replace(/\*\*(.+?)\*\*/g, '<b>$1</b>').replace(/`([^`]+)`/g, '<code>$1</code>');
  const close = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    let m;
    if ((m = l.match(/^(#{1,4})\s+(.*)/))) { close(); out.push(`<h${Math.min(m[1].length + 1, 4)}>${inline(m[2])}</h${Math.min(m[1].length + 1, 4)}>`); }
    else if (/^\s*\|.*\|\s*$/.test(l) && /^\s*\|[\s:|-]+\|\s*$/.test(lines[i + 1] || '')) {
      close(); const cells = r => r.trim().replace(/^\||\|$/g, '').split('|').map(c => inline(c.trim()));
      let t = '<table><thead><tr>' + cells(l).map(c => `<th>${c}</th>`).join('') + '</tr></thead><tbody>'; i += 2;
      for (; i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i]); i++) t += '<tr>' + cells(lines[i]).map(c => `<td>${c}</td>`).join('') + '</tr>';
      i--; out.push(t + '</tbody></table>');
    }
    else if ((m = l.match(/^\s*[-*]\s+(.*)/))) { if (list !== 'ul') { close(); out.push('<ul>'); list = 'ul'; } out.push(`<li>${inline(m[1])}</li>`); }
    else if ((m = l.match(/^\s*\d+[.)]\s+(.*)/))) { if (list !== 'ol') { close(); out.push('<ol>'); list = 'ol'; } out.push(`<li>${inline(m[1])}</li>`); }
    else if (!l.trim()) close();
    else { close(); out.push(`<p>${inline(l)}</p>`); }
  }
  close(); return out.join('');
}
const when = ts => new Date(ts * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' });

function toast(msg, kind = 'info') {
  const t = document.createElement('div'); t.className = 'toast ' + kind; t.textContent = msg; $('toasts').appendChild(t);
  setTimeout(() => t.remove(), kind === 'error' ? 6000 : 3500);
}
async function api(url, opt = {}) {
  const o = { ...opt, headers: { 'X-TZ-Offset': String(new Date().getTimezoneOffset()), ...(opt.headers || {}) } };
  if (o.json !== undefined) { o.method = o.method || 'POST'; o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(o.json); }
  let r;
  try { r = await fetch(url, o); } catch { throw new Error('Unable to connect to the server. Please try again.'); }
  let d = {}; try { d = await r.json(); } catch { /* non-JSON body */ }
  if (r.status === 401 && S.user) { S.user = null; showAuth(); throw new Error(d.error || 'Please log in again.'); }
  if (!r.ok) throw new Error(d.error || `Request failed (${r.status}).`);
  return d;
}
async function run(key, btn, label, fn) { // prevents double submits and shows progress on the button
  if (S.busy.has(key)) return; S.busy.add(key);
  const old = btn && btn.textContent; if (btn) { btn.disabled = true; if (label) btn.textContent = label; }
  try { return await fn(); } catch (e) { toast(e.message, 'error'); } finally { S.busy.delete(key); if (btn) { btn.disabled = false; if (label) btn.textContent = old; } }
}
function confirmBox(title, text, okLabel = 'Delete') {
  return new Promise(res => {
    $('modal-box').innerHTML = `<h3>${esc(title)}</h3><p class="muted">${esc(text)}</p><div class="actions mt"><button class="danger" id="m-ok">${esc(okLabel)}</button><button class="secondary" id="m-no">Cancel</button></div>`;
    $('modal').classList.remove('hidden'); $('m-no').focus();
    const done = v => { $('modal').classList.add('hidden'); res(v); };
    $('m-ok').onclick = () => done(true); $('m-no').onclick = () => done(false);
  });
}
const skeleton = n => Array.from({ length: n }, () => '<div class="skeleton"></div>').join('');
const empty = t => `<div class="empty">${esc(t)}</div>`;
const fail = (e) => `<div class="empty err">${esc(e.message)} <button class="link" data-action="reload">Retry</button></div>`;

/* ---------- auth / shell ---------- */
function showAuth() { $('boot').classList.add('hidden'); $('app').classList.add('hidden'); $('auth').classList.remove('hidden'); }
function setAuthMode(m) {
  S.authMode = m; $('name-field').classList.toggle('hidden', m !== 'signup'); $('auth-btn').textContent = m === 'login' ? 'Login' : 'Create account';
  document.querySelectorAll('[data-auth]').forEach(b => b.classList.toggle('active', b.dataset.auth === m)); $('auth-msg').textContent = '';
  $('password').autocomplete = m === 'login' ? 'current-password' : 'new-password';
}
async function submitAuth(e) {
  e.preventDefault(); const msg = $('auth-msg'); msg.textContent = '';
  const email = $('email').value.trim(), password = $('password').value, name = $('name').value.trim();
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return msg.textContent = 'Please enter a valid email address.';
  if (password.length < 8) return msg.textContent = 'Password must be at least 8 characters.';
  if (S.authMode === 'signup' && name.length < 2) return msg.textContent = 'Please enter your name.';
  await run('auth', $('auth-btn'), 'Please wait…', async () => {
    try { await api('/api/auth/' + S.authMode, { json: S.authMode === 'signup' ? { name, email, password } : { email, password } }); $('password').value = ''; await start(); }
    catch (err) { msg.textContent = err.message; }
  });
}
async function start() {
  try { const m = await api('/api/me'); S.user = m.user; S.profile = m.profile; } catch { return showAuth(); }
  $('boot').classList.add('hidden'); $('auth').classList.add('hidden'); $('app').classList.remove('hidden');
  $('user-pill').textContent = S.user.name; $('welcome').textContent = 'Welcome back, ' + S.user.name;
  fillProfile(); setMinDate(); await loadDocs(); go(location.hash.slice(1) in TITLES ? location.hash.slice(1) : 'dashboard');
}
function go(page) {
  document.querySelectorAll('.section').forEach(s => s.classList.toggle('active', s.id === page));
  document.querySelectorAll('#nav button').forEach(b => b.classList.toggle('active', b.dataset.page === page));
  $('title').textContent = TITLES[page]; history.replaceState(null, '', '#' + page); $('side').classList.remove('open'); window.scrollTo(0, 0);
  ({ dashboard: loadDash, library: renderDocs, tutor: loadChat, notes: loadNotes, quiz: loadQuizList, flash: loadDecks, planner: loadPlans, tracker: loadTracker }[page] || (() => {}))();
}

/* ---------- documents ---------- */
async function loadDocs() {
  try { S.docs = (await api('/api/documents')).documents; } catch (e) { toast(e.message, 'error'); }
  const opts = '<option value="">Select document…</option>' + S.docs.map(d => `<option value="${d.id}">${esc(d.title)}</option>`).join('');
  document.querySelectorAll('select[data-doc]').forEach(s => { const keep = s.value; s.innerHTML = opts; if (S.docs.some(d => String(d.id) === keep)) s.value = keep; else if (S.docs.length === 1) s.value = S.docs[0].id; });
  renderDocs();
}
function renderDocs() {
  $('docs').innerHTML = S.docs.length ? S.docs.map(d => `<div class="listitem"><div><b>${esc(d.title)}</b><div class="muted small">${when(d.created_at)} · ${d.chunks} chunks</div></div><div class="actions"><button class="secondary" data-action="use-doc" data-id="${d.id}">Open in tutor</button><button class="danger" data-action="del-doc" data-id="${d.id}">Delete</button></div></div>`).join('') : empty('No documents yet. Upload your first PDF, TXT or Markdown file.');
}
function useDoc(id) { document.querySelectorAll('select[data-doc]').forEach(s => s.value = id); go('tutor'); }
async function upload() {
  const f = $('file').files[0]; if (!f) return toast('Choose a PDF, TXT or Markdown file first.', 'error');
  if (!/\.(pdf|txt|md)$/i.test(f.name)) return toast('File type not supported. Upload a PDF, TXT or Markdown file.', 'error');
  await run('upload', $('upload-btn'), 'Uploading & indexing…', async () => {
    const fd = new FormData(); fd.append('file', f); const d = await api('/api/upload', { method: 'POST', body: fd });
    toast(`${d.title} indexed (${d.chunks} chunks).`, 'success'); $('file').value = ''; $('file-name').textContent = ''; await loadDocs();
  });
}

/* ---------- dashboard / tracker ---------- */
function chart(series) {
  const max = Math.max(10, ...series.map(s => s.minutes));
  return `<div class="bars" role="img" aria-label="Study minutes per day">${series.map(s => `<div class="bar" title="${s.date}: ${s.minutes} min"><b>${s.minutes || ''}</b><i style="height:${Math.round(100 * s.minutes / max * 0.78)}%"></i><span>${s.date.slice(8)}</span></div>`).join('')}</div>`;
}
const ACT = { document_upload: 'Uploaded a document', ai_tutor: 'Asked the AI Tutor', notes_generated: 'Generated notes', quiz_generated: 'Generated a quiz', quiz_answered: 'Answered a quiz question', flashcards_generated: 'Generated flashcards', planner_created: 'Created a study plan', plan_task_done: 'Completed a plan task', ai_coach: 'Asked the coach' };
async function loadDash() {
  $('stats').innerHTML = skeleton(4);
  try {
    const d = await api('/api/dashboard');
    $('stats').innerHTML = [['Documents', d.documents], ['Tutor questions', d.questions], ['Quiz accuracy', d.quiz_answered ? d.quiz_accuracy + '%' : '—'], ['🔥 Streak', d.current_streak + ' d']].map(([k, v]) => `<div class="card stat"><div class="muted">${k}</div><div class="n">${v}</div></div>`).join('');
    $('chart').innerHTML = chart(d.activity);
    const goal = S.profile.daily_minutes || 120, pct = Math.min(100, Math.round(100 * d.today_minutes / goal));
    $('goal-text').textContent = `${d.today_minutes} of ${goal} minutes today`; $('goalbar').style.width = pct + '%';
    $('badges').innerHTML = d.badges.map(b => `<span class="badge" title="${esc(b.description)}">🏆 ${esc(b.name)}</span>`).join('') || '<span class="muted small">No badges yet.</span>';
    $('recent').innerHTML = d.recent.length ? d.recent.map(a => `<div class="listitem"><div>${esc(ACT[a.activity_type] || a.activity_type)}${a.topic ? ' · ' + esc(a.topic) : ''}<div class="muted small">${esc(a.document_title || '')}</div></div><span class="muted small">${when(a.created_at)}</span></div>`).join('') : empty('Your activity will show up here.');
    const t = (await api('/api/topics')).topics.slice(0, 4);
    $('dash-topics').innerHTML = topicRows(t, 'Complete a quiz to see topic performance.');
  } catch (e) { $('stats').innerHTML = fail(e); }
}
function topicRows(t, msg) {
  return t.length ? t.map(x => `<div class="listitem"><div><b>${esc(x.topic)}</b><div class="muted small">${x.correct}/${x.attempted} correct</div></div><div class="actions"><div class="meter"><i style="width:${x.accuracy}%;background:${x.accuracy >= 70 ? 'var(--ok)' : x.accuracy >= 40 ? 'var(--warn)' : 'var(--bad)'}"></i></div><b>${Math.round(x.accuracy)}%</b></div></div>`).join('') : empty(msg);
}
async function loadTracker() {
  try {
    const d = await api('/api/dashboard'); $('streak-big').textContent = d.current_streak + ' day streak'; $('longest').textContent = d.longest_streak;
    $('tracker-stats').innerHTML = `<p>Total study time: <b>${d.study_minutes} min</b></p><p>Quiz accuracy: <b>${d.quiz_answered ? d.quiz_accuracy + '% (' + d.quiz_answered + ' answers)' : 'no quiz answers yet'}</b></p><p>Tutor questions: <b>${d.questions}</b></p>`;
    $('tracker-badges').innerHTML = d.badges.map(b => `<span class="badge">🏆 ${esc(b.name)}</span>`).join('') || '<span class="muted">No badges yet.</span>';
    $('topics').innerHTML = topicRows((await api('/api/topics')).topics, 'Complete quizzes to build topic performance.');
  } catch (e) { $('topics').innerHTML = fail(e); }
}

/* ---------- tutor ---------- */
const tutorDoc = () => $('tutor-doc').value;
function bubble(role, html) { const log = $('chatlog'); log.insertAdjacentHTML('beforeend', `<div class="bubble ${role}">${html}</div>`); log.scrollTop = log.scrollHeight; return log.lastElementChild; }
async function loadChat() {
  const log = $('chatlog'); log.innerHTML = '';
  if (!tutorDoc()) return log.innerHTML = empty(S.docs.length ? 'Select a document to start asking questions.' : 'Upload a document in My Library first.');
  try { const h = (await api('/api/chat/history?document_id=' + tutorDoc())).messages; if (!h.length) log.innerHTML = empty('Ask your first question about this document.'); h.forEach(m => bubble(m.role === 'user' ? 'user' : 'ai note', m.role === 'user' ? esc(m.content) : md(m.content))); }
  catch (e) { log.innerHTML = fail(e); }
}
async function sendChat() {
  const q = $('chat').value.trim(), did = tutorDoc();
  if (!did) return toast('Select a document first.', 'error'); if (!q) return;
  $('chatlog').querySelector('.empty')?.remove(); bubble('user', esc(q)); $('chat').value = '';
  const wait = bubble('ai', '<span class="muted">Thinking…</span>');
  await run('chat', $('send-btn'), '…', async () => {
    try {
      const d = await api('/api/chat', { json: { document_id: +did, question: q, mode: $('mode').value } });
      wait.className = 'bubble ai note'; wait.innerHTML = md(d.answer) + `<div class="source">Sources: ${d.sources.map(s => 'chunk ' + s.chunk_index).join(', ') || 'none'}</div>`;
    } catch (e) { wait.className = 'bubble ai err'; wait.textContent = e.message; }
    $('chatlog').scrollTop = $('chatlog').scrollHeight; $('chat').focus();
  });
}
async function clearChat() {
  if (!tutorDoc()) return; if (!await confirmBox('Clear chat?', 'This deletes the saved conversation for this document.', 'Clear')) return;
  await run('clear', null, null, async () => { await api('/api/chat?document_id=' + tutorDoc(), { method: 'DELETE' }); loadChat(); });
}

/* ---------- notes ---------- */
async function makeNotes() {
  const did = $('notes-doc').value; if (!did) return toast('Select a document first.', 'error');
  await run('notes', $('notes-btn'), 'Generating…', async () => {
    const d = await api('/api/notes', { json: { document_id: +did, request: $('notes-request').value.trim() } }); showNote(d); toast('Notes saved.', 'success'); loadNotes();
  });
}
function showNote(n) { $('notes-out').className = 'note'; $('notes-out').innerHTML = `<h3>${esc(n.title)}</h3>` + md(n.content); $('notes-actions').innerHTML = `<a class="secondary" href="/api/notes/${n.id}/download?format=pdf">Download PDF</a><a class="secondary" href="/api/notes/${n.id}/download?format=docx">Download DOCX</a>`; }
async function loadNotes() {
  $('notes-list').innerHTML = skeleton(2);
  try { const ns = (await api('/api/notes')).notes; $('notes-list').innerHTML = ns.length ? ns.map(n => `<div class="listitem"><div><b>${esc(n.title)}</b><div class="muted small">${when(n.created_at)}${n.document_title ? ' · ' + esc(n.document_title) : ''}</div></div><div class="actions"><button class="secondary" data-action="view-note" data-id="${n.id}">View</button><button class="danger" data-action="del-note" data-id="${n.id}">Delete</button></div></div>`).join('') : empty('No saved notes yet.'); }
  catch (e) { $('notes-list').innerHTML = fail(e); }
}

/* ---------- quiz ---------- */
async function startQuiz() {
  const did = $('quiz-doc').value; if (!did) return toast('Select a document first.', 'error');
  await run('quiz', $('quiz-btn'), 'Generating…', async () => {
    const d = await api('/api/quiz/generate', { json: { document_id: +did, count: +$('quiz-count').value, difficulty: $('quiz-diff').value } }); await openQuiz(d.quiz_id); loadQuizList();
  });
}
async function openQuiz(id) {
  const q = await api('/api/quiz/' + id); const first = q.questions.findIndex(x => !x.answered);
  S.quiz = { id, qs: q.questions, i: first < 0 ? q.questions.length : first, title: q.document_title }; renderQuiz();
}
function renderQuiz() {
  const z = S.quiz, box = $('quizbox'); if (!z) return box.innerHTML = '';
  if (z.i >= z.qs.length) return finishQuiz();
  const q = z.qs[z.i], pct = Math.round(100 * z.i / z.qs.length);
  box.innerHTML = `<div class="card"><div class="actions" style="justify-content:space-between"><b>${esc(z.title)}</b><span class="muted small">Question ${z.i + 1} of ${z.qs.length}</span></div><div class="progress"><div style="width:${pct}%"></div></div><div class="quizq"><p><b>${esc(q.question)}</b></p>${q.options.map((o, j) => `<button class="opt" data-action="answer" data-j="${j}">${String.fromCharCode(65 + j)}. ${esc(o)}</button>`).join('')}<div id="fb" class="small" aria-live="polite"></div></div><div class="actions mt" id="qnav"></div></div>`;
}
async function answer(btn) {
  const z = S.quiz, q = z.qs[z.i], j = +btn.dataset.j; const opts = [...document.querySelectorAll('.opt')];
  await run('answer', null, null, async () => {
    opts.forEach(o => o.disabled = true);
    try {
      const r = await api(`/api/quiz/${z.id}/answer`, { json: { question_id: q.id, answer: j } }); q.answered = true; q.correct = r.correct;
      opts[j].classList.add(r.correct ? 'correct' : 'wrong'); opts[r.correct_index].classList.add('correct');
      $('fb').innerHTML = `<p class="${r.correct ? 'ok' : 'err'}"><b>${r.correct ? '✓ Correct' : '✗ Incorrect'}</b></p><p class="muted">${esc(r.explanation)}</p>`;
      $('qnav').innerHTML = `<button class="primary" data-action="next-q">${z.i + 1 >= z.qs.length ? 'Finish quiz' : 'Next question'}</button>`;
    } catch (e) { opts.forEach(o => o.disabled = false); throw e; }
  });
}
async function finishQuiz() {
  const z = S.quiz; try {
    const r = await api(`/api/quiz/${z.id}/result`);
    $('quizbox').innerHTML = `<div class="card"><div class="eyebrow">Result</div><h2>${r.correct} / ${r.answered} correct · ${r.percentage}%</h2><div class="progress"><div style="width:${r.percentage}%"></div></div>${r.details.map((d, i) => `<div class="listitem"><div><b>${i + 1}. ${esc(d.question)}</b><div class="small ${d.correct ? 'ok' : 'err'}">Your answer: ${esc(d.options[d.student_answer])}${d.correct ? '' : ' — correct: ' + esc(d.options[d.correct_index])}</div><div class="muted small">${esc(d.explanation)}</div></div></div>`).join('')}</div>`;
    loadQuizList();
  } catch (e) { $('quizbox').innerHTML = fail(e); }
}
async function loadQuizList() {
  try {
    const qs = (await api('/api/quizzes')).quizzes;
    $('quiz-list').innerHTML = qs.length ? qs.map(q => `<div class="listitem"><div><b>${esc(q.document_title)}</b> <span class="muted small">· ${esc(q.difficulty)}</span><div class="muted small">${when(q.created_at)} · ${q.answered}/${q.total} answered${q.percentage === null ? '' : ' · ' + q.percentage + '%'}</div></div><div class="actions"><button class="secondary" data-action="open-quiz" data-id="${q.id}">${q.answered >= q.total ? 'Review' : 'Resume'}</button><button class="danger" data-action="del-quiz" data-id="${q.id}">Delete</button></div></div>`).join('') : empty('No quizzes yet.');
  } catch (e) { $('quiz-list').innerHTML = fail(e); }
}

/* ---------- flashcards ---------- */
function renderCard() {
  const { cards, i, flip } = S.deck; if (!cards.length) return $('flashcard').innerHTML = '<div class="muted">Generate or open a deck to start.</div>';
  $('flashcard').innerHTML = `<div><div class="muted small">${flip ? 'ANSWER' : 'QUESTION'} · ${i + 1}/${cards.length}</div><h2>${esc(flip ? cards[i].answer : cards[i].question)}</h2><div class="muted small">Difficulty: ${esc(cards[i].difficulty)}</div></div>`;
}
async function makeFlash() {
  const did = $('flash-doc').value; if (!did) return toast('Select a document first.', 'error');
  await run('flash', $('flash-btn'), 'Generating…', async () => { const d = await api('/api/flashcards', { json: { document_id: +did, count: +$('flash-count').value } }); S.deck = { cards: d.cards, i: 0, flip: false }; renderCard(); toast(`${d.cards.length} cards saved.`, 'success'); loadDecks(); });
}
async function loadDecks() {
  try { const ds = (await api('/api/flashcards')).decks; $('deck-list').innerHTML = ds.length ? ds.map(d => `<div class="listitem"><div><b>${esc(d.document_title || 'Deck')}</b><div class="muted small">${d.cards} cards · ${when(d.created_at)}</div></div><div class="actions"><button class="secondary" data-action="open-deck" data-id="${d.id}">Open</button><button class="danger" data-action="del-deck" data-id="${d.id}">Delete</button></div></div>`).join('') : empty('No saved decks yet.'); }
  catch (e) { $('deck-list').innerHTML = fail(e); }
}

/* ---------- planner ---------- */
function setMinDate() { const t = new Date(); t.setMinutes(t.getMinutes() - t.getTimezoneOffset()); const iso = t.toISOString().slice(0, 10); $('plan-start').min = iso; $('plan-start').value = iso; $('plan-minutes').value = S.profile.daily_minutes || 120; }
async function makePlan() {
  const did = $('plan-doc').value, start = $('plan-start').value;
  if (!did) return toast('Select a document first.', 'error'); if (!start) return toast('Choose a start date.', 'error'); if (start < $('plan-start').min) return toast('Past dates cannot be selected.', 'error');
  await run('plan', $('plan-btn'), 'Generating…', async () => { await api('/api/planner', { json: { document_id: +did, days: +$('plan-days').value, start_date: start, minutes: +$('plan-minutes').value } }); toast('Plan created.', 'success'); loadPlans(); });
}
async function loadPlans() {
  $('plan-list').innerHTML = skeleton(2);
  try {
    const ps = (await api('/api/plans')).plans;
    $('plan-list').innerHTML = ps.length ? ps.map(p => { const all = p.plan.flatMap(d => d.tasks), done = all.filter(t => t.done).length;
      return `<div class="card mt"><div class="actions" style="justify-content:space-between"><div><b>${esc(p.title || 'Study plan')}</b><div class="muted small">${done}/${all.length} tasks done</div></div><div class="actions"><a class="secondary" href="/api/plans/${p.id}/download">Download PDF</a><button class="danger" data-action="del-plan" data-id="${p.id}">Delete</button></div></div><div class="progress"><div style="width:${all.length ? Math.round(100 * done / all.length) : 0}%"></div></div>
      ${p.plan.map(d => `<div class="listitem"><div><b>Day ${d.day} · ${esc(d.date)}</b> — ${esc(d.title)} <span class="muted small">(${d.minutes} min)</span>${d.tasks.map((t, i) => `<label class="task ${t.done ? 'done' : ''}"><input type="checkbox" data-plan="${p.id}" data-day="${d.day}" data-idx="${i}" ${t.done ? 'checked' : ''}><span>${esc(t.text)}</span></label>`).join('')}</div></div>`).join('')}</div>`; }).join('') : empty('No study plans yet. Generate one above.');
  } catch (e) { $('plan-list').innerHTML = fail(e); }
}
async function toggleTask(cb) {
  cb.disabled = true;
  try { await api(`/api/plans/${cb.dataset.plan}/tasks`, { json: { day: +cb.dataset.day, index: +cb.dataset.idx, done: cb.checked } }); await loadPlans(); }
  catch (e) { cb.checked = !cb.checked; cb.disabled = false; toast(e.message, 'error'); }
}

/* ---------- coach / profile / search ---------- */
async function coach() { await run('coach', $('coach-btn'), 'Analyzing…', async () => { $('coach-out').innerHTML = '<span class="muted">Analyzing your progress…</span>'; try { $('coach-out').innerHTML = md((await api('/api/coach')).answer); } catch (e) { $('coach-out').innerHTML = ''; throw e; } }); }
function fillProfile() { const p = S.profile; $('p-course').value = p.course || ''; $('p-lang').value = p.preferred_language || ''; $('p-style').value = p.explanation_style || 'Detailed'; $('p-min').value = p.daily_minutes || 120; $('p-exam').value = p.exam_date || ''; }
async function saveProfile() {
  const m = +$('p-min').value; if (!(m >= 10 && m <= 600)) return toast('Daily minutes must be between 10 and 600.', 'error');
  await run('profile', null, null, async () => { S.profile = (await api('/api/profile', { method: 'PUT', json: { course: $('p-course').value, preferred_language: $('p-lang').value, explanation_style: $('p-style').value, daily_minutes: m, exam_date: $('p-exam').value } })).profile; fillProfile(); toast('Profile saved. AI answers will use it.', 'success'); });
}
let searchTimer;
function doSearch() {
  clearTimeout(searchTimer); const q = $('global-search').value.trim(), box = $('search-results');
  if (q.length < 2) return box.classList.add('hidden');
  searchTimer = setTimeout(async () => {
    try { const r = (await api('/api/search?q=' + encodeURIComponent(q))).results; box.classList.remove('hidden');
      box.innerHTML = r.length ? r.map(x => `<button data-action="open-result" data-type="${x.type}" data-id="${x.id}"><b>${esc(x.title)}</b><div class="muted small">${x.type}${x.snippet ? ' · ' + esc(x.snippet) : ''}</div></button>`).join('') : '<div class="muted small" style="padding:12px">No results.</div>'; }
    catch (e) { box.classList.add('hidden'); }
  }, 250);
}

/* ---------- events ---------- */
const A = {
  logout: async () => { await api('/api/auth/logout', { method: 'POST' }).catch(() => {}); S.user = null; showAuth(); }, menu: () => $('side').classList.toggle('open'),
  reload: () => go(document.querySelector('.section.active').id), pick: () => $('file').click(), upload, send: sendChat, 'clear-chat': clearChat,
  'use-doc': b => useDoc(b.dataset.id), 'del-doc': async b => { if (await confirmBox('Delete document?', 'Its chunks, chat and quizzes are removed too.')) await run('del', null, null, async () => { await api('/api/documents/' + b.dataset.id, { method: 'DELETE' }); toast('Document deleted.', 'success'); await loadDocs(); }); },
  'make-notes': makeNotes, 'view-note': async b => run('vn', null, null, async () => showNote(await api('/api/notes/' + b.dataset.id))),
  'del-note': async b => { if (await confirmBox('Delete note?', 'This cannot be undone.')) await run('del', null, null, async () => { await api('/api/notes/' + b.dataset.id, { method: 'DELETE' }); loadNotes(); }); },
  'start-quiz': startQuiz, answer, 'next-q': () => { S.quiz.i++; renderQuiz(); }, 'open-quiz': b => run('oq', null, null, () => openQuiz(b.dataset.id)),
  'del-quiz': async b => { if (await confirmBox('Delete quiz?', 'Its answers are removed; topic statistics are kept.')) await run('del', null, null, async () => { await api('/api/quiz/' + b.dataset.id, { method: 'DELETE' }); if (S.quiz && S.quiz.id == b.dataset.id) { S.quiz = null; renderQuiz(); } loadQuizList(); }); },
  'make-flash': makeFlash, flip: () => { S.deck.flip = !S.deck.flip; renderCard(); }, 'next-card': () => { const d = S.deck; if (d.cards.length) { d.i = (d.i + 1) % d.cards.length; d.flip = false; renderCard(); } }, 'prev-card': () => { const d = S.deck; if (d.cards.length) { d.i = (d.i - 1 + d.cards.length) % d.cards.length; d.flip = false; renderCard(); } },
  'open-deck': b => run('od', null, null, async () => { S.deck = { cards: (await api('/api/flashcards/' + b.dataset.id)).cards, i: 0, flip: false }; renderCard(); }),
  'del-deck': async b => { if (await confirmBox('Delete deck?', 'This cannot be undone.')) await run('del', null, null, async () => { await api('/api/flashcards/' + b.dataset.id, { method: 'DELETE' }); loadDecks(); }); },
  'make-plan': makePlan, 'del-plan': async b => { if (await confirmBox('Delete plan?', 'This cannot be undone.')) await run('del', null, null, async () => { await api('/api/plans/' + b.dataset.id, { method: 'DELETE' }); loadPlans(); }); },
  coach, 'save-profile': saveProfile,
  'open-result': b => { $('search-results').classList.add('hidden'); $('global-search').value = ''; const t = b.dataset.type; if (t === 'document') useDoc(b.dataset.id); else if (t === 'note') { go('notes'); A['view-note'](b); } else { go('flash'); A['open-deck'](b); } },
};
document.addEventListener('click', e => {
  const g = e.target.closest('[data-go]'); if (g) return go(g.dataset.go);
  const t = e.target.closest('[data-auth]'); if (t) return setAuthMode(t.dataset.auth);
  const n = e.target.closest('#nav button'); if (n) return go(n.dataset.page);
  const a = e.target.closest('[data-action]'); if (a && A[a.dataset.action]) A[a.dataset.action](a);
  if (!e.target.closest('.searchbox')) $('search-results').classList.add('hidden');
});
document.addEventListener('change', e => {
  if (e.target.matches('input[data-plan]')) toggleTask(e.target);
  if (e.target.id === 'file') $('file-name').textContent = e.target.files[0] ? e.target.files[0].name : '';
  if (e.target.id === 'tutor-doc') loadChat();
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') { $('modal').classList.add('hidden'); $('search-results').classList.add('hidden'); } });
$('chat').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); } });
$('auth-form').addEventListener('submit', submitAuth);
$('global-search').addEventListener('input', doSearch);
const drop = $('drop');
['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', e => { if (e.dataTransfer.files[0]) { $('file').files = e.dataTransfer.files; $('file-name').textContent = e.dataTransfer.files[0].name; } });
api('/api/health').then(h => { $('max-size').textContent = `Supported: PDF, TXT, Markdown · max ${h.max_upload_mb} MB.`; }).catch(() => {});
start();
})();
