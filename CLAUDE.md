# CLAUDE.md

マイクラ内でLT（ライトニングトーク）会を開くためのリポジトリ。Paperサーバー＋スライド表示プラグイン＋スライド配信エンドポイントを、GCP上で必要なときだけ動かす構成。

## 構成
- `plugins/Slideshow/` — スライド表示プラグイン（Maven）。`mvn -f plugins/Slideshow/pom.xml package` → `target/*.jar`。`MediaPlayer` に依存。
- `plugins/MediaPlayer/` — サードパーティ（別gitリポジトリ。`.gitignore`）。スクリーン/マップ描画の土台。
- `servers/minecraft_LT/` — Paperサーバー実体。`./start.sh` で起動（同梱 `runtime/` の JDK25 を使用）。world/jar/runtime等は `.gitignore`。
- `slideshow-endpoint/` — スライド画像を配信するPythonサーバー（既定 `:8765`）。`./start-slides.sh` で起動。`http://127.0.0.1:8765/` が管理UI（デッキ管理・Google Slidesインポート・リサイズ）。
- `gcp/` — VMを必要時だけ作って消す運用。`README.md` 参照。基本は `vm-up.sh` / `vm-down.sh`。永続データは `gs://minecraft_lt`、入口は `mc.issan.dev`（起動時にDNSとTLSを自動構成）。

## スライド運用の現行仕様（誤りやすい・重要）
- デッキは endpoint の `decks.json` から自動発見され `/slideshow browse` に出る。`config.yml` への手書きは不要。
- **スクリーンへの紐付けは「`/slideshow browse` でデッキのアイテムを取得 → スクリーンを右クリック」が現行の方法**。`/slideshow screen` コマンドや `config.yml` の `screen-uuid` による永続化は使わない。紐付けはメモリ上のみで、VM再起動で外れる → そのときは右クリックでやり直す。
- 進行コマンド `start` / `stop` / `next` / `prev` / `goto` はサーバーコンソール（`/run/minecraft.stdin`）からも、OPのゲーム内チャットからも実行可。`browse` / `menu` / `wand` / `screen` はプレイヤー専用。

## LT会当日の運営（オーナー不在で他者に託す場合）
- 託す人向けの当日マニュアル: **`RUNBOOK.md`**
- オーナーの事前準備: **`OWNER-PREP.md`**
- 非常時（VMが落ちた等）の復旧を頼まれたら: `gcp/README.md` の手順に従い、預かった `gcp/mc-lt-operator-key.json` で認証 → `cd gcp && ./vm-up.sh`。数分後 `mc.issan.dev:25565` に再接続し、スライドは browse→右クリックで紐付け直す。
