# unity-packages

Waffle-Plate が公開している **Unity 向けの配布物**の置き場。
Unity Editor 拡張パッケージ（UPM）、それを外から使う Claude Code プラグイン、
Unity の外で動く汎用ツールを収録する。

## 収録パッケージ（UPM）

1 パッケージ 1 フォルダで、UPM の `?path=` でフォルダを直接指して導入する。

| フォルダ | パッケージ名 | 概要 |
| --- | --- | --- |
| [playmode-bridge](playmode-bridge) | `io.github.waffleplate.playmode-bridge` | Play Mode の状態・Game View の撮影・Play Mode の終了を、ファイル経由で外部から扱う |

導入方法は各パッケージの README を参照。

## 収録プラグイン（Claude Code）

このリポジトリは Claude Code のマーケットプレイスも兼ねる。

| フォルダ | プラグイン名 | 概要 |
| --- | --- | --- |
| [plugins/playmode-guard](plugins/playmode-guard) | `playmode-guard` | Play Mode 中の `.cs` 編集をブロックし、再コンパイルのデッドロックを防ぐ |

```
/plugin marketplace add waffleplate/unity-packages
/plugin install playmode-guard@unity-packages
```

## 収録ツール

Unity プロジェクトに何も足さずに、開発 PC の側で動く。このリポジトリを clone して使う。

| フォルダ | 概要 |
| --- | --- |
| [tools/unity-log-keeper](tools/unity-log-keeper) | Unity の Editor / Player のログを上書き前に写し取り、日時付きファイルで長期保存する常駐ツール（Windows / macOS） |

## ライセンス

MIT
