/* 종합계좌 서비스 워커 — 정적 파일 캐시 + 푸시 수신 */
const CACHE = 'pen-v2';
const ASSETS = ['/', '/static/style.css', '/static/app.js',
                '/static/manifest.json?v=2', '/static/icon-192.png?v=2'];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ASSETS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(ks => Promise.all(ks.filter(k => k !== CACHE).map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

/* API 는 항상 네트워크.
   화면(HTML)·app.js·style.css 는 네트워크 우선 — 새로 배포하면 바로 반영되도록.
   이미지는 캐시 우선 — 내용이 바뀌지 않으므로 빠른 쪽이 낫다.

   js/css 를 캐시 우선으로 두면 안 되는 이유: 한 번 설치된 뒤로는 영영 옛 파일을
   내주어 앱을 고쳐도 휴대폰에 반영되지 않는다. 게다가 HTML 만 최신으로 바뀌면
   새 index.html + 옛 app.js 짝이 되어 화면이 통째로 깨진다.
   그래서 셸과 같은 정책으로 묶는다 — 오프라인일 때는 아래 catch 로 캐시가 받쳐준다.
   (이 앱은 데이터가 전부 /api/ 에서 오므로 어차피 오프라인으로는 쓸 수 없다) */
self.addEventListener('fetch', e => {
  const u = new URL(e.request.url);
  if (e.request.method !== 'GET' || u.pathname.startsWith('/api/')) return;

  const isShell = e.request.mode === 'navigate' ||
                  u.pathname === '/' ||
                  u.pathname.endsWith('.json') ||
                  u.pathname.endsWith('.js') ||
                  u.pathname.endsWith('.css');

  if (isShell) {
    e.respondWith(
      fetch(e.request).then(res => {
        if (res.ok && u.origin === location.origin) {
          const copy = res.clone();
          caches.open(CACHE).then(c => c.put(e.request, copy));
        }
        return res;
      }).catch(() => caches.match(e.request))   // 오프라인일 때만 캐시
    );
    return;
  }

  e.respondWith(
    caches.match(e.request).then(hit => hit || fetch(e.request).then(res => {
      if (res.ok && u.origin === location.origin) {
        const copy = res.clone();
        caches.open(CACHE).then(c => c.put(e.request, copy));
      }
      return res;
    }))
  );
});

self.addEventListener('push', e => {
  let d = { title: '퇴직연금', body: '알림', url: '/' };
  try { d = { ...d, ...e.data.json() }; } catch (_) { }
  e.waitUntil(self.registration.showNotification(d.title, {
    body: d.body,
    icon: '/static/icon-192.png',
    badge: '/static/icon-192.png',
    tag: 'pen-daily',
    renotify: true,
    data: { url: d.url }
  }));
});

self.addEventListener('notificationclick', e => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || '/';
  e.waitUntil(clients.matchAll({ type: 'window', includeUncontrolled: true }).then(ws => {
    for (const w of ws) if ('focus' in w) return w.focus();
    return clients.openWindow(url);
  }));
});
