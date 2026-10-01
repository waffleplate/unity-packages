# AGENTS.md

本リポジトリ `unity-packages` で作業する AI コーディングエージェント向けのプロジェクト固有指示の**正本**。

## プロジェクト概要

- **プロジェクト名**: unity-packages
- **概要**: Waffle-Plate が公開する Unity 向け配布物のモノレポ。Unity Editor 拡張パッケージ（UPM）、
  それを外から使う Claude Code プラグイン、Unity の外で動く汎用ツールを収録する。
  UPM は 1 パッケージ 1 フォルダで、`?path=` でフォルダを直接指して導入する。
- **リポジトリ**: https://github.com/waffleplate/unity-packages
- **収録パッケージ**: [playmode-bridge](playmode-bridge) — `io.github.waffleplate.playmode-bridge`
- **収録プラグイン**: [plugins/playmode-guard](plugins/playmode-guard) — `playmode-guard`
- **収録ツール**: [tools/unity-log-keeper](tools/unity-log-keeper) — `unity-log-keeper`
- **セッションアイコン**: 📦

**ここは配布物だけを置くリポジトリで、Unity プロジェクトではない。**
`Assets/` も `ProjectSettings/` も無く、このリポジトリ単体では Unity で開けない。
動作確認は、配布物を導入した側の Unity プロジェクトで行う。

## ここに置くもの / 置かないもの

判断基準は**不特定の利用者に配る Unity 向けの成果物かどうか**。収録できるのは次の 3 種類。

1. **UPM パッケージ** — Unity プロセスの中で動く必要があるもの。`EditorApplication` や
   `ScreenCapture` のようなエディタ API が要るかどうかが判断基準
2. **Claude Code プラグイン** — 1 の出力を外から消費するもの。ホスト側で動くが、パッケージが
   定めた契約（マーカーの心拍と死活閾値など）の実装なので、仕様と同じタグで動く方が乖離しない
3. **ホスト側ツール** — Unity の外（開発 PC の側）で動き、Unity プロジェクトに何も足さずに使えるもの。
   対象を設定と自動検出（既知の置き場所・起動中プロセスの引数など）で決め、特定の環境を埋め込まない

**特定のマシン・特定の運用に属するスクリプトは、ホスト側で動くかどうかに関係なくここには入らない。**
線引きは処理の種類ではなく**何に依存するか**で行う。特定のプロジェクト・パス・外部サービス・
呼び出し側の運用手順（どのウィンドウを前面に出すか、どこへアップロードするか、どの常駐基盤に
載せるか）を前提にするものは、配布物ではなく運用の道具なので呼び出し側のツールが持つ。
プロセスの特定や常駐そのものは、3 の条件を満たす限り収録してよい。

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

## 新しいプラグインを足すとき

1. `plugins/<プラグイン名>/` を作る（kebab-case）
2. `.claude-plugin/plugin.json` を置く（`name` が必須。`version` と各コンポーネントのパスは任意）
3. フックは `hooks/hooks.json`、スクリプトは `scripts/` に置き、README をプラグインフォルダ直下に置く
4. リポジトリ直下の `.claude-plugin/marketplace.json` の `plugins` に 1 件足す（`source` は `./plugins/<名前>`）
5. ルート `README.md` の収録プラグイン表に 1 行足す

規約:

- **同梱スクリプトの参照は `${CLAUDE_PLUGIN_ROOT}` を使う。** 絶対パスを書かない（導入先で解決できない）
- **対象プロジェクトのパスはフック入力の `cwd` から解決する。** スクリプトに特定プロジェクトを
  埋め込まない。1 本で全プロジェクトに効く形にする
- **前提のファイルが無い環境では素通しする。** プラグインの有効化はユーザー単位なので、
  無関係なプロジェクトで動いても害が無いようにする
- **PowerShell スクリプトは ASCII のみで書く。** Windows PowerShell 5.1 は `.ps1` をシステム ANSI
  （日本語環境なら cp932）として読むため、非 ASCII を含むと構文解析が壊れる
- `plugins/` 配下は UPM パッケージではないので **`.meta` は要らない**

## 新しいツールを足すとき

1. `tools/<ツール名>/` を作る（kebab-case。タグは命名規則どおり `<ツール名>-vX.Y.Z`）
2. README（利用者向け）と `CHANGELOG.md` をツールフォルダ直下に置く
3. 言語固有の無視ルールは、ツールフォルダ直下の `.gitignore` に置く（ルートには置かない）
4. ルート `README.md` の収録ツール表に 1 行足す

規約:

- **導入は clone だけで済むようにする。** 言語の標準ライブラリで書き、外部ライブラリに依存しない
  （Python なら `pip install` を要求しない）。導入手順が増えるほど、利用者の環境で動かない理由が増える
- **OS ごとに違う部分（常駐の登録・プロセスの列挙など）は関数単位で分け、他は共通にする。**
  対応 OS は README に明記する
- **起動引数・環境変数をそのままログやファイルに書かない。** Unity Hub は `-accessToken` などの
  認証情報を起動引数で渡す。必要な値だけを取り出す
- **テストはツールフォルダの `tests/` に置き、標準のテストランナーで動くようにする**
  （Python なら `python -m unittest discover -s tools/<ツール名>/tests`）
- `tools/` 配下は UPM パッケージではないので **`.meta` は要らない**。ライセンスはリポジトリルートの
  `LICENSE` に従う（clone して使う前提のため、ツール内に複製しない）

## .meta ファイルの規則

この節は **UPM パッケージフォルダ配下だけ**の話（`plugins/`・`tools/`・`.claude-plugin/` は対象外）。

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
