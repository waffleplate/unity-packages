using System;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace WafflePlate.PlayModeBridge
{
    /// <summary>
    /// Play Mode 中だけ <c>Library/PlayModeBridge/playmode.json</c> を置き、抜けたら消す。
    /// </summary>
    /// <remarks>
    /// リモート（スマホ）から作業するとき、Play 中かどうかを知るのに Unity MCP を経由すると
    /// エディタのフォーカス状態に左右されて当てにならない。ファイルなら Read だけで判定できる。
    ///
    /// 出力先を Library/ にしているのは、Unity 標準の .gitignore が Library/ を除外済みで、
    /// 各リポジトリに .gitignore を1行も足さずに済むため。
    /// </remarks>
    [InitializeOnLoad]
    static class PlayModeMarker
    {
        const string k_FileName = "playmode.json";

        /// <summary>心拍の書き込み間隔（秒）。</summary>
        /// <remarks>
        /// エディタがクラッシュするとマーカーが残り、Play 中だと嘘をつく。読み手が updatedAt の
        /// 古さで「死んだマーカー」を判定できるよう、Play 中は定期的に書き直す。
        /// </remarks>
        const double k_HeartbeatSeconds = 2.0;

        /// <summary>マーカーが消えていないか確かめる間隔（秒）。</summary>
        /// <remarks>
        /// 心拍は「2 秒ごとに書く」だけで実ファイルを見ないため、書いた直後に消されると次の心拍まで
        /// 復旧せず、読み手には最大 <see cref="k_HeartbeatSeconds"/> 秒間「Play していない」と見える。
        /// 既知の原因（バッチモードのワーカー）は静的コンストラクタ側で塞いだが、原因を問わず
        /// 塞げるようにここでも実ファイルの有無を見て食い違いを直す。
        /// </remarks>
        const double k_RepairSeconds = 0.2;

        static double s_NextHeartbeat;
        static double s_NextRepairCheck;

        /// <summary>エディタが終了処理に入ったか。</summary>
        /// <remarks>
        /// 終了時は下の <see cref="IsPlayingSteady"/> がまだ true を返しうるので、削除した後に
        /// 書き戻さないよう別に持つ。終了はドメインリロードを挟まないので静的フィールドでよい。
        /// </remarks>
        static bool s_Quitting;

        /// <summary>Play 中で、かつ抜け始めてもいないか。</summary>
        /// <remarks>
        /// <c>ExitingPlayMode</c> の時点では <c>isPlaying</c> がまだ true なので、それだけで判定すると
        /// 削除した直後に心拍や修復が書き戻してしまう（実測で 1.6 秒間マーカーが復活していた）。
        /// 抜け始めると <c>isPlayingOrWillChangePlaymode</c> が false に落ちるので、その差で見分ける
        /// （実測: 突入時 isPlaying=False/willChange=True、終了時 isPlaying=True/willChange=False）。
        ///
        /// 静的フィールドのフラグで覚えないのは、ドメインリロードで失われるため。Play 終了中に
        /// リロードが挟まる設定では、フラグが false に戻って書き戻しが復活する。
        /// </remarks>
        static bool IsPlayingSteady =>
            EditorApplication.isPlaying && EditorApplication.isPlayingOrWillChangePlaymode;

        static PlayModeMarker()
        {
            // アセットインポート用ワーカー（エディタが起動する -adb2 -batchMode の子プロセス）でも
            // エディタのアセンブリは読まれ、この静的コンストラクタが走る。ワーカーでは isPlaying が
            // 常に false なので、放置すると Sync() がエディタ本体の書いたマーカーを消してしまう。
            // 実測: Play 中にワーカーが削除し、読み手には 1.4 秒間「Play していない」と見えていた
            // （Procmon で削除元が AssetImportWorker のプロセスだと確認済み）。
            //
            // 起動引数（-adb2 / -parentPid）でワーカーだけを狙い撃つ判定も書けるが、そうしない。
            // 検出を外したときの結果が「本体の出力を壊す」（実際に起きた）側なので、非公開の引数に
            // 賭ける理由が無い。バッチモードのマーカーは読み手が居らず、一律に止めても失うものが無い。
            if (Application.isBatchMode) return;

            EditorApplication.playModeStateChanged += OnPlayModeStateChanged;
            EditorApplication.update += OnUpdate;
            EditorApplication.quitting += () =>
            {
                s_Quitting = true;
                Delete();
            };

            // Play 突入時のドメインリロードでこの静的コンストラクタは再実行される。
            // 復帰直後の実状態に合わせておかないと、リロードを挟んだ分だけマーカーがずれる。
            Sync();
        }

        static void OnPlayModeStateChanged(PlayModeStateChange change)
        {
            switch (change)
            {
                case PlayModeStateChange.EnteredPlayMode:
                    Write();
                    break;
                case PlayModeStateChange.ExitingPlayMode:
                case PlayModeStateChange.EnteredEditMode:
                    Delete();
                    break;
            }
        }

        static void OnUpdate()
        {
            if (s_Quitting || !IsPlayingSteady) return;

            var now = EditorApplication.timeSinceStartup;

            if (now >= s_NextHeartbeat)
            {
                Write();
                return;
            }

            if (now < s_NextRepairCheck) return;
            s_NextRepairCheck = now + k_RepairSeconds;

            if (!File.Exists(GetFilePath())) Write();
        }

        static void Sync()
        {
            // Play 終了中にドメインリロードが挟まっても書き戻さないよう、ここも同じ基準で見る。
            if (IsPlayingSteady) Write();
            else Delete();
        }

        static string GetDirectory()
        {
            return PlayModeBridgePaths.Directory;
        }

        static string GetFilePath()
        {
            return Path.Combine(GetDirectory(), k_FileName);
        }

        static void Write()
        {
            s_NextHeartbeat = EditorApplication.timeSinceStartup + k_HeartbeatSeconds;

            try
            {
                var dir = GetDirectory();
                if (!Directory.Exists(dir)) Directory.CreateDirectory(dir);

                var payload = new Payload
                {
                    isPlaying = true,
                    isPaused = EditorApplication.isPaused,
                    isCompiling = EditorApplication.isCompiling,
                    // 無効だとエディタ非フォーカス時に Play が止まる。リモートからは静止画しか
                    // 見えないので、読み手が原因を切り分けられるよう状態を載せる。
                    runInBackground = PlayerSettings.runInBackground,
                    projectPath = PlayModeBridgePaths.ProjectRoot,
                    productName = Application.productName,
                    unityVersion = Application.unityVersion,
                    activeScene = EditorSceneManager.GetActiveScene().name,
                    editorPid = System.Diagnostics.Process.GetCurrentProcess().Id,
                    updatedAt = DateTime.Now.ToString("o")
                };

                File.WriteAllText(GetFilePath(), JsonUtility.ToJson(payload, true));
            }
            catch (Exception e)
            {
                // 書けなくても Play Mode 自体は止めない。リモート側は「マーカーが無い＝Play していない」
                // と誤読するので、原因が追えるようにログには必ず残す。
                Debug.LogError($"[ERROR][PlayModeMarker] マーカーを書けませんでした: {e.Message}");
            }
        }

        static void Delete()
        {
            try
            {
                var path = GetFilePath();
                if (File.Exists(path)) File.Delete(path);
            }
            catch (Exception e)
            {
                Debug.LogError($"[ERROR][PlayModeMarker] マーカーを削除できませんでした: {e.Message}");
            }
        }

        [Serializable]
        class Payload
        {
            public bool isPlaying;
            public bool isPaused;
            public bool isCompiling;
            public bool runInBackground;
            public string projectPath;
            public string productName;
            public string unityVersion;
            public string activeScene;
            public int editorPid;
            public string updatedAt;
        }
    }
}
