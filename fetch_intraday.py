# -*- coding: utf-8 -*-
"""
fetch_intraday.py — KIS OpenAPI 로 국내 종목 현재가를 받아 data/intraday_KR.json 에 쓴다.
장중(평일 09:00~15:30 KST)에 15분마다 GitHub Actions 가 돌린다.

환경변수: KIS_APPKEY, KIS_APPSECRET, KIS_MODE(real|vts, 기본 real)
출력    : data/intraday_KR.json
  {
    "market": "KR", "asof": "2026-09-24 11:15", "asofISO": "2026-09-24T11:15:00+09:00",
    "session": "open" | "closed", "source": "KIS", "count": 27,
    "quotes": { "005930": {"p": 285000, "chg": 1500, "pct": 0.53}, ... }
  }
  p=현재가, chg=전일대비(원, 부호 포함), pct=등락률(%, 부호 포함)

일봉 CSV(kis_daily_*.csv)는 건드리지 않는다. 확정 종가는 fetch_prices.py 가 따로 쌓는다.
"""
import os, sys, json, time, datetime
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data'); os.makedirs(DATA, exist_ok=True)
OUT = os.path.join(DATA, 'intraday_KR.json')
T = json.load(open(os.path.join(HERE, 'tickers.json'), encoding='utf-8'))
KST = datetime.timezone(datetime.timedelta(hours=9))

APPKEY = os.environ.get('KIS_APPKEY', '').strip()
SECRET = os.environ.get('KIS_APPSECRET', '').strip()
if not APPKEY or not SECRET:
    print('KIS_APPKEY / KIS_APPSECRET 환경변수가 없습니다.'); sys.exit(2)
HOST = {'real': 'https://openapi.koreainvestment.com:9443',
        'vts':  'https://openapivts.koreainvestment.com:29443'}[os.environ.get('KIS_MODE', 'real')]


def token():
    r = requests.post(HOST + '/oauth2/tokenP',
                      json={'grant_type': 'client_credentials',
                            'appkey': APPKEY, 'appsecret': SECRET}, timeout=20)
    if r.status_code != 200:
        print('토큰 발급 실패', r.status_code, r.text[:300]); sys.exit(1)
    return r.json()['access_token']


TOK = token()
print('토큰 발급 OK')


def get(path, tr, params, tries=3):
    h = {'content-type': 'application/json; charset=utf-8',
         'authorization': 'Bearer ' + TOK, 'appkey': APPKEY, 'appsecret': SECRET,
         'tr_id': tr, 'custtype': 'P'}
    for i in range(tries):
        try:
            r = requests.get(HOST + path, headers=h, params=params, timeout=15)
            if r.status_code == 200:
                j = r.json()
                if str(j.get('rt_cd', '0')) == '0':
                    return j
                print('   API', j.get('msg_cd'), str(j.get('msg1'))[:80])
            else:
                print('   HTTP', r.status_code, r.text[:120])
        except Exception as e:
            print('   예외', e)
        time.sleep(1.0 * (i + 1))
    return None


def num(x):
    try:
        return float(str(x).replace(',', ''))
    except (TypeError, ValueError):
        return None


def kr_quote(code):
    """국내 주식현재가 시세 FHKST01010100"""
    j = get('/uapi/domestic-stock/v1/quotations/inquire-price', 'FHKST01010100',
            {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': code})
    o = (j or {}).get('output') or {}
    p = num(o.get('stck_prpr'))
    if not p or p <= 0:
        return None
    chg = num(o.get('prdy_vrss')) or 0.0
    pct = num(o.get('prdy_ctrt')) or 0.0
    # 부호: 1 상한 · 2 상승 · 3 보합 · 4 하한 · 5 하락  → 값 부호를 여기에 맞춘다
    sign = str(o.get('prdy_vrss_sign', ''))
    if sign in ('4', '5'):
        chg, pct = -abs(chg), -abs(pct)
    elif sign in ('1', '2'):
        chg, pct = abs(chg), abs(pct)
    elif sign == '3':
        chg, pct = 0.0, 0.0
    as_int = lambda v: int(v) if float(v).is_integer() else v
    return {'p': as_int(p), 'chg': as_int(chg), 'pct': round(pct, 2)}


def session_of(now):
    if now.weekday() >= 5:
        return 'closed'
    hm = now.hour * 100 + now.minute
    return 'open' if 900 <= hm < 1530 else 'closed'


def main():
    now = datetime.datetime.now(KST)
    quotes = {}
    for c in T['KR']:
        q = kr_quote(c)
        if q:
            quotes[c] = q
        time.sleep(0.07)          # 초당 호출 한도(실전 20건) 안쪽
    print('현재가 %d/%d 종목' % (len(quotes), len(T['KR'])))
    if not quotes:
        print('받은 시세가 없습니다 — 파일을 바꾸지 않습니다.'); sys.exit(1)

    sess = session_of(now)
    # 값이 그대로면(휴장·장 마감 후 반복 실행) 커밋을 만들지 않도록 파일을 건드리지 않는다
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding='utf-8'))
            if old.get('quotes') == quotes and old.get('session') == sess:
                print('시세·세션 변화 없음 — 파일 유지'); return
        except Exception:
            pass

    doc = {
        'market': 'KR',
        'asof': now.strftime('%Y-%m-%d %H:%M'),
        'asofISO': now.replace(second=0, microsecond=0).isoformat(),
        'session': sess,
        'source': 'KIS',
        'count': len(quotes),
        'quotes': quotes,
    }
    with open(OUT, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(',', ':'))
    print('저장', OUT, doc['asof'], sess)


if __name__ == '__main__':
    main()
