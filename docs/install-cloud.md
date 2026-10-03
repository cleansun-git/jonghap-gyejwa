# 클라우드에 올리기 (fly.io)

PC를 켜둘 필요가 없습니다. 한 번 올려두면 평일 16:05 에 알아서 마감을 기록하고,
휴대폰 홈 화면 아이콘으로 앱처럼 쓸 수 있습니다.

- 걸리는 시간: 10분쯤
- 비용: shared-cpu-1x · 256MB · 볼륨 1GB 한 대 분량

아래 명령에 나오는 `jonghap-gyejwa` 는 앱 이름입니다. **전 세계에서 겹치면 안 되므로
본인만의 이름으로 바꿔 쓰세요.** 바꿀 때는 `fly.toml` 첫 줄의 `app = "..."` 도 같이 고칩니다.

---

## 1. flyctl 설치

```bash
winget install Fly-io.flyctl
```

## 2. 로그인

```bash
flyctl auth login
```

---

## 3. 앱 만들기

```bash
flyctl apps create jonghap-gyejwa
```

## 4. 저장 공간 만들기

보유 종목·기록이 재배포해도 남아 있어야 하므로 영구 볼륨을 붙입니다.

```bash
flyctl volumes create jonghap_data --size 1 --region nrt -a jonghap-gyejwa -y
```

`--region` 은 `fly.toml` 의 `primary_region` 과 같아야 합니다(기본 `nrt` = 도쿄).

## 5. 비밀번호 넣기

**비밀번호는 반드시 설정해야 합니다.** 없으면 외부 접속이 전부 막힙니다.

```bash
flyctl secrets set PEN_PASSWORD='내가정한비밀번호' -a jonghap-gyejwa
```

> 이 앱은 시세를 직접 입력하는 방식이라 **증권사 API 키가 필요하지 않습니다.**
> KIS 자동 갱신을 쓰기로 했다면([README](../README.md) 참고) 키도 같은 방식으로 넣습니다.
> 키를 화면에 찍지 않고 넘기려면:
>
> ```bash
> flyctl secrets set PEN_KIS_APP_KEY='...' PEN_KIS_APP_SECRET='...' -a jonghap-gyejwa
> ```

## 6. 배포

```bash
flyctl deploy --ha=false -a jonghap-gyejwa
```

`--ha=false` 를 빼면 fly 가 머신을 2대 만들 수 있습니다. 그러면 16:05 기록이 두 번 돌고
볼륨이 둘로 갈라지니 **꼭 붙이세요.**

이렇게 나오면 성공입니다.

```
Visit your newly deployed app at https://jonghap-gyejwa.fly.dev/
```

"Failed to provision IP addresses" 가 나오면:

```bash
flyctl ips allocate-v4 --shared -a jonghap-gyejwa
flyctl ips allocate-v6 -a jonghap-gyejwa
flyctl deploy --ha=false -a jonghap-gyejwa
```

---

## 7. 첫 확인

1. `https://jonghap-gyejwa.fly.dev` 접속 → 비밀번호로 로그인
2. 계좌 탭에 **샘플 데이터**(종목당 약 100만원, 총 1,001만원)가 보이는지 확인
3. `관리 > 현재가 직접 입력` 으로 현재가를 넣어 봅니다
4. `관리 > 오늘 마감 저장` 이 오류 없이 끝나는지 확인

실패하면 `flyctl logs -a jonghap-gyejwa` 의 마지막 줄들을 보세요.

> 처음 뜬 클라우드 앱은 시드(샘플) 데이터로 시작합니다. PC 에서 쓰던 값이 있어도
> 따라오지 않습니다 — 둘은 서로 다른 데이터입니다. 클라우드 쪽에서 다시 맞춰주세요.

## 8. 휴대폰에 앱으로 설치

1. 휴대폰으로 `https://jonghap-gyejwa.fly.dev` 접속 (**아이폰은 사파리**, 안드로이드는 크롬)
2. 로그인 → **홈 화면에 추가**
3. 홈 화면 아이콘으로 실행

알림까지 받으려면 `config.yaml` 의 `notify.push_enabled` 를 `true` 로 바꿔 다시 배포한 뒤,
**설정 탭 → 휴대폰 알림 켜기** 를 누릅니다. `알림 테스트` 로 확인하세요.

> 홈 화면 아이콘으로 실행해야 알림이 옵니다. 브라우저 탭으로 열면 안 옵니다.
> 안 오면 `알림이 안 올 때 (진단)` 을 누르세요.

---

## 알아둘 것

**PC 와 클라우드를 같이 쓰지 마세요.** 클라우드로 올렸으면 기록은 클라우드 한 곳에서만 하세요.
PC 쪽을 켜두면 16:05 기록이 두 곳에 따로 쌓여 서로 어긋납니다.

**머신을 재우지 마세요.** `fly.toml` 의 `auto_stop_machines = false` 와 `min_machines_running = 1` 은
스케줄러가 돌기 위한 설정입니다.

**로그인 시도 제한.** 같은 곳에서 10분에 5번 틀리면 10분간 막힙니다(전체 15번이면 모두).
막힌 동안은 맞는 비밀번호도 받지 않습니다. 10분 뒤에 다시 하세요.

**재배포하면 다시 로그인해야 합니다.** 로그인 상태는 서버 메모리에만 있어서
배포하거나 머신이 다시 켜지면 풀립니다. 데이터는 볼륨에 있어 안 지워집니다.

**잘 도는지 확인**

```bash
flyctl status -a jonghap-gyejwa
flyctl logs -a jonghap-gyejwa
```

로그에 `스케줄러 시작 — 평일 16:05 KST 마감 저장` 이 있으면 스케줄러가 도는 것입니다.

**백업**

```bash
flyctl ssh sftp get /app/data/dc/state.json -a jonghap-gyejwa
flyctl ssh sftp get /app/data/dc/history.csv -a jonghap-gyejwa
```

계좌마다 폴더가 따로입니다(`dc` `isa` `pen` `irp` `gen`).

**코드를 고친 뒤에는** 다시 배포하면 됩니다.

```bash
flyctl deploy --ha=false -a jonghap-gyejwa
```

## 환경변수 (fly secrets)

| 이름 | 뜻 |
|---|---|
| `PEN_PASSWORD` | 로그인 비밀번호. **필수** |
| `PEN_KIS_APP_KEY` / `PEN_KIS_APP_SECRET` | (선택) KIS 시세 키. 자동 갱신을 켤 때만 |
| `PEN_HTTPS` | `1` — fly.toml 에 이미 들어 있습니다 |
| `PEN_CONTACT` | 웹 푸시 연락처 이메일 (선택) |
