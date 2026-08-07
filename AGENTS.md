# AGENTS.md

本リポジトリ `unity-packages` で作業する AI コーディングエージェント向けのプロジェクト固有指示の**正本**。

## プロジェクト概要

- **プロジェクト名**: unity-packages
- **概要**: Waffle-Plate が公開する Unity Editor 拡張パッケージのモノレポ。1 パッケージ 1 フォルダで、
  UPM の `?path=` でフォルダを直接指して導入する。
- **リポジトリ**: https://github.com/waffleplate/unity-packages
- **収録パッケージ**: [playmode-bridge](playmode-bridge) — `io.github.waffleplate.playmode-bridge`

**ここは配布用パッケージだけを置くリポジトリで、Unity プロジェクトではない。**
`Assets/` も `ProjectSettings/` も無く、このリポジトリ単体では Unity で開けない。
動作確認は、パッケージを導入した側の Unity プロジェクトで行う。

## ここに置くもの / 置かないもの

**Unity プロセスの中で動く必要があるものだけ**を置く。`EditorApplication` や `ScreenCapture` の
ようなエディタ API が要るかどうかが判断基準。

ホストOS側で完結する処理（ウィンドウの前面化、プロセスの特定、外部サービスへのアップロード等）は、
Unity の中で動く理由がないのでここには入らない。呼び出し側のツールが持つ。

## エディタ本体以外のプロセスで動かさない

`[InitializeOnLoad]` や `EditorApplication.update` は、**エディタ本体だけでなく、エディタが起動する
アセットインポート用ワーカー（`-adb2 -batchMode` の子プロセス）でも走る**。ワーカーでは
`EditorApplication.isPlaying` が常に false で、ワーカーのログも別ファイル
（`Logs/AssetImportWorker<N>.log`）に出るため、本体のログを見ている限り原因が分からない。

エディタ本体の状態を前提に副作用（ファイルの書き込み・削除）を持つ処理は、
`if (Application.isBatchMode) return;` で無効にすること。

起動引数（`-adb2` / `-parentPid`）でワーカーだけを狙い撃つ判定も書けるが、**採らない**。
公開仕様ではないので検出漏れの余地があり、外したときの結果が「本体の出力を壊す」側になる。
また `-batchMode` では `EditorApplication.update` が回らない（実測）ので、一律に止めても失うものが無い。

実例: playmode-bridge v0.1.1 で、ワーカーがエディタ本体の書いたマーカーを削除していた
（Play 中に 1.4 秒間「Play していない」と見えた）。

## Play 中かどうかを静的フィールドで覚えない

ドメインリロードで静的フィールドは初期値に戻る。Play の開始・終了の前後でリロードが入るかは
プロジェクトの Enter Play Mode Settings 次第なので、**リロードを挟んでも壊れない判定**にすること。

`EditorApplication.isPlaying` は `ExitingPlayMode` の時点でもまだ true である点に注意。
「Play 中で、かつ抜け始めてもいない」は `isPlaying && isPlayingOrWillChangePlaymode` で表す
（突入時は `isPlaying=false / willChange=true`、終了時は `isPlaying=true / willChange=false`）。

## 命名規則

- **フォルダ名**: パッケージ名の末尾セグメント（例: `playmode-bridge`）
- **パッケージ名**: `io.github.waffleplate.<フォルダ名>`（逆ドメイン記法の根拠は GitHub 組織
  `waffleplate` ＝ `waffleplate.github.io`）
- **タグ**: `<フォルダ名>-vX.Y.Z`（例: `playmode-bridge-v0.1.0`）。タグはリポジトリ全体の
  スナップショットになるため、どのパッケージのリリースかが名前で分かるようにする
- **C# 名前空間**: `WafflePlate.<PascalCase>`（名前空間は逆ドメイン記法の対象外）
- **アセンブリ定義**: `WafflePlate.<PascalCase>.Editor`（Editor 専用アセンブリ）

### 名義

公開物に出る名前は 2 系統ある。混ぜない。

| 用途 | 表記 |
| --- | --- |
| 屋号 / 組織（README の主語、GitHub org） | `Waffle-Plate`（org・パッケージ名は `waffleplate`、C# は `WafflePlate`） |
| 著作権者（`LICENSE` / `package.json` の `author`） | `waffle_maker` |

## 新しいパッケージを足すとき

1. リポジトリ直下に**命名規則どおりのフォルダ**を作る
2. `package.json`（`name` / `version` / `displayName` / `description` / `unity` / `license` /
   `documentationUrl` / `author`）を置く
3. `README.md` / `CHANGELOG.md` / `LICENSE.md` を**パッケージフォルダ直下に**置く
4. ルート `README.md` の収録パッケージ表に 1 行足す
5. リリース時に `<フォルダ名>-vX.Y.Z` タグを打ち、`CHANGELOG.md` に節を追加する

**`LICENSE.md` をパッケージ内に置くのは必須。** UPM は `?path=` 指定でそのサブフォルダだけを
取得するため、リポジトリルートの `LICENSE` は配布物に含まれない。パッケージ内に無いと、
導入者はライセンス条文が同梱されていないコードを受け取ることになる。
`CHANGELOG.md` も Package Manager UI がパッケージ単位で参照する。

## .meta ファイルの規則

`.meta` はパッケージの一部なので**必ずコミットする**。導入先ではパッケージが immutable
フォルダに置かれ、Unity は `.meta` を生成できないため、欠けると導入先のコンソールに
次の警告が出続ける（実測: 未対応の状態で 1 セッション 25 回）:

```
Asset Packages/<パッケージ名>/README.md has no meta file, but it's in an immutable folder.
The asset will be ignored.
```

| 対象 | `.meta` | 備考 |
| --- | --- | --- |
| 通常のファイル・フォルダ（`.cs` / `.asmdef` / `package.json`） | **要る** | |
| ルート直下の `.md`（`README` / `CHANGELOG` / `LICENSE` / `Third Party Notices`） | **要る** | `TextScriptImporter` |
| `~` で終わる・`.` で始まるフォルダの中身 | **置かない** | Unity が無視する領域。置くと警告 |
| `Documentation~/` の中身 | **置かない** | 置くと警告ではなく**エラー** |
| `Samples~/` の中身 | **要る** | `~` 付きだが例外。インポート時にコピーされるため |

`.md` の `.meta` の中身は公式パッケージと同形式にする（`com.unity.*` の実物で確認済み）:

```yaml
fileFormatVersion: 2
guid: <32桁の16進を新規生成。既存のものを流用しない>
TextScriptImporter:
  externalObjects: {}
  userData: 
  assetBundleName: 
  assetBundleVariant: 
```

ドキュメントを README 以外に増やすときは `Documentation~/` に入れる。`~` 付きなので
`.meta` が要らず、増やすたびに `.meta` を作る手間も警告の危険も無い。

## README の書き分け

README は**利用者向け**（何ができる / 導入 / 使い方 / ハマりどころ）に限定する。

- 収録方針・命名規則・リリース手順といった**メンテナ向けの規約はこのファイル**に書く
- 「なぜその実装にしたか」は**コード側のコメント**に書く（README に転記しない。二重管理になる）

## ライセンス

MIT（`LICENSE`）。新規パッケージの `package.json` も `"license": "MIT"` で揃える。
