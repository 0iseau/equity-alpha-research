"""Streaming, fail-closed CRSP audit. No strategy performance or alpha selection.

Python standard library only. Outputs are published only after a complete run.
Historical membership is effective-dated, not a claim of archived vendor vintages.
"""
from __future__ import annotations

import argparse
import bisect
import calendar
from collections import Counter, defaultdict
import csv
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
FIELDS = ('PERMNO','YYYYMM','MthCalDt','MthPrc','MthPrcDt','MthCap',
          'MthRet','MthRetx','MthRetFlg','MthDelFlg','MthCompFlg','MthPrevDtFlg')


def number(value):
    if value in ('', '.', None):
        return None
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f'Nonfinite numeric value: {value!r}')
    return result


def month_end(ym):
    y, m = divmod(int(ym), 100)
    return date(y, m, calendar.monthrange(y, m)[1]).isoformat()


def shift(ym, n):
    y, m = divmod(int(ym), 100)
    y, m = divmod(y * 12 + m - 1 + n, 12)
    return y * 100 + m + 1


def rows(path, required):
    with path.open(encoding='utf-8-sig', newline='') as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        if len(set(headers)) != len(headers) or not set(required) <= set(headers):
            raise ValueError(f'{path.name}: missing/duplicate headers')
        for line, row in enumerate(reader, 2):
            if None in row or any(v is None for v in row.values()):
                raise ValueError(f'{path.name}:{line}: malformed CSV row')
            yield row


def fingerprint(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return {'bytes': path.stat().st_size, 'sha256': h.hexdigest()}


class History:
    FIELDS = ('permno','secinfostartdt','secinfoenddt','securitytype',
              'securitysubtype','sharetype','usincflg','primaryexch',
              'securityactiveflg','tradingstatusflg')

    def __init__(self, records):
        self.records = defaultdict(list)
        for r in records:
            start = date.fromisoformat(r['secinfostartdt']).isoformat()
            end = date.fromisoformat(r['secinfoenddt']).isoformat()
            if start > end:
                raise ValueError('Reversed security-history interval')
            record = (start, end, *(r[k] for k in self.FIELDS[3:]))
            self.records[int(r['permno'])].append(record)
        self.starts = {}
        for p, items in self.records.items():
            items[:] = sorted(set(items))
            for a, b in zip(items, items[1:]):
                if a[1] >= b[0]:
                    raise ValueError(f'Ambiguous overlapping history for PERMNO {p}')
            self.starts[p] = [r[0] for r in items]

    def at(self, permno, when):
        idx = bisect.bisect_right(self.starts.get(permno, []), when) - 1
        if idx < 0:
            return None
        r = self.records[permno][idx]
        return r if when <= r[1] else None

    def reason(self, permno, when, cap):
        r = self.at(permno, when)
        if r is None:
            return 'no_effective_history'
        _, _, typ, sub, share, us, exch, active, trading = r
        if (typ, sub, share) != ('EQTY', 'COM', 'NS'):
            return 'not_common_ordinary_equity'
        if us != 'Y':
            return 'not_us_incorporated'
        if exch not in ('N', 'A', 'Q'):
            return 'outside_selected_exchanges'
        if active != 'Y' or trading != 'A':
            return 'not_active_at_cutoff'
        if cap is None or cap <= 0:
            return 'missing_or_nonpositive_cap'
        return 'eligible'


def canonical(r):
    p, ym = int(r['PERMNO']), int(r['YYYYMM'])
    calendar_date = date.fromisoformat(r['MthCalDt'])
    month_end(ym)  # validate period key; CRSP can label the last trading day
    if p <= 0 or calendar_date.year * 100 + calendar_date.month != ym:
        raise ValueError(f'Invalid security/month: {p}, {ym}')
    prc, cap, ret, retx = (number(r[k]) for k in ('MthPrc','MthCap','MthRet','MthRetx'))
    if cap is not None and cap < 0:
        raise ValueError(f'Negative capitalization: {p}, {ym}')
    if any(v is not None and v < -1 for v in (ret, retx)):
        raise ValueError(f'Return below -100%: {p}, {ym}')
    if r['MthDelFlg'] not in ('N','A','P','M','G','V'):
        raise ValueError(f'Unrecognized delisting flag: {r["MthDelFlg"]!r}')
    price_date = r['MthPrcDt']
    if price_date:
        date.fromisoformat(price_date)
        if price_date > r['MthCalDt']:
            raise ValueError('Future price date')
    return (p, ym, r['MthCalDt'], prc, price_date, cap, ret, retx,
            r['MthRetFlg'], r['MthDelFlg'], r['MthCompFlg'], r['MthPrevDtFlg'])


def unique_months(records, counts):
    previous = None
    for r in records:
        counts['raw_rows'] += 1
        current = canonical(r)
        if previous is not None:
            if current[:2] < previous[:2]:
                raise ValueError('Input must be sorted by PERMNO, YYYYMM; no silent reordering')
            if current[:2] == previous[:2]:
                if current != previous:
                    raise ValueError(f'Conflicting stock-month values: {current[:2]}')
                counts['identical_stock_projection_repeats'] += 1
                continue
            yield previous
        previous = current
    if previous is not None:
        yield previous


def decision(db, history, execution_month, use_momentum=False):
    """Target weights set from previous month; execution/tradability is a later gate.

    Eleven complete calendar returns end one month before execution. No future
    return presence, delisting flag, or security end date enters these decisions.
    """
    cutoff = shift(execution_month, -1)
    candidates = []
    for p, cap in db.execute('SELECT permno,cap FROM monthly WHERE ym=? ORDER BY permno', (cutoff,)):
        if history.reason(p, month_end(cutoff), cap) != 'eligible':
            continue
        signal = None
        if use_momentum:
            obs = db.execute('SELECT ym,ret,retflag FROM monthly WHERE permno=? AND ym BETWEEN ? AND ? ORDER BY ym',
                             (p, shift(cutoff, -10), cutoff)).fetchall()
            expected = [shift(cutoff, i) for i in range(-10, 1)]
            if [r[0] for r in obs] != expected or any(r[1] is None or r[2] != 'CR' for r in obs):
                continue
            signal = math.prod(1 + r[1] for r in obs) - 1
        candidates.append((p, cap, signal))
    if use_momentum and candidates:
        candidates = sorted(candidates, key=lambda x: (-x[2], x[0]))[:max(1, math.ceil(len(candidates)/5))]
    total = math.fsum(r[1] for r in candidates)
    return [{'permno': p, 'cap': cap, 'signal': signal, 'weight': cap / total,
             'information_cutoff': month_end(cutoff), 'execution_month': execution_month,
             'payoff_month': shift(execution_month, 1)} for p, cap, signal in sorted(candidates)]


def check_timing(available, decision_time, execution, payoff_start, label_end=None, fit_time=None):
    times = [datetime.fromisoformat(x) for x in (available, decision_time, execution, payoff_start)]
    if not times[0] < times[1] <= times[2] <= times[3]:
        raise ValueError('Information/decision/execution/payoff order violated')
    if label_end is not None:
        if fit_time is None or datetime.fromisoformat(label_end) >= datetime.fromisoformat(fit_time):
            raise ValueError('Unmatured training label')


def account_return(weights, returns):
    """Never drop a held name or renormalize around its missing return."""
    if not weights or any(not math.isfinite(w) or w < 0 for w in weights.values()):
        raise ValueError('Invalid holdings')
    if not math.isclose(math.fsum(weights.values()), 1, abs_tol=1e-10):
        raise ValueError('Holdings must sum to one')
    for p, w in weights.items():
        if w and (p not in returns or returns[p] is None or not math.isfinite(returns[p]) or returns[p] < -1):
            raise ValueError(f'Unresolved payoff for held PERMNO {p}')
    return math.fsum(w * returns[p] for p, w in weights.items() if w)


def run(raw, output):
    if output.exists():
        raise FileExistsError(f'Refusing to overwrite {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = output.with_name(output.name + '.incomplete-' + uuid.uuid4().hex[:8])
    stage.mkdir()
    names = ['crsp_ciz_monthly_stock.csv', 'crsp_ciz_security_history.csv', 'crsp_ciz_delistings.csv',
             'ccm_fundamentals_annual.csv', 'ccm_link_history.csv']
    initial = {n: (raw/n).stat() for n in names}
    db = None
    try:
        history = History(rows(raw/names[1], History.FIELDS))
        print('Security intervals validated; streaming monthly records.', flush=True)
        db = sqlite3.connect(stage/'market.sqlite')
        db.execute('CREATE TABLE monthly(permno INTEGER, ym INTEGER, caldt TEXT, price REAL, pricedate TEXT, cap REAL, ret REAL, retx REAL, retflag TEXT, delflag TEXT, complete TEXT, prevflag TEXT, PRIMARY KEY(permno,ym)) WITHOUT ROWID')
        counts, flags, exclusions = Counter(), Counter(), Counter()
        batch = []
        for r in unique_months(rows(raw/names[0], FIELDS), counts):
            counts['unique_stock_months'] += 1
            flags[(r[9], r[8])] += 1
            exclusions[(r[1], history.reason(r[0], month_end(r[1]), r[5]))] += 1
            counts['missing_returns'] += r[6] is None
            batch.append(r)
            if len(batch) == 20000:
                db.executemany('INSERT INTO monthly VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', batch)
                db.commit()
                batch.clear()
            if counts['unique_stock_months'] % 500000 == 0:
                print(f'{counts["unique_stock_months"]:,} unique stock-months audited', flush=True)
        db.executemany('INSERT INTO monthly VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', batch)
        db.execute('CREATE INDEX monthly_date ON monthly(ym)')
        db.commit()
        coverage = db.execute('SELECT MIN(ym),MAX(ym),COUNT(DISTINCT permno) FROM monthly').fetchone()
        if coverage[0] is None:
            raise ValueError('Empty monthly data')
        with (stage/'universe_counts.csv').open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f); w.writerow(['month','first_exclusion_reason','count'])
            w.writerows((ym, reason, n) for (ym, reason), n in sorted(exclusions.items()))
        event_counts = Counter()
        with (stage/'delisting_audit.csv').open('w', newline='', encoding='utf-8') as f:
            w = csv.writer(f)
            w.writerow(['permno','event_date','action','delret','payment_date','event_month','monthly_return','monthly_delisting_flag','next_month_flag','status'])
            for event in rows(raw/names[2], ('permno','delistingdt','delret','delactiontype','delamtdt')):
                p, dt = int(event['permno']), date.fromisoformat(event['delistingdt'])
                ym = dt.year*100+dt.month
                found = db.execute('SELECT ret,delflag FROM monthly WHERE permno=? AND ym=?', (p,ym)).fetchone()
                nxt = db.execute('SELECT delflag FROM monthly WHERE permno=? AND ym=?', (p,shift(ym,1))).fetchone()
                status = ('outside_monthly_coverage' if ym < coverage[0] or ym > coverage[1] else
                          'no_event_month_row' if found is None else
                          'missing_monthly_return' if found[0] is None else
                          'embedded_do_not_add_delret' if found[1] in ('A','P') else
                          'unresolved_terminal_payoff')
                event_counts[status] += 1
                w.writerow([p,dt.isoformat(),event['delactiontype'],event['delret'],event['delamtdt'],ym,
                            found[0] if found else '',found[1] if found else '',nxt[0] if nxt else '',status])
        examples = {}
        for ym in (198704, 200612):
            if coverage[0] <= shift(ym,-1) <= coverage[1]:
                examples[str(ym)] = {name: decision(db,history,ym,momentum) for name,momentum in [('reference',False),('momentum',True)]}
        (stage/'decision_examples.json').write_text(json.dumps(examples,indent=2,allow_nan=False),encoding='utf-8')
        # A real historical failure path, for independent manual reconciliation.
        trace = db.execute('SELECT * FROM monthly WHERE permno=10000 ORDER BY ym').fetchall()
        (stage/'permno_10000_trace.json').write_text(json.dumps(trace,indent=2,allow_nan=False),encoding='utf-8')
        fingerprints = {n: fingerprint(raw/n) for n in names}
        for n in names:
            now = (raw/n).stat()
            if (now.st_size, now.st_mtime_ns) != (initial[n].st_size, initial[n].st_mtime_ns):
                raise ValueError(f'Input changed during audit: {n}')
        report = {'status':'AUDIT_COMPLETE_RESEARCH_GATES_OPEN', 'created_utc':datetime.now(timezone.utc).isoformat(),
                  'code_sha256':fingerprint(Path(__file__))['sha256'], 'python':sys.version,
                  'inputs':fingerprints,'counts':dict(counts),'coverage':coverage,
                  'return_flags':{f'{d}/{r}':n for (d,r),n in sorted(flags.items())},
                  'delistings':dict(event_counts),
                  'gates':['Slides cover multiple factor models; evaluation specification and factor files remain to be finalized',
                           'Missing terminal payoffs and execution/cash timing require resolution',
                           'Fundamentals have no demonstrated point-in-time vintage/release fields',
                           'Final holdout boundaries must be recorded before performance exploration',
                           'Historical effective dates do not prove original vendor availability'],
                  'performance_evaluated':False}
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite integrity check failed')
        db.close(); db = None
        (stage/'audit.json').write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
        stage.rename(output)
        print(json.dumps(report,indent=2),flush=True)
        return report
    except BaseException as exc:
        if db is not None:
            db.close()
        (stage/'FAILED.txt').write_text(f'{type(exc).__name__}: {exc}',encoding='utf-8')
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw',type=Path,default=ROOT/'data/raw')
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    run(args.raw,args.output)
