# 반려식물 관리 서비스

식물을 자꾸 죽이는 초보자를 위한 개인 반려식물 관리 웹 서비스입니다.
화분 센서(토양수분·조도·온도·습도) 값으로 식물 상태를 판정하고, 물이나 빛이 부족하면 먼저 알려 줍니다.
웹에서 센서 그래프, 사진첩, 다이어리, 할 일, 식물 상담소(AI 답변)를 쓸 수 있습니다.

Django 6.0 · SQLite · Django 템플릿 + 순수 JavaScript · Python 3.14

## 처음 실행하는 방법

```powershell
pip install -r requirements.txt
copy .env.example .env
```

`.env`의 `DJANGO_SECRET_KEY`를 긴 임의 문자열로 바꿉니다.

```powershell
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

```powershell
python manage.py migrate
python manage.py loaddata crops      # 작물 기준값
python manage.py runserver
```

브라우저에서 http://127.0.0.1:8000 을 열고 회원가입 → 작물 선택 → 이름 짓기 순서로 시작합니다.
식물 상담소를 쓰려면 `.env`에 `LLM_PROVIDER`, `LLM_API_KEY`, `LLM_MODEL`을 채웁니다(비어 있으면 상담소는 꺼진 상태로 표시).

## 폴더

| 폴더 | 내용 |
|---|---|
| `config/` | 설정, 주소 연결, 테스트 실행기(테스트 중 외부 네트워크 차단) |
| `accounts/` | 회원가입·로그인·온보딩·사용 안내, 프로필 |
| `plants/` | 작물·화분·센서값·사진·할 일, 상태 판정, 그래프, 센서 수신 API, 센서 기기 관리, 관리 명령(`management/commands`), 작물 초기 데이터(`fixtures/crops.json`) |
| `alerts/` | 알림 기록과 알림 설정, 센서 점검 |
| `diary/` | 개인 다이어리 |
| `advisor/` | 식물 상담소(화분 데이터를 요약해 AI에게 질문, 대화 기록·하루 한도) |
| `templates/` | 공통 화면 틀 |
| `static/` | CSS, JavaScript, 작물 그림(`characters/`) |

## 센서 전송 API

센서는 `POST /api/readings`로 JSON을 보내고, 헤더 `X-API-Key`에 키를 넣습니다. 화분 하나에서 값 하나를 보낼 때는 화분 키와 `{"moisture": 42.5, "light": 12.3, "temp": 23.1, "humidity": 55}`를 보냅니다. 라즈베리파이 같은 기기가 여러 화분 값을 한 번에 보낼 때는 "내 기기" 화면에서 기기를 등록해 받은 기기 키와 `{"device_id": "...", "readings": [{"time": "...", "soil1": ..., "soil2": ..., "light": ..., "temp": ..., "hum": ..., "n_samples": 1}]}`를 보냅니다. 키가 맞지 않으면 401이고, 서버 확인은 `GET /health`입니다.

## 테스트

```powershell
python manage.py test
```

테스트 중에는 실제 AI 호출과 외부 네트워크 연결을 막아 둡니다(`.env`에 키가 있어도 호출하지 않음).
