#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
노리주간보호센터 — 사회복지 공모사업 실시간 알림봇 (1단계 프로토타입)

동작 개요
  1) 지정한 복지 게시판(들)의 최신 목록을 JSON API로 직접 가져온다 (브라우저 불필요)
  2) 제목에 핵심 키워드가 포함된 글만 골라낸다
  3) 이미 알린 글은 state.json 에 기록해 두고 다시 알리지 않는다
  4) 새 공고를 메신저(Webhook / 네이버웍스)로 발송한다

이 파일은 외부 라이브러리로 'requests' 하나만 사용합니다.
환경변수(secrets)로 동작을 제어하므로 코드를 수정할 필요가 거의 없습니다.
"""

import os
import json
import sys
import time
import datetime
import urllib.parse

import requests

# ──────────────────────────────────────────────────────────────────────────
# 1. 감시할 소스(게시판) 목록  ── 여기만 늘리면 소스가 추가됩니다
#    welfare.net 계열은 base/mi/bbsId 세 값만 바꾸면 다른 지부·게시판도 동작합니다.
# ──────────────────────────────────────────────────────────────────────────
SOURCES = [
    {
        "name": "대구사회복지사협회 복지소식",
        "type": "welfare_net",          # 처리 방식(핸들러) 식별자
        "api_base": "https://api.welfare.net/daegu",
        "page_base": "https://www.welfare.net/daegu/community/welfare-news",
        "mi": 5200,                      # 메뉴 ID
        "bbsId": 5208,                   # 게시판 ID (복지소식)
    },
    # ── 나중에 소스를 늘릴 때 예시 (복지소식 외 '공지사항' 등 동일 계열 게시판) ──
    # {
    #     "name": "대구사회복지사협회 공지사항",
    #     "type": "welfare_net",
    #     "api_base": "https://api.welfare.net/daegu",
    #     "page_base": "https://www.welfare.net/daegu/community/notice",
    #     "mi": 5100, "bbsId": 5108,
    # },
]

# ──────────────────────────────────────────────────────────────────────────
# 2. 핵심 키워드 (제목에 하나라도 포함되면 알림)
#    공백은 무시하고 비교하므로 '기능보강'과 '기능 보강'은 동일하게 잡힙니다.
# ──────────────────────────────────────────────────────────────────────────
KEYWORDS = [
    "기능보강", "환경개선", "공모사업", "지원사업", "물품지원",
    # 시설 개선 계열 추가 추천(불필요하면 줄을 지우세요)
    "개보수", "리모델링", "기자재", "가전", "후원물품",
]

STATE_FILE = "state.json"   # 이미 알린 글 ID 저장 파일
KST = datetime.timezone(datetime.timedelta(hours=9))


# ──────────────────────────────────────────────────────────────────────────
# 소스별 수집 핸들러
# ──────────────────────────────────────────────────────────────────────────
def fetch_welfare_net(src):
    """welfare.net 계열 게시판에서 최신 글 목록을 표준 형식으로 반환."""
    url = f"{src['api_base']}/na/ntt/selectNttList.do"
    params = {"mi": src["mi"], "bbsId": src["bbsId"], "currPage": 1}
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; nori-welfare-bot/1.0)",
        "Accept": "application/json",
    }
    resp = requests.get(url, params=params, headers=headers, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    items = []
    for it in (data.get("nttListPaging", {}) or {}).get("list", []) or []:
        ntt_sn = it.get("nttSn")
        title = (it.get("nttSj") or "").strip()
        if not ntt_sn or not title:
            continue
        detail = f"{src['page_base']}/board-detail?nttSn={ntt_sn}"
        items.append({
            "uid": f"{src['bbsId']}-{ntt_sn}",   # 소스 간 충돌 방지용 전역 ID
            "title": title,
            "date": (it.get("regDt") or "").strip(),
            "url": detail,
            "is_notice": (it.get("noticeAt") == "Y"),
            "source": src["name"],
        })
    return items


HANDLERS = {"welfare_net": fetch_welfare_net}


# ──────────────────────────────────────────────────────────────────────────
# 키워드 필터
# ──────────────────────────────────────────────────────────────────────────
def matches_keyword(title):
    flat = title.replace(" ", "")
    for kw in KEYWORDS:
        if kw.replace(" ", "") in flat:
            return kw
    return None


# ──────────────────────────────────────────────────────────────────────────
# 중복 방지 상태 파일
# ──────────────────────────────────────────────────────────────────────────
def load_state():
    if not os.path.exists(STATE_FILE):
        return None  # 최초 실행
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f).get("notified", []))
    except Exception:
        return set()


def save_state(notified_set):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump({"notified": sorted(notified_set)}, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────────────────────────────────
# 알림 발송
#   - 기본: 범용 Webhook (Slack/Discord/Teams/Telegram 등 테스트용으로 즉시 사용)
#   - 네이버웍스 Bot 연동은 자격증명(secrets) 채워지면 자동으로 그쪽으로 발송
# ──────────────────────────────────────────────────────────────────────────
def build_message(item, matched_kw):
    now = datetime.datetime.now(KST).strftime("%Y-%m-%d %H:%M")
    return (
        "📢 [새 공모사업 알림] 주간보호센터 기능보강/환경개선 공고\n"
        f"📌 제목: {item['title']}\n"
        f"🏷️ 매칭 키워드: {matched_kw}\n"
        f"📆 작성일: {item['date']}   |   출처: {item['source']}\n"
        f"📅 확인일시: {now}\n"
        f"🔗 링크: {item['url']}"
    )


NW_KEYS = ["NW_BOT_ID", "NW_CHANNEL_ID", "NW_CLIENT_ID",
           "NW_CLIENT_SECRET", "NW_SERVICE_ACCOUNT", "NW_PRIVATE_KEY"]


def channel_configured():
    """발송 채널(네이버웍스 또는 Webhook)이 하나라도 설정돼 있는지."""
    return all(os.getenv(k) for k in NW_KEYS) or bool(os.getenv("WEBHOOK_URL"))


def post_with_retry(desc, do_request, attempts=3):
    """일시적 오류(네트워크/타임아웃/5xx/429)에 한해 지수 백오프로 재시도.
    4xx 같은 영구 오류는 즉시 올림. 성공 시 응답 객체 반환."""
    for i in range(attempts):
        try:
            r = do_request()
            r.raise_for_status()
            return r
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status not in (429, 500, 502, 503, 504) or i == attempts - 1:
                raise
        except (requests.ConnectionError, requests.Timeout):
            if i == attempts - 1:
                raise
        wait = 2 ** i  # 1, 2, 4초
        print(f"[재시도] {desc} 일시 실패 → {wait}초 후 재시도 ({i + 1}/{attempts})",
              file=sys.stderr)
        time.sleep(wait)


def webhook_payload(url, message):
    """Webhook URL의 호스트를 보고 채널에 맞는 페이로드를 만든다.
    - 디스코드: content(문자열)   - 슬랙/팀즈: text   - 텔레그램: chat_id+text
    - 알 수 없는 채널: text·content 둘 다 문자열로 담아 호환성 최대화."""
    host = (urllib.parse.urlparse(url).netloc or "").lower()
    if "discord" in host:
        return {"content": message}
    if "slack" in host:
        return {"text": message}
    if "office.com" in host or "office365" in host:   # Teams(O365 커넥터)
        return {"text": message}
    if "telegram" in host:
        payload = {"text": message}
        chat_id = os.getenv("TELEGRAM_CHAT_ID")
        if chat_id:                                    # 텔레그램은 chat_id 필수
            payload["chat_id"] = chat_id
        return payload
    # 그 외(미지의 서비스): 가장 흔한 두 키를 문자열로 동시 제공
    return {"text": message, "content": message}


def notify(message):
    """우선순위: 네이버웍스 Bot → 범용 Webhook → 화면 출력.
    반환: (channel, delivered) — delivered=True 면 실제 발송에 성공한 것."""
    # (A) 네이버웍스 Bot API (자격증명이 모두 있을 때만)
    if all(os.getenv(k) for k in NW_KEYS):
        try:
            send_naver_works(message)
            return ("naver_works", True)
        except Exception as e:
            print(f"[경고] 네이버웍스 발송 실패 → Webhook/출력으로 대체: {e}", file=sys.stderr)

    # (B) 범용 Webhook (테스트/대체용)
    hook = os.getenv("WEBHOOK_URL")
    if hook:
        try:
            payload = webhook_payload(hook, message)
            post_with_retry("Webhook 발송", lambda: requests.post(hook, json=payload, timeout=15))
            return ("webhook", True)
        except Exception as e:
            print(f"[경고] Webhook 발송 실패: {e}", file=sys.stderr)

    # (C) 채널 미설정이거나 모든 발송이 실패: 로그로 출력 (로컬 점검용)
    print("----- (발송 채널 미설정 또는 발송 실패 / 미리보기) -----")
    print(message)
    return ("stdout", False)


def send_naver_works(message):
    """네이버웍스 Bot 메시지 발송 (JWT로 access token 발급 후 전송)."""
    import jwt  # PyJWT 필요 (네이버웍스 사용할 때만)

    client_id = os.environ["NW_CLIENT_ID"]
    client_secret = os.environ["NW_CLIENT_SECRET"]
    service_account = os.environ["NW_SERVICE_ACCOUNT"]
    private_key = os.environ["NW_PRIVATE_KEY"]
    bot_id = os.environ["NW_BOT_ID"]
    channel_id = os.environ["NW_CHANNEL_ID"]

    now = int(time.time())
    assertion = jwt.encode(
        {"iss": client_id, "sub": service_account, "iat": now, "exp": now + 3600},
        private_key, algorithm="RS256",
    )
    token_res = post_with_retry(
        "네이버웍스 토큰 발급",
        lambda: requests.post(
            "https://auth.worksmobile.com/oauth2/v2.0/token",
            data={
                "assertion": assertion,
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "bot",
            }, timeout=15,
        ),
    )
    access_token = token_res.json()["access_token"]

    msg_url = f"https://www.worksapis.com/v1.0/bots/{bot_id}/channels/{channel_id}/messages"
    post_with_retry(
        "네이버웍스 메시지 발송",
        lambda: requests.post(
            msg_url,
            headers={"Authorization": f"Bearer {access_token}",
                     "Content-Type": "application/json"},
            json={"content": {"type": "text", "text": message}}, timeout=15,
        ),
    )


# ──────────────────────────────────────────────────────────────────────────
# 메인
# ──────────────────────────────────────────────────────────────────────────
def main():
    prev = load_state()
    first_run = prev is None
    notified = set() if first_run else set(prev)

    # 1) 전 소스 수집
    collected = []
    for src in SOURCES:
        handler = HANDLERS.get(src["type"])
        if not handler:
            print(f"[경고] 알 수 없는 소스 타입: {src['type']}", file=sys.stderr)
            continue
        try:
            collected.extend(handler(src))
        except Exception as e:
            print(f"[경고] 수집 실패 ({src['name']}): {e}", file=sys.stderr)

    # 2) 키워드 매칭 + 신규 여부 판정
    hits = []
    for item in collected:
        kw = matches_keyword(item["title"])
        if kw and item["uid"] not in notified:
            hits.append((item, kw))

    # 3) 최초 실행이면 폭탄 방지: 현재 글을 '확인됨'으로만 기록하고 발송 안 함
    if first_run:
        for item in collected:
            notified.add(item["uid"])
        save_state(notified)
        print(f"[최초 실행] 기준선 설정 완료 — 기존 글 {len(collected)}건 기록(발송 안 함). "
              f"다음 실행부터 신규 공고만 알립니다.")
        return

    # 4) 발송 (오래된 글이 아래로 가도록 작성일 기준 정렬)
    if not hits:
        print("신규 공고 없음.")
        save_state(notified)
        return

    hits.sort(key=lambda x: x[0]["date"])
    configured = channel_configured()
    delivered, failed, channel = 0, 0, "stdout"
    for item, kw in hits:
        channel, ok = notify(build_message(item, kw))
        if ok:
            # 실제 발송 성공 → 기록(중복 방지)
            notified.add(item["uid"])
            delivered += 1
        elif not configured:
            # 채널 미설정(로컬 미리보기) → 재시도 의미 없으니 기록만
            notified.add(item["uid"])
        else:
            # 채널은 있는데 발송 실패 → 기록하지 않음(다음 실행에서 자동 재시도)
            failed += 1

    save_state(notified)
    if failed:
        print(f"신규 {len(hits)}건 중 {delivered}건 발송, {failed}건 실패 — "
              f"실패분은 다음 실행 때 자동 재시도됩니다. (채널: {channel})", file=sys.stderr)
        # 발송 실패가 GitHub Actions 로그에 빨간 X로 보이도록 종료 코드 1
        # (성공분 state.json 은 위에서 이미 저장됨 → 워크플로의 커밋 step은 always() 로 실행)
        sys.exit(1)
    print(f"신규 {delivered}건 발송 완료 (채널: {channel}).")


if __name__ == "__main__":
    main()
