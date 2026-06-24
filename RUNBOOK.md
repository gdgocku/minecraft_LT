# マイクラLT会 当日運営 RUNBOOK

対象: 当日の運営を託される人（issanは不在）
本番日: 2026-06-26 ／ 最終更新: 〔記入〕

## あなたの役割と前提
- issanは当日不在。あなたが進行オペレーターです。
- **VM（サーバー）はissanが事前に起動済み**。普段の操作はマイクラとブラウザだけで完結し、GCPには触りません。
- GCPに触るのは「VMが落ちて戻らない」非常時だけ（§5）。そのための鍵を預かっています。
- **Windowsの人へ**: 当日の操作（マイクラ＋ブラウザ＋ゲーム内チャット）はOSに依存せずそのまま使えます。GCP操作（§5）が必要な非常時だけは **WSL か Git Bash** で実行してください（PowerShell直打ちは不可）。迷ったら Claude Code に任せるのが確実です。

接続先（固定。IPが変わってもこのURLで届きます）:
- マイクラ: `mc.issan.dev:25565`
- スライド管理UI: `https://mc.issan.dev`

## 0. 受け取り物チェック
- [ ] OP権限のあるマイクラアカウントで `mc.issan.dev` に入れる
- [ ] `https://mc.issan.dev` のスライドUIが開ける
- [ ] `mc-lt-operator-key.json`（非常時用の鍵）とこのリポジトリ
- [ ] **gcloud CLI 導入済み**（鍵で認証。個人アカウントのログインは不要）
- [ ] issanと一度リハーサル済み（vm-up→スライド紐付け→送り→vm-down を通した）
- [ ] 当日のデッキ名・登壇順 → §付録

## 1. 開始30分前チェック
1. マイクラで `mc.issan.dev:25565` に接続できる
2. ブラウザで `https://mc.issan.dev` を開く（各デッキが見える）
3. スクリーンに紐付け＆表示: `/slideshow browse` → 出したいデッキのアイテムを取得 → そのアイテムを持って**スクリーンを右クリック**（紐付くと同時に1枚目が表示される）
4. `/slideshow next 〔deck〕` `/slideshow prev 〔deck〕` で送り・戻しできる
5. 確認できたら `/slideshow goto 〔deck〕 0` で先頭に戻して待機

## 2. スライドの登録・差し替え（登壇者ごと）
管理UI `https://mc.issan.dev` で:
1. 上部でデッキを選択（or 新規作成。名前は英数字と `. _ -`）
2. Google Slidesは「共有 = リンクを知る全員が閲覧可」にしてURLを貼り→インポート（または PNG/JPG を直接アップロード）
3. ツールバーの**リサイズ**でスクリーン解像度に合わせる（ブロック数×128。例: 16×7のスクリーンなら 2048×896px）。**サイズ不一致だとプラグインが表示を拒否します**
4. マイクラ側で反映: `/slideshow reload` の後 `/slideshow browse` で確認
- 起動中の差し替えは polling（既定30秒）でも自動反映されます

## 3. 本番の進行操作

### 表示開始（スクリーンへの紐付け）はゲーム内の右クリック
1. `/slideshow browse` でデッキ一覧を開く
2. 出したいデッキのアイテムを取得
3. そのアイテムを持って**スクリーンを右クリック** → 紐付き＆1枚目を表示

### 送り操作は2通り（どちらも同じコマンド体系）

**方法A（推奨・ゲーム内チャット）**: OPでマイクラに入り、チャットに打つ:
```
/slideshow next 〔deck〕         … 次へ
/slideshow prev 〔deck〕         … 戻る
/slideshow goto 〔deck〕 〔番号〕  … 指定ページへ
/slideshow stop 〔deck〕         … 停止
```

**方法B（issan従来のコンソール方式）**: 端末からサーバーコンソールに流す:
```
gcloud compute ssh minecraft-lt --zone=asia-northeast1-b \
  --command 'echo "slideshow next 〔deck〕" > /run/minecraft.stdin'
```
SSHを張りっぱなしにして `cat > /run/minecraft.stdin` を開けば、issanがローカルでやっていた「起動ターミナルに直打ち」と同じ感覚で送れます（1行打つごとにEnterで送信）。
- 方法Bは鍵でSSHが通ることが前提（リハーサルで確認済みのはず）
- ※ 紐付け（browse→右クリック）はプレイヤー操作なので、方法Bでもそこだけはゲーム内で行います

## 4. トラブルシュート（issanは不在。まずここ）
| 症状 | 確認・対処 |
|---|---|
| スライドが画面に出ない | 紐付けが外れた可能性（VM再起動後など）。`/slideshow browse` でデッキのアイテムを取り、**スクリーンを右クリックで再紐付け**（同時に再表示される） |
| マイクラに繋がらない | VM生存を確認（§6）。起動直後ならDNS反映待ち（最大数分） |
| スライドUI(https)が開かない | VM生存を確認。証明書/Caddyの一時不調なら数十秒後に再試行 |
| 画像が「サイズ不一致」で出ない | UIのリサイズボタンでスクリーン解像度に合わせる |
| スライドが古いまま | `/slideshow reload`、またはUIで再アップ後に30秒待つ |

困ったら **Claude Code を開いてこのRUNBOOKを読ませ、症状を伝える**のが速いです。

## 5. 非常時：VMが落ちて戻らない
1. Claude Code を開き「マイクラのVMが落ちた。`gcp/` の手順で復旧して」と依頼（このRUNBOOKと `gcp/README.md` を参照させる）
2. 手動なら:
   ```
   gcloud auth activate-service-account --key-file=mc-lt-operator-key.json   # 初回のみ
   gcloud config set project gdgoc-kyoto-university
   cd gcp && ./vm-up.sh          # 数分待つ
   ```
   表示される `mc.issan.dev:25565` に再接続。**直近10分ごとのバックアップから復元**されます。
3. 復旧後は紐付けが外れているので、§1の手順（browse→右クリック）でやり直す。

## 6. VMが生きているかの確認
```
gcloud auth activate-service-account --key-file=mc-lt-operator-key.json   # 初回のみ
gcloud config set project gdgoc-kyoto-university
gcloud compute instances list          # minecraft-lt が RUNNING か
```

## 7. 終了後
基本はissanが翌日 `vm-down.sh` ＋鍵失効を行うので、**あなたは何もしなくてOK**。
（issanから「終わったら落として」と頼まれた場合のみ `cd gcp && ./vm-down.sh`）

