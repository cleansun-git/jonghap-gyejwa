# 종합계좌 — 계좌 기록 앱 · 빌드 명세서

## 0. 무엇을 만드는가

계좌를 기록하는 PWA. FastAPI 백엔드 + 바닐라 JS PWA 프런트.
탭은 **계좌 하나당 한 장 + 성과 + 설정** —
하단 탭은 **계좌 / 성과 / 설정** 셋이고, 계좌는 그 안의 칩 줄에서 고른다 —
계좌 5개(퇴직연금·ISA·연금저축·IRP·일반).

> 2026-09-16 계좌가 6개가 되면서 **하단 탭에서 계좌를 뺐다.** 375px 폰에서 탭 8개면
> 하나가 47px 이라 "퇴직연금" 네 글자가 안 들어간다. 계좌 탭 맨 위에 칩 줄을 두고
> 칩마다 금액을 띄운다 — 전환 횟수는 그대로(한 번)이고, 전체 현황이 한 화면에 들어온다.
> 칩 위에 전 계좌 합계 한 줄. 계좌가 더 늘어도 칩 줄만 늘어난다.

> **`autoPrice: False`** 를 붙인 계좌는 KIS 로 시세를 받지 않는다. 자동갱신을 아예
> 시도하지 않고(시도하면 종목마다 실패해 평일마다 '시세를 받지 못했습니다' 알림만 울린다),
> 현재가는 「관리 > 현재가 직접 입력」으로 넣는다. 마감 기록은 그 값으로 정상으로 쌓인다.
> 종목코드 규칙도 KIS 6자리가 아니라 영숫자 1~20자다.
> **이 앱은 다섯 계좌 전부 `autoPrice: False` 다.** API 키 없이 바로 쓸 수 있게 한 것이고,
> 현재가는 사람이 넣는다. 자기 KIS 키로 자동갱신을 쓰려면 `accounts.py` 에서 `True` 로 바꾼다.
>
> **계좌 여러 개** 구조다. 계좌 key 는 짧은 코드(`dc` `isa` `pen` `irp` `gen`)이고
> 화면에는 이름만 나온다.
> · 계좌 등록부는 `src/accounts.py` 한 곳. 여기에 한 줄 더하면 데이터 폴더·API·탭이 따라 생긴다.
> · 데이터는 계좌마다 폴더가 따로다 — `data/dc/`, `data/isa/`.
>   한 파일에 계좌 칸을 더하는 쪽이 합계는 쉽지만, 이미 쌓인 기록의 형식을 바꿔야 한다.
>   그 기록이 사용자의 자산 이력이라 옮기다 깨지는 위험을 지지 않았다.
> · 예전 구조(`data/state.json`)는 처음 뜰 때 `data/dc/` 로 한 번 옮긴다.
>   옮기기 전 `data/_backup_before_accounts/` 에 사본을 남긴다.
> · **저장소·서비스 함수는 계좌를 반드시 첫 인자로 받는다.** 기본값을 두지 않는다 —
>   빠뜨린 호출이 조용히 다른 계좌 파일을 건드리는 것보다 TypeError 로 터지는 편이 낫다.
> · 화면은 `/api/auth` 가 주는 등록부로 탭을 찍는다. 계좌를 더할 때 HTML 은 손대지 않는다.
> · 성과 탭은 맨 앞의 **전체**(모든 계좌 합계)와 계좌 하나씩을 칩으로 골라 본다.
>   합계 KPI 는 스냅샷을 더해 만들고(오늘 마감 전에도 맞는 값), 그래프는 계좌별 history 를
>   날짜로 합친다. **합치기 시작하는 날은 모든 계좌가 첫 기록을 가진 날 중 가장 늦은 날**이다 —
>   그 전까지 합치면 계좌가 하나씩 등장할 때마다 총자산이 계단처럼 뛰어 실제로 없었던 급등으로
>   읽힌다. 기록이 한 줄도 없는 계좌가 있으면 합계 그래프를 아예 그리지 않는다.
>   그 날 이후 어떤 계좌에 줄이 없는 날은 그 계좌의 직전 기록을 끌어다 쓴다(그러지 않으면
>   그날 총자산만 푹 꺼진다). 비중 카드는 전체일 때 **계좌별 비중**으로 바뀐다.

> **체결 탭은 두지 않는다.** 그 기능은 계좌 탭 안에 들어 있다.
> 종목 줄을 누르면 매수·매도·수정·삭제 시트가 열리고, 나머지(현금·배당·현재가 직접 입력·
> 오늘 마감 저장)는 요약 맨 아래 접이식 「관리」 안에 있다.
> 계좌 한 장은 "계좌 한 개 = 보기 + 입력이 한 탭에 끝나는 단위" 다 —
> 계좌를 더하면 이 구조가 그대로 복제된다(`.tabbar` 는 버튼 수만큼 자동으로 나뉜다).

**전략 엔진이 없다.** 주문을 계산하지 않는다.
사용자가 증권사 앱에서 실제로 한 매매를 계좌 탭에서 기록하면, 계좌·성과 탭이 그것을 보여준다.

## 1. 파일 구조 (이대로 만든다)

```
종합계좌/
├─ VERSION                     "1.0.0"
├─ README.md
├─ requirements.txt
├─ config.yaml
├─ .gitignore
├─ secrets.example.json
├─ docs/SPEC.md                (이 문서)
├─ docs/install-cloud.md       클라우드(fly.io) 배포 순서
├─ tests/                      외부 패키지 없이 도는 테스트 (tests/README.md)
├─ src/
│   ├─ accounts.py             계좌 등록부 — 탭 하나 = 계좌 하나
│   ├─ settings.py             config.yaml + secrets.json + data/overrides.json 로드
│   ├─ store.py                data/ 읽기·쓰기 (원자적 교체, 백업)
│   ├─ market.py               KIS API 시세 조회
│   └─ daily_close.py          그날 마감 스냅샷을 history.csv 에 기록
├─ web/
│   ├─ app.py                  FastAPI 라우팅 + 인증 + 스케줄러
│   ├─ service.py              계산·비즈니스 로직 (snapshot/history/체결/보유CRUD)
│   ├─ push.py                 웹 푸시 (VAPID 키쌍은 첫 실행에 스스로 만든다)
│   └─ static/
│       ├─ index.html
│       ├─ app.js
│       ├─ style.css
│       ├─ sw.js
│       ├─ manifest.json
│       └─ icon-192.png / icon-512.png / icon-maskable.png
└─ data/                        (런타임 생성. .gitignore 대상)
    └─ <계좌>/                   dc · isa · pen · irp · gen
        ├─ state.json
        ├─ history.csv
        ├─ trades.csv
        └─ dividends.csv
```

## 2. 데이터 모델

### data/<계좌>/state.json

```json
{
  "version": 1,
  "holdings": [
    {"id":"h1","code":"441640","name":"KODEX 미국배당커버드콜액티브",
     "asset":"선진국주식","pay":"월중","qty":81,"buyPrice":11920,
     "price":12280,"prevPrice":12280,"priceDate":"2026-10-01","memo":""}
  ],
  "cash": 1000000,
  "strategy": {"text":"", "updatedAt": null},
  "startDate": null,
  "priceUpdatedAt": "2026-10-01T16:00:00"
}
```

- `id` — 종목 고유키. `code` 는 바뀔 수 있고 같은 코드가 두 번 들어갈 수도 있으므로 **id 로만 지목한다.**
  새 id 는 `h` + 밀리초 타임스탬프 + 2자리 난수.
- `pay` — `"월중"` | `"월말"` | `""`(빈 문자열 = 기타). 이 세 가지 외에는 받지 않는다.
- `asset` — 자유 문자열. 기본 후보: 국내주식 / 선진국주식 / 국내채권 / 해외채권 / 금 / 암호화폐
- `price` 는 현재가, `prevPrice` 는 **직전 거래일 종가**. 시세를 갱신할 때
  `priceDate` 가 오늘과 다르면 갱신 전에 `price` 를 `prevPrice` 로 옮긴다.
  같은 날 두 번 갱신해도 `prevPrice` 가 망가지지 않게 하기 위한 것이다.

### data/<계좌>/history.csv (일별 마감 스냅샷 · 성과 탭 원천)

헤더: `date,total,buyTotal,evalPl,retPct,cash,holdingsValue,midValue,endValue,etcValue,divMonth,savedAt`

- 같은 날짜가 이미 있으면 **덮어쓴다** (하루에 여러 번 저장해도 안전).
- `midValue`/`endValue`/`etcValue` = 월중/월말/기타 그룹의 평가금액 합계.
- `divMonth` = 그 날짜가 속한 달의 배당 합계.

### data/<계좌>/trades.csv (체결·변경 이력)

헤더: `ts,date,action,code,name,qty,price,amount,note`

- `action`: `buy` | `sell` | `add` | `remove` | `edit` | `cash` | `dividend`
- 계좌 탭(종목 시트·관리)에서 일어난 모든 변경을 여기에 남긴다. 되돌리기용이 아니라 기록용이다.

### data/<계좌>/dividends.csv

헤더: `date,code,name,amount,ts`

## 3. 시드 데이터 (data/<계좌>/state.json 이 없을 때 이 값으로 만든다)

`src/store.py` 의 `SEED_HOLDINGS` 상수. **샘플 데이터다 — 실제 보유가 아니다.**

종목당 평가금액을 100만원에 맞췄다(`qty = round(1,000,000 / price)`). 매수단가는 현재가에서
±3% 로 엇갈리게 넣었다 — 손익에 빨강(수익)과 파랑(손실)이 둘 다 보여야 색 규칙이 첫 화면에서
드러난다. 금액이 전부 떨어지는 숫자인 것도 의도다(받는 사람이 샘플임을 바로 알아본다).

| code | name | asset | pay | qty | buyPrice | price |
|---|---|---|---|---|---|---|
| 441640 | KODEX 미국배당커버드콜액티브 | 선진국주식 | 월중 | 81 | 11920 | 12280 |
| 493810 | TIGER 미국AI빅테크10타겟데일리커버드콜 | 선진국주식 | 월중 | 90 | 11460 | 11115 |
| 498400 | KODEX 200타겟위클리커버드콜 | 국내주식 | 월중 | 47 | 20560 | 21180 |
| 498410 | KODEX 금융고배당TOP10타겟위클리커버드콜 | 국내주식 | 월말 | 86 | 12060 | 11695 |
| 0219E0 | KODEX 200커버드콜액티브 | 국내주식 | 월말 | 116 | 8370 | 8620 |
| 0040Y0 | SOL 팔란티어커버드콜OTM채권혼합 | 선진국주식 | 월말 | 127 | 8100 | 7855 |
| 0013R0 | RISE 테슬라미국채타겟커버드콜혼합(합성) | 선진국주식 | 월말 | 131 | 7390 | 7615 |
| 494300 | KODEX 미국나스닥100데일리커버드콜OTM | 선진국주식 | 월말 | 115 | 8990 | 8720 |
| 361580 | RISE 200TR | 국내주식 | (빈칸) | 16 | 61850 | 63710 |

`0040Y0`·`0013R0` 은 이름이 채권혼합이지만 평가손익을 움직이는 것은 팔란티어·테슬라
주가다. 그래서 자산군을 해외채권이 아니라 **선진국주식**으로 둔다.

`cash` = 1,000,000, `priceUpdatedAt` = `"2026-10-01T16:00:00"`,
`priceDate` 전부 `"2026-10-01"`, `prevPrice` 는 `price` 와 같은 값으로 시작.

`isa`·`pen`·`irp`·`gen` 은 **종목 없이 현금 100만원씩**이다. 받는 사람이 「종목 추가」로
자기 종목을 넣는 것이 배포형답고, 그 과정에서 빈 계좌 화면도 함께 확인된다.

시드 배당 (`data/dc/dividends.csv` 초기 2줄, 전부 date=2026-10-02):

| code | name | amount |
|---|---|---|
| 0219E0 | KODEX 200커버드콜액티브 | 10000 |
| 498410 | KODEX 금융고배당TOP10타겟위클리커버드콜 | 8000 |

**검산 (반드시 이 값이 나와야 한다 — 퇴직연금 탭)**

- 월중 소계: 매수 2,963,240 · 평가 2,990,490 · 손익 +27,250 (+0.92%)
- 월말 소계: 매수 5,038,720 · 평가 5,003,640 · 손익 −35,080 (−0.70%)
- 기타 소계: 매수 989,600 · 평가 1,019,360 · 손익 +29,760 (+3.01%)
- 총 매수 8,991,560 · 총 평가 9,013,490 · 현금 1,000,000
- **총금액 10,013,490 · 평가손익 +21,930 · 수익률 +0.24%**
- 2026-10 배당 합계 18,000

## 4. API 계약 (백엔드·프런트가 이 계약만 보고 각자 만든다. 어기면 화면이 빈다)

인증·푸시: 쿠키명은 `pen_session`, 환경변수는 `PEN_PASSWORD`, `PEN_HTTPS`, `PEN_NO_SCHEDULER`.

| 메서드 | 경로 | 본문 | 응답 |
|---|---|---|---|
| GET | `/api/auth` | — | `{required,authed,version}` |
| POST | `/api/login` | `{password}` | `{ok}` |
| POST | `/api/logout` | — | `{ok}` |
| GET | `/api/snapshot` | — | §5 SNAPSHOT |
| GET | `/api/history?days=180` | — | `{history:[...], trades:[...], dividends:[...]}` |
| POST | `/api/holding` | §6 HoldingIn | `{ok,message,id}` |
| POST | `/api/holding/delete` | `{id}` | `{ok,message}` |
| POST | `/api/prices` | `{prices:{id:price,...}}` | `{ok,message,updated}` |
| POST | `/api/refresh-prices` | — | `{ok,message,updated,failed:[...]}` |
| POST | `/api/cash` | `{amount}` | `{ok,message}` |
| POST | `/api/dividend` | `{code,name,amount,date}` | `{ok,message}` |
| POST | `/api/strategy` | `{text}` | `{ok,message}` |
| POST | `/api/close-today` | — | `{ok,message}` |
| POST | `/api/start` | `{start_date}` | `{ok,message}` |
| POST | `/api/run-now` | — | `{ok,message}` |
| GET | `/api/push/key` | — | `{publicKey}` |
| POST | `/api/push/subscribe` | 구독 JSON | `{ok}` |
| POST | `/api/push/test` | — | `{ok,sent}` |

오류는 `HTTPException(400, detail=...)` → 프런트가 `j.detail` 을 보여준다.

## 5. SNAPSHOT 응답 (계좌 탭이 이것만으로 그려진다)

```json
{
  "today": "2026-10-02",
  "weekday": 4,
  "version": "1.0.0",
  "started": true,
  "start_date": null,
  "priceUpdatedAt": "2026-10-01T16:00:00",
  "priceStale": false,
  "totals": {
    "total": 10013490,
    "holdingsValue": 9013490,
    "cash": 1000000,
    "buyTotal": 8991560,
    "evalPl": 21930,
    "retPct": 0.00244,
    "dayChange": 0, "dayChangePct": 0.0, "hasPrev": false, "prevDate": null,
    "lastMonthLabel": "2026-09", "lastMonthDividend": 0,
    "thisMonthLabel": "2026-10", "thisMonthDividend": 18000,
    "totalDividend": 18000
  },
  "groups": [
    {"key":"월중","label":"월중 배당","items":[],
     "subtotal":{"buyAmount":2963240,"evalAmount":2990490,"pl":27250,"retPct":0.0092,"count":3}},
    {"key":"월말","label":"월말 배당","items":[],"subtotal":{}},
    {"key":"기타","label":"기타","items":[],"subtotal":{}}
  ],
  "strategy": {"text":"", "updatedAt": null},
  "telegram_enabled": false
}
```

ITEM 한 건의 모양:

```json
{"id":"h1","code":"441640","name":"KODEX 미국배당커버드콜액티브","asset":"선진국주식",
 "pay":"월중","qty":81,"buyPrice":11920,"price":12280,"prevPrice":12280,
 "buyAmount":965520,"evalAmount":994680,"pl":29160,"retPct":0.03019,
 "dayPl":0,"dayPct":0.0,"weight":0.09933,"memo":""}
```

- `retPct` 는 **소수**다 (0.0302 = +3.02%). 프런트의 `pct()` 가 ×100 한다.
- `weight` = evalAmount / totals.total
- 그룹은 항상 3개를 **이 순서로** 보낸다. 종목이 0개인 그룹도 빈 items 로 보낸다
  (프런트가 "없음"을 그린다).
- `dayChange` — `history.csv` 의 **가장 최근 date < today** 행의 `total` 과 비교한다.
  그런 행이 없으면 `hasPrev:false`, `dayChange:0`.
- `priceStale` — `priceUpdatedAt` 이 3일보다 오래됐으면 true.
- `lastMonthDividend` — 지난 달(오늘 기준 −1개월) 배당 합계. 오늘이 2026-10-02 이면 2026-09.

## 6. HoldingIn (계좌 탭의 종목 시트에서 오는 본문)

```json
{"id": null,
 "code":"441640", "name":"...", "asset":"선진국주식", "pay":"월중",
 "qty":81, "buyPrice":11920, "price":12280, "memo":"",
 "action":"edit",
 "deltaQty":0, "deltaPrice":0,
 "confirm_price": false}
```

`id` 가 null 이면 신규 추가, 있으면 그 종목 수정. `action` 은 trades.csv 에 남길 라벨
(`edit` | `buy` | `sell`). `deltaQty`/`deltaPrice` 는 action 이 buy/sell 일 때 그날 체결분.

**종목 시트의 동작 두 가지를 반드시 구분한다.**

1. **직접 수정** (`action:"edit"`) — 수량·현재가·매수단가를 최종값으로 덮어쓴다.
2. **매수/매도 추가** (`action:"buy"|"sell"`) — `deltaQty` 주를 `deltaPrice` 에 체결한 것으로
   보고 **가중평균 단가를 다시 계산한다**:
   - 매수: `newQty = qty + deltaQty`,
     `newBuyPrice = (qty*buyPrice + deltaQty*deltaPrice) / newQty` (반올림)
   - 매도: `newQty = qty - deltaQty` (보유수량 초과면 400 오류),
     **매도는 평균단가를 바꾸지 않는다.** 0주가 되면 종목을 지우지 않고 qty=0 으로 남긴다.
   - 매도 시 실현손익 `(deltaPrice - buyPrice) * deltaQty` 를 trades.csv 의 `amount` 에 기록.

**중복 입력 가드** (2026-09-13 추가): buy/sell 이 trades.csv 의 최근 10분 안 기록과
종목·액션·수량·단가가 모두 같고 `confirm_dup` 이 false 면 `400` + `"중복 확인: …"`.
프런트는 confirm() 으로 되묻고, 예면 `confirm_dup:true` 로 재전송, 아니오면 저장하지 않고 시트를 닫는다.

**오타 가드**:
서버는 `price` 가 기존 `price` 대비 ±30% 를 넘고 `confirm_price` 가 false 면
`400` 과 함께 `"현재가가 기존 12,280원과 30% 이상 차이납니다. 확인 후 다시 보내주세요."` 를 던진다.
프런트는 이 오류를 받으면 `confirm()` 으로 되묻고 `confirm_price:true` 로 재전송한다.

## 7. 화면 — 탭별 요구사항

`web/static/style.css` 의 **디자인 토큰·클래스를 재사용**한다
(`.card .kpi .kpis .item .seg .sheet .tabbar .btn .chart .legend .grid3 .notice .empty` 등).
한국 증권 관행: **상승·수익 = 빨강(`--up`), 하락·손실 = 파랑(`--down`)**. 이미 style.css 가 그렇다.
범주 색에는 빨강·파랑을 쓰지 않는다 — 수익/손실로 읽힌다. 무채색 단계(`--g-*`)와 `--a1`~`--a6` 를 쓴다.
통화는 전부 **원(₩)**.

### 7-1. 계좌 탭 (`#tab-<계좌key>`) — 보기와 입력이 한 탭에

계좌마다 한 장씩, 전부 같은 모양이다 (app.js 의 `accountSection()` 하나가 찍는다).

> 2026-09-16 체결 탭을 없애고 그 기능을 여기로 합쳤다.
> 날마다 하는 일(매수·매도 기록)은 종목 줄을 눌러 시트로 하고,
> 가끔 쓰는 것(현금·배당·현재가 직접 입력·마감)은 접이식 「관리」 안에 둔다.
> 체결 탭에 있던 보유 종목 목록은 아래 그룹 표와 같은 것이라 없앴다.

1. **시세 경고** (`#priceNotice`) — `priceStale` 이면 `.notice.warn` 으로 「시세가 오래됐습니다」.
   아니면 `hidden`. (체결 탭 맨 위에 있던 것)
2. **KPI 3개** (`.kpis` 2열 그리드) — 순서 고정
   - `자산` — `totals.total`. 한 줄 전체(`.kpi.wide`), 바로 아래 `evalPl (retPct)` 를 색 입혀(`.v2`)
   - `월 배당` — `totals.thisMonthDividend` (오늘이 속한 달에 지급일이 찍힌 배당 합계)
   - `현금성자산` — `totals.cash`
   - 설명 문구는 어디에도 넣지 않는다 (2026-09-13 사용자 요청).
3. **그룹 표** — 월중 / 월말 / 기타 중 **종목이 있는 것만**. 각각 `.card` 하나.
   (2026-09-16: 빈 그룹은 카드를 만들지 않는다. ISA 는 배당 시기를 정하지 않아 전부 '기타' 라
   빈 카드 두 장이 따라 나왔다. 종목이 하나도 없는 계좌일 때만 빈 안내를 한 줄 보여준다.)
   - 카드 제목: 그룹명 + 우측에 종목 수와 그룹 소계 수익률(색)
   - 증권사 잔고 화면과 같은 형식(2026-09-16): 종목명 + 평가손익/수익률 · 평가금액/매수금액 ·
     보유수량 · 매수단가/현재가 를 한 칸에 두 줄씩. 칸이 많아 가로로 밀어 보되
     종목명 칸(`.bn`)은 sticky 로 왼쪽에 고정. **body 가 가로로 스크롤되면 안 된다.**
   - **행(`tr.tap`)을 누르면 종목 시트가 열린다** — 매수 / 매도 / 수정 / 삭제 (§7-1-1).
     가로로 미는 동안에는 브라우저가 click 을 취소하므로 스크롤과 부딪히지 않는다.
   - 각 카드 하단에 소계 행: 매수금액 합 · 평가금액 합 · 손익 · 수익률
   - 종목이 없는 그룹은 `.empty` 로 `아직 종목이 없습니다.`
4. **버튼 줄** (`.btns2`) — `시세 자동갱신` (`POST /api/refresh-prices`) · `종목 추가` (시트 신규 모드)
5. **내일의 전략** (`.card`) — `<textarea>` 수기 입력.
   - 자동저장하지 않는다. `저장` 버튼을 누를 때만 `POST /api/strategy`.
   - 마지막 저장 시각을 `.hint` 로 보여준다.
   - 내용이 바뀌었는데 저장하지 않고 탭을 옮기면 토스트로 알린다.
6. **관리** (`details.fold`) — 기본은 접혀 있다. 열면 네 가지:
   - `현금` — 숫자 입력 + 저장 (`POST /api/cash`)
   - `배당` — 종목 선택(select) + 금액 + 날짜(기본 오늘) → `POST /api/dividend`.
     배당을 적어도 현금은 저절로 늘지 않는다 — 토스트로 한 번 짚어준다.
   - `현재가 직접 입력` — 보유 종목을 이름+숫자칸 한 줄씩 나열, `현재가 반영` → `POST /api/prices`.
     **비워 둔 종목은 손대지 않는다.** 시세 자동갱신이 막혔을 때의 대비책이다.
     머리 오른쪽에 마지막 시세 시각(`#priceAt2`).
     여기서는 줄을 눌러도 시트가 열리지 않는다 — 칸을 누르다 시트가 열리는 사고를 막는 쪽이 낫다.
   - `운용 시작일` — date + 저장 + `시작일 지우기` (`POST /api/start`).
     계좌마다 다른 값이라 설정 탭이 아니라 여기에 있다 (2026-09-16).
     **시작일 이전의 일별 기록은 성과 그래프에서 빠진다** (2026-09-18 사용자 요청 "성과는 오늘부터").
     지우지 않고 가리기만 하므로 시작일을 비우면 그대로 돌아온다. 배당·체결 이력은 가리지 않는다 —
     월 배당 막대는 그 달 전체를 보여줘야 한다.
   - `오늘 마감 저장` (`POST /api/close-today`) — 성과 탭 기록을 쌓는다.

#### 7-1-1. 종목 시트 (`#sheet`)

계좌 탭의 종목 줄과 `종목 추가` 버튼이 이 하나를 돌려 쓴다.
세그먼트(`.seg`): `매수` / `매도` / `수정` / `삭제` — 신규 모드에서는 세그먼트를 감춘다.

- 매수·매도 → `체결수량` + `체결단가` 입력 → §6 의 가중평균 재계산.
  **칸을 미리 채우지 않는다** — 보유 수량이 적혀 있으면 그대로 눌러 전량을 한 번 더 사는 사고가 난다.
- 수정 → 수량·매수단가·현재가·자산군·배당시기(월중/월말/기타)·메모 전체를 최종값으로 덮어쓴다
- 삭제 → `confirm()` 으로 되묻고 `POST /api/holding/delete`
- 신규 → 종목코드(6자리 영숫자, 예: `0219E0`)·종목명·자산군·배당시기·수량·매수단가·현재가
- 서버가 막는 두 가지는 `confirm()` 으로 되묻고 확인 표시를 달아 다시 보낸다:
  30% 이상 벗어난 단가(`confirm_price`), 최근 10분 안의 같은 체결(`confirm_dup`).
- 시트 안내 문구는 화면에 두지 않는다 — 칸 이름(체결수량/수량)과 버튼 글자가 이미 말해준다.

### 7-2. 성과 탭 (`#tab-perf`)

> 2026-09-13 사용자 요청으로 단순화: 제목 아래 줄·기록 부족 안내 박스·KPI 보조 문구 삭제.
> KPI 는 총금액 / 평가손익(아래 수익률) / 누적 배당 / 배당수익률(누적). 그래프 제목은 총금액 추이 · 평가손익 추이.

`lineChart()` 는 인라인 SVG 로 직접 그린다(외부 라이브러리 금지).
`barChart()` 를 같은 스타일로 하나 추가한다.

1. **KPI 4개**: 총자산 / 누적 평가손익 / 누적 배당 /
   배당수익률(누적배당 ÷ 매수금액 — 라벨에 `누적 기준` 명시, 연환산 아님)
2. `총자산 추이` — 라인차트 (history.csv `total`)
3. `누적 평가손익` — 라인차트, `zero:true` (0선 표시)
4. `월 배당` — 막대차트, 최근 12개월. 값 없는 달은 0으로 채워 연속되게.
5. `그룹별 비중` — 월중/월말/기타/현금 4개를 가로 누적 막대 + 범례.
   style.css 토큰 색만 쓴다.
6. 기록이 2일 미만이면 `데이터가 2일 이상 쌓이면 그래프가 그려집니다.`

### 7-3. 설정 탭 (`#tab-set`)

> 2026-09-13 사용자 요청으로 단순화: 제목 아래 줄·카드 설명 삭제, 결과 문구는 토스트로.
> 현재 설정은 계좌·보유 종목·자동 실행(snapshot.dailyAt)·마지막 시세·기록 일수·버전만. 면책은 한 줄.

운용 시작일, 휴대폰 알림(웹 푸시), 현재 설정 요약, 지금 실행, 로그아웃.

1. `운용 시작일` — date + 저장 + `시작일 지우기 (바로 운용)` — 이 앱은 시작일이 없으면 바로 운용 중으로 본다
2. `알림` — `휴대폰 알림 켜기` / `알림 테스트` / `알림이 안 올 때 (진단)` + `#pushDiag`
   (구독·해제·진단 세 핸들러)
3. `현재 설정` — `.kv` 목록: 계좌, 보유 종목 수, 총 매수금액, 현금,
   월중/월말/기타 종목 수, 마지막 시세 갱신, 기록 일수
4. `수동 실행` — `지금 실행` → `POST /api/run-now` (시세 갱신 + 오늘 마감 저장 + 푸시 발송)
5. `로그아웃`
6. `.disclaimer` — 이 앱은 기록·조회용이며 실제 매매를 하지 않는다는 문구

## 8. 백엔드 세부

- `web/app.py` — 스케줄러는 **평일 16:05 KST**
  (`CronTrigger(day_of_week="mon-fri", hour=16, minute=5)`) 에 `run_daily_job()`:
  (정각이 아닌 이유: 같은 KIS 키를 쓰는 다른 프로그램이 16:00 에 토큰을 받으면 겹친다.
  KIS 는 토큰 발급을 키당 1분 1회만 허용한다. 이 앱은 KIS 를 안 쓰므로 바꿔도 된다)
 
  **개장일 확인** → 시세 갱신 → 오늘 마감 저장 → 푸시(`총자산 · 평가손익`).

  개장일 확인(2026-09-16 추가)은 `market.is_market_open()` — KIS 휴장일 API(`CTCA0903R`)에
  그날 `opnd_yn` 을 묻는다. 공휴일 목록을 코드에 박아두면 매년 손봐야 하고 임시공휴일을 놓친다.
  **조회가 실패하면 개장일로 본다(fail-open).** 공휴일에 같은 값이 한 줄 더 남는 것은 upsert 로
  덮이지만, API 장애로 평일 마감을 빠뜨리면 그날 기록이 영영 비고 알림도 오지 않기 때문이다.
  주말은 API 없이 요일로 거른다. 설정 탭의 「지금 실행」(`manual=True`)은 이 검사를 건너뛴다.
  `PEN_NO_SCHEDULER=1` 이면 끈다. 텔레그램 관련 코드는 **넣지 않는다** (이 앱에는 없다).

  **KIS 키가 없으면**(이 배포형의 기본) 휴장일을 확인할 방법이 아예 없으므로 주말만 거르고
  평일은 모두 개장일로 둔다. 공휴일에도 마감 한 줄이 쌓이지만, 현재가를 손으로 넣는 앱이라
  그 줄은 전날과 같은 값이고 성과 탭에서 평평한 구간으로 보일 뿐이다.
- `src/market.py` — KIS 조회. `autoPrice: True` 인 계좌에서만 쓴다:
  `http_json()`(재시도), `get_access_token()`(24시간 파일 캐시 `data/.kis_token_cache.json`),
  `get_current_price()`(tr_id `FHKST01010100`), `get_stock_name()`(tr_id `CTPF1002R`),
  `normalize()`. **안전장치 두 개를 반드시 유지한다**:
  1. 0원 가드 — 현재가가 0 이하이면 실패로 처리하고 반영하지 않는다.
  2. 종목명 대조 — 조회된 실제 종목명이 state 의 이름과 다르면 그 종목은 건너뛴다.

  API 키는 `secrets.json` 의 `kis_app_key`/`kis_app_secret` 에서 읽는다.
  **키가 없으면 예외를 던지지 말고** `{"ok":false,"message":"KIS 키가 설정되지 않았습니다..."}`
  로 조용히 실패해야 한다 (키 없이도 앱 전체는 정상 동작해야 한다).
  호출 간 0.6초 대기, 최대 3회 재시도.
- `src/store.py` — `_safe_replace`/`_safe_backup`
  (원자적 교체, `.bak` 백업, OneDrive 잠금 대비 재시도). CSV 는 `utf-8-sig`.
- `web/service.py` — 계산은 **전부 여기서** 한다. app.py 는 라우팅만.
  금액은 정수 원 단위로 반올림. 나눗셈 분모가 0이면 `0.0` 을 반환한다(ZeroDivisionError 금지).

## 9. 코드 관습 (어기지 말 것)

- 파이썬 파일 첫 줄 `# -*- coding: utf-8 -*-`, 그 다음 한글 docstring.
- **주석은 한글**로, "무엇"이 아니라 **"왜"** 를 적는다. "무엇"은 코드가 말한다.
- `from __future__ import annotations`
- 프런트는 **바닐라 JS**. 빌드 도구·프레임워크·외부 CDN 라이브러리 **금지**.
  폰트만 Google Fonts(IBM Plex Sans KR / IBM Plex Mono)를 쓴다.
- `app.js` 는 `'use strict';` 로 시작, `$`/`$$`/`esc()`/`toast()`/`api()` 헬퍼를 그대로 가져온다.
- 사용자에게 보이는 문구는 전부 **한국어 존댓말**.
- 값을 못 내는 지표는 0 이나 100% 로 채우지 않고 `—` 로 둔다.

## 10. 하지 말 것

- 투자 판단·종목 추천을 앱이 하지 않는다. 기록과 조회만 한다.
- API 키·비밀번호를 HTML/JS 에 넣지 않는다.
- `data/` 를 git 에 올리지 않는다 (`.gitignore`).
- 텔레그램 연동을 넣지 않는다.
- 외부 차트 라이브러리를 쓰지 않는다 (인라인 SVG).
