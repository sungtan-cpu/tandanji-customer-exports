"""Portable XLSX -> verify -> BOM CSV -> verify -> hash-checked desktop copy."""
import csv
import hashlib
import re
import shutil
from pathlib import Path
from openpyxl import Workbook, load_workbook


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def add_months(month, offset):
    y, m = map(int, month.split('-'))
    y, m = divmod(y * 12 + m - 1 + offset, 12)
    return f'{y:04d}-{m + 1:02d}'


def validate_rows(data):
    assert data['customers'] == len(data['rows']) == len(data['audit'])
    assert len({a['order'] for a in data['audit']}) == data['customers']
    from decimal import Decimal
    assert all(Decimal(a['amount']).is_finite() and Decimal(a['amount']) != 0 for a in data['audit'])
    assert data['sourceRows'] == data['duplicatesRemoved'] + data['zeroRemoved'] + data['customers']
    assert data['missingEmails'] == sum(not a['email'] for a in data['audit'])
    for row, a in zip(data['rows'], data['audit']):
        assert row == [a['email']] * 3 + [a['phone']] * 3
        assert re.fullmatch(r'\+82-10-\d{4}-\d{4}', a['phone']), '휴대폰 형식 확인 필요'
        assert all(isinstance(v, str) for v in row)


def verify_xlsx(path, expected):
    w = load_workbook(path, data_only=False)
    try:
        assert w.sheetnames == ['고객업로드']
        s = w.active
        assert [[v if v is not None else '' for v in r] for r in s.values] == expected
        for row in s.iter_rows(min_row=2):
            for cell in row:
                assert cell.data_type != 'f' and cell.number_format == '@'
                assert cell.value is None or isinstance(cell.value, str)
    finally:
        w.close()


def export(data, out, basename):
    validate_rows(data)
    out.mkdir(parents=True, exist_ok=True)
    xp, cp = out / (basename + '.xlsx'), out / (basename + '.csv')
    if xp.exists() or cp.exists():
        raise RuntimeError('이미 생성된 파일이 있습니다. 미완료 결과를 확인하세요. 덮어쓰지 않습니다.')
    expected = [['EMAIL'] * 3 + ['PHONE'] * 3, *data['rows']]
    w = Workbook()
    s = w.active
    s.title = '고객업로드'
    for row in expected:
        s.append(row)
        for cell in s[s.max_row]:
            cell.number_format = '@'
            cell.data_type = 's'
    w.save(xp)
    w.close()
    verify_xlsx(xp, expected)
    with cp.open('x', encoding='utf-8-sig', newline='') as f:
        csv.writer(f).writerows(expected)
    with cp.open(encoding='utf-8-sig', newline='') as f:
        assert list(csv.reader(f)) == expected
    assert cp.read_bytes().startswith(b'\xef\xbb\xbf')
    return {'xlsx': str(xp.resolve()), 'csv': str(cp.resolve()),
            'hashes': {'xlsx': digest(xp), 'csv': digest(cp)},
            'verified': True, 'xlsxBeforeCsv': True}


def save_desktop(report, desktop_root):
    assert report['verified']
    prep = add_months(report['scheduledDate'][:7], 1)
    dest = Path(desktop_root) / f'{int(prep[5:])}월 먼딜준비'
    dest.mkdir(parents=True, exist_ok=True)
    saved = {}
    for ext in ('xlsx', 'csv'):
        source = Path(report[ext])
        assert digest(source) == report['hashes'][ext], '검증된 작업 파일이 변경되었습니다.'
        target = dest / source.name
        if target.exists() and digest(target) != report['hashes'][ext]:
            raise RuntimeError('동일 이름의 다른 파일이 있어 덮어쓰지 않습니다.')
        if not target.exists():
            shutil.copy2(source, target)
        assert digest(target) == report['hashes'][ext]
        saved[ext] = str(target)
    report.update(desktopFiles=saved, preparationMonth=prep)
