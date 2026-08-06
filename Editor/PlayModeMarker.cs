using System;
using System.IO;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;

namespace Dilander.PlayModeMarker
{
    /// <summary>
    /// Play Mode 中だけ <c>Library/PlayModeMarker/playmode.json</c> を置き、抜けたら消す。
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
        const string k_DirName = "PlayModeMarker";
        const string k_FileName = "playmode.json";

        /// <summary>心拍の書き込み間隔（秒）。</summary>
        /// <remarks>
        /// エディタがクラッシュするとマーカーが残り、Play 中だと嘘をつく。読み手が updatedAt の
        /// 古さで「死んだマーカー」を判定できるよう、Play 中は定期的に書き直す。
        /// </remarks>
        const double k_HeartbeatSeconds = 2.0;

        static double s_NextHeartbeat;

        static PlayModeMarker()
        {
            EditorApplication.playModeStateChanged += OnPlayModeStateChanged;
            EditorApplication.update += OnUpdate;
            EditorApplication.quitting += Delete;

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
            if (!EditorApplication.isPlaying) return;
            if (EditorApplication.timeSinceStartup < s_NextHeartbeat) return;
            Write();
        }

        static void Sync()
        {
            if (EditorApplication.isPlaying) Write();
            else Delete();
        }

        static string GetDirectory()
        {
            return PlayModeMarkerPaths.Directory;
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
                    projectPath = PlayModeMarkerPaths.ProjectRoot,
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
