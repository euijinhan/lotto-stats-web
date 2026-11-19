#!/usr/bin/env python3
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone, timedelta

DATA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "lotto-history.json")
API_URL = "https://www.dhlottery.co.kr/common.do?method=getLottoNumber&drwNo={}"
KST = timezone(timedelta(hours=9))


def fetch_draw(draw_no: int, retries: int = 3, timeout: int = 10):
    url = API_URL.format(draw_no)
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; DropTableLottoBot/1.0)",
        "Accept": "application/json, text/javascript, */*; q=0.01",
    }
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
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
                return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt == retries:
                raise RuntimeError(f"{draw_no}회차 조회 실패: {e}") from e
            time.sleep(0.8 * attempt)
    return None


def load_existing():
    if not os.path.exists(DATA_PATH):
        return []
    with open(DATA_PATH, "r", encoding="utf-8") as f:
        obj = json.load(f)
    return obj.get("draws", [])


def main():
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    draws = load_existing()
    last_no = draws[-1][0] if draws else 0
    print(f"현재 저장된 마지막 회차: {last_no}회")

    new_count = 0
    cur_no = last_no + 1

    while True:
        row = fetch_draw(cur_no)
        if row is None:
            print(f"{cur_no}회차 데이터가 아직 없어 수집을 종료합니다.")
            break
        draws.append(row)
        new_count += 1
        if new_count % 50 == 0:
            print(f"수집 진행 중... {cur_no}회차 완료 (+{new_count}건)")
        cur_no += 1
        time.sleep(0.05)

    if new_count == 0 and os.path.exists(DATA_PATH):
        print("신규 회차가 없어 기존 JSON 파일을 유지합니다.")
        return

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

    print(f"완료: 총 {len(draws)}회차 저장 (신규 +{new_count}건, 최신 {last_row[0]}회 / {last_row[1]})")


if __name__ == "__main__":
    main()
