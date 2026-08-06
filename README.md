# unity-packages

Waffle-Plate が公開している **Unity Editor 拡張パッケージ**の置き場。
1 パッケージ 1 フォルダで、UPM の `?path=` でフォルダを直接指して導入する。

## 収録パッケージ

| フォルダ | パッケージ名 | 概要 |
| --- | --- | --- |
| [playmode-bridge](playmode-bridge) | `io.github.waffleplate.playmode-bridge` | Play Mode の状態・Game View の撮影・Play Mode の終了を、ファイル経由で外部から扱う |

## 導入

```json
"io.github.waffleplate.playmode-bridge":
  "https://github.com/waffleplate/unity-packages.git?path=/playmode-bridge#playmode-bridge-v0.1.0"
```

詳細は各パッケージの README を参照。

## ここに置くもの / 置かないもの

**Unity プロセスの中で動く必要があるものだけ**を置く。`EditorApplication` や
`ScreenCapture` のようなエディタ API が要るかどうかが判断基準。

ホストOS側で完結する処理（ウィンドウの前面化、プロセスの特定、外部サービスへの
アップロード等）は、Unity の中で動く理由がないのでここには入らない。

## 命名規則

- **フォルダ名**: パッケージ名の末尾セグメント（`playmode-bridge`）
- **パッケージ名**: `io.github.waffleplate.<フォルダ名>`。逆ドメイン記法の根拠は
  GitHub 組織 `waffleplate`（＝`waffleplate.github.io`）であって、実在しない
  `waffleplate.com` ではない
- **タグ**: `<フォルダ名>-vX.Y.Z`。タグはリポジトリ全体のスナップショットなので、
  どのパッケージのリリースかが名前で分かるようにする
- **名前空間**: `WafflePlate.<PascalCase>`（C# の名前空間は逆ドメイン記法の対象外）

## ライセンス

MIT
