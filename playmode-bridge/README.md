# Play Mode Bridge

Unity エディタの **Play Mode の状態・画面・終了操作を、ファイル経由で外部から扱えるようにする**
Editor 拡張パッケージ。

外部プロセス（CI・自動化スクリプト・遠隔操作エージェント等）から Unity を扱うとき、
エディタ API を直接叩く経路はエディタのフォーカス状態やコンパイル状態に左右されて当てにならない。
このパッケージは `EditorApplication.update` からファイルを読み書きするだけなので、
**呼び出し側は Read と Write しか使わない**。

## できること

| 機能 | 出力 / 入力 |
| --- | --- |
| Play 中かどうかの判定 | `Library/PlayModeBridge/playmode.json`（Play 中だけ存在する） |
| Game View の撮影 | 要求 `capture.request` → 結果 `capture.result.json` ＋ 画像 `latest.png` |
| Play Mode の終了 | 要求 `exitplay.request` → 結果 `exitplay.result.json` |

出力先を `Library/` にしているのは、Unity 標準の `.gitignore` が既に `Library/` を除外しているため。
**導入したプロジェクトに `.gitignore` を1行も足さずに済む。**

## 収録の基準

機能を足すかどうかは、次の**両方**を満たすかで決める。

1. **エディタが非フォーカス、またはコンパイル保留中でも動く必要がある**
2. **ファイルの読み書きだけで完結する**

裏を返すと、**エディタの対話的な経路（Unity MCP 等）で普通に通る操作は入れない**。
入れ始めるとそちらの劣化コピーになり、どちらを使うべきか判断できなくなる。
シーンやコンポーネントの編集、アセット操作はこのパッケージの領分ではない。

ウィンドウの前面化やプロセスの特定のような**ホストOS側で完結する処理**も入らない。
Unity の中で動く必要がないものは、呼び出し側のツールが持つ。

## 導入

Unity の Package Manager から *Add package from git URL* で次を指定する。

```
https://github.com/waffleplate/unity-packages.git?path=/playmode-bridge#playmode-bridge-v0.1.0
```

`manifest.json` に直接書く場合:

```json
{
  "dependencies": {
    "io.github.waffleplate.playmode-bridge": "https://github.com/waffleplate/unity-packages.git?path=/playmode-bridge#playmode-bridge-v0.1.0"
  }
}
```

タグを省くと既定ブランチのその時点のコミットに解決され、ハッシュが
`Packages/packages-lock.json` に記録される。**タグは付けることを勧める** —
付けないとプロジェクトごとに違うコミットへ固定され、どれがどれだか分からなくなる。

要件: Unity 2021.3 以降。Editor 専用アセンブリなのでビルド成果物には含まれない。

## 使い方

### Play 中かどうかを知る

`Library/PlayModeBridge/playmode.json` の有無で判定する。Play 中だけ存在する。

```json
{
  "isPlaying": true,
  "isPaused": false,
  "isCompiling": false,
  "runInBackground": false,
  "projectPath": "...",
  "productName": "...",
  "unityVersion": "6000.3.21f1",
  "activeScene": "Main",
  "editorPid": 12345,
  "updatedAt": "2026-08-06T14:28:44.1234567+09:00"
}
```

`updatedAt` は 2 秒ごとに更新される**心拍**。エディタがクラッシュするとマーカーが残って
「Play 中」と嘘をつくので、**読み手は `updatedAt` の古さで死んだマーカーを判別すること**。

### Game View を撮る

`Library/PlayModeBridge/capture.request` を置くと、Play 中の Game View が
`latest.png` に書き出される。中身に `1`〜`4` を書くと `superSize` 指定になる（既定 1）。

結果は `capture.result.json` に出る。**画像が存在すること自体が今回の成功を意味する**
（撮影の前に前回の画像を必ず消すため、古い画像を今回の結果として誤読しない）。

```json
{
  "ok": true,
  "imagePath": "...",
  "bytes": 65184,
  "activeScene": "Main",
  "runInBackground": false,
  "error": "",
  "completedAt": "..."
}
```

Scene View ではなく Game View を `ScreenCapture` で撮るので、URP のポストプロセスや UI を
含めた実際の画面が得られる。撮る直前に Game View タブを表に出す（別タブの裏に隠れていると
フレームが進んでいても撮影が完了しないため）。

**`Run In Background` が無効なプロジェクトでは、エディタが非フォーカスだとフレームが進まず
撮影は必ずタイムアウトする**（上限 10 秒）。呼び出し側でエディタを前面化してから要求すること。
このパッケージは `PlayerSettings.runInBackground` を書き換えない — 追跡ファイルである
`ProjectSettings.asset` を触らないため。

### Play Mode を終了する

`Library/PlayModeBridge/exitplay.request` を置くと Play Mode を抜ける。
結果は `exitplay.result.json`（上限 30 秒）。`wasPlaying` が false なら元々 Play 中ではなく、
何もしていない。

Play 中に `.cs` を編集すると、再コンパイルが Play 終了まで保留される設定
（Preferences の *Script Changes While Playing* = *Recompile After Finished Playing*）では
エディタ API 経由の `ExitPlaymode` が「コンパイル中」で弾かれ、停止ボタンを人手で押すまで
復帰できなくなる。**この経路はそこで詰まない**のが存在理由。

進行中であることは `exitplay.pending` という**ファイル**に持つ。Play を抜けるとドメインリロードで
静的フィールドが消えるため、メモリに持つと結果を書く主体が消えて呼び出し側にはタイムアウトしか
見えなくなる。

## ライセンス

MIT
