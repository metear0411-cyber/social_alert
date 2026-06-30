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


def notify(message):
    """우선순위: 네이버웍스 Bot → 범용 Webhook → 화면 출력."""
    # (A) 네이버웍스 Bot API (자격증명이 모두 있을 때만)
    nw_keys = ["NW_BOT_ID", "NW_CHANNEL_ID", "NW_CLIENT_ID",
               "NW_CLIENT_SECRET", "NW_SERVICE_ACCOUNT", "NW_PRIVATE_KEY"]
    if all(os.getenv(k) for k in nw_keys):
        try:
            send_naver_works(message)
            return "naver_works"
        except Exception as e:
            print(f"[경고] 네이버웍스 발송 실패 → Webhook/출력으로 대체: {e}", file=sys.stderr)

    # (B) 범용 Webhook (테스트/대체용)
    hook = os.getenv("WEBHOOK_URL")
    if hook:
        try:
            payload = {"text": message, "content": {"type": "text", "text": message}}
            r = requests.post(hook, json=payload, timeout=15)
            r.raise_for_status()
            return "webhook"
        except Exception as e:
            print(f"[경고] Webhook 발송 실패 → 화면 출력으로 대체: {e}", file=sys.stderr)

    # (C) 어떤 채널도 없을 때: 로그로 출력 (로컬 점검용)
    print("----- (발송 채널 미설정 / 미리보기) -----")
    print(message)
    return "stdout"


def send_naver_works(message):
    """네이버웍스 Bot 메시지 발송 (JWT로 access token 발급 후 전송)."""
    import time, jwt  # PyJWT 필요 (네이버웍스 사용할 때만)

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
    token_res = requests.post(
        "https://auth.worksmobile.com/oauth2/v2.0/token",
        data={
            "assertion": assertion,
            "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
            "client_id": client_id,
            "client_secret": client_secret,
            "scope": "bot",
        }, timeout=15,
    )
    token_res.raise_for_status()
    access_token = token_res.json()["access_token"]

    msg_url = f"https://www.worksapis.com/v1.0/bots/{bot_id}/channels/{channel_id}/messages"
    r = requests.post(
        msg_url,
        headers={"Authorization": f"Bearer {access_token}",
                 "Content-Type": "application/json"},
        json={"content": {"type": "text", "text": message}}, timeout=15,
    )
    r.raise_for_status()


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
    channel = "stdout"
    for item, kw in hits:
        channel = notify(build_message(item, kw))
        notified.add(item["uid"])

    save_state(notified)
    print(f"신규 {len(hits)}건 발송 완료 (채널: {channel}).")


if __name__ == "__main__":
    main()
