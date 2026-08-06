# Changelog

このパッケージの変更履歴。書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に、
バージョンは [Semantic Versioning](https://semver.org/lang/ja/) に従う。

## [0.1.0] - 2026-08-06

動作確認: Unity 6000.3.21f1 (Windows)

### Added

- Play Mode の状態を `Library/PlayModeBridge/playmode.json` に出力（Play 中だけ存在し、2 秒ごとに
  `updatedAt` を更新する心拍付き）
- Game View の撮影（`capture.request` → `latest.png` ＋ `capture.result.json`、`superSize` 1〜4 対応）
- Play Mode の終了（`exitplay.request` → `exitplay.result.json`）。再コンパイル保留中でも詰まない
