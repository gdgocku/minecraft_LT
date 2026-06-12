# GCP 運用スクリプト

ディスク常駐コストを避けるため、永続データはすべて `gs://minecraft_lt` に置き、
VM は遊ぶときだけ作って終わったら丸ごと削除する構成。

```
gs://minecraft_lt/
├── server/      # Paper サーバー一式（world, plugins, jar, JDK runtime 含む）
├── slideshow/   # slideshow_endpoint.py と slides/
└── ops/         # startup-script.sh, save-to-bucket.sh
```

## 初回セットアップ

```bash
./upload-initial.sh   # ローカルのサーバー一式をバケットへ
```

※ ローカルの `runtime/`（Linux 用 JDK 25）ごとアップロードするので、VM 側で
Java のインストールは不要。

## 普段の使い方

```bash
./vm-up.sh     # VM 作成 → 自動でバケットから復元・起動（数分）
./vm-down.sh   # ワールドをバケットへ保存 → VM とディスクを完全削除
```

起動後の接続先は `vm-up.sh` が表示する（Minecraft: 25565, スライド: 8765）。

## 仕組み

- VM は `--metadata=startup-script-url` でバケット上の `startup-script.sh` を実行し、
  `/opt/minecraft/` に復元して systemd で `minecraft` / `slideshow` を起動する。
- 10 分ごとに `save-to-bucket.sh` が world・plugins・設定・slides をバケットへ rsync
  （Spot VM のプリエンプション対策）。
- `systemctl stop minecraft` 時も `ExecStopPost` で必ずバケットへ保存される。
- デフォルトは Spot VM（`config.sh` の `PROVISIONING=standard` で通常 VM に変更可）。
  ゾーンやマシンタイプも `config.sh` で変更。

## ローカルに世界を戻す

```bash
./pull-from-bucket.sh
```
