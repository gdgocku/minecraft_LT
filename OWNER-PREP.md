
# オーナー事前準備（issan用）

当日(2026-06-26)は不在。本人がいる今日〜前日に、ここを上から順にやれば託せる。
託す人の当日マニュアルは `RUNBOOK.md`。

## 今日(6/24) — 認証とリハーサルは本人がいるうちに
### 1. 操作用の鍵を発行
```
cd gcp && ./grant-operator-access.sh
```
→ `gcp/mc-lt-operator-key.json` が出来る（最小権限: VM作成/削除・`gs://minecraft_lt`の読み書きのみ。git管理外）。

### 2. 託す人の実機でリハーサル（最重要）
託す人のマシン（gcloud ＋ このリポジトリ）で:
```
gcloud auth activate-service-account --key-file=mc-lt-operator-key.json
gcloud config set project gdgoc-kyoto-university
cd gcp && ./vm-up.sh            # 数分待つ → mc.issan.dev:25565 に接続
```
- ゲーム内: `/slideshow browse` → アイテム取得 → スクリーン右クリックで紐付け → `/slideshow next 〔deck〕`
- 方法B(コンソール)も通るか確認:
  ```
  gcloud compute ssh minecraft-lt --zone=asia-northeast1-b \
    --command 'echo "slideshow next 〔deck〕" > /run/minecraft.stdin'
  ```
- 落とす: `./vm-down.sh`

→ 権限不足やSSH不通が出たら、**本人がいる今日のうちに**直す（grantのロール追加→再発行など）。当日に持ち越さない。

### 3. 鍵を安全に渡す
- 公開チャット・gitに置かない（`.gitignore`済み）。1Password共有／暗号化／対面USB等で。

## 〜前日(6/25) — コンテンツ準備
### 4. スライドを用意（ローカルで作ってバケットへ）
```
cd slideshow-endpoint && ./start-slides.sh        # 別端末で起動
# ブラウザ http://127.0.0.1:8765/ で登壇者ごとにデッキ作成
#   → Google Slidesインポート / 画像アップ → リサイズでスクリーン解像度に合わせる
cd gcp && ./upload-initial.sh                      # バケットに反映
```
- 当日までに揃わない分は、当日 託す人がUIで追加してもOK。

### 5. スクリーンの確認
- 会場ワールドに登壇用スクリーン（MediaPlayer）が設置済みか確認。無ければゲーム内で設置し、`upload-initial.sh` でワールドごとバケットへ。
- 紐付け自体は当日 託す人が browse→右クリックでやるので事前準備は不要。

### 6. RUNBOOKの付録を記入
- `RUNBOOK.md` 末尾の進行表（登壇順・デッキ名・スクリーン）を埋める。

## 前日夜〜当日朝 — 箱を立てて渡す
### 7. 通常VMで起動（プリエンプション回避）
```
cd gcp && PROVISIONING=standard ./vm-up.sh
```
- 表示される `mc.issan.dev:25565` / `https://mc.issan.dev` を託す人へ（DNSは自動更新）。
- 「`RUNBOOK.md` を読んで」と伝える。

## 終了後（翌日でOK）
```
cd gcp && ./vm-down.sh                 # 保存して削除
cd gcp && ./revoke-operator-access.sh  # 鍵を失効
```
- 託す人に渡した鍵ファイルの削除も依頼。

