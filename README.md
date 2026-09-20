# 쩜일프로 시세 저장소

한국투자증권(KIS) OpenAPI 로 **매일 자동으로** 일봉을 받아 CSV 에 쌓는 저장소입니다.
PC 를 켜둘 필요가 없습니다 — 깃허브가 대신 돌립니다.

```
GitHub Actions ──KIS API──> data/*.csv ──raw.githubusercontent──> 클로드 → 아티팩트
```

## 들어 있는 것

| 파일 | 설명 |
|---|---|
| `.github/workflows/prices.yml` | 하루 두 번(한국장·미국장 마감 후) 자동 실행 |
| `fetch_prices.py` | KIS 호출 + CSV 누적 |
| `tickers.json` | 받을 종목 목록 (40개) |
| `data/kis_daily_KR.csv` | 국내 일봉 `code,date,close` |
| `data/kis_daily_US.csv` | 미국 일봉 |

## 처음 설정 (10분)

1. 이 폴더를 새 저장소로 올립니다.
   ```bash
   git init && git add . && git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<본인>/jjeom1pro-prices.git
   git push -u origin main
   ```
2. 저장소 → **Settings → Secrets and variables → Actions → New repository secret**
   - `KIS_APPKEY` : 발급받은 앱키
   - `KIS_APPSECRET` : 발급받은 시크릿
   - (모의투자 키를 쓰면 Variables 에 `KIS_MODE` = `vts` 추가)
3. **Actions 탭 → 시세 수집 → Run workflow** 로 한 번 수동 실행.
   `since` 에 `20241201` 을 넣으면 과거치까지 한 번에 채웁니다.
4. 로그에 `종목 27/27`, `13/13` 이 뜨고 `data/` 에 커밋이 생기면 성공입니다.

## 잘 안 될 때

**토큰 발급 실패 / HTTP 403** — KIS 가 해외 IP 를 막았을 가능성이 큽니다.
워크플로의 `runs-on: ubuntu-latest` 를 `runs-on: self-hosted` 로 바꾸고,
본인 PC 에 [self-hosted runner](https://docs.github.com/actions/hosting-your-own-runners)
를 설치하면 **같은 워크플로가 집 IP 로** 돕니다. 나머지는 그대로입니다.

**종목 0/27** — App Key 는 맞는데 서비스 신청이 안 된 상태일 수 있습니다.
KIS Developers 포털에서 신청 상태를 확인하세요.

**커밋이 안 생김** — 값이 하나도 안 바뀌었다는 뜻입니다(휴장일 등). 정상입니다.

## 주의

- 비공개 저장소로 두셔도 됩니다. Actions 무료 사용량(월 2,000분) 안에서 충분히 돕니다.
- `KIS_APPKEY` / `KIS_APPSECRET` 은 **절대 코드나 커밋에 넣지 마세요.** Secrets 에만 둡니다.
- 공개 저장소로 두면 클로드가 토큰 없이 바로 읽습니다(시세 자체는 비밀이 아닙니다).
