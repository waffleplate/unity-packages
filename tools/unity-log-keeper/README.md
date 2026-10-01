# unity-log-keeper

Unity の Editor / Player のログを**上書きされる前に写し取り、日時付きのファイルで残す**常駐ツール。
Unity プロジェクトには何も足さない（パッケージの導入も `manifest.json` の変更も不要）。
その PC で開く全プロジェクトが対象で、Windows と macOS で動く。

Unity のログは再起動で上書きされる。既定の場所の `Editor.log` と `Player.log` は `-prev` の
2 世代まで、`-logFile` で置き場所を変えた `Editor.log` と MPPM（Multiplayer Play Mode）の
仮想プレイヤーのログは 1 世代しか残らない。数日前の不具合を後から調べたいときにはもう無い。

## 前提

- Python 3.10 以降（標準ライブラリだけで動く。`pip install` は不要）

## 導入

このリポジトリを clone し、常駐を登録する。登録すると同時に起動する。

```
python tools/unity-log-keeper/unity_log_keeper.py install
```

- Windows: タスクスケジューラに `unity-log-keeper` というタスクを作る（ログオン時に起動、コンソール窓なし）
- macOS: `~/Library/LaunchAgents/io.github.waffleplate.unity-log-keeper.plist` を置いて launchd に読ませる

登録にはスクリプトの絶対パスが入るので、**clone した場所を動かしたら `install` をやり直す**。

解除:

```
python tools/unity-log-keeper/unity_log_keeper.py uninstall
```

常駐させずに試すなら `run`（Ctrl+C で止まる）。`run --once` は 1 回だけ監視して、写し始めたファイルを表示する。

## 保存先

| OS | 既定の保存先 |
| --- | --- |
| Windows | `%LOCALAPPDATA%\unity-log-keeper\logs` |
| macOS | `~/Library/Logs/unity-log-keeper` |

```
<保存先>/
  <プロジェクト名>/Editor_20260930-120501.log              … -logFile 指定のエディタ
  <プロジェクト名>/Editor-mppm4a0879a2_20260930-121003.log  … MPPM の仮想プレイヤー
  <製品名>/Player-<会社名>_20260930-130000.log              … Player
  <製品名>/Player-<ログ名>_20260930-130500.log              … -logFile 指定の Player（ログ名は指定したファイル名の本体）
  _default/Editor_20260930-090000.log                       … 既定の場所の Editor.log
  _keeper/keeper.log                                        … このツール自身の動作ログ
```

- ファイル名の日時は**写し始めた時刻**（ローカル時刻）。ログの 1 ファイルが、エディタ／Player の 1 回の起動に当たる
- 既定の場所の `Editor.log` は全プロジェクトが同じファイルに書くので、どのプロジェクトのものか決められない。
  そのため `_default` にまとめる。プロジェクトごとに分けたいなら、Unity Hub のプロジェクト設定で
  起動引数に `-logFile "<プロジェクトの絶対パス>\Logs\Editor.log"` を足す
- 製品名が同じで会社名が違う Player（`DefaultCompany/foo` と `MyCompany/foo`）は、ファイル名の会社名で見分ける
- 保存先の合計が上限を超えたら、**更新日時の古いファイルから削除する**（直近 10 分以内に書き込んだファイルは消さない）。
  保存先のフォルダには他のファイルを置かないこと。同じく削除の対象になる

## 設定

設定ファイルは無くても動く。変えたい項目だけを JSON で書く。

| OS | 設定ファイル |
| --- | --- |
| Windows | `%LOCALAPPDATA%\unity-log-keeper\config.json` |
| macOS | `~/Library/Application Support/unity-log-keeper/config.json` |

```json
{
  "dest_dir": "D:/UnityLogs",
  "max_total_mb": 5120,
  "interval_sec": 2.0,
  "discover_interval_sec": 10.0,
  "player_include": ["*"],
  "player_exclude": ["Valve/*", "poncle/*"],
  "extra_globs": ["C:/Builds/MyGame/*.log"]
}
```

| キー | 既定値 | 意味 |
| --- | --- | --- |
| `dest_dir` | 上表 | 保存先 |
| `max_total_mb` | `5120` | 保存先の合計の上限（MB） |
| `interval_sec` | `2.0` | ログファイルを見る間隔（秒） |
| `discover_interval_sec` | `10.0` | 起動中の Unity と Player のログを探し直す間隔（秒） |
| `player_include` | `["*"]` | 写す Player。`会社名/製品名` に対するワイルドカード（大文字小文字は区別しない） |
| `player_exclude` | `[]` | 写さない Player。`player_include` より優先 |
| `extra_globs` | `[]` | 追加で写すファイルのパターン。保存先のフォルダは親フォルダ名、ファイル名はファイル名の本体になる |

**Player は既定で PC 上の全 Unity 製品が対象になる。** 市販のゲームも Unity 製なら `LocalLow`
（macOS は `~/Library/Logs`）にログを書くので、遊んだゲームのログも残る。開発中のものだけにしたいなら
`player_include` を自分の会社名に絞る（例: `["DefaultCompany/*", "MyCompany/*"]`）。

設定を変えたら常駐を再起動する（`uninstall` → `install`）。実際に使われている設定は `show-config` で確認できる。

## 何を監視するか

| 対象 | 見つけ方 |
| --- | --- |
| Editor（既定の場所） | Windows `%LOCALAPPDATA%\Unity\Editor\Editor.log` / macOS `~/Library/Logs/Unity/Editor.log` |
| Editor（`-logFile` 指定） | 起動中の Unity の起動引数から `-projectPath` と `-logFile` を読む。アセットインポートのワーカー（`-batchMode`）は除く |
| MPPM | 見つけたプロジェクトの `Logs/Editor.log-mppm*.txt`。一度見つけたプロジェクトは覚えておき、エディタを閉じた後も見る |
| Player | Windows `%USERPROFILE%\AppData\LocalLow\<会社名>\<製品名>\Player.log` / macOS `~/Library/Logs/<会社名>/<製品名>/Player.log` |
| Player（`-logFile` 指定） | 起動中のプロセスのうち、起動引数に `-logFile` を持ち、Unity のビルドの構成（Windows: 隣に `<名前>_Data` と `UnityPlayer.dll`／macOS: `.app` 内に `UnityPlayer.dylib`）を持つもの。`-batchMode` の Player も含む。`player_include` / `player_exclude` は `<名前>_Data/app.info` の会社名・製品名で判定する |

起動引数には Hub が渡す認証情報（`-accessToken` 等）が含まれる。このツールは `-projectPath` と
`-logFile` だけを取り出し、起動引数をログや保存ファイルに書かない。

## できないこと

- **Play 1 回ごとには分けられない。** 区切りはエディタ／Player の起動単位。Play の開始・終了を知るには
  Unity の中のフックが要り、「プロジェクトに何も足さない」と両立しない
- **写した行に時刻は付けない。** このツールが読んだ時刻では監視間隔ぶんずれるため。Editor は起動引数に
  `-timestamps` を足せば Unity 自身が各行に時刻を付ける
- **常駐が止まっていた間の出力は取れない。** また `-logFile` 指定の Editor と MPPM は、上書きの直前
  （最後の監視から新しい起動が書き始めるまで、最大で監視間隔ぶん）に書かれた末尾を取りこぼしうる。
  既定の場所の Editor と Player は `-prev` へ退避されたファイルからその分を補う
- 古いエディタが終了処理を終える前に新しいエディタが起動すると、`-logFile` のログは
  「新しい起動の出力」「NUL で埋まった未書き込みの領域」「古いエディタの最後の出力」の形になる。
  このツールは NUL の領域の手前で止まって埋まるのを待ち、古いエディタの最後の出力は前の保存ファイルへ回す。
  元の `Editor.log` をエディタで開いて NUL が並んでいても、それは Unity 側の書き方によるもの
- 同じ Player を 2 本同時に起動したときの `Player.log` の混在は、元のファイルのとおりに写る（分けない）
- `-logFile` 指定のエディタ・Player は、起動中のプロセスを探し直す間隔（既定 10 秒）より短く終わると見つけられない。
  `-logFile` が相対パスの場合も対象外（起動した側の作業フォルダが分からないため）
- `LocalLow` の Player は、2 秒以内に起動し直すと間の 1 回分が残らない（`Player-prev.log` へ退避された後、
  次の起動でさらに上書きされる）
- 再起動の判定は「縮んだか」「別のファイルに置き換わったか」「先頭と、前回写し終えた位置の直前が
  一致するか」で行う。上書き後の内容がその位置まで前回とバイト単位で同じなら、続きとして扱ってしまう
- **macOS: 書類・デスクトップ・iCloud Drive の下にあるプロジェクトの MPPM ログは読めない。**
  launchd から起動したプロセスにはこれらのフォルダへのアクセス権が無い。システム設定の
  「プライバシーとセキュリティ > フルディスクアクセス」で Python を許可するか、プロジェクトを
  それ以外の場所に置く。`_keeper/keeper.log` に「読めません」と出ていればこれに当たる

## 困ったとき

- 何が起きているかは `<保存先>/_keeper/keeper.log` を見る。見つけたファイル・写し始め・写し終わり・削除を記録している
- 「既に起動しています」と出たら常駐版が動いている。二重に写さないよう、同時には 1 つしか動かない
