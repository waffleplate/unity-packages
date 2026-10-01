# Changelog

このツールの変更履歴。書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に、
バージョンは [Semantic Versioning](https://semver.org/lang/ja/) に従う。

## [Unreleased]

### Added

- Editor（既定の場所・`-logFile` 指定）、MPPM の仮想プレイヤー、Player（`LocalLow`・`-logFile` 指定）の
  ログを上書き前に写し取り、
  写し始めた日時付きのファイルで保存する
- 上書きの検出（縮んだ・別ファイルに置き換わった・先頭か前回位置の直前が変わった）と、
  `-prev` へ退避されたファイルからの末尾の補完
- 新旧のエディタの起動が重なって `-logFile` に NUL の未書き込み領域ができたとき、その手前で待つ。
  古いエディタが終了処理中に書いた末尾は前の保存ファイルへ回す
- 保存先の容量上限による古い順の削除
- 常駐の登録と解除（Windows: タスクスケジューラ / macOS: launchd）
