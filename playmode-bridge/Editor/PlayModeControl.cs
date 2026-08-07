using System;
using System.Globalization;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace WafflePlate.PlayModeBridge
{
    /// <summary>
    /// リクエストファイルを検出したら Play Mode を終了する。
    /// </summary>
    /// <remarks>
    /// Unity MCP 経由の <c>ExitPlaymode</c> は、再コンパイルが Play 終了まで保留される設定で
    /// Play 中に <c>.cs</c> を編集すると「コンパイル中」で弾かれ、停止ボタンを人手で押すまで
    /// 復帰できなくなる。リモートではそこで詰むため、MCP を通さない経路を用意する。
    /// <c>EditorApplication.update</c> から呼ぶのでガードにもフォーカス状態にも依存しない。
    ///
    /// やり取りは全部ファイル。リモート側は Write と Read だけで完結する。
    ///   要求: Library/PlayModeBridge/exitplay.request
    ///   結果: Library/PlayModeBridge/exitplay.result.json
    /// </remarks>
    [InitializeOnLoad]
    static class PlayModeControl
    {
        const string k_RequestName = "exitplay.request";
        const string k_ResultName = "exitplay.result.json";

        /// <summary>終了を要求してから完了を待っている最中であることを示すファイル。</summary>
        /// <remarks>
        /// Play Mode を抜けるとドメインリロードが走り、静的フィールドは全部消える。
        /// 進行中であることをメモリに持つと、リロードを挟んだ瞬間に「誰も結果を書かない」状態になり、
        /// 呼び出し側にはタイムアウトしか見えなくなる。だからファイルに持たせる。
        /// </remarks>
        const string k_PendingName = "exitplay.pending";

        const double k_PollSeconds = 0.5;

        /// <summary>終了要求から Edit Mode に戻るまで待つ上限（秒）。</summary>
        const double k_TimeoutSeconds = 30.0;

        static double s_NextPoll;

        static PlayModeControl()
        {
            // アセットインポート用ワーカーでも走ってしまうため無効にする（理由は PlayModeMarker）。
            // 防ぎたいのは要求の横取り: ワーカーが先に exitplay.request を消して処理すると、
            // 実際には Play 中でもワーカー視点では違うので wasPlaying=false が結果として書かれる。
            //
            // 一律に止めても失うものは無い。実測では -batchmode で EditorApplication.update が
            // 回らず、ガードが無くても要求は処理されなかった（12 秒の実行中ずっと無応答）。
            if (Application.isBatchMode) return;

            EditorApplication.update += OnUpdate;

            // Play を抜けた直後のドメインリロードでこの静的コンストラクタは再実行される。
            // 進行中の要求はファイルにしか残っていないので、復帰したらまず決着させる。
            ResolvePending();
        }

        static string Dir => PlayModeBridgePaths.Directory;
        static string RequestPath => Path.Combine(Dir, k_RequestName);
        static string ResultPath => Path.Combine(Dir, k_ResultName);
        static string PendingPath => Path.Combine(Dir, k_PendingName);

        static void OnUpdate()
        {
            if (EditorApplication.timeSinceStartup < s_NextPoll) return;
            s_NextPoll = EditorApplication.timeSinceStartup + k_PollSeconds;

            if (File.Exists(PendingPath))
            {
                ResolvePending();
                return;
            }

            if (!File.Exists(RequestPath)) return;
            Begin();
        }

        static void Begin()
        {
            // 要求は先に消す。終了に失敗しても同じ要求で無限に再試行しないため。
            TryDelete(RequestPath);

            // 前回の結果も先に消す。残したままだと、今回の結果が書かれる前に読まれたときに
            // 前回の成否を今回のものとして誤読する。
            TryDelete(ResultPath);

            if (!IsPlaying())
            {
                WriteResult(true, false, null);
                return;
            }

            EditorApplication.ExitPlaymode();

            // 実際の遷移はフレーム終端なので、ここではまだ Edit Mode に戻っていない。
            try
            {
                EnsureDirectory();
                var deadline = DateTime.Now.AddSeconds(k_TimeoutSeconds);
                File.WriteAllText(PendingPath, deadline.ToString("o", CultureInfo.InvariantCulture));
            }
            catch (Exception e)
            {
                // 終了自体は要求済み。完了を見届けられないことだけを正直に返す。
                WriteResult(false, true, $"終了を要求しましたが、完了を確認できません: {e.Message}");
            }
        }

        static void ResolvePending()
        {
            if (!File.Exists(PendingPath)) return;

            if (!IsPlaying())
            {
                TryDelete(PendingPath);
                WriteResult(true, true, null);
                return;
            }

            DateTime deadline;
            if (!TryReadDeadline(out deadline))
            {
                // 期限が読めないと待ち続けるか即座に諦めるかしかない。放置すると進行中ファイルが
                // 残り続けて以降の要求を全部塞ぐので、消して失敗を返す。
                TryDelete(PendingPath);
                WriteResult(false, true, "進行中の記録が壊れていたため中断しました。もう一度要求してください。");
                return;
            }

            if (DateTime.Now < deadline) return;

            TryDelete(PendingPath);
            WriteResult(false, true,
                $"Play Mode を抜けられませんでした（{k_TimeoutSeconds:0} 秒待機）。"
                + "エディタがモーダルダイアログで止まっている可能性があります。");
        }

        /// <summary>Play Mode から完全に抜けきったかどうか。</summary>
        /// <remarks>
        /// 終了処理の途中では <c>isPlaying</c> が先に false になる。そこで完了と判断すると、
        /// まだ遷移中のうちに成功を返してしまうので、遷移予告の方も見る。
        /// </remarks>
        static bool IsPlaying()
        {
            return EditorApplication.isPlaying || EditorApplication.isPlayingOrWillChangePlaymode;
        }

        static bool TryReadDeadline(out DateTime deadline)
        {
            deadline = DateTime.MinValue;
            try
            {
                var text = File.ReadAllText(PendingPath).Trim();
                return DateTime.TryParse(text, CultureInfo.InvariantCulture,
                    DateTimeStyles.RoundtripKind, out deadline);
            }
            catch
            {
                return false;
            }
        }

        static void EnsureDirectory()
        {
            if (!Directory.Exists(Dir)) Directory.CreateDirectory(Dir);
        }

        static void TryDelete(string path)
        {
            try { if (File.Exists(path)) File.Delete(path); }
            catch (Exception e) { Debug.LogError($"[ERROR][PlayModeControl] 削除できません {path}: {e.Message}"); }
        }

        static void WriteResult(bool ok, bool wasPlaying, string error)
        {
            try
            {
                EnsureDirectory();

                var payload = new Result
                {
                    ok = ok,
                    wasPlaying = wasPlaying,
                    isPlaying = EditorApplication.isPlaying,
                    activeScene = UnityEditor.SceneManagement.EditorSceneManager.GetActiveScene().name,
                    error = error ?? string.Empty,
                    completedAt = DateTime.Now.ToString("o")
                };

                File.WriteAllText(ResultPath, JsonUtility.ToJson(payload, true));
            }
            catch (Exception e)
            {
                Debug.LogError($"[ERROR][PlayModeControl] 結果を書けませんでした: {e.Message}");
            }
        }

        [Serializable]
        class Result
        {
            public bool ok;

            /// <summary>要求を受けた時点で Play 中だったか。false なら何もしていない。</summary>
            public bool wasPlaying;

            public bool isPlaying;
            public string activeScene;
            public string error;
            public string completedAt;
        }
    }
}
