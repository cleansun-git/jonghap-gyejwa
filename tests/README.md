# 테스트

외부 패키지 없이 돕니다. `python` 만 있으면 됩니다(pytest 안 씁니다).

```bash
python tests/test_accounts.py
python tests/test_dailyjob.py
python tests/test_crud.py
```

셋을 한 번에:

```bash
for t in accounts dailyjob crud; do python tests/test_$t.py || break; done
```

통과하면 마지막 줄에 `전부 통과`, 실패하면 실패한 항목을 적고 종료코드 1 로 끝납니다.

## 안전장치 — 실제 데이터를 건드리지 않는다

세 파일 모두 **맨 위에서** 다음 두 가지를 합니다. 이 순서를 바꾸지 마세요
(`settings` 가 불러와지는 순간 데이터 폴더가 정해지므로, import 보다 먼저 와야 합니다).

- `PEN_DATA_DIR` 를 **임시 폴더**로 돌려놓습니다. 그래서 `data/` 의 실제 보유·기록을
  건드리지 않고, 끝나면 그 임시 폴더를 지웁니다.
- `PEN_KIS_APP_KEY` / `PEN_KIS_APP_SECRET` 를 **지웁니다**. 키가 없어야
  KIS 를 한 번도 부르지 않습니다 — 테스트가 네트워크를 타지 않습니다.

## 무엇을 보는가

| 파일 | 보는 것 |
|---|---|
| `test_accounts.py` | 계좌 등록부, 경로 탈출 방어(`..`·`dc/../isa` 가 ValueError), 계좌 격리, 시드 금액·자산군·배당 |
| `test_dailyjob.py` | `autoPrice=False` 분기 — KIS 를 안 부르는지, 키 없이 휴장일 판정, 마감이 쌓이는지, upsert, 수동 실행 |
| `test_crud.py` | 종목 추가·매수(가중평균)·매도·수정·삭제, 현재가 직접 입력, 현금·배당, 마감, 성과 합계 |

## 시드를 바꾸면 테스트도 고쳐야 합니다

`src/store.py` 의 `SEED` 를 자기 보유로 바꾸면 금액을 검산하는 항목들이 당연히 깨집니다.
그때는 `test_accounts.py` 의 `[3]`·`[6]` 과 `test_crud.py` 의 `[1]`~`[3]` 에 적힌
기대값을 자기 값으로 바꾸거나, 그 블록을 지우면 됩니다.
나머지(경로 방어·계좌 격리·CRUD·마감)는 시드와 무관하게 그대로 돕니다.
