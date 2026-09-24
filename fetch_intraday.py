# -*- coding: utf-8 -*-
"""
fetch_intraday.py — KIS OpenAPI 로 국내 종목 현재가를 받아 data/intraday_KR.json 에 쓴다.
GitHub Actions 가 평일 09:00~20:15 KST 에 10분마다 돌린다.

· 개장일에만 동작한다. 휴장일(명절·공휴일)이면 KIS 를 한 번만 확인하고 아무것도 쓰지 않는다.
· 09:00~15:30  정규장        session=open,   phase=regular
  15:30~20:00  애프터마켓     session=open,   phase=after   (넥스트레이드 포함 통합시세)
  20:00 이후   마감           session=closed, phase=closed  (그날 마지막 값으로 한 번 기록)

환경변수: KIS_APPKEY, KIS_APPSECRET, KIS_MODE(real|vts, 기본 real)
출력    : data/intraday_KR.json
  {
    "market": "KR", "asof": "2026-09-29 11:10", "asofISO": "2026-09-29T11:10:00+09:00",
    "session": "open" | "closed", "phase": "regular" | "after" | "closed",
    "tradeDate": "2026-09-29", "source": "KIS", "count": 27,
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

OPEN_HM, REG_CLOSE_HM, AFTER_CLOSE_HM = 900, 1530, 2000   # 09:00 · 15:30 · 20:00

APPKEY = os.environ.get('KIS_APPKEY', '').strip()
SECRET = os.environ.get('KIS_APPSECRET', '').strip()
if not APPKEY or not SECRET:
    print('KIS_APPKEY / KIS_APPSECRET 환경변수가 없습니다.'); sys.exit(2)
HOST = {'real': 'https://openapi.koreainvestment.com:9443',
        'vts':  'https://openapivts.koreainvestment.com:29443'}[os.environ.get('KIS_MODE', 'real')]


def now_kst():
    t = os.environ.get('INTRADAY_NOW')          # 시험용: "2026-09-29 16:10"
    if t:
        return datetime.datetime.strptime(t, '%Y-%m-%d %H:%M').replace(tzinfo=KST)
    return datetime.datetime.now(KST)


def token():
    r = requests.post(HOST + '/oauth2/tokenP',
                      json={'grant_type': 'client_credentials',
                            'appkey': APPKEY, 'appsecret': SECRET}, timeout=20)
    if r.status_code != 200:
        print('토큰 발급 실패', r.status_code, r.text[:300]); sys.exit(1)
    return r.json()['access_token']


TOK = None


def get(path, tr, params, tries=3, quiet=False):
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
                if not quiet:
                    print('   API', j.get('msg_cd'), str(j.get('msg1'))[:80])
                return None
            if not quiet:
                print('   HTTP', r.status_code, r.text[:120])
        except Exception as e:
            if not quiet:
                print('   예외', e)
        time.sleep(1.0 * (i + 1))
    return None


def num(x):
    try:
        return float(str(x).replace(',', ''))
    except (TypeError, ValueError):
        return None


def last_trade_date(code='069500'):
    """국내 일자별시세 FHKST01010400 — 가장 최근 거래일(YYYYMMDD). 개장일 장중에는 오늘 날짜가 나온다."""
    j = get('/uapi/domestic-stock/v1/quotations/inquire-daily-price', 'FHKST01010400',
            {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': code,
             'FID_PERIOD_DIV_CODE': 'D', 'FID_ORG_ADJ_PRC': '0'})
    ds = [o.get('stck_bsop_date') for o in ((j or {}).get('output') or []) if o.get('stck_bsop_date')]
    return max(ds) if ds else None


def kr_quote(code, market):
    """국내 주식현재가 시세 FHKST01010100.
    market: 'J'=KRX, 'UN'=KRX+넥스트레이드 통합. 통합이 안 되는 종목(ETF 등)은 KRX 로 다시 받는다."""
    o = {}
    for mk in ([market, 'J'] if market != 'J' else ['J']):
        j = get('/uapi/domestic-stock/v1/quotations/inquire-price', 'FHKST01010100',
                {'FID_COND_MRKT_DIV_CODE': mk, 'FID_INPUT_ISCD': code}, quiet=(mk != 'J'))
        o = (j or {}).get('output') or {}
        if num(o.get('stck_prpr')):
            break
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


def phase_of(now):
    hm = now.hour * 100 + now.minute
    if hm < OPEN_HM:
        return None                      # 개장 전 — 쓰지 않는다
    if hm < REG_CLOSE_HM:
        return 'regular'
    if hm < AFTER_CLOSE_HM:
        return 'after'
    return 'closed'


def main():
    global TOK
    now = now_kst()
    today = now.strftime('%Y%m%d')
    if now.weekday() >= 5:
        print('주말 — 건너뜀'); return
    phase = phase_of(now)
    if phase is None:
        print('개장 전(%s) — 건너뜀' % now.strftime('%H:%M')); return

    TOK = token(); print('토큰 발급 OK')
    td = last_trade_date()
    print('최근 거래일', td)
    if td is None:
        print('거래일 확인 실패 — 이번 회차는 건너뜀'); sys.exit(1)
    if td != today:
        print('오늘(%s)은 휴장일 — 아무것도 쓰지 않음' % today); return

    # 마감(20시 이후) 기록은 하루 한 번만
    old = None
    if os.path.exists(OUT):
        try:
            old = json.load(open(OUT, encoding='utf-8'))
        except Exception:
            old = None
    if phase == 'closed' and old and old.get('session') == 'closed' \
            and old.get('tradeDate') == now.strftime('%Y-%m-%d'):
        print('오늘 마감 기록이 이미 있음 — 건너뜀'); return

    market = 'J' if phase == 'regular' else 'UN'    # 15:30 이후는 넥스트레이드 가격까지
    quotes = {}
    for c in T['KR']:
        q = kr_quote(c, market)
        if q:
            quotes[c] = q
        time.sleep(0.07)          # 초당 호출 한도(실전 20건) 안쪽
    print('현재가 %d/%d 종목 (%s)' % (len(quotes), len(T['KR']), market))
    if not quotes:
        print('받은 시세가 없습니다 — 파일을 바꾸지 않습니다.'); sys.exit(1)

    sess = 'closed' if phase == 'closed' else 'open'
    doc = {
        'market': 'KR',
        'asof': now.strftime('%Y-%m-%d %H:%M'),
        'asofISO': now.replace(second=0, microsecond=0).isoformat(),
        'session': sess,
        'phase': phase,
        'tradeDate': now.strftime('%Y-%m-%d'),
        'source': 'KIS' if market == 'J' else 'KIS (KRX+NXT 통합)',
        'count': len(quotes),
        'quotes': quotes,
    }
    with open(OUT, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(',', ':'))
    print('저장', OUT, doc['asof'], sess, phase)


if __name__ == '__main__':
    main()
