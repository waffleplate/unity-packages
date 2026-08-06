# Changelog

このパッケージの変更履歴。書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に、
バージョンは [Semantic Versioning](https://semver.org/lang/ja/) に従う。

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
