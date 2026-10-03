/* 종합계좌 PWA — 퇴직연금·ISA 등 계좌별 관리.
   헬퍼·탭 전환·차트·푸시·바텀시트.
   다른 점은 두 가지뿐이다: 통화가 달러가 아니라 원화이고,
   주문을 계산하지 않고 사용자가 실제로 한 매매를 기록한다.

   계좌 탭(퇴직연금·ISA·…)은 서버의 계좌 등록부를 받아 이 파일이 찍어 낸다 (2026-09-16).
   그래서 계좌를 더할 때 고칠 곳은 서버 src/accounts.py 한 군데뿐이다. */
'use strict';

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const WD = ['월', '화', '수', '목', '금', '토', '일'];

/* ---------- 유틸 ---------- */
/* 원화는 소수점이 없다. 반올림한 정수에 "원"만 붙인다. */
const krw = v => Math.round(Number(v) || 0).toLocaleString('ko-KR') + '원';

/* 종목 표 칸 안의 숫자. 칸마다 "원" 을 붙이면 폰 폭(375px)에서 다섯 칸이 안 들어가
   수익률이 화면 밖으로 밀려난다. 금액은 바로 아래 소계 줄에 "원" 과 함께 다시 나오므로 칸에서는 뺀다. */
const n0 = v => Math.round(Number(v) || 0).toLocaleString('ko-KR');

/* 부호 붙은 숫자(단위 없음). 증권사 화면처럼 평가손익 칸에 쓴다. */
const mn0 = v => {
  const n = Math.round(Number(v) || 0);
  return (n > 0 ? '+' : n < 0 ? '−' : '') + Math.abs(n).toLocaleString('ko-KR');
};

/* 부호를 앞에 붙인 금액. 마이너스는 하이픈이 아니라 U+2212 라 자릿수가 흔들리지 않는다. */
const mkrw = v => {
  const n = Math.round(Number(v) || 0);
  if (n === 0) return krw(0);
  return (n > 0 ? '+' : '−') + krw(Math.abs(n));
};

/* 서버가 주는 비율은 전부 소수다(−0.0389). 여기서 한 번만 ×100 한다. */
const pct = (v, d = 2) => {
  const n = (Number(v) || 0) * 100;
  return (n >= 0 ? '+' : '−') + Math.abs(n).toFixed(d) + '%';
};

/* 한국 증권 관행: 오르면 빨강(up), 내리면 파랑(down). */
const cls = v => v > 0 ? 'up' : (v < 0 ? 'down' : 'flat');

const esc = s => String(s).replace(/[&<>"]/g, c =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/* 억·만 보조 표기. "123,456,789원" 은 아홉 자리라 한눈에 안 들어온다.
   앞자리만 잘라 "1억 2,345만" 으로 읽어준다. 버림으로 자르는 이유는
   반올림하면 실제 금액보다 커 보이는 쪽으로 틀리기 때문이다. */
function kshort(v) {
  const raw = Math.round(Number(v) || 0);
  const n = Math.abs(raw), sign = raw < 0 ? '−' : '';
  if (n < 10000) return sign + n.toLocaleString('ko-KR') + '원';
  const eok = Math.floor(n / 100000000);
  const man = Math.floor((n % 100000000) / 10000);
  if (eok > 0) return sign + eok + '억' + (man ? ' ' + man.toLocaleString('ko-KR') + '만' : '');
  return sign + man.toLocaleString('ko-KR') + '만';
}

/* 차트 세로축 눈금. 원 단위를 그대로 찍으면 축 글씨가 그래프를 덮는다. */
function axisKrw(v) {
  const n = Math.abs(v), sign = v < 0 ? '−' : '';
  if (n >= 100000000) return sign + (n / 100000000).toFixed(n >= 1000000000 ? 0 : 2) + '억';
  if (n >= 10000) return sign + Math.round(n / 10000).toLocaleString('ko-KR') + '만';
  return sign + Math.round(n).toLocaleString('ko-KR');
}

/* "2026-09-09T16:00:27" -> "2026-09-09 16:00". 초까지는 볼 일이 없다. */
const fmtTs = s => s ? String(s).replace('T', ' ').slice(0, 16) : '—';

/* CSV 로 온 값은 전부 문자열이다. 숫자로 못 바꾸면 null 을 돌려
   차트에서 0 이 아니라 끊긴 구간으로 그려지게 한다. */
const num = v => { const n = parseFloat(v); return isFinite(n) ? n : null; };

const kpi = (k, v, s, c) =>
  `<div class="kpi"><span class="k">${k}</span><span class="v ${c || ''}">${v}</span><span class="s">${s}</span></div>`;

function toast(msg, ms = 2600) {
  const t = $('#toast'); t.textContent = msg; t.classList.add('on');
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove('on'), ms);
}

async function api(path, opts = {}) {
  const r = await fetch(path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' }, ...opts
  });
  if (r.status === 401) { showLogin(); throw new Error('로그인이 필요합니다'); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(errText(j));
  return j;
}

/* FastAPI 의 detail 은 두 가지 모양으로 온다.
   우리가 던진 400 은 문자열이지만, Pydantic 검증 실패(422)는 객체 배열이라
   그대로 쓰면 토스트에 "[object Object]" 가 뜬다. 배열이면 msg 만 뽑아 붙인다. */
function errText(j) {
  const d = j && j.detail;
  if (typeof d === 'string' && d) return d;
  if (Array.isArray(d) && d.length) {
    const msgs = d.map(x => (x && x.msg) || '').filter(Boolean);
    if (msgs.length) return '입력값을 확인해주세요: ' + msgs.join(', ');
  }
  return '요청이 실패했습니다';
}

/* ---------- 로그인 ---------- */
function showLogin() { $('#login').classList.remove('hidden'); $('#app').classList.add('hidden'); }
function showApp() { $('#login').classList.add('hidden'); $('#app').classList.remove('hidden'); }

$('#loginForm').addEventListener('submit', async e => {
  e.preventDefault();
  $('#loginErr').textContent = '';
  try {
    await api('/api/login', { method: 'POST', body: JSON.stringify({ password: $('#pw').value }) });
    showApp(); await start();
  } catch (err) { $('#loginErr').textContent = err.message; }
});

/* ---------- 계좌 ---------- */
/* 계좌 목록은 서버(src/accounts.py)가 정한다. 화면은 받은 대로 탭을 만든다 —
   IRP·연금저축을 더할 때 이 파일을 고칠 일이 없게 하려는 것이다. */
let ACCOUNTS = [{ key: 'dc', label: '퇴직연금' }];
/* 계좌가 여섯 개가 되면서 하단 탭에서 계좌를 뺐다 (2026-09-16).
   TAB 은 하단 탭(계좌/성과/설정), ACCT 는 계좌 탭이 보여주는 계좌다. */
let TAB = 'acct';
let ACCT = 'dc';
/* 성과 탭이 보고 있는 것. 'all' 이면 모든 계좌를 합쳐서 본다. */
const ALL = 'all';
let PERF = ALL;

const SNAPS = {};        // 계좌별 스냅샷
const HISTS = {};        // 계좌별 기록 (성과 탭이 쓴다)
const STRAT_BASE = {};   // 계좌별 '마지막으로 서버와 맞춘 전략 본문'

const acctOf = k => ACCOUNTS.find(a => a.key === k) || {};
const acctLabel = k => acctOf(k).label || k;
/* KIS 로 시세를 못 받는 계좌는 자동갱신 버튼을 감추고 종목코드 규칙도 다르다. */
const autoPrice = k => acctOf(k).autoPrice !== false;

/* 계좌 하나짜리 주소. account 를 안 붙이면 서버가 기본 계좌(퇴직연금)로 본다. */
const url = (path, acct, extra) =>
  path + '?account=' + encodeURIComponent(acct) + (extra ? '&' + extra : '');

/* 그 계좌 탭 안의 자리 하나. id 를 계좌마다 만들지 않고 data-r 로 찾는다. */
const el = (acct, r) => $(`#tab-${acct} [data-r="${r}"]`);

/* 보유 종목은 그룹 3개에 나뉘어 온다. 한 줄로 펴서 쓰는 곳이 많다. */
const items = acct => {
  const s = SNAPS[acct];
  return s && s.groups ? s.groups.reduce((a, g) => a.concat(g.items || []), []) : [];
};

/* 계좌 탭 한 장. 계좌가 몇 개든 같은 모양이라 여기 한 군데만 고치면 전부 바뀐다. */
function accountSection(a) {
  const k = esc(a.key);
  return `<section id="tab-${k}" class="tab" data-acct="${k}">
    <div class="notice hidden" data-r="notice"></div>
    <div class="kpis" data-r="kpis"></div>
    <div data-r="groups"></div>

    ${autoPrice(a.key)
      ? `<div class="btns2">
      <button class="btn" data-act="refresh">시세 자동갱신</button>
      <button class="btn" data-act="add">종목 추가</button>
    </div>`
      : `<button class="btn full" data-act="add">종목 추가</button>`}

    <div class="card">
      <h2>내일의 전략</h2>
      <p class="hint">자동으로 저장되지 않습니다. 저장 버튼을 눌러야 남습니다.</p>
      <textarea data-r="strat" placeholder="내일 무엇을 할지 적어두세요."></textarea>
      <button class="btn primary full" data-act="stratSave">저장</button>
      <p class="hint" data-r="stratMeta"></p>
    </div>

    <details class="card fold">
      <summary>관리</summary>
      <div class="fold-body">
        <div class="sect">
          <h3>현금</h3>
          <div class="row">
            <input type="number" data-r="cash" inputmode="numeric" step="1" min="0" placeholder="예수금">
            <button class="btn primary" data-act="cashSave">저장</button>
          </div>
        </div>

        <div class="sect">
          <h3>배당</h3>
          <select data-r="divCode" aria-label="종목"></select>
          <div class="row mt8">
            <input type="number" data-r="divAmount" inputmode="numeric" step="1" min="0"
                   placeholder="금액" aria-label="금액">
            <input type="date" data-r="divDate" aria-label="지급일">
          </div>
          <button class="btn primary full" data-act="divSave">배당 저장</button>
        </div>

        <div class="sect">
          <div class="card-head">
            <h3>현재가 직접 입력</h3>
            <span class="hd-r mono" data-r="priceAt">—</span>
          </div>
          <div data-r="priceRows"></div>
          <button class="btn primary full" data-act="pricesApply">현재가 반영</button>
        </div>

        <div class="sect">
          <h3>운용 시작일</h3>
          <div class="row">
            <input type="date" data-r="startDate" aria-label="운용 시작일">
            <button class="btn primary" data-act="startSave">저장</button>
          </div>
          <button class="btn ghost full" data-act="startClear">시작일 지우기</button>
        </div>

        <button class="btn ghost full" data-act="closeToday">오늘 마감 저장</button>
      </div>
    </details>
  </section>`;
}

/* 계좌 화면·칩 줄·탭바·성과 탭 계좌 선택을 한 번에 만든다. */
function buildTabs() {
  $('#acctTabs').innerHTML = ACCOUNTS.map(accountSection).join('');
  $('#acctBar').innerHTML =
    '<div class="acct-total"><span class="k">전체</span>' +
      '<span class="v" id="allTotal">—</span>' +
      '<span class="v2" id="allPl"></span></div>' +
    '<div class="acctbar">' + ACCOUNTS.map(a =>
      `<button type="button" class="chip" data-pick="${esc(a.key)}">` +
      `<span class="cn">${esc(a.label)}</span><span class="cv">—</span></button>`).join('') +
    '</div>';
  $('#tabbar').innerHTML =
    '<button data-tab="acct"><span>계좌</span></button>' +
    '<button data-tab="perf"><span>성과</span></button>' +
    '<button data-tab="set"><span>설정</span></button>';
  /* 맨 앞이 '전체' — 계좌를 다 합친 값이다. */
  $('#perfSeg').innerHTML =
    `<button type="button" class="chip" data-perf="${ALL}"><span class="cn">전체</span></button>` +
    ACCOUNTS.map(a =>
      `<button type="button" class="chip" data-perf="${esc(a.key)}">` +
      `<span class="cn">${esc(a.label)}</span></button>`).join('');

  $$('#tabbar button').forEach(b => b.addEventListener('click', () => go(b.dataset.tab)));
  $$('#acctBar [data-pick]').forEach(b => b.addEventListener('click', () => pick(b.dataset.pick)));
  $$('#perfSeg button').forEach(b => b.addEventListener('click', () => {
    PERF = b.dataset.perf;
    $$('#perfSeg button').forEach(x => x.classList.toggle('on', x === b));
    loadHistory(PERF);
  }));

  ACCT = ACCOUNTS[0].key;
  PERF = ALL;
  go('acct');
}

/* 칩 줄의 금액. 계좌를 바꿀 때가 아니라 스냅샷이 바뀔 때마다 다시 그린다.
   전체 합계는 지금까지 받아 둔 계좌만 더한다 — 아직 못 받은 계좌를 0 으로 세면
   합계가 실제보다 작게 보인다. */
function renderAcctBar() {
  const loaded = ACCOUNTS.map(a => SNAPS[a.key]).filter(Boolean);
  const total = loaded.reduce((x, s) => x + (s.totals.total || 0), 0);
  const pl = loaded.reduce((x, s) => x + (s.totals.evalPl || 0), 0);
  const buy = loaded.reduce((x, s) => x + (s.totals.buyTotal || 0), 0);
  $('#allTotal').textContent = loaded.length ? krw(total) : '—';
  const pe = $('#allPl');
  pe.textContent = loaded.length ? `${mkrw(pl)} (${pct(buy ? pl / buy : 0)})` : '';
  pe.className = 'v2 ' + cls(pl);

  $$('#acctBar [data-pick]').forEach(b => {
    const s = SNAPS[b.dataset.pick];
    b.classList.toggle('on', b.dataset.pick === ACCT);
    b.querySelector('.cv').textContent = s ? kshort(s.totals.total) : '—';
  });
}

/* 계좌 고르기. 하단 탭이 아니라 칩이 계좌를 바꾼다. */
function pick(k) {
  if (k !== ACCT && stratDirty(ACCT))
    toast('전략이 저장되지 않았습니다. 저장 버튼을 눌러야 남습니다.', 3600);
  ACCT = k;
  go('acct');
}

/* ---------- 탭 ---------- */
function go(t) {
  /* 전략은 자동저장하지 않는다. 고쳐만 놓고 나가면 그대로 날아가므로 알려준다. */
  if (TAB === 'acct' && t !== 'acct' && stratDirty(ACCT))
    toast('전략이 저장되지 않았습니다. 저장 버튼을 눌러야 남습니다.', 3600);

  TAB = t;
  $$('#tabbar button').forEach(x => x.classList.toggle('active', x.dataset.tab === t));
  /* 계좌 화면은 여러 장이 깔려 있고 그중 고른 하나만 보인다. */
  $$('.tab').forEach(s => s.classList.toggle('active',
    t === 'acct' ? s.id === 'tab-' + ACCT : s.id === 'tab-' + t));
  $('#acctBar').classList.toggle('hidden', t !== 'acct');
  $('#topTitle').textContent = t === 'perf' ? '성과' : t === 'set' ? '설정' : acctLabel(ACCT);
  /* 제목 아래 줄은 어느 탭에도 두지 않는다 — 같은 숫자가 바로 아래 KPI 에 크게 나온다. */
  $('#topSub').textContent = '';
  $('#topSub').classList.add('hidden');
  window.scrollTo(0, 0);

  if (t === 'acct') renderAcctBar();
  else if (t === 'perf') {
    $$('#perfSeg button').forEach(x => x.classList.toggle('on', x.dataset.perf === PERF));
    loadHistory(PERF);
  } else if (t === 'set') renderSettings();
}

/* ---------- 새로고침 ---------- */
$('#refresh').addEventListener('click', () => refresh(true));

/* 계좌 하나만 다시 받는다. 탭을 옮길 때마다 전 계좌를 받으면 느려진다. */
async function reload(acct) {
  SNAPS[acct] = await api(url('/api/snapshot', acct));
  renderAccount(acct);
  renderAcctBar();
}

async function refresh(manual) {
  const btn = $('#refresh'); btn.classList.add('spin');
  try {
    /* 설정 탭의 '현재 설정'이 계좌를 전부 보여주므로 한 번에 받아 둔다. */
    await Promise.all(ACCOUNTS.map(a => reload(a.key)));
    renderAcctBar();
    renderSettings();
    if (TAB === 'perf') await loadHistory(PERF, true);
    else ACCOUNTS.forEach(a => { HISTS[a.key] = null; });   // 다음 진입 때 다시 받게
    if (manual) toast('새로고침 완료');
  } catch (e) { toast(e.message); }
  finally { btn.classList.remove('spin'); }
}

async function loadHistory(acct, force) {
  /* '전체' 는 계좌마다 따로 받아 와서 합친다 — 서버에 합계 API 를 두지 않은 이유는
     계좌 폴더가 따로라 어차피 하나씩 읽어야 하고, 합치는 규칙(아래 mergeTotals)을
     화면 쪽에 두는 편이 고치기 쉽기 때문이다. */
  const need = acct === ALL ? ACCOUNTS.map(a => a.key) : [acct];
  await Promise.all(need.map(async k => {
    if (HISTS[k] && !force) return;
    try { HISTS[k] = await api(url('/api/history', k, 'days=180')); }
    catch (e) { toast(e.message); }
  }));
  renderPerf(acct);
}

/* ---------- 계좌 탭 그리기 ---------- */
const stratDirty = acct => {
  const t = el(acct, 'strat');
  return !!t && t.value !== (STRAT_BASE[acct] || '');
};

function renderAccount(acct) {
  const s = SNAPS[acct];
  if (!s) return;
  const t = s.totals, list = items(acct);

  /* 시세가 오래됐다는 경고는 맨 위에. */
  const nt = el(acct, 'notice');
  if (s.priceStale) {
    nt.className = 'notice warn';
    nt.innerHTML = '<b>시세가 오래됐습니다</b>';
  } else nt.className = 'notice hidden';

  /* KPI 는 세 개만 둔다 — 자산(한 줄 전체) · 월 배당 · 현금성자산. 설명 문구는 넣지 않는다.
     자산의 수익률은 보조 글씨가 아니라 금액 바로 아래에 색을 입혀 크게 쓴다.
     월 배당은 '오늘이 속한 달' 에 지급일이 찍힌 배당의 합이다 — 달이 바뀌면 0 에서 다시 쌓인다. */
  el(acct, 'kpis').innerHTML =
    `<div class="kpi wide"><span class="k">자산</span><span class="v">${krw(t.total)}</span>` +
      `<span class="v2 ${cls(t.evalPl)}">${mkrw(t.evalPl)} (${pct(t.retPct)})</span></div>` +
    `<div class="kpi"><span class="k">월 배당</span><span class="v">${krw(t.thisMonthDividend)}</span></div>` +
    `<div class="kpi"><span class="k">현금성자산</span><span class="v">${krw(t.cash)}</span></div>`;

  /* 종목이 없는 그룹은 카드를 만들지 않는다 (2026-09-16 ISA 추가).
     ISA 는 배당 시기를 정하지 않아 전부 '기타' 로 온다 — 빈 카드 두 장이 따라 나오면
     화면만 길어진다. 종목이 하나도 없는 계좌일 때만 빈 안내를 한 줄 보여준다. */
  const shown = (s.groups || []).filter(g => (g.items || []).length);
  el(acct, 'groups').innerHTML = shown.length ? shown.map(g => {
    const gl = g.items, st = g.subtotal || {};
    const head = `<div class="card-head"><h2>${esc(g.label)}</h2>` +
      `<span class="hd-r"><span class="cnt">${gl.length}종목</span>` +
      `<span class="${cls(st.retPct)}">${pct(st.retPct)}</span></span></div>`;

    /* 증권사 잔고 화면과 같은 형식 (2026-09-16 사용자 요청).
       한 칸에 두 줄씩 짝지어 넣는다 — 평가손익/수익률, 평가금액/매수금액, 매수단가/현재가.
       칸이 많아 폰 폭을 넘으므로 옆으로 밀어서 본다. 대신 종목명 칸은 왼쪽에 고정(sticky)해
       밀어도 어느 종목 줄인지 보이게 했다.
       줄을 누르면 매수·매도·수정·삭제 시트가 열린다 — 체결 탭이 하던 일이다.
       옆으로 미는 동안에는 브라우저가 click 을 취소하므로 스크롤과 부딪히지 않는다. */
    const rows = gl.map(it => `<tr class="tap" data-hid="${esc(it.id)}">
        <td class="bn"><span class="g-nm">${esc(it.name)}</span></td>
        <td class="mono ${cls(it.pl)}">${mn0(it.pl)}<span class="b2">${pct(it.retPct)}</span></td>
        <td class="mono">${n0(it.evalAmount)}<span class="b2">${n0(it.buyAmount)}</span></td>
        <td class="mono">${n0(it.qty)}</td>
        <td class="mono">${n0(it.buyPrice)}<span class="b2">${n0(it.price)}</span></td>
      </tr>`).join('');

    return `<div class="card">${head}
      <div class="btable"><table>
        <thead><tr>
          <th class="bn">종목명</th>
          <th>평가손익<span class="b2">수익률</span></th>
          <th>평가금액<span class="b2">매수금액</span></th>
          <th>보유수량</th>
          <th>매수단가<span class="b2">현재가</span></th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      <div class="gsub">
        <div><span class="k">매수금액</span><span class="v">${krw(st.buyAmount)}</span></div>
        <div><span class="k">평가금액</span><span class="v">${krw(st.evalAmount)}</span></div>
        <div><span class="k">손익</span><span class="v ${cls(st.pl)}">${mkrw(st.pl)}</span></div>
        <div><span class="k">수익률</span><span class="v ${cls(st.retPct)}">${pct(st.retPct)}</span></div>
      </div></div>`;
  }).join('') : '<div class="card"><div class="empty">아직 종목이 없습니다.</div></div>';

  /* 고쳐 놓고 아직 저장하지 않았다면 서버 값으로 덮어쓰지 않는다.
     화면에 돌아올 때마다(visibilitychange) 새로고침이 돌기 때문이다. */
  const st = s.strategy || {};
  if (!stratDirty(acct)) {
    el(acct, 'strat').value = st.text || '';
    STRAT_BASE[acct] = el(acct, 'strat').value;
  }
  el(acct, 'stratMeta').textContent = st.updatedAt
    ? `마지막 저장 ${fmtTs(st.updatedAt)}`
    : '아직 저장한 전략이 없습니다.';

  renderManage(acct);
}

/* ---------- 관리 (계좌 탭 안의 접이식 묶음) ---------- */
/* 체결 탭이 하던 일 가운데 날마다 쓰지 않는 것만 남았다.
   보유 종목 목록은 위 그룹 표가 대신하므로 여기서는 현재가 칸만 나열한다. */
function renderManage(acct) {
  const s = SNAPS[acct], t = s.totals, list = items(acct);

  el(acct, 'priceAt').textContent =
    s.priceUpdatedAt ? '시세 ' + fmtTs(s.priceUpdatedAt).slice(5) : '—';

  /* 새로고침이 끼어들어도 손으로 적어 둔 현재가는 지우지 않는다. */
  const typed = {};
  $$(`#tab-${acct} input[data-price]`).forEach(i => {
    if (i.value !== '') typed[i.dataset.price] = i.value;
  });

  /* 이름과 입력칸 한 줄씩. 종목을 눌러 여는 시트는 위 그룹 표가 맡으므로 여기서는 걸지 않는다
     (같은 줄에서 칸을 누르다 시트가 열리는 사고를 막는 쪽이 낫다). */
  el(acct, 'priceRows').innerHTML = list.length ? list.map(it => `
    <div class="fillrow">
      <div class="fl"><div class="fn">${esc(it.name)}</div></div>
      <input type="number" class="price-input" inputmode="numeric" step="1" min="0"
             data-price="${esc(it.id)}" placeholder="${n0(it.price)}" aria-label="${esc(it.name)} 현재가"
             value="${typed[it.id] != null ? esc(typed[it.id]) : ''}">
    </div>`).join('') : '<div class="empty">아직 종목이 없습니다.</div>';

  /* 입력 중인 칸은 건드리지 않는다. 타이핑 도중 값이 튀면 그보다 짜증나는 게 없다. */
  const cash = el(acct, 'cash');
  if (document.activeElement !== cash) cash.value = Math.round(Number(t.cash) || 0);

  const sd = el(acct, 'startDate');
  if (document.activeElement !== sd) sd.value = s.start_date || '';

  const dc = el(acct, 'divCode'), prevDiv = dc.value;
  dc.innerHTML = list.length
    ? list.map(it => `<option value="${esc(it.id)}">${esc(it.name)}</option>`).join('')
    : '<option value="">보유 종목이 없습니다</option>';
  if (prevDiv) dc.value = prevDiv;
  const dd = el(acct, 'divDate');
  if (!dd.value) dd.value = s.today;
}

/* ---------- 계좌 탭의 버튼·종목 줄 (한 자리에서 위임 처리) ---------- */
/* 계좌마다 핸들러를 다시 걸지 않는다. 탭이 몇 장이든 이 한 줄이 전부 받는다. */
$('#acctTabs').addEventListener('click', ev => {
  const sec = ev.target.closest('section[data-acct]');
  if (!sec) return;
  const acct = sec.dataset.acct;

  const row = ev.target.closest('tr[data-hid]');
  if (row) return openSheet(acct, row.dataset.hid);

  const btn = ev.target.closest('[data-act]');
  if (!btn) return;
  const act = btn.dataset.act;
  if (act === 'add') return openSheet(acct, null);
  if (act === 'refresh') return doRefreshPrices(acct, btn);
  if (act === 'pricesApply') return doPricesApply(acct, btn);
  if (act === 'cashSave') return doCashSave(acct, btn);
  if (act === 'divSave') return doDivSave(acct, btn);
  if (act === 'stratSave') return doStratSave(acct, btn);
  if (act === 'closeToday') return doCloseToday(acct, btn);
  if (act === 'startSave') return doStart(acct, el(acct, 'startDate').value);
  if (act === 'startClear') return doStart(acct, null);
});

/* 버튼 하나를 잠그고 일을 시킨 뒤 푼다. 연타로 같은 요청이 두 번 가는 것을 막는다. */
async function withBtn(btn, label, fn) {
  const old = btn.textContent;
  btn.disabled = true;
  if (label) btn.textContent = label;
  try { await fn(); }
  finally { btn.disabled = false; btn.textContent = old; }
}

async function doRefreshPrices(acct, btn) {
  await withBtn(btn, '시세를 받는 중…', async () => {
    try {
      const r = await api(url('/api/refresh-prices', acct), { method: 'POST' });
      const failed = (r.failed || []).map(f => (f && (f.name || f.code)) || String(f));
      toast((r.message || `${r.updated || 0}종목을 갱신했습니다`) +
        (failed.length ? ` (실패 ${failed.length}건: ${failed.join(', ')})` : ''), 4200);
      HISTS[acct] = null; await reload(acct);
    } catch (e) { toast(e.message, 4200); }
  });
}

async function doPricesApply(acct, btn) {
  const inputs = $$(`#tab-${acct} input[data-price]`), prices = {};
  inputs.forEach(i => {
    const v = i.value.trim();
    if (v === '') return;                       // 비워 둔 종목은 손대지 않는다
    const n = Number(v);
    if (isFinite(n) && n > 0) prices[i.dataset.price] = Math.round(n);
  });
  if (!Object.keys(prices).length) return toast('입력한 현재가가 없습니다');

  await withBtn(btn, null, async () => {
    try {
      const r = await api(url('/api/prices', acct),
        { method: 'POST', body: JSON.stringify({ prices }) });
      inputs.forEach(i => { i.value = ''; });   // 반영했으니 입력칸을 비운다
      toast(r.message || `${r.updated || 0}종목의 현재가를 반영했습니다`);
      HISTS[acct] = null; await reload(acct);
    } catch (e) { toast(e.message); }
  });
}

async function doCashSave(acct, btn) {
  /* 빈 칸을 0 원으로 읽지 않는다. 지우다 만 것인지 정말 0 인지 알 수 없다. */
  const raw = el(acct, 'cash').value.trim();
  const amount = Math.round(Number(raw));
  if (raw === '' || !isFinite(amount) || amount < 0)
    return toast('남은 예수금을 숫자로 적어주세요.');
  await withBtn(btn, null, async () => {
    try {
      const r = await api(url('/api/cash', acct),
        { method: 'POST', body: JSON.stringify({ amount }) });
      toast(r.message || '현금을 저장했습니다'); HISTS[acct] = null; await reload(acct);
    } catch (e) { toast(e.message); }
  });
}

async function doDivSave(acct, btn) {
  const it = items(acct).find(x => x.id === el(acct, 'divCode').value);
  if (!it) return toast('종목을 선택해주세요.');
  const amount = Math.round(Number(el(acct, 'divAmount').value));
  if (!isFinite(amount) || amount <= 0) return toast('배당금을 입력해주세요.');
  const date = el(acct, 'divDate').value || SNAPS[acct].today;

  await withBtn(btn, null, async () => {
    try {
      const r = await api(url('/api/dividend', acct), {
        method: 'POST',
        body: JSON.stringify({ code: it.code, name: it.name, amount, date })
      });
      el(acct, 'divAmount').value = '';
      /* 화면에서 뺀 안내를 여기서 한 번 짚는다 — 배당을 적어도 현금은 저절로 늘지 않는다. */
      toast((r.message || '배당을 기록했습니다.') + ' 현금은 따로 맞춰주세요.', 4200);
      HISTS[acct] = null; await reload(acct);
    } catch (e) { toast(e.message); }
  });
}

async function doStratSave(acct, btn) {
  const text = el(acct, 'strat').value;
  await withBtn(btn, null, async () => {
    try {
      const r = await api(url('/api/strategy', acct),
        { method: 'POST', body: JSON.stringify({ text }) });
      STRAT_BASE[acct] = text;
      toast(r.message || '전략을 저장했습니다');
      await reload(acct);
    } catch (e) { toast(e.message); }
  });
}

async function doCloseToday(acct, btn) {
  await withBtn(btn, null, async () => {
    try {
      const r = await api(url('/api/close-today', acct), { method: 'POST' });
      toast(r.message || '오늘 마감을 저장했습니다', 3600);
      HISTS[acct] = null; await reload(acct);
    } catch (e) { toast(e.message); }
  });
}

async function doStart(acct, v) {
  if (v === '') return toast('날짜를 선택해주세요');
  try {
    const r = await api(url('/api/start', acct),
      { method: 'POST', body: JSON.stringify({ start_date: v }) });
    toast(r.message || '저장했습니다'); await reload(acct);
  } catch (e) { toast(e.message); }
}

/* ---------- 종목 시트 ---------- */
/* 바텀시트 상태. id 가 null 이면 신규 추가 모드다. */
let SHEET = { acct: null, id: null, action: 'buy' };

/* 액션마다 보여줄 칸이 다르다. label 의 data-f 로 지목해 켜고 끈다. */
const SHEET_FIELDS = {
  add: ['code', 'name', 'asset', 'pay', 'qty', 'buyPrice', 'price', 'memo'],
  buy: ['qty', 'price'],
  sell: ['qty', 'price'],
  edit: ['asset', 'pay', 'qty', 'buyPrice', 'price', 'memo'],
  remove: []
};
const SHEET_BTN = { add: '추가', buy: '매수 반영', sell: '매도 반영', edit: '수정 반영', remove: '삭제' };

/* state 의 자산군은 자유 문자열이라 select 에 없는 값이 들어 있을 수 있다.
   그대로 두면 수정하다가 자산군이 통째로 날아가므로 없는 값은 끼워 넣는다. */
function setSelect(sel, v) {
  const val = v == null ? '' : String(v);
  sel.value = val;
  if (sel.value !== val) {
    sel.insertAdjacentHTML('beforeend', `<option value="${esc(val)}">${esc(val)}</option>`);
    sel.value = val;
  }
}

function sheetItem() {
  return SHEET.id ? items(SHEET.acct).find(x => x.id === SHEET.id) || null : null;
}

function sheetFields(it) {
  setSelect($('#fAsset'), it ? it.asset : '선진국주식');
  setSelect($('#fPay'), it ? it.pay : '');
  $('#fCode').value = it ? it.code : '';
  $('#fName').value = it ? it.name : '';
  $('#fMemo').value = it ? (it.memo || '') : '';
  $('#fBuyPrice').value = it ? it.buyPrice : '';
  /* 매수·매도 칸은 "그날 체결분"이다. 보유 수량이 미리 적혀 있으면
     그대로 눌러 전량을 한 번 더 사는 사고가 난다. 반드시 비워 둔다. */
  const delta = SHEET.action === 'buy' || SHEET.action === 'sell';
  $('#fQty').value = (it && !delta) ? it.qty : '';
  $('#fPrice').value = (it && !delta) ? it.price : '';
}

function syncSheet() {
  const a = SHEET.action, show = SHEET_FIELDS[a] || [];
  $$('#sheetFields label').forEach(l => l.classList.toggle('hidden', show.indexOf(l.dataset.f) < 0));
  /* 같은 칸이 상황에 따라 뜻이 달라진다. 글자만 갈아 끼운다. */
  const delta = a === 'buy' || a === 'sell';
  $('label[data-f="qty"] .lb').textContent = delta ? '체결수량 (주)' : '수량 (주)';
  $('label[data-f="price"] .lb').textContent = delta ? '체결단가 (원)' : '현재가 (원)';
  /* 시트 안내 문구는 화면에 두지 않는다 — 칸 이름(체결수량/수량)과 버튼 글자가 이미 말해준다. */
  $('#sheetSubmit').textContent = SHEET_BTN[a] || '반영';
}

function openSheet(acct, id) {
  const it = id ? items(acct).find(x => x.id === id) : null;
  SHEET = { acct, id: it ? it.id : null, action: it ? 'buy' : 'add' };
  /* 계좌가 여럿이라 어느 계좌의 종목인지 제목에 밝힌다 — ISA 종목을 퇴직연금에
     넣는 실수가 여기서 걸린다. */
  $('#sheetTitle').innerHTML = `${esc(it ? it.name : '종목 추가')}` +
    `<span class="sheet-acct">${esc(acctLabel(acct))}</span>`;
  $('#sheetErr').textContent = '';
  /* 신규는 고를 것이 없으므로 세그먼트를 감춘다. */
  $('#sheetSeg').classList.toggle('hidden', !it);
  $$('#sheetSeg button').forEach(b => b.classList.toggle('active', b.dataset.a === 'buy'));
  sheetFields(it);
  syncSheet();
  $('#sheet').classList.remove('hidden');
}
function closeSheet() { $('#sheet').classList.add('hidden'); }

$$('#sheetSeg button').forEach(b => b.addEventListener('click', () => {
  SHEET.action = b.dataset.a;
  $$('#sheetSeg button').forEach(x => x.classList.toggle('active', x === b));
  $('#sheetErr').textContent = '';
  /* 액션을 바꾸면 칸의 뜻이 바뀐다. 남은 값이 엉뚱하게 실려 가지 않도록 다시 채운다. */
  sheetFields(sheetItem());
  syncSheet();
}));

$('#sheetCancel').addEventListener('click', closeSheet);
$('.sheet-bg').addEventListener('click', closeSheet);

$('#sheetForm').addEventListener('submit', async e => {
  e.preventDefault();
  $('#sheetErr').textContent = '';
  const a = SHEET.action, acct = SHEET.acct, it = sheetItem();
  const val = sel => { const v = $(sel).value.trim(); return v === '' ? null : Number(v); };
  const bad = m => { $('#sheetErr').textContent = m; };

  if (a === 'remove') {
    if (!it) return closeSheet();
    if (!confirm(`${it.name} 을(를) ${acctLabel(acct)} 목록에서 지웁니다.\n` +
                 `지난 체결 기록은 그대로 남습니다. 정말 지울까요?`)) return;
    return sheetSend('/api/holding/delete', acct, { id: it.id });
  }

  /* HoldingIn 은 언제나 전체 모양으로 보낸다. 서버는 id 로 종목을 지목하고
     action 으로 trades.csv 에 남길 라벨을 정한다. */
  const body = {
    id: it ? it.id : null,
    code: it ? it.code : $('#fCode').value.trim().toUpperCase(),
    name: it ? it.name : $('#fName').value.trim(),
    asset: $('#fAsset').value,
    pay: $('#fPay').value,
    qty: it ? it.qty : 0,
    buyPrice: it ? it.buyPrice : 0,
    price: it ? it.price : 0,
    memo: it ? (it.memo || '') : '',
    action: 'edit',
    deltaQty: 0,
    deltaPrice: 0,
    confirm_price: false,
    confirm_dup: false
  };

  if (a === 'buy' || a === 'sell') {
    const q = val('#fQty'), p = val('#fPrice');
    if (!q || q <= 0) return bad('체결수량을 적어주세요.');
    if (!p || p <= 0) return bad('체결단가를 적어주세요.');
    if (a === 'sell' && q > (it ? it.qty : 0))
      return bad(`보유 수량(${(it ? it.qty : 0).toLocaleString('ko-KR')}주)보다 많이 팔 수는 없습니다.`);
    body.action = a;
    body.deltaQty = Math.round(q);
    body.deltaPrice = Math.round(p);
  } else {
    /* 수정·신규는 최종값을 그대로 덮어쓴다. 신규도 라벨은 edit 로 보낸다
       (§6 의 action 은 edit|buy|sell 셋뿐이고, 신규는 id 가 null 인 것으로 구분된다). */
    const q = val('#fQty'), bp = val('#fBuyPrice'), p = val('#fPrice');
    if (q === null || q < 0) return bad('수량을 적어주세요.');
    if (bp === null || bp <= 0) return bad('매수단가를 적어주세요.');
    if (p === null || p <= 0) return bad('현재가를 적어주세요.');
    if (!it) {
      /* 시세 자동갱신을 쓰는 계좌는 KIS 6자리, 그렇지 않으면 BTC 처럼 자유 문자열이다. */
      const okCode = autoPrice(acct)
        ? /^[0-9A-Z]{6}$/.test(body.code)
        : /^[0-9A-Z][0-9A-Z._-]{0,19}$/.test(body.code);
      if (!okCode) return bad(autoPrice(acct)
        ? '종목코드는 영문·숫자 여섯 자리입니다. (예: 0219E0)'
        : '종목코드는 영문·숫자 1~20자입니다. (예: BTC)');
      if (!body.name) return bad('종목명을 적어주세요.');
    }
    body.qty = Math.round(q);
    body.buyPrice = Math.round(bp);
    body.price = Math.round(p);
    body.memo = $('#fMemo').value.trim();
  }

  return sheetSend('/api/holding', acct, body);
});

async function sheetSend(path, acct, body) {
  const btn = $('#sheetSubmit'); btn.disabled = true;
  try {
    const r = await api(url(path, acct), { method: 'POST', body: JSON.stringify(body) });
    closeSheet();
    toast(r.message || '반영했습니다', 4200);
    HISTS[acct] = null;
    await reload(acct);
  } catch (e) {
    /* 중복 가드: 방금 같은 매수·매도가 기록돼 있으면 서버가 "중복 확인:" 으로 막는다.
       맞다고 하면(정말 두 번 산 경우) 확인 표시를 달아 다시 보내고, 아니면 아무것도 저장하지 않는다. */
    if (!body.confirm_dup && e.message.indexOf('중복 확인:') === 0) {
      btn.disabled = false;
      if (!confirm(e.message.replace(/^중복 확인:\s*/, ''))) {
        closeSheet();
        return toast('저장하지 않았습니다');
      }
      return sheetSend(path, acct, Object.assign({}, body, { confirm_dup: true }));
    }
    /* 오타 가드: 서버가 "30% 이상 차이" 로 막으면 되묻고,
       맞다고 하면 확인 표시를 달아 같은 본문을 다시 보낸다. */
    if (body.confirm_price === false && e.message.indexOf('30%') >= 0) {
      btn.disabled = false;
      if (!confirm(e.message + '\n\n입력한 값이 맞으면 이대로 반영합니다. 진행할까요?')) return;
      return sheetSend(path, acct, Object.assign({}, body, { confirm_price: true }));
    }
    $('#sheetErr').textContent = e.message;
  } finally { btn.disabled = false; }
}

/* ---------- 성과 ---------- */
/* 계좌별 일별 기록을 날짜 하나로 합친다.

   합치기 시작하는 날은 '모든 계좌가 첫 기록을 가진 날' 중 가장 늦은 날이다.
   그 전 날짜까지 합치면 계좌가 하나씩 등장할 때마다 총자산이 계단처럼 뛰어올라,
   실제로는 벌어지지 않은 급등으로 읽힌다.
   그 날 이후 특정 계좌에 줄이 없는 날(마감 실패 등)은 그 계좌의 직전 기록을 끌어다 쓴다 —
   빼버리면 그날 총자산만 푹 꺼진다. */
function mergeHistory() {
  const per = ACCOUNTS.map(a => {
    const rows = (((HISTS[a.key] || {}).history) || []).slice()
      .sort((x, y) => String(x.date) < String(y.date) ? -1 : 1);
    return { key: a.key, rows };
  });
  /* 기록이 아직 한 줄도 없는 계좌가 있으면 합계를 그리지 않는다. 그 계좌만 빼고 더하면
     '전체'라고 써 놓고 일부만 더한 값이 나온다. 없는 계좌의 첫 날짜를 도달 불가능한
     값으로 두면 아래 start 가 커져 dates 가 비고, 그래프는 "기록이 쌓이면" 안내만 낸다. */
  const start = per.reduce((mx, p) => {
    const f = p.rows.length ? String(p.rows[0].date) : '9999-99-99';
    return f > mx ? f : mx;
  }, '');
  if (!per.length || start === '9999-99-99') return { dates: [], total: [], evalPl: [] };
  const dates = [...new Set(per.flatMap(p => p.rows.map(r => String(r.date))))]
    .filter(d => d >= start).sort();

  const total = [], evalPl = [];
  const at = per.map(() => 0);           // 계좌마다 '지금까지 읽은 줄' 위치
  dates.forEach(d => {
    let tSum = 0, pSum = 0, ok = true;
    per.forEach((p, i) => {
      while (at[i] + 1 < p.rows.length && String(p.rows[at[i] + 1].date) <= d) at[i]++;
      const r = p.rows[at[i]];
      if (!r || String(r.date) > d) { ok = false; return; }
      tSum += num(r.total) || 0;
      pSum += num(r.evalPl) || 0;
    });
    total.push(ok ? tSum : null);
    evalPl.push(ok ? pSum : null);
  });
  return { dates, total, evalPl };
}

function renderPerf(acct) {
  const all = acct === ALL;
  const loaded = ACCOUNTS.map(a => SNAPS[a.key]).filter(Boolean);
  const snap = all ? loaded[0] : SNAPS[acct];
  if (!snap) return;

  /* 전체일 때 합계는 스냅샷(지금 값)을 더해 만든다. 기록(history)이 아니라
     스냅샷이라 오늘 마감 전에도 바로 맞는 값이 나온다. */
  const t = all ? {
    total: loaded.reduce((x, s) => x + s.totals.total, 0),
    buyTotal: loaded.reduce((x, s) => x + s.totals.buyTotal, 0),
    evalPl: loaded.reduce((x, s) => x + s.totals.evalPl, 0),
    cash: loaded.reduce((x, s) => x + s.totals.cash, 0),
    totalDividend: loaded.reduce((x, s) => x + s.totals.totalDividend, 0),
    retPct: 0,
  } : snap.totals;
  if (all) t.retPct = t.buyTotal ? t.evalPl / t.buyTotal : 0;

  const HIST = HISTS[acct];
  const merged = all ? mergeHistory() : null;
  const H = all ? [] : ((HIST && HIST.history) || []).slice()
    .sort((a, b) => String(a.date) < String(b.date) ? -1 : 1);
  const dates = all ? merged.dates : H.map(r => String(r.date));

  /* 설명 문구 없이 숫자만 (2026-09-13 사용자 요청). 계좌 탭과 같은 모양 —
     평가손익 밑에 수익률을 색 입혀 크게. 기록이 모자라다는 안내는 각 그래프 칸에서 한 줄로만.
     배당수익률은 누적배당 ÷ 매수금액(연환산 아님)이라 라벨에 '누적' 을 붙인다. 매수금액 0 이면 "—". */
  const divYield = t.buyTotal ? t.totalDividend / t.buyTotal : null;
  $('#perfKpis').innerHTML =
    `<div class="kpi"><span class="k">총금액</span><span class="v">${krw(t.total)}</span></div>` +
    `<div class="kpi"><span class="k">평가손익</span>` +
      `<span class="v ${cls(t.evalPl)}">${mkrw(t.evalPl)}</span>` +
      `<span class="v2 ${cls(t.retPct)}">${pct(t.retPct)}</span></div>` +
    `<div class="kpi"><span class="k">누적 배당</span><span class="v">${krw(t.totalDividend)}</span></div>` +
    `<div class="kpi"><span class="k">배당수익률(누적)</span>` +
      `<span class="v">${divYield === null ? '—' : pct(divYield)}</span></div>`;

  $('#chartTotal').innerHTML = lineChart(
    [{ name: '총금액', color: 'var(--brand)',
       values: all ? merged.total : H.map(r => num(r.total)) }],
    dates, { fmt: axisKrw });

  /* 누적 손익은 부호에 따라 선 색을 맞춘다(플러스 빨강 · 마이너스 파랑). */
  const pnl = all ? merged.evalPl : H.map(r => num(r.evalPl));
  const lastPnl = pnl.reduce((a, v) => v !== null ? v : a, 0);
  $('#chartPnl').innerHTML = lineChart(
    [{ name: '평가손익', color: lastPnl < 0 ? 'var(--down)' : 'var(--up)', values: pnl }],
    dates, { zero: true, fmt: axisKrw });

  /* 월 배당은 지급이 없는 달도 0 으로 채워 12칸을 연속되게 만든다.
     빠진 달을 건너뛰면 막대 간격이 달마다 달라져 읽을 수 없다. */
  const months = lastMonths(12, snap.today);
  const byMonth = {};
  const divSrc = all
    ? ACCOUNTS.flatMap(a => ((HISTS[a.key] || {}).dividends) || [])
    : ((HIST && HIST.dividends) || []);
  divSrc.forEach(d => {
    const m = String(d.date || '').slice(0, 7);
    if (m.length === 7) byMonth[m] = (byMonth[m] || 0) + (parseFloat(d.amount) || 0);
  });
  $('#chartDiv').innerHTML = barChart(months.map(m => byMonth[m] || 0), months,
    { fmt: axisKrw, xfmt: m => Number(m.slice(5)) + '월' });

  /* 한 계좌를 볼 때는 배당시기 비중, 전체를 볼 때는 계좌별 비중.
     색은 무채색 단계만 쓴다 — 이 앱에서 빨강은 수익, 파랑은 손실이라
     범주 색으로 쓰면 계좌 하나가 '수익', 다른 하나가 '손실'로 읽힌다. */
  $('#mixTitle').textContent = all ? '계좌별 비중' : '그룹별 비중';
  let parts;
  if (all) {
    parts = ACCOUNTS.map((a, i) => ({
      k: a.label,
      v: (SNAPS[a.key] && SNAPS[a.key].totals.total) || 0,
      col: `var(--a${(i % 6) + 1})`
    }));
  } else {
    const g = snap.groups || [];
    const gv = k => { const x = g.find(z => z.key === k); return (x && x.subtotal && x.subtotal.evalAmount) || 0; };
    parts = [
      { k: '월중', v: gv('월중'), col: 'var(--g-mid)' },
      { k: '월말', v: gv('월말'), col: 'var(--g-end)' },
      { k: '기타', v: gv('기타'), col: 'var(--g-etc)' },
      { k: '현금', v: Number(t.cash) || 0, col: 'var(--g-cash)' }
    ];
  }
  const sum = parts.reduce((a, p) => a + p.v, 0);
  /* 값이 0 인 칸은 범례에서도 뺀다. ISA 처럼 한 그룹에 몰린 계좌에서
     "월중 0.0% · 0원" 같은 줄만 늘어놓게 되기 때문이다. */
  const shown = parts.filter(p => p.v > 0);
  $('#chartMix').innerHTML = sum > 0
    ? `<div class="stackbar">${shown.map(p =>
        `<span style="background:${p.col};width:${(p.v / sum * 100).toFixed(2)}%"></span>`).join('')}</div>` +
      `<div class="legend box">${shown.map(p =>
        `<span><i style="background:${p.col}"></i>${p.k} ${(p.v / sum * 100).toFixed(1)}% · ${kshort(p.v)}</span>`).join('')}</div>`
    : '<div class="empty">표시할 자산이 없습니다.</div>';
}

/* ---------- 설정 ---------- */
function renderSettings() {
  const any = ACCOUNTS.map(a => SNAPS[a.key]).find(Boolean);
  if (!any) return;

  /* 계좌마다 한 줄 — 종목 수와 마지막 시세. 금액은 각 계좌 탭에 이미 크게 나온다. */
  const rows = ACCOUNTS.map(a => {
    const s = SNAPS[a.key];
    if (!s) return [a.label, '—'];
    const n = (s.groups || []).reduce((x, g) => x + (g.items || []).length, 0);
    return [a.label, `${n}종목 · ${s.priceUpdatedAt ? fmtTs(s.priceUpdatedAt).slice(5) : '시세 없음'}`];
  });
  rows.push(['자동 실행', '평일 ' + (any.dailyAt || '16:05')]);
  rows.push(['버전', any.version || '—']);

  $('#cfgList').innerHTML = rows.map(([k, v]) =>
    `<div><span>${esc(k)}</span><span class="mono">${esc(v)}</span></div>`).join('');
}

$('#btnRun').addEventListener('click', async () => {
  const btn = $('#btnRun'), label = btn.textContent;
  btn.disabled = true; btn.textContent = '실행 중…';
  try {
    const r = await api('/api/run-now', { method: 'POST' });
    toast(r.message || '실행했습니다', 4200);
    ACCOUNTS.forEach(a => { HISTS[a.key] = null; });
    await refresh();
  } catch (e) { toast(e.message, 4200); }
  finally { btn.disabled = false; btn.textContent = label; }
});
$('#btnLogout').addEventListener('click', async () => {
  await api('/api/logout', { method: 'POST' }).catch(() => { });
  location.reload();
});

/* ---------- 푸시 ---------- */
const b64 = s => {
  const p = '='.repeat((4 - s.length % 4) % 4);
  const r = (s + p).replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from(atob(r), c => c.charCodeAt(0));
};
$('#btnPush').addEventListener('click', async () => {
  try {
    if (!('serviceWorker' in navigator) || !('PushManager' in window))
      return toast('이 브라우저는 알림을 지원하지 않습니다. 홈 화면에 추가한 뒤 다시 시도해보세요.', 4200);
    const perm = await Notification.requestPermission();
    if (perm !== 'granted') return toast('알림 권한이 거부되었습니다.', 4200);
    const reg = await navigator.serviceWorker.ready;
    const { publicKey } = await api('/api/push/key');
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true, applicationServerKey: b64(publicKey)
    });
    await api('/api/push/subscribe', { method: 'POST', body: JSON.stringify(sub) });
    const any = ACCOUNTS.map(a => SNAPS[a.key]).find(Boolean);
    toast(`알림을 켰습니다. 평일 ${(any && any.dailyAt) || '16:05'} 에 보내드립니다.`, 3600);
  } catch (e) { toast('실패: ' + e.message, 4200); }
});
/* 알림이 안 올 때 — 서버는 정상인데 기기에서 막히는 경우를 가려낸다.
   서비스워커가 직접 알림을 띄워보고(로컬), 푸시 구독 상태를 그대로 보여준다. */
$('#btnPushDiag').addEventListener('click', async () => {
  const box = $('#pushDiag');
  box.classList.remove('hidden');
  const L = [];
  try {
    L.push('알림 권한: ' + (window.Notification ? Notification.permission : '지원 안 함'));
    L.push('홈화면 앱으로 실행: ' +
      (window.matchMedia('(display-mode: standalone)').matches ||
        navigator.standalone ? '예' : '아니오 (브라우저 탭)'));

    if (!('serviceWorker' in navigator)) { L.push('서비스워커: 지원 안 함'); }
    else {
      const reg = await navigator.serviceWorker.getRegistration();
      if (!reg) L.push('서비스워커: 등록 안 됨');
      else {
        L.push('서비스워커 active: ' + (reg.active ? '있음' : '없음'));
        L.push('서비스워커 waiting: ' + (reg.waiting ? '있음 (업데이트 대기 중)' : '없음'));
        const sub = await reg.pushManager.getSubscription();
        L.push('푸시 구독: ' + (sub ? '있음 …' + sub.endpoint.slice(-12) : '없음'));

        if (Notification.permission === 'granted') {
          await reg.showNotification('로컬 테스트', {
            body: '이 알림이 보이면 기기 알림 자체는 정상입니다.',
            icon: '/static/icon-192.png', tag: 'pen-diag', renotify: true
          });
          L.push('');
          L.push('→ 방금 "로컬 테스트" 알림을 띄웠습니다.');
          L.push('   보이면: 기기는 정상, 푸시 전달 문제');
          L.push('   안 보이면: 기기 알림 설정 문제');
        }
      }
    }
  } catch (e) { L.push('오류: ' + e.message); }
  box.textContent = L.join('\n');
});

$('#btnPushTest').addEventListener('click', async () => {
  try {
    const r = await api('/api/push/test', { method: 'POST' });
    toast(r.sent ? `${r.sent}대에 보냈습니다.` : '등록된 기기가 없습니다. 먼저 휴대폰 알림을 켜주세요.', 3600);
  } catch (e) { toast(e.message); }
});

/* ---------- 시작 ---------- */
/* 계좌 목록을 먼저 받아 탭을 만든 다음에 숫자를 채운다. */
async function start() {
  try {
    const a = await api('/api/auth');
    if (Array.isArray(a.accounts) && a.accounts.length) ACCOUNTS = a.accounts;
  } catch { /* 못 받으면 기본 계좌 하나로 뜬다 */ }
  buildTabs();
  await refresh();
}

(async function init() {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => { });
  }
  try {
    const a = await api('/api/auth');
    if (a.required && !a.authed) { showLogin(); return; }
    showApp(); await start();
  } catch { showLogin(); }
})();

document.addEventListener('visibilitychange', () => {
  if (!document.hidden && Object.keys(SNAPS).length) refresh();
});


/* 오늘이 속한 달까지 n 개월치 "YYYY-MM" 라벨. */
function lastMonths(n, today) {
  const d = new Date(String(today || '').slice(0, 7) + '-01T00:00:00');
  const base = isNaN(d.getTime()) ? new Date() : d;
  const out = [];
  for (let i = n - 1; i >= 0; i--) {
    const x = new Date(base.getFullYear(), base.getMonth() - i, 1);
    out.push(x.getFullYear() + '-' + String(x.getMonth() + 1).padStart(2, '0'));
  }
  return out;
}

/* 인라인 SVG 라인차트 — 외부 라이브러리를 쓰지 않는다 */
function lineChart(series, labels, opt = {}) {
  const n = labels.length;
  if (n < 2) return '<div class="empty">기록이 2일 이상 쌓이면 표시됩니다</div>';
  const W = 340, H = 150, L = 40, R = 8, T = 8, B = 20;
  let vals = series.flatMap(s => s.values).filter(v => v !== null);
  if (opt.band) vals = vals.concat([...(opt.band.lo || []), ...(opt.band.hi || [])].filter(v => v !== null));
  if (!vals.length) return '<div class="empty">표시할 값이 없습니다.</div>';
  let lo = Math.min(...vals), hi = Math.max(...vals);
  if (opt.zero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
  if (hi === lo) { hi += 1; lo -= 1; }
  const pad = (hi - lo) * .1; lo -= pad; hi += pad;
  const iw = W - L - R, ih = H - T - B;
  const X = i => L + (n > 1 ? iw * i / (n - 1) : 0);
  const Y = v => T + ih * (1 - (v - lo) / (hi - lo));
  const fmt = opt.fmt || (v => Math.round(v));
  let o = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img">`;
  for (let k = 0; k < 4; k++) {
    const v = lo + (hi - lo) * k / 3, y = Y(v);
    o += `<line class="gl" x1="${L}" y1="${y.toFixed(1)}" x2="${W - R}" y2="${y.toFixed(1)}"/>`;
    o += `<text class="tk" x="${L - 5}" y="${(y + 3).toFixed(1)}" text-anchor="end">${fmt(v)}</text>`;
  }
  if (opt.zero && lo < 0 && hi > 0)
    o += `<line class="zl" x1="${L}" y1="${Y(0).toFixed(1)}" x2="${W - R}" y2="${Y(0).toFixed(1)}"/>`;
  if (opt.band) {
    let run = [];
    const flush = () => {
      if (run.length > 1) {
        const top = run.map(i => `${X(i).toFixed(1)},${Y(opt.band.hi[i]).toFixed(1)}`).join(' ');
        const bot = run.slice().reverse().map(i => `${X(i).toFixed(1)},${Y(opt.band.lo[i]).toFixed(1)}`).join(' ');
        o += `<polygon class="bandp" points="${top} ${bot}"/>`;
      }
      run = [];
    };
    for (let i = 0; i < n; i++) {
      (opt.band.lo[i] === null || opt.band.hi[i] === null) ? flush() : run.push(i);
    }
    flush();
  }
  series.forEach(s => {
    let seg = [];
    const flush = () => { if (seg.length > 1) o += `<polyline class="ln" points="${seg.join(' ')}" stroke="${s.color}"/>`; seg = []; };
    s.values.forEach((v, i) => v === null ? flush() : seg.push(`${X(i).toFixed(1)},${Y(v).toFixed(1)}`));
    flush();
    const last = s.values.reduce((a, v, i) => v !== null ? i : a, -1);
    if (last >= 0) o += `<circle class="dot" cx="${X(last).toFixed(1)}" cy="${Y(s.values[last]).toFixed(1)}" r="3.5" fill="${s.color}"/>`;
  });
  const step = Math.max(1, Math.floor(n / 4));
  for (let i = 0; i < n; i += step)
    o += `<text class="tk" x="${X(i).toFixed(1)}" y="${H - 6}" text-anchor="middle">${labels[i].slice(5)}</text>`;
  return o + '</svg>';
}

/* 인라인 SVG 막대차트. lineChart 와 같은 크기·같은 축 처리라 나란히 놓아도 눈금이 맞는다.
   막대는 언제나 0 에서 자라야 하므로 축 범위에 0 을 반드시 넣는다. */
function barChart(values, labels, opt = {}) {
  const n = labels.length;
  if (!n) return '<div class="empty">표시할 값이 없습니다.</div>';
  const W = 340, H = 150, L = 40, R = 8, T = 8, B = 20;
  const vals = values.map(v => Number(v) || 0);
  let lo = Math.min(0, ...vals), hi = Math.max(0, ...vals);
  if (hi === lo) hi = lo + 1;
  const pad = (hi - lo) * .1;
  hi += pad; if (lo < 0) lo -= pad;
  const iw = W - L - R, ih = H - T - B;
  const Y = v => T + ih * (1 - (v - lo) / (hi - lo));
  const bw = iw / n, w = Math.max(2, bw * .62);
  const fmt = opt.fmt || (v => Math.round(v));
  const xfmt = opt.xfmt || (s => String(s).slice(5));
  let o = `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img">`;
  for (let k = 0; k < 4; k++) {
    const v = lo + (hi - lo) * k / 3, y = Y(v);
    o += `<line class="gl" x1="${L}" y1="${y.toFixed(1)}" x2="${W - R}" y2="${y.toFixed(1)}"/>`;
    o += `<text class="tk" x="${L - 5}" y="${(y + 3).toFixed(1)}" text-anchor="end">${fmt(v)}</text>`;
  }
  const y0 = Y(0);
  vals.forEach((v, i) => {
    if (!v) return;                                   // 값이 없는 달은 칸만 비워 둔다
    const cx = L + bw * i + bw / 2, y = Y(v);
    o += `<rect class="barr ${v >= 0 ? 'pos' : 'neg'}" x="${(cx - w / 2).toFixed(1)}" ` +
      `y="${Math.min(y, y0).toFixed(1)}" width="${w.toFixed(1)}" ` +
      `height="${Math.max(1, Math.abs(y - y0)).toFixed(1)}" rx="2"/>`;
  });
  if (lo < 0 && hi > 0)
    o += `<line class="zl" x1="${L}" y1="${y0.toFixed(1)}" x2="${W - R}" y2="${y0.toFixed(1)}"/>`;
  /* 가로 라벨은 맨 뒤에서부터 건너뛴다. 앞에서부터 세면 정작 궁금한
     마지막 달(이번 달)에 라벨이 안 붙는 일이 생긴다. */
  const step = Math.max(1, Math.ceil(n / 6));
  for (let i = n - 1; i >= 0; i -= step)
    o += `<text class="tk" x="${(L + bw * i + bw / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle">${xfmt(labels[i])}</text>`;
  return o + '</svg>';
}
