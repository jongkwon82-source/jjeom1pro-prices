# -*- coding: utf-8 -*-
"""
fetch_intraday.py — KIS OpenAPI 로 한국·미국 종목 현재가를 받아 data/ 에 쓴다.
GitHub Actions 가 10분마다 돌리고, 각 시장은 자기 개장 시간에만 스스로 동작한다.

 한국 (KST)  개장일 09:00~15:30 정규장(KRX) · 15:30~20:00 애프터(KRX+넥스트레이드 통합) · 20:00 이후 마감 1회
 미국 (뉴욕)  개장일 09:30~16:00 정규장 (조기폐장일 13:00) · 폐장 후 마감 1회
              서머타임은 뉴욕 시간대로 자동 처리 (한국시간 22:30~05:00 / 겨울 23:30~06:00)
 휴장일·주말·개장 전에는 KIS 를 부르지 않거나(미국) 한 번만 확인하고(한국) 아무것도 쓰지 않는다.

출력
  data/intraday_KR.json · data/intraday_US.json   시장별 원본
  data/intraday.json                               두 시장을 합친 것 — 아티팩트가 읽는 형식
    { "market":"KR+US", "asof":"2026-09-29 23:40", "session":"open", "phase":"regular",
      "updatedAt":"...ISO...", "source":"KIS", "count":40,
      "markets": { "KR": {asof, session, phase, tradeDate, closeAt, ...}, "US": {...} },
      "quotes":  { "005930": {"p":285000,"chg":1500,"pct":0.53,"m":"KR","o":false,"t":"2026-09-29 20:05"},
                   "NVDA":   {"p":187.2,"chg":-1.3,"pct":-0.69,"m":"US","o":true,"t":"2026-09-29 23:40"} } }
    p=현재가, chg=전일대비(부호 포함), pct=등락률%, m=시장, o=지금 장중인지, t=그 시장 기준시각(KST)

환경변수: KIS_APPKEY, KIS_APPSECRET, KIS_MODE(real|vts, 기본 real)
일봉 CSV(kis_daily_*.csv)는 건드리지 않는다.
"""
import os, sys, json, time, datetime
from zoneinfo import ZoneInfo
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data'); os.makedirs(DATA, exist_ok=True)
T = json.load(open(os.path.join(HERE, 'tickers.json'), encoding='utf-8'))
KST = ZoneInfo('Asia/Seoul')
NY = ZoneInfo('America/New_York')

# 뉴욕증시(NYSE·나스닥) 휴장일 / 조기폐장일(13:00) — 해마다 12월에 다음 해 것을 추가하세요
US_HOLIDAYS = {
    '2026-01-01', '2026-01-19', '2026-02-16', '2026-04-03', '2026-05-25', '2026-06-19',
    '2026-07-03', '2026-09-07', '2026-11-26', '2026-12-25',
    '2027-01-01', '2027-01-18', '2027-02-15', '2027-03-26', '2027-05-31', '2027-06-18',
    '2027-07-05', '2027-09-06', '2027-11-25', '2027-12-24',
}
US_EARLY_CLOSE = {'2026-11-27', '2026-12-24', '2027-11-26'}

APPKEY = os.environ.get('KIS_APPKEY', '').strip()
SECRET = os.environ.get('KIS_APPSECRET', '').strip()
if not APPKEY or not SECRET:
    print('KIS_APPKEY / KIS_APPSECRET 환경변수가 없습니다.'); sys.exit(2)
HOST = {'real': 'https://openapi.koreainvestment.com:9443',
        'vts':  'https://openapivts.koreainvestment.com:29443'}[os.environ.get('KIS_MODE', 'real')]


def now_utc():
    t = os.environ.get('INTRADAY_NOW')          # 시험용: "2026-09-29 16:10" (한국시간)
    if t:
        return datetime.datetime.strptime(t, '%Y-%m-%d %H:%M').replace(tzinfo=KST).astimezone(datetime.timezone.utc)
    return datetime.datetime.now(datetime.timezone.utc)


# ───────────── KIS 공통 ─────────────
_TOK = None


def token():
    """토큰 발급(한 번 받으면 재사용). KIS 는 1분에 한 번만 내주므로 걸리면 65초 기다렸다 다시 받는다."""
    global _TOK
    if _TOK:
        return _TOK
    for i in range(3):
        try:
            r = requests.post(HOST + '/oauth2/tokenP',
                              json={'grant_type': 'client_credentials',
                                    'appkey': APPKEY, 'appsecret': SECRET}, timeout=20)
            if r.status_code == 200 and r.json().get('access_token'):
                _TOK = r.json()['access_token']; print('토큰 발급 OK')
                return _TOK
            print('토큰 발급 실패 (%d/3)' % (i + 1), r.status_code, r.text[:300])
        except Exception as e:
            print('토큰 발급 예외 (%d/3)' % (i + 1), e)
        if i < 2:
            print('   65초 기다렸다 다시 시도합니다')
            time.sleep(65)
    sys.exit(1)


def get(path, tr, params, tries=3, quiet=False):
    h = {'content-type': 'application/json; charset=utf-8',
         'authorization': 'Bearer ' + token(), 'appkey': APPKEY, 'appsecret': SECRET,
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


def as_num(v, nd=4):
    v = round(float(v), nd)
    return int(v) if v.is_integer() else v


def load(path):
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return None


def save(path, doc):
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(doc, fh, ensure_ascii=False, separators=(',', ':'))


def already_closed(path, trade_date):
    old = load(path)
    return bool(old and old.get('session') == 'closed' and old.get('tradeDate') == trade_date)


# ───────────── 한국 ─────────────
def kr_last_trade_date(today, code='005930'):
    """가장 최근 거래일(YYYYMMDD). 개장일 장중에는 오늘 날짜가 나온다.
    ① 기간별시세 FHKST03010100 (fetch_prices.py 가 매일 쓰는 검증된 API) ② 안 되면 일자별시세"""
    start = (datetime.datetime.strptime(today, '%Y%m%d') - datetime.timedelta(days=20)).strftime('%Y%m%d')
    j = get('/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice', 'FHKST03010100',
            {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': code,
             'FID_INPUT_DATE_1': start, 'FID_INPUT_DATE_2': today,
             'FID_PERIOD_DIV_CODE': 'D', 'FID_ORG_ADJ_PRC': '0'})
    ds = [o.get('stck_bsop_date') for o in ((j or {}).get('output2') or []) if o.get('stck_bsop_date')]
    if ds:
        return max(ds)
    print('   기간별시세로 거래일 확인 실패 — 일자별시세로 다시 시도')
    j = get('/uapi/domestic-stock/v1/quotations/inquire-daily-price', 'FHKST01010400',
            {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': code,
             'FID_PERIOD_DIV_CODE': 'D', 'FID_ORG_ADJ_PRC': '0'})
    ds = [o.get('stck_bsop_date') for o in ((j or {}).get('output') or []) if o.get('stck_bsop_date')]
    return max(ds) if ds else None


def kr_quote(code, market):
    """국내 현재가 FHKST01010100. market: 'J'=KRX, 'UN'=KRX+넥스트레이드 통합(안 되면 KRX 로)."""
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
    sign = str(o.get('prdy_vrss_sign', ''))      # 1 상한 · 2 상승 · 3 보합 · 4 하한 · 5 하락
    if sign in ('4', '5'):
        chg, pct = -abs(chg), -abs(pct)
    elif sign in ('1', '2'):
        chg, pct = abs(chg), abs(pct)
    elif sign == '3':
        chg, pct = 0.0, 0.0
    return {'p': as_num(p), 'chg': as_num(chg), 'pct': round(pct, 2)}


def run_kr(now):
    out = os.path.join(DATA, 'intraday_KR.json')
    k = now.astimezone(KST)
    hm = k.hour * 100 + k.minute
    if k.weekday() >= 5:
        print('[한국] 주말 — 건너뜀'); return False
    if hm < 900 or hm >= 2030:
        print('[한국] 운영시간 아님(%s KST) — 건너뜀' % k.strftime('%H:%M')); return False
    phase = 'regular' if hm < 1530 else ('after' if hm < 2000 else 'closed')
    today = k.strftime('%Y%m%d'); tday = k.strftime('%Y-%m-%d')
    if phase == 'closed' and already_closed(out, tday):
        print('[한국] 오늘 마감 기록이 이미 있음 — 건너뜀'); return False
    td = kr_last_trade_date(today)
    print('[한국] 최근 거래일', td)
    if td is None:
        print('[한국] 거래일 확인 실패 — 이번 회차는 건너뜀'); return False
    if td != today:
        print('[한국] 오늘(%s)은 휴장일 — 아무것도 쓰지 않음' % today); return False
    market = 'J' if phase == 'regular' else 'UN'
    quotes = {}
    for c in T['KR']:
        q = kr_quote(c, market)
        if q:
            quotes[c] = q
        time.sleep(0.07)
    print('[한국] 현재가 %d/%d 종목 (%s)' % (len(quotes), len(T['KR']), market))
    if not quotes:
        return False
    save(out, {
        'market': 'KR', 'asof': k.strftime('%Y-%m-%d %H:%M'),
        'asofISO': k.replace(second=0, microsecond=0).isoformat(),
        'session': 'closed' if phase == 'closed' else 'open', 'phase': phase,
        'tradeDate': tday,
        'closeAt': datetime.datetime(k.year, k.month, k.day, 20, 0, tzinfo=KST).isoformat(),
        'source': 'KIS' if market == 'J' else 'KIS (KRX+NXT 통합)',
        'count': len(quotes), 'quotes': quotes})
    print('[한국] 저장', k.strftime('%H:%M'), phase)
    return True


# ───────────── 미국 ─────────────
def us_quote(sym):
    """해외 현재체결가 HHDFS00000300. 거래소(NAS/NYS/AMS)는 tickers.json 의 US_EXCD 부터 차례로."""
    first = T.get('US_EXCD', {}).get(sym, 'NAS')
    for ex in [first] + [x for x in ('NAS', 'NYS', 'AMS') if x != first]:
        j = get('/uapi/overseas-price/v1/quotations/price', 'HHDFS00000300',
                {'AUTH': '', 'EXCD': ex, 'SYMB': sym}, quiet=True)
        o = (j or {}).get('output') or {}
        p = num(o.get('last'))
        if not p or p <= 0:
            continue
        base = num(o.get('base'))
        if base and base > 0:                       # 전일종가가 있으면 직접 계산(부호 혼동 없음)
            chg = p - base; pct = chg / base * 100
        else:
            chg = num(o.get('diff')) or 0.0; pct = num(o.get('rate')) or 0.0
            if str(o.get('sign', '')) in ('4', '5'):
                chg, pct = -abs(chg), -abs(pct)
        return {'p': as_num(p), 'chg': as_num(chg), 'pct': round(pct, 2)}
    return None


def run_us(now):
    out = os.path.join(DATA, 'intraday_US.json')
    e = now.astimezone(NY)
    tday = e.strftime('%Y-%m-%d')
    if e.weekday() >= 5:
        print('[미국] 주말 — 건너뜀'); return False
    if str(e.year) not in {d[:4] for d in US_HOLIDAYS}:
        print('[미국] 경고: %d년 휴장일 목록이 없습니다 — US_HOLIDAYS 에 추가하세요' % e.year)
    if tday in US_HOLIDAYS:
        print('[미국] 오늘(%s 뉴욕)은 휴장일 — 건너뜀' % tday); return False
    close_hm = 1300 if tday in US_EARLY_CLOSE else 1600
    hm = e.hour * 100 + e.minute
    if hm < 930 or hm >= close_hm + 30:
        print('[미국] 정규장 시간 아님(%s 뉴욕) — 건너뜀' % e.strftime('%H:%M')); return False
    phase = 'regular' if hm < close_hm else 'closed'
    if phase == 'closed' and already_closed(out, tday):
        print('[미국] 오늘 마감 기록이 이미 있음 — 건너뜀'); return False
    quotes = {}
    for s in T['US']:
        q = us_quote(s)
        if q:
            quotes[s] = q
        time.sleep(0.07)
    print('[미국] 현재가 %d/%d 종목' % (len(quotes), len(T['US'])))
    if not quotes:
        return False
    k = now.astimezone(KST)
    save(out, {
        'market': 'US', 'asof': k.strftime('%Y-%m-%d %H:%M'),          # 한국시간으로 표시
        'asofET': e.strftime('%Y-%m-%d %H:%M'),
        'asofISO': k.replace(second=0, microsecond=0).isoformat(),
        'session': 'closed' if phase == 'closed' else 'open', 'phase': phase,
        'tradeDate': tday,                                             # 뉴욕 날짜
        'closeAt': datetime.datetime(e.year, e.month, e.day, close_hm // 100, close_hm % 100,
                                     tzinfo=NY).isoformat(),
        'source': 'KIS', 'count': len(quotes), 'quotes': quotes})
    print('[미국] 저장', e.strftime('%H:%M 뉴욕'), phase)
    return True


# ───────────── 합치기 ─────────────
def build_combined(now):
    mk_docs = {}
    for mk in ('KR', 'US'):
        d = load(os.path.join(DATA, 'intraday_%s.json' % mk))
        if d and d.get('quotes'):
            mk_docs[mk] = d
    if not mk_docs:
        return
    quotes, markets = {}, {}
    for mk, d in mk_docs.items():
        is_open = d.get('session') == 'open'
        for c, q in d['quotes'].items():
            quotes[c] = dict(q, m=mk, o=is_open, t=d.get('asof'))
        markets[mk] = {k: d.get(k) for k in
                       ('asof', 'asofISO', 'asofET', 'session', 'phase', 'tradeDate', 'closeAt', 'source', 'count')
                       if d.get(k) is not None}
    opens = [mk for mk, m in markets.items() if m.get('session') == 'open']
    latest = max(markets.values(), key=lambda m: m.get('asofISO') or '')
    lead = markets[opens[0]] if opens else latest
    save(os.path.join(DATA, 'intraday.json'), {
        'market': '+'.join(markets), 'asof': lead.get('asof'),
        'session': 'open' if opens else 'closed',
        'phase': lead.get('phase') if opens else 'closed',
        'updatedAt': now.astimezone(KST).replace(microsecond=0).isoformat(),
        'source': 'KIS', 'count': len(quotes), 'markets': markets, 'quotes': quotes})
    print('합본 저장 data/intraday.json —', ', '.join('%s:%s' % (m, markets[m]['session']) for m in markets))


def main():
    now = now_utc()
    wrote = run_kr(now)
    wrote = run_us(now) or wrote
    if wrote:
        build_combined(now)


if __name__ == '__main__':
    main()
