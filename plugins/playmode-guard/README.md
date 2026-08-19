# Play Mode Guard

Unity が **Play Mode の間、`.cs` の編集をブロックする** Claude Code プラグイン。

Preferences の *Script Changes While Playing* が *Recompile After Finished Playing* のとき、
Play 中に `.cs` を触ると再コンパイルが Play 終了まで保留される。この状態ではエディタ API 経由の
`ExitPlaymode` も「コンパイル中」で弾かれ、**停止ボタンを人手で押すまで復帰できない**。
このプラグインはその事故を、編集が起きる前に止める。

Play 中かどうかの判定には [playmode-bridge](../../playmode-bridge) が書くマーカーを使う。

## 前提

対象の Unity プロジェクトに `playmode-bridge` が導入されていること。
マーカー（`Library/PlayModeBridge/playmode.json`）が無いプロジェクトでは、このプラグインは
**常に素通しする**。そのためユーザー単位で有効化しても、Unity 以外のプロジェクトには影響しない。

**現状 Windows 専用。** フックは PowerShell スクリプトで、`powershell` が無い環境では
フックがエラーになるだけで編集はブロックされない（＝素通し）。

## 導入

```
/plugin marketplace add waffleplate/unity-packages
/plugin install playmode-guard@unity-packages
```

## 何を止めて、何を通すか

| ツール | 判定 |
| --- | --- |
| `Edit` / `Write` / `MultiEdit` | 対象が `.cs` なら止める |
| `Bash` | 「`.cs` への言及」と「書き込み動詞」が**両方**揃ったときだけ止める |

`Bash` の書き込み動詞は、リダイレクト（`> x.cs` / `>> x.cs` / ヒアドキュメント）と
`sed -i`・`cp`・`mv`・`rm`・`tee`・`touch`・`rsync`・`install`・`patch`・`truncate`・`unlink`。
両方を要求するので、`grep` / `ls` / `git diff` で `.cs` を挙げるだけの読み取りは通る。
`.csproj` / `.csv` / `.css` は `.cs` と誤認しない。

## 判定の条件

- マーカーが無ければ素通し
- マーカーが **10 秒より古ければ**、クラッシュで残った死んだマーカーとみなして素通し
  （心拍は 2 秒間隔。閾値の根拠は [playmode-bridge の README](../../playmode-bridge/README.md) を参照）
- フック入力が解釈できないときは素通し（fail-open）。マーカーはあるが更新時刻が読めないときは止める（fail-safe）

プロジェクトルートはフック入力の `cwd` から解決するので、スクリプト 1 本で全プロジェクトに効く。

## 限界

- **事故を止めるものであって、回避を防ぐものではない。** 難読化した書き込み（インタプリタ経由など）は通り抜ける
- `Assets/` の外にある `.cs`（他ツールの fixture 等）も Play 中は一律で止まる。Unity の再コンパイルとは
  無関係だが、パスで例外を設けるより安全側に倒している
- `MultiEdit` の入力形状は公式ドキュメントに記載が無い。`file_path` を含まない形だった場合、
  `MultiEdit` は素通しになる

## ライセンス

MIT
