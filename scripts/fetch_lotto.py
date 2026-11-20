#!/usr/bin/env python3
"""
동행복권 로또 당첨 번호 초기 전체 수집 및 증분 업데이트 스크립트.
- 1순위: 동행복권 공식 API (한국 IP 환경에서 고속 수집)
- 2순위: 네이버 검색 결과 파싱 (GitHub Actions 등 해외 IP에서 동행복권 차단 시 자동 전환)
- data/lotto-history.json 파일이 없으면 1회차부터 최신 회차까지 전체 수집합니다.
- 기존 파일이 있으면 lastDrawNo 이후(lastDrawNo + 1 ~)의 새 회차만 증분 수집합니다.
- 저장 포맷(경량 배열): [회차, "YYYY-MM-DD", n1, n2, n3, n4, n5, n6, 보너스]
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)

DATA_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data",
    "lotto-history.json",
)
DHLOTTERY_URL = "https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={}"
NAVER_SEARCH_URL = "https://search.naver.com/search.naver?where=nexearch&query={}"
KST = timezone(timedelta(hours=9))
FIRST_DRAW_DATE = date(2002, 12, 7)


def calc_draw_date(draw_no: int) -> str:
    return (FIRST_DRAW_DATE + timedelta(days=(draw_no - 1) * 7)).strftime("%Y-%m-%d")


def fetch_from_dhlottery(draw_no: int, timeout: int = 4):
    url = DHLOTTERY_URL.format(draw_no)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; DropTableLottoBot/1.0)",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        if data.get("returnValue") == "success":
            return [
                int(data["drwNo"]),
                str(data["drwNoDate"]),
                int(data["drwtNo1"]),
                int(data["drwtNo2"]),
                int(data["drwtNo3"]),
                int(data["drwtNo4"]),
                int(data["drwtNo5"]),
                int(data["drwtNo6"]),
                int(data["bnusNo"]),
            ]
        return "NOT_FOUND"


def _query_naver(query_text: str, draw_no: int, timeout: int = 10):
    query = urllib.parse.quote(query_text)
    url = NAVER_SEARCH_URL.format(query)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("utf-8", errors="ignore")

    # 현재 페이지가 요청한 회차 결과인지 검증 (미추첨 회차 요청 시 최신 회차가 뜨는 것 방지)
    m_round = re.search(r'class=["\']_lotto-btn-current["\'][^>]*>.*?(\d+)\s*회', html, re.S)
    if not m_round:
        m_round = re.search(r'<a[^>]*class=["\'][^"\']*select[^"\']*["\'][^>]*>\s*(\d+)\s*회', html)
    if not m_round:
        m_round = re.search(r'(\d+)회차\s*당첨번호', html)
    if not m_round or int(m_round.group(1)) != draw_no:
        return "NOT_FOUND"

    m_win = re.search(r'class=["\'][^"\']*winning_number[^"\']*["\'][^>]*>(.*?)</div>', html, re.S)
    m_bonus = re.search(r'class=["\'][^"\']*bonus_number[^"\']*["\'][^>]*>(.*?)</div>', html, re.S)
    if not m_win or not m_bonus:
        raise RuntimeError(f"{draw_no}회차 네이버 HTML 파싱 실패")

    win_nums = [int(n) for n in re.findall(r'<span[^>]*class=["\'][^"\']*ball[^"\']*["\'][^>]*>\s*(\d+)\s*</span>', m_win.group(1))]
    bonus_nums = [int(n) for n in re.findall(r'<span[^>]*class=["\'][^"\']*ball[^"\']*["\'][^>]*>\s*(\d+)\s*</span>', m_bonus.group(1))]

    if len(win_nums) != 6 or len(bonus_nums) != 1:
        raise RuntimeError(f"{draw_no}회차 번호 추출 개수 오류: win={win_nums}, bonus={bonus_nums}")

    m_date = re.search(r'\((\d{4})\.(\d{2})\.(\d{2})\.\)', html)
    draw_date = f"{m_date.group(1)}-{m_date.group(2)}-{m_date.group(3)}" if m_date else calc_draw_date(draw_no)

    return [draw_no, draw_date] + win_nums + [bonus_nums[0]]


def fetch_from_naver(draw_no: int, timeout: int = 10):
    # "로또 645회 당첨번호"는 "로또 6/45" 게임명과 혼동되어 최신 회차가 반환되므로 "제N회" 형식을 우선 사용
    res = _query_naver(f"로또 제{draw_no}회 당첨번호", draw_no, timeout=timeout)
    if res == "NOT_FOUND":
        res = _query_naver(f"{draw_no}회 로또 당첨번호", draw_no, timeout=timeout)
    return res


def fetch_draw(draw_no: int, use_naver_only: bool = False):
    if not use_naver_only:
        try:
            res = fetch_from_dhlottery(draw_no)
            return (None if res == "NOT_FOUND" else res), False
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
            print(f"{draw_no}회차: 동행복권 API 응답 없음 → 네이버 검색 소스로 자동 전환합니다.")
            use_naver_only = True

    today_kst = datetime.now(KST).strftime("%Y-%m-%d")
    is_past_draw = calc_draw_date(draw_no) < today_kst

    for attempt in range(1, 6):
        try:
            res = fetch_from_naver(draw_no)
            if res == "NOT_FOUND" and is_past_draw and attempt < 4:
                time.sleep(1.5 * attempt)
                continue
            return (None if res == "NOT_FOUND" else res), use_naver_only
        except urllib.error.HTTPError as e:
            if e.code in (403, 429, 503):
                wait_sec = 15 * attempt
                print(f"{draw_no}회차: HTTP {e.code} 일시 제한 → {wait_sec}초 대기 후 재시도 ({attempt}/5)")
                time.sleep(wait_sec)
                if attempt == 5:
                    raise RuntimeError(f"{draw_no}회차 조회 실패: {e}") from e
                continue
            if attempt == 5:
                raise RuntimeError(f"{draw_no}회차 조회 실패: {e}") from e
            time.sleep(2.0 * attempt)
        except (urllib.error.URLError, TimeoutError, OSError, RuntimeError) as e:
            if attempt == 5:
                raise RuntimeError(f"{draw_no}회차 조회 실패: {e}") from e
            time.sleep(2.0 * attempt)

    return None, use_naver_only


def load_existing():
    if not os.path.exists(DATA_PATH):
        return []
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        obj = json.load(f)
    return obj.get("draws", [])


def save_draws(draws):
    draws.sort(key=lambda x: x[0])
    last_row = draws[-1]
    payload = {
        "updatedAt": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S KST"),
        "lastDrawNo": last_row[0],
        "lastDrawDate": last_row[1],
        "totalCount": len(draws),
        "draws": draws,
    }
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    return last_row


def _fetch_paced(draw_no: int, use_naver_only: bool):
    row, used_naver = fetch_draw(draw_no, use_naver_only=use_naver_only)
    time.sleep(0.35 if used_naver else 0.05)
    return row, used_naver


def main():
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    draws = load_existing()
    existing_nos = {row[0] for row in draws}
    last_no = draws[-1][0] if draws else 0
    print(f"현재 저장된 마지막 회차: {last_no}회 (총 {len(draws)}건)")

    est_latest = (datetime.now(KST).date() - FIRST_DRAW_DATE).days // 7 + 1
    new_count = 0
    cur_no = last_no + 1
    use_naver_only = False

    try:
        # 첫 회차로 동행복권 API 접근 가능 여부를 먼저 판별
        if cur_no <= est_latest:
            row, use_naver_only = fetch_draw(cur_no, use_naver_only=False)
            if row is not None:
                if row[0] not in existing_nos:
                    draws.append(row)
                    existing_nos.add(row[0])
                    new_count += 1
                cur_no += 1
            else:
                est_latest = cur_no - 1

        # 밀린 회차가 많을 경우(예: 10회 이상) 2개 스레드 + 완만한 간격으로 안전 수집
        bulk_end = est_latest - 1
        if cur_no <= bulk_end and (bulk_end - cur_no + 1) >= 10:
            targets = [n for n in range(cur_no, bulk_end + 1) if n not in existing_nos]
            print(f"안정 병렬 수집 시작 (2스레드): {targets[0]}회 ~ {targets[-1]}회 ({len(targets)}건)")
            done_cnt = 0
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = {executor.submit(_fetch_paced, n, use_naver_only): n for n in targets}
                for fut in as_completed(futures):
                    n = futures[fut]
                    row, _ = fut.result()
                    if row is not None and row[0] not in existing_nos:
                        draws.append(row)
                        existing_nos.add(row[0])
                        new_count += 1
                    elif row is None:
                        print(f"경고: {n}회차 데이터를 찾지 못했습니다.")
                    done_cnt += 1
                    if done_cnt % 50 == 0 or done_cnt == len(targets):
                        print(f"병렬 수집 진행 중... {done_cnt}/{len(targets)}건 완료")
            cur_no = bulk_end + 1

        # 최신 회차 부근은 순차 확인하여 미추첨 회차에서 정확히 종료
        while True:
            if cur_no in existing_nos:
                cur_no += 1
                continue
            row, use_naver_only = fetch_draw(cur_no, use_naver_only=use_naver_only)
            if row is None:
                print(f"{cur_no}회차 데이터가 아직 없어 수집을 종료합니다.")
                break
            draws.append(row)
            existing_nos.add(row[0])
            new_count += 1
            if new_count % 50 == 0:
                print(f"수집 진행 중... {cur_no}회차 완료 (+{new_count}건)")
            cur_no += 1
            time.sleep(0.35 if use_naver_only else 0.05)
    finally:
        if new_count > 0 and draws:
            last_row = save_draws(draws)
            print(f"저장 완료: 총 {len(draws)}회차 (신규 +{new_count}건, 최신 {last_row[0]}회 / {last_row[1]})")
        elif os.path.exists(DATA_PATH):
            print("신규 회차가 없어 기존 JSON 파일을 유지합니다.")


if __name__ == "__main__":
    main()
