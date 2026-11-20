# 다른 컴퓨터에서 시작하기

## 1. 받기와 설치

GitHub 공개 `sungtan-cpu/tandanji-customer-exports` 접근 권한이 있는 계정으로 저장소를 받습니다. ZIP 다운로드 또는 Git clone 후 **저장소 루트 폴더**를 작업 폴더로 엽니다. Python 3.11 이상과 Node.js 20 이상이 PATH에 있어야 합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install
Copy-Item config.example.json config.local.json
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`config.local.json`은 Git에 올리지 않습니다. desktopRoot가 빈 문자열이면 현재 Windows 사용자의 `Desktop/먼딜`을 사용합니다. OneDrive 등 다른 바탕화면이면 실제 경로로 바꿉니다. cdpUrl은 로그인에 사용할 로컬 브라우저 연결 주소, chatSpace는 승인된 방 ID입니다.

공개본의 `adminHost`와 `chatSpace`는 실제 값이 아닌 자리표시자입니다. adminHost에는 `https://` 없이 실제 고도몰 관리자 도메인을, chatSpace에는 기존 승인된 Chat 방 ID를 **로컬 설정 파일에서만** 입력합니다. 아래 브라우저 실행 예시의 `YOUR_GODOMALL_ADMIN_HOST`도 실제 도메인으로 바꿉니다. 로그인 아이디·비밀번호는 이 설정 파일에도 저장하지 않고 브라우저에서 직접 입력합니다.

## 2. 고도몰 로그인

Codex 내장 브라우저가 가능하면 그 브라우저에서 직접 로그인하고 브라우저준비.md에 따라 다운로드 증빙을 준비합니다. 로그인 세션은 새 PC에서 직접 만들어야 합니다.

자동 Chrome 다운로드를 쓸 때는 사용자 전용 프로필이 아닌 **이 업무용 별도 프로필**을 사용하세요. 예시 Chrome 경로가 없으면 설치 위치에 맞춥니다.

```powershell
# 현재 폴더를 customer-exports로 연 상태
$profileDir = Join-Path (Get-Location) 'browser-profile'
& 'C:\Program Files\Google\Chrome\Application\chrome.exe' --remote-debugging-port=9222 --remote-debugging-address=127.0.0.1 "--user-data-dir=$profileDir" 'https://YOUR_GODOMALL_ADMIN_HOST/order/order_list_all.php'
```

열린 Chrome 화면에서 직접 로그인합니다. 원격 디버깅 포트를 외부 네트워크로 공개하지 않습니다. 브라우저 프로필을 Git에 올리지 않습니다. 실행 시 로그인 만료/추가 인증이면 중단합니다.

## 3. 기존 Google Chat 연결

기존 승인된 Chat 방의 웹훅은 Git에 포함하지 않았습니다. 해당 방에서 사용할 웹훅을 새 PC에 안전하게 설정해야 합니다. 명령 이력에 URL을 남기지 않도록 현재 PowerShell에서 비밀 입력으로 받는 예시입니다.

```powershell
$chatSecret = Read-Host '기존 Google Chat 웹훅 URL' -AsSecureString
$env:GOOGLE_CHAT_WEBHOOK_URL = [System.Net.NetworkCredential]::new('', $chatSecret).Password
```

이 환경변수는 해당 PowerShell 세션과 그 하위 실행에만 적용됩니다. 예약 실행은 별도의 안전한 비밀 설정이 필요합니다. 채팅 메시지나 저장소에 웹훅 URL을 붙이지 마세요. 자동으로 다른 PC의 설정이 복사되지는 않습니다.

## 4. 먼저 실제 테스트

종료일이 지난 기간을 선택해 두 업무를 각각 검증합니다. 예시:

```powershell
.\.venv\Scripts\python.exe run.py --job mundil --scheduled-date 2026-11-02 --test
.\.venv\Scripts\python.exe run.py --job half --scheduled-date 2026-11-20 --test
```

실제 다운로드, 주문 집합 대조, XLSX/CSV 검증, 준비 폴더 복사 해시, Chat 수신이 모두 성공해야 해당 업무의 테스트 성공 기록이 생깁니다. 테스트도 실제 승인된 Chat 방에 알림을 보내며 파일명은 `_테스트`로 구분됩니다. 두 PC에서 동일 작업을 중복 진행하지 마세요.

내장 브라우저로 파일을 준비했다면 `--prepared 'work/half/download.json'`을 추가합니다. 수동 원본의 암호는 메타데이터에만 두고 Git/로그에 노출하지 않습니다.

## 5. 정상 실행과 재실행

테스트 성공 후 README 예시에서 `--test`를 빼고 실행합니다. 재실행에도 **원래 업무 예정일**을 유지합니다. 같은 결과의 검증/해시/알림 성공이 있으면 재생성과 재전송을 하지 않고 준비 폴더 누락만 복구합니다.

전송 시도 중 연결이 끊기면 `chatState: sending`으로 남습니다. Chat에서 해당 기간 메시지를 확인하세요. 수신이 확인되면 보고서의 chatState를 sent, chatSentAt을 확인된 시각으로 복구한 뒤 재실행합니다. 미수신이 명확히 확인된 경우에만 sending 상태를 제거하고 재시도합니다. 상태를 확인하지 않고 자동 재전송하지 않습니다.

부분 생성 파일이 있고 보고서가 없으면 덮어쓰지 않고 중단합니다. 에이전트가 해당 결과 폴더의 파일을 검사하고 별도 백업 후 재시도하세요. 남은 run.lock은 다른 실행이 없다는 사실을 확인한 후에만 삭제합니다. Python `-O` 옵션은 검증을 끄므로 금지합니다.

## 6. 일정 옮기기

새 PC 실제 테스트 후 정기작업프롬프트.md로 한국 시간 매월 2일/20일 09:30을 등록합니다. 이 저장소에는 일정을 자동 등록하는 동작이 없습니다. 기존 PC 정기 작업과 중복하지 않도록 전환일을 정합니다. 로컬 브라우저 방식은 해당 PC가 켜져 있고 로그인·Chat 비밀 설정이 준비돼 있어야 합니다.
