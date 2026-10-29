"""Independent checks on completed audit outputs, using a read-only database."""
import argparse
import csv
import json
import math
from pathlib import Path
import sqlite3

from audit_market_data import ROOT, History, rows, decision, shift, month_end, fingerprint


def verify(folder, raw):
    summary = json.loads((folder/'audit.json').read_text(encoding='utf-8'))
    for name, expected in summary['inputs'].items():
        if fingerprint(raw/name) != expected:
            raise ValueError(f'Input changed since audit: {name}')
    h = History(rows(raw/'crsp_ciz_security_history.csv',History.FIELDS))
    db = sqlite3.connect((folder/'market.sqlite').resolve().as_uri()+'?mode=ro',uri=True)
    results = []
    try:
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Database integrity failure')
        count = db.execute('SELECT COUNT(*) FROM monthly').fetchone()[0]
        if count != summary['counts']['unique_stock_months']:
            raise ValueError('Database count mismatch')
        with (folder/'universe_counts.csv').open(newline='',encoding='utf-8') as f:
            if sum(int(r['count']) for r in csv.DictReader(f)) != count:
                raise ValueError('Exclusion counts do not reconcile')
        for execution in (198704,200512):
            cutoff = shift(execution,-1)
            # Reconstruct a history source that ends at cutoff. No eventual end
            # dates or later history intervals remain visible to the algorithm.
            trimmed = []
            for p, records in h.records.items():
                for r in records:
                    if r[0] <= month_end(cutoff):
                        values = [str(p),r[0],min(r[1],month_end(cutoff)),*r[2:]]
                        trimmed.append(dict(zip(History.FIELDS,values)))
            hpast = History(trimmed)
            full = {k:decision(db,h,execution,k) for k in (False,True)}
            db.execute(f'CREATE TEMP VIEW monthly AS SELECT * FROM main.monthly WHERE ym <= {int(cutoff)}')
            past = {k:decision(db,hpast,execution,k) for k in (False,True)}
            db.execute('DROP VIEW temp.monthly')
            if full != past:
                raise ValueError(f'Future data changed historical decisions: {execution}')
            for k, holdings in full.items():
                if not holdings or not math.isclose(math.fsum(r['weight'] for r in holdings),1,abs_tol=1e-12):
                    raise ValueError('Empty or unnormalized decision')
            results.append({'execution_month':execution,'future_removal':'PASS',
                            'reference_holdings':len(full[False]),'momentum_holdings':len(full[True])})
        # Trace the first identifier in the supplied file without selecting it on performance.
        before_cap = db.execute('SELECT cap FROM monthly WHERE permno=10000 AND ym=198703').fetchone()[0]
        after_cap = db.execute('SELECT cap FROM monthly WHERE permno=10000 AND ym=198706').fetchone()[0]
        before = h.reason(10000,'1987-03-31',before_cap)
        after = h.reason(10000,'1987-06-30',after_cap)
        terminal = db.execute('SELECT ym,ret,delflag,pricedate FROM monthly WHERE permno=10000 AND ym=198706').fetchone()
        if before != 'eligible' or after == 'eligible' or terminal is None or terminal[2] != 'P':
            raise ValueError('PERMNO 10000 event trace differs from reviewed evidence')
        outcome = {'checks':results,'counts_reconcile':True,'database_integrity':'ok',
                   'trace':{'permno':10000,'before':before,'after':after,'terminal_row_retained':terminal},
                   'audit_manifest_sha256':fingerprint(folder/'audit.json')['sha256'],
                   'verification_code_sha256':fingerprint(Path(__file__))['sha256'],
                   'decision_code_sha256':fingerprint(ROOT/'src/audit_market_data.py')['sha256']}
        path=folder/'verification.json'
        with path.open('x',encoding='utf-8') as f: json.dump(outcome,f,indent=2,allow_nan=False)
        print(json.dumps(outcome,indent=2))
        return outcome
    finally:
        db.close()


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder',type=Path)
    parser.add_argument('--raw',type=Path,default=ROOT/'data/raw')
    args=parser.parse_args()
    verify(args.folder,args.raw)
