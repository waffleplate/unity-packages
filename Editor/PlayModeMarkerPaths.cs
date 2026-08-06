using System.IO;
using UnityEngine;

namespace Dilander.PlayModeMarker
{
    /// <summary>
    /// マーカーと撮影結果の出力先。
    /// </summary>
    /// <remarks>
    /// Library/ 配下に置くのは、Unity 標準の .gitignore が既に除外しているため。
    /// 各リポジトリに .gitignore を1行も足さずに済む。
    /// </remarks>
    static class PlayModeMarkerPaths
    {
        /// <summary>プロジェクトルート（Assets の親）。</summary>
        public static string ProjectRoot =>
            Path.GetFullPath(Path.Combine(Application.dataPath, ".."));

        /// <summary>出力先ディレクトリ。</summary>
        public static string Directory =>
            Path.Combine(Path.Combine(ProjectRoot, "Library"), "PlayModeMarker");
    }
}
