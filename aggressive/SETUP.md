# Aggressive Engine — Phase B Setup Guide

사용자가 수동으로 해야 할 셋업 (2026-04-23).

## 1. Alpaca API 키 발급 (5분)

1. 로그인: https://app.alpaca.markets/paper/dashboard/overview
   (계정: andrewcha231@gmail.com, paper mode)
2. 왼쪽 사이드바 → **API Keys** → **Generate New Key**
3. Paper Account Keys 복사:
   - Key ID (public)
   - Secret Key (private)
4. PowerShell 세션 환경 변수 설정 (임시):
   ```powershell
   $env:ALPACA_API_KEY = "YOUR_KEY_HERE"
   $env:ALPACA_API_SECRET = "YOUR_SECRET_HERE"
   ```
5. 영구 설정 (권장, PowerShell profile):
   ```powershell
   notepad $PROFILE
   # 파일 끝에 추가:
   $env:ALPACA_API_KEY = "YOUR_KEY_HERE"
   $env:ALPACA_API_SECRET = "YOUR_SECRET_HERE"
   $env:TELEGRAM_BOT_TOKEN = "..."
   $env:TELEGRAM_CHAT_ID = "..."
   ```

## 2. Telegram bot 생성 (3분)

1. Telegram 앱 → **@BotFather** 검색 → Start
2. `/newbot` 명령:
   ```
   name: r1000_aggressive_alerts
   username: r1000_agg_alerts_bot  (반드시 _bot 로 끝)
   ```
3. BotFather가 보내는 **HTTP API token** 복사 (e.g. `7123456789:AAH...xyz`)
4. 생성한 봇에게 아무 메시지 보냄 (예: "hi")
5. 브라우저에서:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
   JSON 응답에서 `"chat":{"id": 123456789, ...}` 찾아 chat_id 복사
6. PowerShell:
   ```powershell
   $env:TELEGRAM_BOT_TOKEN = "7123456789:AAH...xyz"
   $env:TELEGRAM_CHAT_ID = "123456789"
   ```

## 3. Python 의존성 설치 (2분)

```powershell
py -3 -m pip install alpaca-py python-telegram-bot
```

`alpaca-py`는 Alpaca 공식 SDK (REST + websocket).
`python-telegram-bot`은 이미 requests로 대체 가능하니 optional.

## 4. 연결 테스트 (1분 each)

### Alpaca paper 연결:
```powershell
py -3 aggressive/agg_config.py
```
출력 확인:
```
ALPACA_API_KEY: PKXXXXX... (OK)
```

실제 계정 접속 테스트 (추후 추가 script):
```powershell
py -3 aggressive/test_alpaca_connection.py
```

### Telegram 알림 테스트:
```powershell
py -3 aggressive/telegram_alert.py
```
Telegram 에서 "Aggressive engine telegram_alert.py smoke test" 메시지 수신 확인.

## 5. 보안 주의사항

- `$env:` 설정값은 **절대 git 에 commit 하지 말 것**
- `.gitignore` 에 `*.env`, `credentials.json` 추가 (이미 있음)
- Paper mode only until Phase E 완료
- Live mode 전환 전 user 명시적 승인 필요

## 6. 다음 단계 (user 셋업 완료 후)

사용자가 위 단계 완료 후 알려주면:
- Phase B1.1 **Alpaca 연결 확인 스크립트** 실행
- Phase B1.2 **Real-time bar subscriber** 작성 (WebSocket)
- Phase B1.3 **Event calendar loader**

## 7. 비용 예상

- Alpaca paper mode: **$0** (무료)
- Telegram bot: **$0** (무료)
- AWS Lambda (Phase E 이후): **$2-5/월**
- Total for 3-month paper trial: **$0**
