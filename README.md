# Instagram 自動投稿（@boxshokunin）

`posts/` にフォルダを入れておくと、指定した時刻に GitHub Actions が Instagram へ自動で投稿します。

## 投稿の予約のしかた

`posts/` の中に、**「日付_時刻_好きな名前」** のフォルダを作ります（時刻は日本時間）。

```
posts/
  2026-10-20_1900_new-feature/
    1.jpg          ← 画像（JPEGのみ）。複数入れるとカルーセル投稿（最大10枚、名前順）
    2.jpg
    caption.txt    ← キャプション（ハッシュタグもここに書く）
  2026-10-22_1230_reel/
    video.mp4      ← 動画1本だけならリール投稿
    caption.txt
```

- 30分ごとに確認するので、投稿は指定時刻から **0〜30分ほど遅れて** 出ます（GitHubの混雑でさらに遅れることがあります）
- 画像は **JPEG（.jpg）だけ** です。PNGなどは .jpg に変換してください
- 画像の縦横比は **4:5（縦長）〜 1.91:1（横長）** の範囲にしてください
- キャプションは2,200文字まで、ハッシュタグは30個までです
- 投稿が終わると `posted.json` に記録され、同じものが二度投稿されることはありません
- 失敗したら次の回にもう一度試し、3回失敗したら諦めます（理由は `posted.json` の `failed` に残ります）

`examples/` にサンプルがあります。

> ⚠ このリポジトリは **公開（Public）** です。Instagram が画像を取りに来られるようにするためです。
> 予約中の画像やキャプションは、投稿前でも URL を知っている人なら見られます。トークンは Secrets に入れるので公開されません。

## 最初の設定（1回だけ）

### 1. GitHub にリポジトリを作る
1. GitHub で **New repository** → 名前は `insta-autopost` など、**Public** を選んで作成
2. このフォルダの中身をアップロード（push）する

### 2. トークンを Secret に登録する
1. リポジトリの **Settings → Secrets and variables → Actions → New repository secret**
2. Name: `IG_ACCESS_TOKEN`、Secret: Meta の画面で発行した Instagram のトークン
3. 「Add secret」

### 3. 動くか確認する
1. リポジトリの **Actions** タブ →「Instagram 自動投稿」→ **Run workflow**
2. mode で **check** を選んで実行 → ログに「OK: @boxshokunin として投稿できます」と出れば成功

### 4. 投稿内容を確認する（任意）
- 同じく **Run workflow** で mode を **dry-run** にすると、投稿せずに「今投稿されるもの」を表示します

### 5. トークンの自動延長を設定する
トークンは60日で切れるので、「トークン自動延長」が毎月1日と15日に延長します。
延長したトークンで Secret を上書きするために、GitHub のトークン（PAT）が必要です。

1. GitHub 右上のアイコン → **Settings → Developer settings → Personal access tokens → Fine-grained tokens → Generate new token**
2. Repository access: **Only select repositories** → このリポジトリだけ
3. Permissions → Repository permissions → **Secrets: Read and write**
4. 有効期限はできるだけ長く（最長1年）。切れる前に作り直してください
5. 発行したトークンを、手順2と同じ方法で Secret `GH_PAT` として登録
6. **Actions →「トークン自動延長」→ Run workflow** で一度動かして、成功すればOK

## ローカルで試す（任意）

```bash
cp .env.example .env      # .env に IG_ACCESS_TOKEN を書く（.env は GitHub に上がりません）
python post.py --check
python post.py --dry-run --now "2026-10-20 19:00"
```

## 困ったとき

| 症状 | 原因と対処 |
| --- | --- |
| check が `Invalid OAuth access token` | トークンの期限切れか貼り間違い。Meta の画面で再発行して Secret を更新 |
| 投稿が `failed` に入る | `posted.json` の `last_error` を確認。直したら、そのフォルダの `failed` の行を消すと再挑戦します |
| しばらく投稿されない | 60日間リポジトリに動きがないと GitHub が定期実行を止めます。Actions タブで再度有効にしてください |
