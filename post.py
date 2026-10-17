"""Instagram 予約投稿スクリプト。

posts/ の中のフォルダ（例: 2026-10-20_1900_new-feature）のうち、
投稿時刻（日本時間）を過ぎていて、まだ posted.json に記録がないものを投稿する。

使い方:
    python post.py            # 時刻が来た投稿を実際に投稿する
    python post.py --dry-run  # 投稿せずに、何が投稿されるかだけ表示する
    python post.py --check    # トークンが使えるか確認する
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).resolve().parent
POSTS_DIR = ROOT / "posts"
LOG_FILE = ROOT / "posted.json"

API_VERSION = os.environ.get("IG_API_VERSION", "v23.0")
API_BASE = f"https://graph.instagram.com/{API_VERSION}"

FOLDER_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d{2})(\d{2})(?:_.*)?$")
IMAGE_EXTS = {".jpg", ".jpeg"}
VIDEO_EXTS = {".mp4", ".mov"}
MAX_MEDIA = 10        # カルーセルの上限
MAX_CAPTION = 2200
MAX_HASHTAGS = 30
MAX_ATTEMPTS = 3      # 同じ投稿の失敗がこの回数に達したら諦める
MAX_PER_RUN = 3       # 1回の実行で投稿する最大件数（たまっていても連投しすぎない）


def load_dotenv():
    """ローカル実行用に .env を読み込む（GitHub Actions では Secrets を使う）。"""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def api(method, path, token, params=None):
    query = urllib.parse.urlencode({**(params or {}), "access_token": token})
    url = f"{API_BASE}/{path}"
    data = None
    if method == "GET":
        url += "?" + query
    else:
        data = query.encode()
    req = urllib.request.Request(url, data=data, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Instagram API エラー ({e.code}): {body}") from None


def load_log():
    if LOG_FILE.exists():
        return json.loads(LOG_FILE.read_text(encoding="utf-8"))
    return {"posted": {}, "failed": {}}


def save_log(log):
    LOG_FILE.write_text(json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def scheduled_time(folder_name):
    m = FOLDER_RE.match(folder_name)
    if not m:
        return None
    date, hour, minute = m.groups()
    return datetime.strptime(f"{date} {hour}:{minute}", "%Y-%m-%d %H:%M").replace(tzinfo=JST)


def read_post(folder):
    """フォルダから画像・動画とキャプションを読み、Instagramの制限を確認する。"""
    media = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in IMAGE_EXTS | VIDEO_EXTS
    )
    others = [
        p.name for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in {".png", ".webp", ".heic", ".gif"}
    ]
    caption_file = folder / "caption.txt"
    caption = caption_file.read_text(encoding="utf-8").strip() if caption_file.exists() else ""

    problems = []
    if others:
        problems.append(f"JPEG以外の画像は投稿できません（.jpg に変換してください）: {', '.join(others)}")
    if not media:
        problems.append("画像（.jpg）か動画（.mp4）が入っていません")
    if len(media) > MAX_MEDIA:
        problems.append(f"画像・動画は{MAX_MEDIA}個までです（今は{len(media)}個）")
    if len(caption) > MAX_CAPTION:
        problems.append(f"キャプションは{MAX_CAPTION}文字までです（今は{len(caption)}文字）")
    if caption.count("#") > MAX_HASHTAGS:
        problems.append(f"ハッシュタグは{MAX_HASHTAGS}個までです")
    return media, caption, problems


def public_url(path):
    """GitHub 上の公開URL。Instagram はここから画像・動画を取りに来る。"""
    base = os.environ.get("MEDIA_BASE_URL")
    if not base:
        repo = os.environ.get("GITHUB_REPOSITORY")
        ref = os.environ.get("GITHUB_SHA", "main")
        if not repo:
            raise RuntimeError("MEDIA_BASE_URL か GITHUB_REPOSITORY を設定してください")
        base = f"https://raw.githubusercontent.com/{repo}/{ref}"
    rel = path.relative_to(ROOT).as_posix()
    return f"{base.rstrip('/')}/{urllib.parse.quote(rel)}"


def is_video(path):
    return path.suffix.lower() in VIDEO_EXTS


def create_container(ig_id, token, path, caption=None, carousel_item=False):
    url = public_url(path)
    if is_video(path):
        params = {"media_type": "VIDEO" if carousel_item else "REELS", "video_url": url}
    else:
        params = {"image_url": url}
    if carousel_item:
        params["is_carousel_item"] = "true"
    if caption:
        params["caption"] = caption
    return api("POST", f"{ig_id}/media", token, params)["id"]


def wait_until_ready(container_id, token, timeout=600):
    """動画などの処理が終わるまで待つ。"""
    deadline = time.time() + timeout
    while True:
        status = api("GET", container_id, token, {"fields": "status_code"}).get("status_code")
        if status in (None, "FINISHED", "PUBLISHED"):
            return
        if status in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram側の処理に失敗しました（status: {status}）")
        if time.time() > deadline:
            raise RuntimeError("Instagram側の処理が時間内に終わりませんでした")
        time.sleep(5)


def publish(ig_id, token, media, caption):
    if len(media) == 1:
        container = create_container(ig_id, token, media[0], caption=caption)
    else:
        children = [create_container(ig_id, token, p, carousel_item=True) for p in media]
        for child in children:
            wait_until_ready(child, token)
        container = api("POST", f"{ig_id}/media", token, {
            "media_type": "CAROUSEL",
            "children": ",".join(children),
            "caption": caption,
        })["id"]
    wait_until_ready(container, token)
    return api("POST", f"{ig_id}/media_publish", token, {"creation_id": container})["id"]


def due_posts(now, log):
    if not POSTS_DIR.exists():
        return []
    posts = []
    for folder in sorted(p for p in POSTS_DIR.iterdir() if p.is_dir()):
        when = scheduled_time(folder.name)
        if when is None:
            print(f"スキップ: フォルダ名の形式が違います → {folder.name}（例: 2026-10-20_1900_タイトル）")
            continue
        if when > now or folder.name in log["posted"]:
            continue
        if log["failed"].get(folder.name, {}).get("attempts", 0) >= MAX_ATTEMPTS:
            continue
        posts.append(folder)
    return posts


def main():
    parser = argparse.ArgumentParser(description="Instagram 予約投稿")
    parser.add_argument("--dry-run", action="store_true", help="投稿せずに内容だけ表示する")
    parser.add_argument("--check", action="store_true", help="トークンが使えるか確認する")
    parser.add_argument("--now", help="現在時刻を指定する（テスト用。例: '2026-10-20 19:00'）")
    args = parser.parse_args()

    load_dotenv()
    token = os.environ.get("IG_ACCESS_TOKEN", "")
    if not token and not args.dry_run:
        sys.exit("IG_ACCESS_TOKEN が設定されていません")

    if args.check:
        me = api("GET", "me", token, {"fields": "user_id,username"})
        print(f"OK: @{me['username']} として投稿できます")
        return

    now = (datetime.strptime(args.now, "%Y-%m-%d %H:%M").replace(tzinfo=JST)
           if args.now else datetime.now(JST))
    log = load_log()
    posts = due_posts(now, log)[:MAX_PER_RUN]
    if not posts:
        print(f"{now:%Y-%m-%d %H:%M} 時点で投稿するものはありません")
        return

    ig_id = None
    had_error = False
    for folder in posts:
        media, caption, problems = read_post(folder)
        print(f"\n▼ {folder.name}（{len(media)}個のメディア）")
        if problems:
            for p in problems:
                print(f"  × {p}")
            had_error = True
            if not args.dry_run:
                log["failed"][folder.name] = {"attempts": MAX_ATTEMPTS, "last_error": " / ".join(problems)}
                save_log(log)
            continue

        if args.dry_run:
            for p in media:
                print(f"  - {public_url(p) if os.environ.get('GITHUB_REPOSITORY') or os.environ.get('MEDIA_BASE_URL') else p.name}")
            print("  キャプション:\n    " + caption.replace("\n", "\n    "))
            continue

        try:
            if ig_id is None:
                ig_id = api("GET", "me", token, {"fields": "user_id"})["user_id"]
            media_id = publish(ig_id, token, media, caption)
        except Exception as e:  # 1件の失敗で他の投稿を止めない
            had_error = True
            entry = log["failed"].setdefault(folder.name, {"attempts": 0})
            entry["attempts"] += 1
            entry["last_error"] = str(e)[:500]
            print(f"  × 失敗（{entry['attempts']}/{MAX_ATTEMPTS}回目）: {e}")
        else:
            log["posted"][folder.name] = {"media_id": media_id, "posted_at": datetime.now(JST).isoformat()}
            log["failed"].pop(folder.name, None)
            print(f"  ○ 投稿しました（media_id: {media_id}）")
        save_log(log)

    if had_error:
        sys.exit(1)


if __name__ == "__main__":
    main()
