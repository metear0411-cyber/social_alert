# 인계서 — 노리 공모사업 알림봇 (Claude Code 이어작업용)

> 이 문서는 Claude Code가 이 프로젝트를 이어받아 작업하기 위한 인수인계 문서다.
> 사용자(동욱)는 코드를 직접 읽거나 리뷰하지 않는다. 기술 구현은 전적으로 위임되며,
> 설명·제안은 코드 가독성에 의존하지 말고 자연어로 한다.
> 일/업무 대화에서는 목표는 존중하되, 수단·전제에 더 나은 선택지나 사실관계 오류가 보이면
> "이건 어때요?" 식으로 옵션을 제시하고 결정권은 사용자에게 둔다.

---

## 1. 프로젝트 목적

대구 사회복지 게시판을 주기적으로 감시해, **기능보강·환경개선·지원사업** 등 시설 관련
공모/지원 공고가 새로 올라오면 메신저로 즉시 알리는 봇. 별도 서버 없이 GitHub Actions로 운영.
대상: 노리주간보호센터(대구 달서구, 정원 58명).

---

## 2. 현재 상태 (1단계 프로토타입 — 완료, 실측 검증됨)

전 파이프라인(수집 → 키워드 매칭 → 중복방지 → 알림 메시지 생성)을 **라이브 API에 붙여 검증 완료.**
- 최초 실행 = 기준선만 기록(발송 안 함) → 정상
- 기존 글 미확인 처리 후 재실행 → "지원사업" 매칭 글 1건 감지·메시지 생성 → 정상

### 파일 구성
```
welfare_alert.py                      # 본체 (수집/필터/중복방지/알림)
requirements.txt                      # requests, PyJWT, cryptography
README.md                             # 비개발자용 설치 안내서
.github/workflows/welfare-alert.yml   # 평일 09:00/14:00 KST 자동 실행 + state.json 커밋
state.json                            # (실행 시 자동 생성) 알린 글 ID 기록
```

---

## 3. 확정된 핵심 기술 사실 (재조사 불필요 — 이미 검증함)

대상 사이트 `welfare.net/daegu`는 한국사회복지사협회 통합 플랫폼(전국 지부)의 대구지부.
Nuxt3 SPA + 전자정부 표준프레임워크(egovframework) 백엔드.

- **데이터 API (인증 불필요, GET):**
  `https://api.welfare.net/daegu/na/ntt/selectNttList.do?mi=5200&bbsId=5208&currPage=1`
- 응답 구조: `resp.json()["nttListPaging"]["list"]` 가 게시글 배열
- **게시글 필드 매핑:**
  - `nttSj` → 제목
  - `regDt` → 작성일 (형식 `"2026.06.29"`)
  - `nttSn` → 게시물 식별자 (상세 링크에 사용)
  - `noticeAt` → 공지 고정 여부("Y"/"N")
  - `ctgryCd` → 카테고리 코드 (복지소식 게시판은 null. 일부 게시판은 11=채용/12=입찰/13=모집/14=행사/그외=홍보)
  - 기타: `nttRdcnt`(조회수), `fileChk`(첨부수), `regNm`(작성자명)
- **상세페이지(사람이 클릭) URL:**
  `https://www.welfare.net/daegu/community/welfare-news/board-detail?nttSn={nttSn}`
- **게시판 식별자:** 복지소식 = `mi=5200, bbsId=5208`
- **확장 포인트:** 같은 계열의 다른 게시판/타 지부는 `api_base`·`mi`·`bbsId`만 바꾸면 동일 핸들러로 동작.
- (참고) 상세 데이터 API는 `/na/ntt/selectNttInfo.do` 이나, 현재 봇은 목록만 사용하므로 미사용.
- (참고) `community/welfare-news` 등으로 직접 호출하면 JWT 인증 엔트리포인트가 걸리며,
  현재 그 핸들러에 Jackson 버전 버그가 있어 401 대신 500을 반환함. 정상 경로는 위의 `selectNttList.do`.

---

## 4. 이번 단계에서 내린 설계 결정 (오마카세로 위임받아 확정)

1. **크롤링 방식**: Playwright/Selenium 대신 내부 JSON API 직접 호출(`requests`).
   브라우저 불필요 → GitHub Actions에서 가장 가벼움. (사용자 동의 완료)
2. **소스 범위**: 협회 복지소식 1곳을 견고하게 완성하고, 소스를 끼워넣는 구조(`SOURCES` 리스트 + `HANDLERS` 맵)로 설계. 복지넷·사랑의열매는 다음 단계.
3. **스케줄**: 선착순 공고 특성상 매일 1회 대신 **평일 09:00·14:00 KST 2회**.
4. **중복방지 영속화**: GitHub Actions에서 `state.json`을 저장소에 다시 커밋(`[skip ci]`)하는 방식.
5. **알림 채널**: 기본은 범용 Webhook(`WEBHOOK_URL`, Slack/Discord/Teams/Telegram 호환).
   네이버웍스 Bot 발송 코드는 이미 포함되어 있고, 6개 시크릿이 모두 채워지면 자동 전환.

---

## 5. 키워드 (현재)

`기능보강, 환경개선, 공모사업, 지원사업, 물품지원, 개보수, 리모델링, 기자재, 가전, 후원물품`
- 공백 무시 비교 → "기능 보강" = "기능보강"
- `welfare_alert.py` 상단 `KEYWORDS` 리스트에서 관리.

---

## 6. 알림 발송 구조

`notify(message)` 우선순위: **네이버웍스 Bot → 범용 Webhook → 화면 출력(미설정 시)**

- 네이버웍스 필요 시크릿(6개): `NW_BOT_ID, NW_CHANNEL_ID, NW_CLIENT_ID, NW_CLIENT_SECRET, NW_SERVICE_ACCOUNT, NW_PRIVATE_KEY`
- 발송 로직: JWT(RS256) assertion → `auth.worksmobile.com/oauth2/v2.0/token`에서 access token 발급
  → `worksapis.com/v1.0/bots/{botId}/channels/{channelId}/messages` 로 `{"content":{"type":"text","text":...}}` POST.
- ⚠️ 사용자가 운영 중인 네이버웍스 봇 자격증명을 아직 받지 못함. 받는 즉시 시크릿에 등록하면 동작.

---

## 7. 다음 작업 후보 (우선순위 제안)

1. **네이버웍스 Bot 실연동 검증** — 자격증명 확보 후 실제 채널 발송 테스트.
   (현재 `send_naver_works`는 작성됐으나 라이브 검증 전. 토큰 발급/메시지 포맷 실측 필요.)
2. **소스 확장** — 시설 기능보강/환경개선 공고가 더 자주 뜨는 곳:
   - 복지넷(bokji.net) 사업공모 — `https://www.bokji.net/not/biz/01_01.bokji` (구조 별도 조사 필요)
   - 사랑의열매 대구사회복지공동모금회 — 실제로 협회 게시판에도 공동모금회 공고가 올라옴(확인됨)
   - 달서구청/대구시청 공고 게시판
   각 소스는 새 핸들러 함수 + `HANDLERS` 등록 + `SOURCES` 항목 추가로 붙는다.
   수집 결과는 `{uid, title, date, url, is_notice, source}` 표준 형식으로 정규화할 것.
3. **카테고리/본문 기반 정밀 필터** — 제목만으로 놓치는 공고 대비, 상세 API(`selectNttInfo.do`) 본문에서
   '대상: 시설', '지원금', '한도' 등 2차 필터 옵션화.
4. **호스팅 이전 옵션** — 사용자가 8845HS 미니PC 자가호스팅 서버(Windows+WSL2, Docker/Portainer,
   Cloudflare Tunnel)를 구축 중. GitHub Actions 대신 미니PC cron/Docker로 옮기면 시크릿·로그 관리가
   더 수월할 수 있음. 단, GitHub Actions도 충분히 합리적이므로 사용자 선택에 맡길 것.

---

## 8. 로컬 테스트 방법

```bash
pip install -r requirements.txt
python welfare_alert.py          # 최초 = 기준선(발송X). state.json 생성됨
python welfare_alert.py          # 신규 없으면 "신규 공고 없음."
# 발송 미리보기 테스트: state.json에서 특정 uid("5208-893414" 등) 제거 후 재실행하면
# 해당 글이 신규로 잡혀 메시지가 화면에 출력됨(WEBHOOK_URL 미설정 시 stdout).
```

---

## 9. 사용자 컨텍스트 메모

- 브랜드: 노리주간보호센터. BI 컬러 — main #5C3D00, accent #F5C200 (이 봇엔 직접 영향 없음).
- 플랫폼 전제: Windows/Android 크로스 호환이 기본. Apple 전용 솔루션 배제.
- 톤: 직설적·협업적·차분하고 정제된 한국어. 축약형(ㅇㅇ체) 지양.
- 사용자는 코드 리뷰 불가 → 변경 시 "무엇이/왜 바뀌는지"를 자연어로 설명.

---

## 10. 변경 이력

### 2단계 — 발송 안정화 (완료, 오프라인 검증)
1단계 프로토타입을 저장소에 올린 뒤, 알림 발송 경로를 견고하게 보강함.
- **채널별 페이로드 분기**: `WEBHOOK_URL` 호스트로 메신저 종류를 판별해 형식을 맞춤
  (디스코드=`content` 문자열 / 슬랙·팀즈=`text` / 텔레그램=`text`+`chat_id`).
  기존엔 `content`를 객체로 보내 **디스코드 발송이 깨졌었음** → 수정됨.
  텔레그램은 `TELEGRAM_CHAT_ID` 시크릿이 추가로 필요(README 반영).
- **재시도**: 네트워크 오류·타임아웃·5xx·429 에 한해 지수 백오프(1·2초)로 최대 3회.
  4xx 등 영구 오류는 즉시 중단. `post_with_retry()` 가 Webhook·네이버웍스 양쪽에 적용됨.
- **발송 성공분만 기록**: 발송 실패한 공고는 `state.json` 에 기록하지 않아 다음 실행에서
  자동 재시도됨(기존엔 실패해도 '완료'로 기록돼 공고가 영구 유실되던 문제 수정).
  `notify()` 반환값이 `(channel, delivered)` 튜플로 바뀜.
- **실패 가시화**: 발송 실패 시 종료 코드 1 → Actions에서 빨간 X. 단 워크플로의 state 커밋
  step은 `if: always()` 라 성공분 기록은 항상 커밋됨(중복 방지 유지).
- ⚠️ 라이브 검증은 작업 환경의 외부망 차단으로 미실시 — 오프라인 단위/통합 테스트로만 확인.
  실제 채널 발송은 사용자 환경(GitHub Actions)에서 확인 필요.

### 3단계 — 소스 확장 인프라 (완료, 오프라인 검증)
새 게시판을 안전하게 늘릴 수 있는 토대를 마련함.
- **`load_sources()`**: 코드의 `SOURCES` + (있으면) 저장소 루트의 `sources.json` 을 병합.
  welfare.net 계열 게시판은 파이썬을 안 건드리고 JSON 데이터로 추가 가능(GitHub 웹 편집).
  항목에 `"enabled": false` 면 건너뜀. `main()` 은 이제 `load_sources()` 를 사용.
- **`--probe` 모드**: `python welfare_alert.py --probe [필터]` — 발송·state 없이 각 소스의
  수집 결과와 키워드 매칭을 출력. 새 소스의 mi/bbsId·필드 매핑을 네트워크 되는 곳에서 즉시 검증.
- ⚠️ **작업 환경 외부망 차단 확정**: 조직 egress 정책이 `api.welfare.net`·`bokji.net`·
  `chest.or.kr`(사랑의열매)·`developers.worksmobile.com` 등을 모두 403 차단(프록시 로그 확인).
  → 이 환경에선 신규 사이트 구조 조사·라이브 수집·네이버웍스 브라우저 작업이 불가.
  복지넷/사랑의열매 등 welfare.net **비계열** 사이트는 응답 샘플 1건 확보 후 전용 핸들러 작성 필요.
- 크롬 MCP는 이 세션에 미연결. 네이버웍스 콘솔 작업은 사용자 환경 또는 별도 브라우저 도구 필요.
