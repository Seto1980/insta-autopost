"""Instagram のアクセストークンを延長する（有効期限60日 → また60日）。

延長したトークンは new_token.txt に書き出す。
GitHub Actions ではそのファイルを使って Secret を上書きし、すぐ消す。
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

token = os.environ.get("IG_ACCESS_TOKEN", "")
if not token:
    sys.exit("IG_ACCESS_TOKEN が設定されていません")

query = urllib.parse.urlencode({"grant_type": "ig_refresh_token", "access_token": token})
try:
    with urllib.request.urlopen(f"https://graph.instagram.com/refresh_access_token?{query}", timeout=60) as res:
        data = json.load(res)
except urllib.error.HTTPError as e:
    sys.exit(f"トークンの延長に失敗しました ({e.code}): {e.read().decode('utf-8', errors='replace')}")

new_token = data["access_token"]
if os.environ.get("GITHUB_ACTIONS"):
    print(f"::add-mask::{new_token}")  # ログにトークンが出ないように隠す
Path("new_token.txt").write_text(new_token, encoding="utf-8")
print(f"トークンを延長しました（あと約{int(data.get('expires_in', 0)) // 86400}日有効）")
