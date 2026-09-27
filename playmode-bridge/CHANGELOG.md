# Changelog

このパッケージの変更履歴。書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に、
バージョンは [Semantic Versioning](https://semver.org/lang/ja/) に従う。

## [0.3.0] - 2026-09-28

動作確認: Unity 6000.3.22f1 (Windows)

### Added

- マーカーに `exitRequestPath` を追加。Play Mode を抜けるための要求ファイルの絶対パスを載せる。
  保留コンパイルで詰まった読み手が最初に見るのはマーカーなので、そこに脱出口を置く

### Changed

- README に「MCP が `COMPILATION_IN_PROGRESS` を返し続けるとき」の節を新設し、導入手順より前に
  置いた。終了経路の説明が最終節にしか無く、詰まった側から辿れなかったため
- 保留コンパイルは Play 中に編集しなくても起きる（Edit Mode で書かれた `.cs` が未取り込みのまま
  残り、Play 開始で取り込まれる）ことを README に明記。`EditorApplication.isCompiling` を
  Play 開始直前に見ても防げない
- 脱出口を使う前に Play の所有者を確かめるよう README に明記。マーカーに所有者が無いため、
  「抜けられる」とだけ書くと他人の Play を止める。Play を持たない側は待っても復旧しないことも
  あわせて書いた（自力で脱出口に辿り着かず 4 分超待った実測がある）

## [0.2.0] - 2026-08-07

動作確認: Unity 6000.3.21f1 (Windows)

### Fixed

- **アセットインポート用ワーカーがエディタ本体の出力を壊していた問題を修正。**
  エディタが起動する `-adb2 -batchMode` の子プロセスでもこのパッケージの `[InitializeOnLoad]` が走り、
  ワーカーでは `isPlaying` が常に false のため、エディタ本体が書いたマーカーを削除していた。
  実測では Play 中に 1.4 秒間マーカーが消え、読み手には「Play していない」と見えていた。

  撮影と Play 終了も同じ露出があった。ワーカーが先に `capture.request` / `exitplay.request` を
  消して処理すると、ワーカー視点では常に Play 中ではないため、誤った失敗結果が書かれる
  （マーカーでの発生は実測で確認済み。他 2 つは同じ構造に対する予防措置）

  バッチモードでは 3 クラスとも動作しない。これで失うものは無く、`-batchmode` では
  `EditorApplication.update` が回らないため、この制限が無くても要求は処理されない（実測）
- Play 停止後、マーカーが最大 1.6 秒復活していた問題を修正。`ExitingPlayMode` の時点では
  `isPlaying` がまだ true のため、削除した直後に心拍が書き戻していた。
  判定は `isPlayingOrWillChangePlaymode` との組み合わせで行う。静的フィールドのフラグで覚えると
  Play 終了中にドメインリロードが挟まる設定で失われ、書き戻しが復活するため

### Added

- マーカーが消えていないかを Play 中 0.2 秒ごとに確認し、消えていれば即座に書き直す。
  上記の原因は特定して塞いだが、心拍だけでは「書いた後に何かに消される」と次の心拍まで
  復旧しない構造自体が残るため、原因を問わない防御として入れる

### Changed

- README に死活判定の閾値（`updatedAt` が 10 秒以上古ければ死んだマーカー）を実測値つきで明記

## [0.1.1] - 2026-08-06

動作確認: Unity 6000.3.21f1 (Windows)

コードの変更は無く、配布物の同梱漏れの修正のみ。

### Added

- `LICENSE.md` をパッケージ内に同梱。UPM は `?path=` 指定でサブフォルダだけを取得するため、
  リポジトリルートの `LICENSE` は配布物に含まれていなかった
- `CHANGELOG.md` を追加

### Fixed

- `.md` に `.meta` が無く、導入先のコンソールに `has no meta file, but it's in an immutable
  folder` 警告が出続けていた問題を修正

## [0.1.0] - 2026-08-06

動作確認: Unity 6000.3.21f1 (Windows)

### Added

- Play Mode の状態を `Library/PlayModeBridge/playmode.json` に出力（Play 中だけ存在し、2 秒ごとに
  `updatedAt` を更新する心拍付き）
- Game View の撮影（`capture.request` → `latest.png` ＋ `capture.result.json`、`superSize` 1〜4 対応）
- Play Mode の終了（`exitplay.request` → `exitplay.result.json`）。再コンパイル保留中でも詰まない
