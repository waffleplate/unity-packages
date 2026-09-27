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

出力先が `Library/` なので、**導入したプロジェクトに `.gitignore` を1行も足さずに済む**。

## MCP が `COMPILATION_IN_PROGRESS` を返し続けるとき

Play 中に `.cs` が取り込まれると、*Script Changes While Playing* が
*Recompile After Finished Playing* の設定では再コンパイルが Play 終了まで保留される。
この状態では Unity MCP の呼び出しが**内容によらず**弾かれ、脱出手段の `ExitPlaymode` も
同じゲートに掛かるため、エディタ API 経由では復帰できない。

**`Library/PlayModeBridge/exitplay.request` を置けば抜けられる。** この経路は
`EditorApplication.update` から回っていてコンパイルのゲートの外側にあり、
保留コンパイルで張り付いた状態から復帰できる（実測 14.5 秒）。
詳細は後述の「Play Mode を終了する」。

**置く前に「自分が始めた Play か」を確かめること。** マーカーは Play の所有者を持たないので、
同じプロジェクトを複数のセッションが開いていると、抜けさせた先が他人の撮影や計測ということが起きる。

- **自分が Play を始めた** → そのまま `exitplay.request` を置いてよい
- **自分は始めていない / 分からない** → 止めると他人の作業が終わる。停止の可否を人に確認すること。
  ただし**待っても解けない**。保留コンパイルはプロジェクト単位でゲートを閉じるので、Play を
  持たない側はリトライを何度重ねても復旧できず、誰かが Play を抜けるまで閉じたままになる
  （実測では巻き添え側は脱出口に辿り着かず、Play を持っていたセッションが抜けた副作用で
  4 分 16 秒後にようやく復旧した）

**この状態は Play 中に誰も編集していなくても起きる。** Edit Mode で書かれた `.cs` が
エディタ非フォーカスのため未取り込みで残っていると、Play 開始をきっかけに取り込みが走り、
その分の再コンパイルが Play 終了まで保留される。Play 開始直前に
`EditorApplication.isCompiling` を見ても、取り込みがまだ始まっていないので false のままになる。

## 導入

Unity の Package Manager から *Add package from git URL* で次を指定する。

```
https://github.com/waffleplate/unity-packages.git?path=/playmode-bridge#playmode-bridge-v0.3.0
```

`manifest.json` に直接書く場合:

```json
{
  "dependencies": {
    "io.github.waffleplate.playmode-bridge": "https://github.com/waffleplate/unity-packages.git?path=/playmode-bridge#playmode-bridge-v0.3.0"
  }
}
```

**タグは付けることを勧める** — 省くと既定ブランチのその時点のコミットに解決され、
プロジェクトごとに違うコミットへ固定される。

Editor 専用アセンブリなのでビルド成果物には含まれない。

**バッチモード（`-batchMode`）では動作しない。** エディタが起動するアセットインポート用ワーカーも
バッチモードの Unity プロセスで、そこでこのパッケージが動くとエディタ本体の出力を壊すため
（v0.2.0 で修正、詳細は `CHANGELOG.md`）。

これで失うものは無い。`-batchmode` では `EditorApplication.update` が回らず、**この制限が無くても
要求は処理されない**（ガードを外した状態で 12 秒間実行し、要求ファイルが消費されないことを実測）。
CI の `-batchmode -executeMethod` からは元から使えない。

**動作確認: Unity 6000.3.21f1 (Windows)**。`package.json` の下限は 2021.3 としているが、これは
使用している API（`EditorApplication` / `ScreenCapture` / `EditorSceneManager`）がそれ以前から
存在することによる宣言で、古いバージョンでの実測ではない。

## 使い方

### Play 中かどうかを知る

`Library/PlayModeBridge/playmode.json` の有無で判定する。Play 中だけ存在する
（ただし有無だけで即断しないこと。後述の閾値と注意を読むこと）。

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
  "exitRequestPath": "C:\\path\\to\\project\\Library\\PlayModeBridge\\exitplay.request",
  "updatedAt": "2026-08-06T14:28:44.1234567+09:00"
}
```

`exitRequestPath` は Play Mode を抜けるための要求ファイルの置き場所（v0.3.0 で追加）。
このファイルを空で作れば Play が終わる。marker を読んだ時点で脱出口に気づけるように、
値としても持たせている。**区切り文字は OS のもの**（Windows なら `\`）なので、
`/` 前提でパスを分割・比較しないこと。

`updatedAt` は 2 秒ごとに更新される**心拍**。エディタがクラッシュするとマーカーが残って
「Play 中」と嘘をつくので、**読み手は `updatedAt` の古さで死んだマーカーを判別すること**。

**閾値は 10 秒を推奨する** — `updatedAt` が現在時刻より 10 秒以上古ければ死んだマーカーと見なす。

根拠は実測（Unity 6000.3.21f1 / Windows）。心拍間隔を n=199 回、約 400 秒分ぶん観測した結果は
次のとおりで、10 秒は実測上限の約 5 倍にあたる。

| 条件 | n | p50 | max |
| --- | --- | --- | --- |
| `Run In Background` 有効 | 161 | 2.005 | 2.012 |
| `Run In Background` 無効 | 38 | 2.091 | 2.100 |

**エディタが非フォーカスでも心拍は乱れない。** 心拍は `EditorApplication.update` に乗っており、
Player のループを止める `Run In Background` の影響をほとんど受けない（無効時に約 90ms 遅くなるだけ）。
これは撮影とは対照的で、撮影の方は非フォーカスだとフレームが進まず必ず失敗する（後述）。

閾値を心拍間隔ぎりぎり（2〜3 秒）に詰めないこと。OS のスケジューリング・ディスク I/O・読み手自身の
ポーリング周期がそれぞれ数百 ms 単位で効くため、生きている Play を死んだと誤判定する。

#### 不在の判定は 1 回で決めない

v0.2.0 未満には、Play 中にマーカーが約 1.4 秒消える不具合があった（アセットインポート用ワーカーが
消していた。詳細は `CHANGELOG.md`）。v0.2.0 で原因を塞ぎ、加えて Play 中は 0.2 秒ごとに実ファイルを
確認して消えていれば書き直すようにしたので、**現在は Play 中に消えることは確認されていない**。

それでも、不在が意味を持つ判定をするなら **0.5 秒以上あけて 2 回以上連続で不在を確認する**ことを勧める。
書き込みは瞬間的に行われるため、読み手のタイミング次第では過渡状態を踏み得る。

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

Scene View ではなく Game View を撮るので、URP のポストプロセスや UI を含めた実際の画面が
得られる。撮る直前に Game View タブを表に出す（別タブの裏に隠れているとフレームが進んでいても
撮影が完了しないため）。

**`Run In Background` が無効なプロジェクトでは、エディタが非フォーカスだとフレームが進まず
撮影は必ずタイムアウトする**（上限 10 秒）。呼び出し側でエディタを前面化してから要求すること。
このパッケージは `PlayerSettings.runInBackground` を書き換えない。

### Play Mode を終了する

`Library/PlayModeBridge/exitplay.request` を置くと Play Mode を抜ける。
結果は `exitplay.result.json`（上限 30 秒）。`wasPlaying` が false なら元々 Play 中ではなく、
何もしていない。

Play 中に `.cs` を編集すると、再コンパイルが Play 終了まで保留される設定
（Preferences の *Script Changes While Playing* = *Recompile After Finished Playing*）では
エディタ API 経由の `ExitPlaymode` が「コンパイル中」で弾かれる。Unity MCP からは
`COMPILATION_IN_PROGRESS` として見え、待っても解けない（Play を抜けるまで保留され続けるため）。
**この経路はそこで詰まない**のが存在理由。

## ライセンス

MIT
