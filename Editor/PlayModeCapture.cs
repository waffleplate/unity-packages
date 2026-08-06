using System;
using System.IO;
using UnityEditor;
using UnityEngine;

namespace Dilander.PlayModeMarker
{
    /// <summary>
    /// リクエストファイルを検出したら Game View を PNG に書き出す。
    /// </summary>
    /// <remarks>
    /// リモートから「今どう動いているか」を見る手段。Unity MCP 経由の撮影は
    /// エディタのフォーカス状態に左右されるうえ、URP では Unity_Camera_Capture が失敗するため、
    /// Play 中の Game View をそのまま撮る ScreenCapture に寄せている。
    ///
    /// やり取りは全部ファイル。リモート側は Write と Read だけで完結する。
    ///   要求: Library/PlayModeMarker/capture.request     （中身に 1〜4 を書くと superSize 指定）
    ///   結果: Library/PlayModeMarker/capture.result.json
    ///   画像: Library/PlayModeMarker/latest.png          （成功時のみ存在する）
    /// </remarks>
    [InitializeOnLoad]
    static class PlayModeCapture
    {
        const string k_RequestName = "capture.request";
        const string k_ResultName = "capture.result.json";
        const string k_ImageName = "latest.png";

        const double k_PollSeconds = 0.5;

        /// <summary>撮影要求から PNG が現れるまで待つ上限（秒）。</summary>
        /// <remarks>
        /// ScreenCapture.CaptureScreenshot はフレーム終端で書き出すため即座には現れない。
        /// runInBackground が無効でエディタが非フォーカスだとフレームが進まず永遠に現れないので、
        /// 待ち続けずに打ち切って理由を返す。
        /// </remarks>
        const double k_TimeoutSeconds = 10.0;

        static double s_NextPoll;
        static bool s_Pending;
        static double s_PendingDeadline;

        static PlayModeCapture()
        {
            EditorApplication.update += OnUpdate;
        }

        static string Dir => PlayModeMarkerPaths.Directory;
        static string RequestPath => Path.Combine(Dir, k_RequestName);
        static string ResultPath => Path.Combine(Dir, k_ResultName);
        static string ImagePath => Path.Combine(Dir, k_ImageName);

        static void OnUpdate()
        {
            if (s_Pending)
            {
                WaitForImage();
                return;
            }

            if (EditorApplication.timeSinceStartup < s_NextPoll) return;
            s_NextPoll = EditorApplication.timeSinceStartup + k_PollSeconds;

            if (!File.Exists(RequestPath)) return;
            Begin();
        }

        static void Begin()
        {
            int superSize = ReadSuperSize();

            // 要求は先に消す。撮影が失敗しても同じ要求で無限に再試行しないため。
            TryDelete(RequestPath);

            // 前回の画像は、撮影を試みる前に必ず消す。「画像の存在＝今回の撮影が成功した」を
            // 不変条件にするため、Play Mode 判定などで弾かれる経路でも残してはならない。
            TryDelete(ImagePath);

            if (!EditorApplication.isPlaying)
            {
                WriteResult(false, "Play Mode ではありません。Play 中の Game View のみ撮影できます。", 0);
                return;
            }

            try
            {
                if (!Directory.Exists(Dir)) Directory.CreateDirectory(Dir);

                // Game View が別タブの裏に隠れていると、フレームが進んでいても描画されず
                // ScreenCapture が永遠に完了しない（実測。Project Settings タブに隠れて再現した）。
                // 症状はフレーム停止と見分けが付かないので、撮る前に必ず表に出す。
                FocusGameView();

                ScreenCapture.CaptureScreenshot(ImagePath, superSize);
                s_Pending = true;
                s_PendingDeadline = EditorApplication.timeSinceStartup + k_TimeoutSeconds;
            }
            catch (Exception e)
            {
                WriteResult(false, $"撮影の開始に失敗しました: {e.Message}", 0);
            }
        }

        static void WaitForImage()
        {
            if (File.Exists(ImagePath))
            {
                long size = 0;
                try { size = new FileInfo(ImagePath).Length; } catch { }

                // 書き込み途中の 0 バイトを掴まないよう、サイズが乗るまで待つ
                if (size > 0)
                {
                    s_Pending = false;
                    WriteResult(true, null, size);
                    return;
                }
            }

            if (EditorApplication.timeSinceStartup < s_PendingDeadline) return;

            s_Pending = false;
            // 原因を断定しない。Game View が隠れているケースを runInBackground のせいだと
            // 誤診した実績がある（そちらは FocusGameView で潰したが、断定口調は残さない）。
            var reason = PlayerSettings.runInBackground
                ? "撮影がタイムアウトしました。Play が一時停止しているか、フレームが進んでいません。"
                : "撮影がタイムアウトしました。Run In Background が無効なので、エディタが非フォーカスだと"
                  + " フレームが進みません。呼び出し側でエディタを前面化してから撮り直してください。";
            WriteResult(false, reason, 0);
        }

        /// <summary>Game View タブを表に出す。無ければ開く。</summary>
        /// <remarks>
        /// UnityEditor.GameView は internal なので型名で解決する。リモートからはタブの前後関係が
        /// 見えないため、失敗しても撮影自体は続ける（結果の error で理由が分かる）。
        /// </remarks>
        static void FocusGameView()
        {
            try
            {
                var type = System.Type.GetType("UnityEditor.GameView,UnityEditor");
                if (type == null) return;

                var window = EditorWindow.GetWindow(type, false, null, true);
                if (window != null) window.Focus();
            }
            catch (Exception e)
            {
                Debug.LogWarning($"[WARN][PlayModeCapture] Game View を前面化できません: {e.Message}");
            }
        }

        static int ReadSuperSize()
        {
            try
            {
                var text = File.ReadAllText(RequestPath).Trim();
                if (int.TryParse(text, out var value) && value >= 1 && value <= 4) return value;
            }
            catch { }
            return 1;
        }

        static void TryDelete(string path)
        {
            try { if (File.Exists(path)) File.Delete(path); }
            catch (Exception e) { Debug.LogError($"[ERROR][PlayModeCapture] 削除できません {path}: {e.Message}"); }
        }

        static void WriteResult(bool ok, string error, long bytes)
        {
            try
            {
                if (!Directory.Exists(Dir)) Directory.CreateDirectory(Dir);

                var payload = new Result
                {
                    ok = ok,
                    imagePath = ok ? ImagePath : string.Empty,
                    bytes = bytes,
                    activeScene = UnityEditor.SceneManagement.EditorSceneManager.GetActiveScene().name,
                    runInBackground = PlayerSettings.runInBackground,
                    error = error ?? string.Empty,
                    completedAt = DateTime.Now.ToString("o")
                };

                File.WriteAllText(ResultPath, JsonUtility.ToJson(payload, true));
            }
            catch (Exception e)
            {
                Debug.LogError($"[ERROR][PlayModeCapture] 結果を書けませんでした: {e.Message}");
            }
        }

        [Serializable]
        class Result
        {
            public bool ok;
            public string imagePath;
            public long bytes;
            public string activeScene;
            public bool runInBackground;
            public string error;
            public string completedAt;
        }
    }
}
