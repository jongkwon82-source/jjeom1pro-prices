# -*- coding: utf-8 -*-
"""
fetch_prices.py — KIS OpenAPI 로 일봉을 받아 data/*.csv 에 누적한다.
GitHub Actions 에서도, 윈도우에서도 똑같이 돈다.

환경변수: KIS_APPKEY, KIS_APPSECRET, KIS_MODE(real|vts, 기본 real)
인자    : python fetch_prices.py [조회시작일 YYYYMMDD]  (기본: 최근 25일)
출력    : data/kis_daily_KR.csv, data/kis_daily_US.csv   (code,date,close)
          기존 파일이 있으면 같은 날짜는 덮어쓰고 새 날짜만 추가한다.
"""
import os, sys, csv, json, time, datetime
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, 'data'); os.makedirs(DATA, exist_ok=True)
T = json.load(open(os.path.join(HERE, 'tickers.json'), encoding='utf-8'))

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
            r = requests.get(HOST + path, headers=h, params=params, timeout=25)
            if r.status_code == 200:
                j = r.json()
                if str(j.get('rt_cd', '0')) == '0':
                    return j
                print('   API', j.get('msg_cd'), str(j.get('msg1'))[:80]); return None
            print('   HTTP', r.status_code, r.text[:120])
        except Exception as e:
            print('   예외', e)
        time.sleep(1.5 * (i + 1))
    return None

def kr_daily(code, start, end):
    """국내 기간별시세 FHKST03010100 · 요청당 최대 100건"""
    rows, cur = {}, end
    while cur >= start:
        s = max(start, (datetime.datetime.strptime(cur, '%Y%m%d')
                        - datetime.timedelta(days=140)).strftime('%Y%m%d'))
        j = get('/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice',
                'FHKST03010100',
                {'FID_COND_MRKT_DIV_CODE': 'J', 'FID_INPUT_ISCD': code,
                 'FID_INPUT_DATE_1': s, 'FID_INPUT_DATE_2': cur,
                 'FID_PERIOD_DIV_CODE': 'D', 'FID_ORG_ADJ_PRC': '0'})
        out = [o for o in ((j or {}).get('output2') or []) if o.get('stck_bsop_date')]
        if not out: break
        for o in out: rows[o['stck_bsop_date']] = float(o['stck_clpr'])
        oldest = min(o['stck_bsop_date'] for o in out)
        if oldest <= start: break
        cur = (datetime.datetime.strptime(oldest, '%Y%m%d')
               - datetime.timedelta(days=1)).strftime('%Y%m%d')
        time.sleep(0.12)
    return rows

def us_daily(sym, start, end):
    """해외 기간별시세 HHDFS76240000 · GUBN 0=일 · 요청당 최대 100건"""
    rows, cur = {}, end
    first = T['US_EXCD'].get(sym, 'NAS')
    cand = [first] + [x for x in ('NAS', 'NYS', 'AMS') if x != first]
    excd = None
    while cur >= start:
        got = None
        for e in ([excd] if excd else cand):
            j = get('/uapi/overseas-price/v1/quotations/dailyprice', 'HHDFS76240000',
                    {'AUTH': '', 'EXCD': e, 'SYMB': sym, 'GUBN': '0',
                     'BYMD': cur, 'MODP': '1'})
            out = [o for o in ((j or {}).get('output2') or []) if o.get('xymd')]
            if out: got, excd = out, e; break
        if not got: break
        for o in got: rows[o['xymd']] = float(o['clos'])
        oldest = min(o['xymd'] for o in got)
        if oldest <= start: break
        cur = (datetime.datetime.strptime(oldest, '%Y%m%d')
               - datetime.timedelta(days=1)).strftime('%Y%m%d')
        time.sleep(0.12)
    return rows

def load_csv(p):
    m = {}
    if os.path.exists(p):
        with open(p, encoding='utf-8-sig', newline='') as fh:
            for r in csv.DictReader(fh):
                try: m.setdefault(r['code'], {})[r['date']] = float(r['close'])
                except (KeyError, ValueError): pass
    return m

def save_csv(p, m):
    with open(p, 'w', newline='', encoding='utf-8') as fh:
        w = csv.writer(fh); w.writerow(['code', 'date', 'close'])
        for c in sorted(m):
            for d in sorted(m[c]):
                v = m[c][d]
                w.writerow([c, d, int(v) if float(v).is_integer() else v])

def ymd(d): return d[:4] + '-' + d[4:6] + '-' + d[6:]

def main():
    end = datetime.date.today().strftime('%Y%m%d')
    start = sys.argv[1] if len(sys.argv) > 1 else \
        (datetime.date.today() - datetime.timedelta(days=25)).strftime('%Y%m%d')
    print('조회 기간', start, '~', end)
    total_new = 0
    for name, codes, fn in (('KR', T['KR'], kr_daily), ('US', T['US'], us_daily)):
        path = os.path.join(DATA, 'kis_daily_%s.csv' % name)
        m = load_csv(path); before = sum(len(v) for v in m.values()); ok = 0
        for c in codes:
            r = fn(c, start, end)
            if r: ok += 1
            for d, v in r.items(): m.setdefault(c, {})[ymd(d)] = v
        save_csv(path, m)
        after = sum(len(v) for v in m.values())
        print('%s: 종목 %d/%d · 행 %d → %d (+%d)' % (name, ok, len(codes), before, after, after - before))
        total_new += after - before
    print('새로 추가된 행 합계:', total_new)

if __name__ == '__main__':
    main()
