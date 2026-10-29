import csv
from collections import Counter
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import audit_market_data as a


def stock(p=1, ym=198703, **kw):
    row = dict(zip(a.FIELDS, [str(p),str(ym),a.month_end(ym),'10',a.month_end(ym),
                             '100','0.1','0.1','CR','N','G','PE']))
    row.update(kw)
    return row


def hist(p=1, start='1980-01-01', end='1987-06-11', **kw):
    row = dict(zip(a.History.FIELDS, [str(p),start,end,'EQTY','COM','NS','Y','N','Y','A']))
    row.update(kw)
    return row


def database(records):
    db = sqlite3.connect(':memory:')
    db.execute('CREATE TABLE monthly(permno,ym,caldt,price,pricedate,cap,ret,retx,retflag,delflag,complete,prevflag)')
    db.executemany('INSERT INTO monthly VALUES(?,?,?,?,?,?,?,?,?,?,?,?)', [a.canonical(r) for r in records])
    return db


class AuditTests(unittest.TestCase):
    def test_missing_zero_and_nonfinite(self):
        self.assertIsNone(a.number(''))
        self.assertEqual(a.number('0'), 0)
        for value in ['nan','inf','-inf','bad']:
            with self.assertRaises(ValueError): a.number(value)

    def test_calendar_boundaries(self):
        self.assertEqual(a.shift(200001,-1),199912)
        self.assertEqual(a.month_end(200002),'2000-02-29')
        self.assertEqual(a.canonical(stock(ym=198605,MthCalDt='1986-05-30',MthPrcDt='1986-05-30'))[1],198605)
        with self.assertRaises(ValueError): a.canonical(stock(MthCalDt='1987-04-01'))

    def test_repeat_projection_and_conflict(self):
        counts = Counter()
        r = stock()
        self.assertEqual(len(list(a.unique_months([r,dict(r,DisDivAmt='999')],counts))),1)
        self.assertEqual(counts['identical_stock_projection_repeats'],1)
        with self.assertRaises(ValueError): list(a.unique_months([r,stock(MthRet='0.2')],Counter()))
        with self.assertRaises(ValueError): list(a.unique_months([stock(ym=198704),r],Counter()))

    def test_invalid_return_and_future_price(self):
        with self.assertRaises(ValueError): a.canonical(stock(MthRet='-1.1'))
        with self.assertRaises(ValueError): a.canonical(stock(MthPrcDt='1987-04-01'))
        self.assertEqual(a.canonical(stock(MthRet='-1'))[6],-1)

    def test_dead_firm_eligible_before_exit(self):
        h = a.History([hist(securityenddt='1987-06-11',hdrprimaryexch='Q')])
        self.assertEqual(h.reason(1,'1987-03-31',100),'eligible')
        self.assertEqual(h.reason(1,'1987-07-01',100),'no_effective_history')
        self.assertEqual(h.reason(1,'1987-03-31',None),'missing_or_nonpositive_cap')

    def test_history_ambiguity_fails(self):
        with self.assertRaises(ValueError): a.History([hist(),hist(start='1986-01-01')])
        self.assertEqual(len(a.History([hist(),hist()]).records[1]),1)

    def test_future_removal_does_not_change_decisions(self):
        past = [stock(p, a.shift(198703,n)) for p in (1,2) for n in range(-10,1)]
        future = [stock(1,198704,MthRet='-1',MthDelFlg='P')]
        h = a.History([hist(1),hist(2,end='2099-12-31')])
        db1,db2 = database(past),database(past+future)
        try:
            for momentum in (False,True):
                self.assertEqual(a.decision(db1,h,198704,momentum),a.decision(db2,h,198704,momentum))
            self.assertEqual({r['permno'] for r in a.decision(db2,h,198704)}, {1,2})
            self.assertAlmostEqual(sum(r['weight'] for r in a.decision(db1,h,198704)),1)
        finally: db1.close(); db2.close()

    def test_calendar_gaps_not_row_lags(self):
        db = database([stock(ym=a.shift(198703,n)) for n in range(-11,1) if n != -4])
        try: self.assertEqual(a.decision(db,a.History([hist()]),198704,True),[])
        finally: db.close()

    def test_partial_return_not_full_momentum_month(self):
        records = [stock(ym=a.shift(198703,n)) for n in range(-10,1)]
        records[0]['MthRetFlg'] = 'NS'
        db = database(records)
        try: self.assertEqual(a.decision(db,a.History([hist()]),198704,True),[])
        finally: db.close()

    def test_terminal_loss_and_missing_payoff(self):
        self.assertAlmostEqual(a.account_return({1:.25,2:.75},{1:-1,2:.1}),-.175)
        for values in ({2:.1},{1:None,2:.1},{1:float('nan'),2:.1}):
            with self.assertRaises(ValueError): a.account_return({1:.25,2:.75},values)

    def test_timing_and_label_maturity(self):
        a.check_timing('2000-01-01','2000-01-02','2000-01-03','2000-01-03','1999-12-31','2000-01-01')
        with self.assertRaises(ValueError): a.check_timing('2000-01-02','2000-01-02','2000-01-03','2000-01-03')
        with self.assertRaises(ValueError): a.check_timing('2000-01-01','2000-01-02','2000-01-03','2000-01-03','2000-01-01','2000-01-01')

    def test_atomic_run_and_refusal_to_overwrite(self):
        temp_root = a.ROOT / 'tmp' / 'audit_tests'
        temp_root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as tmp:
            raw = Path(tmp)/'raw'; raw.mkdir()
            def write(name,fields,data):
                with (raw/name).open('w',newline='',encoding='utf-8') as f:
                    w=csv.DictWriter(f,fields); w.writeheader(); w.writerows(data)
            write('crsp_ciz_monthly_stock.csv',a.FIELDS,[stock(),stock()])
            write('crsp_ciz_security_history.csv',a.History.FIELDS,[hist()])
            write('crsp_ciz_delistings.csv',['permno','delistingdt','delret','delactiontype','delamtdt'],[])
            for name in ['ccm_fundamentals_annual.csv','ccm_link_history.csv']: (raw/name).write_text('id\n')
            out=Path(tmp)/'out'
            result=a.run(raw,out)
            self.assertEqual(result['counts']['unique_stock_months'],1)
            self.assertFalse(result['performance_evaluated'])
            self.assertTrue((out/'audit.json').exists())
            with self.assertRaises(FileExistsError): a.run(raw,out)
            write('crsp_ciz_monthly_stock.csv',a.FIELDS,[stock(),stock(MthRet='.9')])
            failed=Path(tmp)/'failed'
            with self.assertRaises(ValueError): a.run(raw,failed)
            self.assertFalse(failed.exists())
            self.assertEqual(len(list(Path(tmp).glob('failed.incomplete-*/FAILED.txt'))),1)


if __name__ == '__main__': unittest.main()
