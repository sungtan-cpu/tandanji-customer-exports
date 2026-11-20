"""All identities below are synthetic; no network, Chrome, or Chat calls."""
import copy
import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import run
from lib import core, multi
from lib.output import export, save_desktop, digest, add_months

HEADERS = ['주문번호', '주문자이름', '주문자이메일', '주문자휴대폰번호', '총 결제 금액', '주문일자', '주문상품명']


def row(order='SYNTH-1', money='100', email='sample@example.com', phone='010-0000-0001',
        when='2026-10-25 12:00:00', goods='먼딜 테스트 상품'):
    return [order, '가상고객', email, phone, money, when, goods]


def meta(rows, keyword='먼딜', job='mundil'):
    ids = {r[0] for r in rows}
    proof = dict(start='2026-10-20', end='2026-11-19', keyword=keyword, dateBasis='o.regDt',
                 key='og.goodsNm', first=job == 'half', withdrawn=job == 'mundil',
                 orderCount=len(ids), orderFingerprint=multi.fingerprint(ids))
    return dict(month='2026-11', start='2026-10-20', end='2026-11-19',
                dateBasis='주문일', template='주문통합리스트_주문별', proof=proof)


def data():
    rows = [row(), row(), row('SYNTH-2', '0'), row('SYNTH-3', email='')]
    return core.process(meta(rows), [HEADERS, *rows])


class Periods(unittest.TestCase):
    def test_mundil_leap_year(self):
        self.assertEqual(run.period('mundil', dt.date(2028, 3, 2)), ('2028-02-20', '2028-02-29'))

    def test_mundil_nonleap(self):
        self.assertEqual(run.period('mundil', dt.date(2027, 3, 2)), ('2027-02-20', '2027-02-28'))

    def test_half_year_boundary(self):
        self.assertEqual(run.period('half', dt.date(2027, 1, 20)), ('2026-12-20', '2027-01-19'))

    def test_wrong_scheduled_day(self):
        with self.assertRaises(AssertionError):
            run.period('half', dt.date(2026, 11, 2))

    def test_preparation_year_boundary(self):
        self.assertEqual(add_months('2026-12', 1), '2027-01')


class Processing(unittest.TestCase):
    def test_dedup_zero_and_missing_email(self):
        d = data()
        self.assertEqual((d['customers'], d['duplicatesRemoved'], d['zeroRemoved'], d['missingEmails']), (2, 1, 1, 1))
        self.assertEqual(d['rows'][1][:3], ['', '', ''])
        self.assertEqual(d['rows'][0][3:], ['+82-10-0000-0001'] * 3)

    def test_order_is_key_not_email_phone(self):
        rows = [row(), row('SYNTH-2')]
        d = core.process(meta(rows), [HEADERS, *rows])
        self.assertEqual(d['customers'], 2)

    def test_first_row_kept_even_if_zero(self):
        rows = [row(money='0'), row(money='100')]
        d = core.process(meta(rows), [HEADERS, *rows])
        self.assertEqual((d['customers'], d['zeroRemoved'], d['duplicatesRemoved']), (0, 1, 1))

    def test_ui_order_mismatch_fails(self):
        rows = [row()]
        m = meta(rows)
        m['proof']['orderFingerprint'] += 1
        with self.assertRaises(ValueError):
            core.process(m, [HEADERS, *rows])

    def test_outside_period_fails(self):
        rows = [row(when='2026-10-19 23:59:59')]
        with self.assertRaises(ValueError):
            core.process(meta(rows), [HEADERS, *rows])

    def test_wrong_first_order_condition_fails(self):
        m = meta([row()], job='half', keyword='approved')
        m['proof']['first'] = False
        with self.assertRaises(AssertionError):
            run.proof_check(m['proof'], m['start'], m['end'], 'approved', 'half')

    def test_phone_format_fails(self):
        rows = [row(phone='123')]
        with self.assertRaises(ValueError):
            core.process(meta(rows), [HEADERS, *rows])

    def test_multisource_boundaries_and_zero_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'work/half').mkdir(parents=True)
            rules = [dict(id='old', keyword='OLD', **{'from': '0001-01-01 00:00:00', 'until': '2026-10-14 11:36:59'}),
                     dict(id='new', keyword='NEW', **{'from': '2026-10-14 12:23:00', 'until': '9999-12-31 23:59:59'}),
                     dict(id='zero', keyword='ZERO', **{'from': '0001-01-01 00:00:00', 'until': '9999-12-31 23:59:59'})]
            (root / 'rules.json').write_text(json.dumps(rules), encoding='utf-8')
            tables = {'old': [HEADERS, row('SYNTH-OLD', when='2026-10-14 11:36:59'), row('SYNTH-GAP', when='2026-10-14 11:37:00')],
                      'new': [HEADERS, row('SYNTH-NEW', when='2026-10-14 12:23:00')]}
            sources = []
            for r in rules:
                rs = tables.get(r['id'], [HEADERS])[1:]
                proof = dict(start='2026-09-20', end='2026-10-19', keyword=r['keyword'], dateBasis='o.regDt',
                             key='og.goodsNm', first=True, withdrawn=False, orderCount=len(rs),
                             orderFingerprint=multi.fingerprint([a[0] for a in rs]))
                sources.append(dict(rule=r['id'], path=r['id'] if rs else None, proof=proof))
            m = dict(month='2026-10', start='2026-09-20', end='2026-10-19', dateBasis='주문일',
                     template='주문통합리스트_주문별', sources=sources)
            (root / 'work/half/download.json').write_text(json.dumps(m), encoding='utf-8')
            with patch.object(multi, 'ROOT', root), patch.object(core, 'load', side_effect=lambda s: tables[s['rule']]):
                multi.main()
            d = json.loads((root / 'work/half/customers.json').read_text('utf-8'))
            self.assertEqual(d['customers'], 2)
            self.assertEqual(d['timeExcludedRows'], 1)
            self.assertEqual(d['ruleCounts'], {'new': 1, 'old': 1})


class Files(unittest.TestCase):
    def test_prepared_run_resume_restores_only_missing_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / 'raw.xls'
            rs = [row(when='2020-10-25 12:00:00')]
            raw.write_text('<table><tr>' + ''.join('<th>' + h + '</th>' for h in HEADERS) + '</tr>' +
                           ''.join('<tr>' + ''.join('<td>' + v + '</td>' for v in r) + '</tr>' for r in rs) + '</table>', encoding='utf-8')
            m = dict(month='2020-10', start='2020-10-20', end='2020-10-31', dateBasis='주문일', template='주문통합리스트_주문별')
            proof = dict(start=m['start'], end=m['end'], keyword='먼딜', dateBasis='o.regDt', key='og.goodsNm',
                         first=False, withdrawn=True, orderCount=1, orderFingerprint=multi.fingerprint(['SYNTH-1']))
            m['sources'] = [dict(rule='mundil', path=str(raw), proof=proof)]
            prepared = root / 'prepared.json'
            prepared.write_text(json.dumps(m), encoding='utf-8')
            (root / 'config.local.json').write_text(json.dumps(dict(desktopRoot=str(root / 'Desktop/먼딜'))), encoding='utf-8')
            argv = ['run.py', '--job', 'mundil', '--scheduled-date', '2020-11-02', '--test', '--no-notify', '--prepared', str(prepared)]
            with patch.object(run, 'ROOT', root), patch.object(sys, 'argv', argv):
                run.main()
                rp = root / 'results/mundil_2020-10-20_2020-10-31_test/처리결과.json'
                report = json.loads(rp.read_text('utf-8'))
                self.assertFalse(report['complete'])
                Path(report['desktopFiles']['csv']).unlink()
                raw.unlink()  # proves rerun does not redownload or reprocess
                run.main()
                self.assertTrue(Path(report['desktopFiles']['csv']).exists())

    def test_chat_success_records_confirmed_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = data()
            r = export(d, root / 'results', '가상')
            r.update(job='mundil', start=d['start'], end=d['end'], customers=2,
                     duplicatesRemoved=1, zeroRemoved=1, missingEmails=1, scheduledDate='2026-11-02')
            save_desktop(r, root / 'Desktop/먼딜')
            response = io.BytesIO(json.dumps({'name': 'spaces/TEST_SPACE/messages/confirmed'}).encode())
            with patch.dict(run.os.environ, {'GOOGLE_CHAT_WEBHOOK_URL': 'https://chat.googleapis.com/v1/spaces/TEST_SPACE/messages'}), \
                    patch.object(run.urllib.request, 'urlopen', return_value=response):
                run.send_chat(r, d, {'chatSpace': 'TEST_SPACE'}, root / 'report.json')
            self.assertEqual(r['chatState'], 'sent')
            self.assertTrue(r['chatSentAt'])

    def test_roundtrip_text_bom_hash_and_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = data()
            r = export(d, root / 'result', '가상고객')
            r.update(scheduledDate='2026-11-20')
            save_desktop(r, root / 'Desktop/먼딜')
            self.assertEqual(r['preparationMonth'], '2026-12')
            for ext in ('xlsx', 'csv'):
                self.assertEqual(digest(r[ext]), digest(r['desktopFiles'][ext]))
            Path(r['desktopFiles']['csv']).unlink()
            save_desktop(r, root / 'Desktop/먼딜')
            self.assertTrue(Path(r['desktopFiles']['csv']).exists())

    def test_no_overwrite_different_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            r = export(data(), root / 'result', '가상고객')
            r.update(scheduledDate='2026-11-20')
            target = root / 'Desktop/먼딜/12월 먼딜준비'
            target.mkdir(parents=True)
            (target / '가상고객.xlsx').write_text('existing different content')
            with self.assertRaises(RuntimeError):
                save_desktop(r, root / 'Desktop/먼딜')
            self.assertEqual((target / '가상고객.xlsx').read_text(), 'existing different content')

    def test_no_formula_phone_and_missing_phone_rejected(self):
        d = data()
        d['rows'][0][3:] = ['="+82-10-0000-0001"'] * 3
        with self.assertRaises(AssertionError):
            with tempfile.TemporaryDirectory() as tmp:
                export(d, Path(tmp), 'bad')

    def test_chat_already_sent_does_not_send(self):
        with patch.object(run.urllib.request, 'urlopen') as urlopen:
            run.send_chat({'chatSentAt': 'confirmed'}, {}, {}, Path('unused'))
            urlopen.assert_not_called()

    def test_chat_uncertain_does_not_resend(self):
        with patch.object(run.urllib.request, 'urlopen') as urlopen:
            with self.assertRaises(RuntimeError):
                run.send_chat({'chatState': 'sending'}, {}, {}, Path('unused'))
            urlopen.assert_not_called()


if __name__ == '__main__':
    unittest.main()
