"""먼딜·3팩 40% 고객 추출. 외부 설정/원본/결과는 Git에 넣지 않는다."""
import argparse
import calendar
import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from lib import core, multi
from lib.output import export, save_desktop, digest, validate_rows

ROOT = Path(__file__).resolve().parent
KST = dt.timezone(dt.timedelta(hours=9))


def read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


def period(job, scheduled):
    prev = scheduled.replace(day=1) - dt.timedelta(days=1)
    start = prev.replace(day=20)
    end = prev if job == 'mundil' else scheduled.replace(day=19)
    assert scheduled.day == (2 if job == 'mundil' else 20), '원래 업무 예정일을 지정하세요.'
    return start.isoformat(), end.isoformat()


def proof_check(p, start, end, keyword, job):
    expected = dict(start=start, end=end, keyword=keyword, dateBasis='o.regDt',
                    key='og.goodsNm', first=job == 'half', withdrawn=job == 'mundil')
    assert all(p.get(k) == v for k, v in expected.items()), '검색 조건 불일치'
    assert isinstance(p.get('orderCount'), int) and p['orderCount'] >= 0
    assert isinstance(p.get('orderFingerprint'), int)


def collect(job, start, end, config):
    rules = read(ROOT / 'rules.json') if job == 'half' else [dict(id='mundil', keyword='먼딜')]
    sources = []
    env = dict(os.environ, GODO_CDP_URL=config['cdpUrl'], GODO_ADMIN_HOST=config['adminHost'])
    for r in rules:
        if job == 'half' and (r['from'][:10] > end or r['until'][:10] < start):
            continue
        subprocess.run([shutil.which('node') or 'node', str(ROOT / 'download.cjs'),
                        start, end, r['keyword'], job], check=True, cwd=ROOT, env=env)
        source = read(ROOT / 'work/half/download.json')
        source.update(rule=r['id'], proof=read(ROOT / 'work/half/search.json'))
        sources.append(source)
    return dict(month=end[:7], start=start, end=end, dateBasis='주문일',
                template='주문통합리스트_주문별', sources=sources)


def process_manifest(meta, job):
    assert meta['dateBasis'] == '주문일' and meta['template'] == '주문통합리스트_주문별'
    rules = {r['id']: r for r in read(ROOT / 'rules.json')} if job == 'half' else {}
    if job == 'mundil':
        assert len(meta['sources']) == 1
    for s in meta['sources']:
        keyword = rules[s['rule']]['keyword'] if job == 'half' else '먼딜'
        proof_check(s['proof'], meta['start'], meta['end'], keyword, job)
    if job == 'half':
        write(ROOT / 'work/half/download.json', meta)
        multi.main()
        return read(ROOT / 'work/half/customers.json')
    s = meta['sources'][0]
    assert s['proof']['orderCount'] > 0, '검색 0건: 조건과 원본을 확인하세요.'
    table = core.load(s)
    cols = {core.norm(c): i for i, c in enumerate(table[0])}
    goods = next(cols[k] for k in ('주문상품명', '상품명') if k in cols)
    assert all('먼딜' in str(r[goods]) for r in table[1:] if any(r)), '상품명 불일치'
    return core.process({**meta, 'proof': s['proof']}, table)


def send_chat(report, data, config, report_path):
    if report.get('chatSentAt'):
        return
    if report.get('chatState') == 'sending':
        raise RuntimeError('이전 전송 결과가 불확실합니다. Chat 방에서 수신 확인 후 상태를 복구하세요. 자동 재전송하지 않습니다.')
    webhook = os.environ.get('GOOGLE_CHAT_WEBHOOK_URL', '')
    u = urllib.parse.urlparse(webhook)
    assert u.scheme == 'https' and u.hostname == 'chat.googleapis.com', 'Google Chat 웹훅 설정 필요'
    assert u.path == f"/v1/spaces/{config['chatSpace']}/messages", 'Google Chat 방 불일치'
    assert report['verified'] and report.get('desktopFiles')
    for ext in ('xlsx', 'csv'):
        assert digest(report['desktopFiles'][ext]) == report['hashes'][ext]
    label = '먼딜' if report['job'] == 'mundil' else '3팩 40% (기존 반값)'
    message = (f"[{label} 고객 작업 완료]\n검색기간: {report['start']} ~ {report['end']}\n"
               f"최종 고객: {report['customers']}명\n주문번호 중복 제거: {report['duplicatesRemoved']}행\n"
               f"0원 주문 제외: {report['zeroRemoved']}건\n이메일 빈칸: {report['missingEmails']}건\n"
               '전화번호 +82 TEXT / XLSX 먼저 검증 후 BOM CSV 저장 / 전체 값·건수 일치\n'
               f"저장위치: {Path(report['desktopFiles']['xlsx']).parent}\n"
               f"{Path(report['xlsx']).name}\n{Path(report['csv']).name}")
    for r in data.get('rules', []):
        message += f"\n상품: {r['keyword']} / {r['from']} ~ {r['until']} / 최종 {data['ruleCounts'].get(r['id'], 0)}명"
    if report['job'] == 'half':
        for label, a in [('첫 고객', data['audit'][0]), ('마지막 고객', data['audit'][-1])]:
            message += f"\n\n{label} (파일 순서)\n이름: {a['name']}\n주문번호: {a['order']}\n이메일: {a['email'] or '(없음)'}\n전화번호: {a['phone']}"
    report['chatState'] = 'sending'
    write(report_path, report)
    request = urllib.request.Request(webhook, json.dumps({'text': message}).encode(),
                                     {'Content-Type': 'application/json; charset=utf-8'})
    # Do not print HTTP exceptions: they may contain webhook credentials.
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            answer = json.load(response)
        assert answer.get('name', '').startswith(f"spaces/{config['chatSpace']}/messages/")
    except Exception:
        raise RuntimeError('Chat 전송 결과 확인 필요. 방에서 수신 여부를 확인하세요.') from None
    report.update(chatState='sent', chatSentAt=dt.datetime.now(KST).isoformat())
    write(report_path, report)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--job', choices=['mundil', 'half'], required=True)
    p.add_argument('--scheduled-date', required=True, help='재실행일이 아닌 원래 업무 예정일')
    p.add_argument('--start')
    p.add_argument('--end')
    p.add_argument('--test', action='store_true')
    p.add_argument('--prepared', type=Path, help='내장 브라우저에서 준비한 다운로드 메타데이터')
    p.add_argument('--no-notify', action='store_true', help='파일만 검증; 전체 완료로 기록하지 않음')
    args = p.parse_args()
    assert not sys.flags.optimize, '검증을 위해 python -O를 사용하지 마세요.'
    scheduled = dt.date.fromisoformat(args.scheduled_date)
    start, end = period(args.job, scheduled)
    if args.start or args.end:
        assert args.start and args.end, '시작일·종료일 모두 필요'
        start, end = args.start, args.end
    assert dt.date.fromisoformat(start) <= dt.date.fromisoformat(end)
    assert dt.date.fromisoformat(end) < dt.datetime.now(KST).date(), '완결되지 않은 기간: 종료일 다음 날 실행하세요.'
    config = read(ROOT / 'config.local.json')
    desktop = config.get('desktopRoot') or str(Path.home() / 'Desktop' / '먼딜')
    key = f'{args.job}_{start}_{end}' + ('_test' if args.test else '')
    out = ROOT / 'results' / key
    rp = out / '처리결과.json'
    acceptance = ROOT / 'work' / f'{args.job}_test_success.json'
    if not args.test and not acceptance.exists():
        raise RuntimeError('새 PC에서 --test 실제 검증·저장·알림 성공 후 운영하세요.')
    work = ROOT / 'work'
    work.mkdir(exist_ok=True)
    lock = work / 'run.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        if rp.exists():
            report = read(rp)
            assert report['verified'] and report['scheduledDate'] == scheduled.isoformat()
            data = read(out / 'customers.json')
            assert digest(out / 'customers.json') == report['customerDataHash'], '고객 검증 자료 변경'
            validate_rows(data)
        else:
            meta = read(args.prepared) if args.prepared else collect(args.job, start, end, config)
            assert meta['start'] == start and meta['end'] == end and meta['month'] == end[:7]
            assert not any(k in meta for k in ('asOf', 'runKey', 'fileSuffix')), '현재 진행본은 정기 결과와 분리하세요.'
            data = process_manifest(meta, args.job)
            prefix = '먼딜고객' if args.job == 'mundil' else '반값구매고객'
            name = f"{prefix}_{start.replace('-', '')}_{end.replace('-', '')}" + ('_테스트' if args.test else '')
            result = export(data, out, name)
            report = {k: data[k] for k in ('start', 'end', 'customers', 'duplicatesRemoved', 'zeroRemoved', 'missingEmails')}
            report.update(result, job=args.job, scheduledDate=scheduled.isoformat(), complete=False)
            write(out / 'customers.json', data)
            report['customerDataHash'] = digest(out / 'customers.json')
            write(rp, report)
        save_desktop(report, desktop)
        write(rp, report)
        if not args.no_notify:
            send_chat(report, data, config, rp)
            report['complete'] = True
            write(rp, report)
            if args.test:
                write(acceptance, {'report': str(rp), 'verified': True, 'chatSentAt': report['chatSentAt']})
        print(f"{'완료' if report.get('complete') else '파일 검증 완료·알림 미완료'}: {args.job} / {start} ~ {end} / {report['customers']}명")
    finally:
        lock.unlink(missing_ok=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Fixed description; no source row, secret, webhook URL, or traceback in normal logs.
        print(f'중단: {str(exc) if isinstance(exc, (AssertionError, RuntimeError)) else type(exc).__name__}. 필요한 설정·로그인·기존 결과를 확인하세요.', file=sys.stderr)
        sys.exit(1)
