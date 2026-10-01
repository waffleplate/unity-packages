import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import unity_log_keeper as ulk  # noqa: E402


class FakeClock:
    """保存ファイル名の日時を 1 秒ずつ進める（同じ秒に切り替えが重なる場合は別途検証する）。"""

    def __init__(self):
        self.t = datetime(2026, 9, 30, 12, 0, 0)

    def __call__(self):
        self.t += timedelta(seconds=1)
        return self.t


class KeeperTestBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.src_dir = self.root / "src"
        self.src_dir.mkdir()
        self.dest = self.root / "dest"
        self.cfg = {**ulk.default_config(), "dest_dir": str(self.dest)}

    def tearDown(self):
        self._tmp.cleanup()

    def keeper(self):
        return ulk.Keeper(self.cfg, now=FakeClock())

    def source(self, name="Editor.log", group="proj", kind="Editor"):
        p = os.path.normcase(os.path.abspath(self.src_dir / name))
        return p, {p: ulk.Source(p, group, kind)}

    def dest_files(self, group="proj"):
        return sorted((self.dest / group).iterdir())

    @staticmethod
    def write(path, data, mode="wb"):
        with open(path, mode) as f:
            f.write(data)


class ParseArgsTest(unittest.TestCase):
    def test_flags_are_case_insensitive(self):
        ea = ulk.parse_editor_args(["Unity.exe", "-projectpath", "C:/p", "-LOGFILE", "C:/p/Logs/Editor.log"])
        self.assertEqual(ea, ulk.EditorArgs("C:/p", "C:/p/Logs/Editor.log"))

    def test_import_worker_is_excluded(self):
        self.assertIsNone(ulk.parse_editor_args(["Unity.exe", "-adb2", "-batchMode", "-projectPath", "C:/p"]))

    def test_logfile_to_stdout_or_missing(self):
        self.assertIsNone(ulk.parse_editor_args(["Unity.exe", "-projectPath", "C:/p", "-logFile", "-"]).log_file)
        self.assertIsNone(ulk.parse_editor_args(["Unity.exe", "-projectPath", "C:/p", "-logFile"]).log_file)
        self.assertIsNone(ulk.parse_editor_args(["Unity.exe", "-logFile", "-timestamps"]).log_file)

    def test_secrets_are_not_returned(self):
        ea = ulk.parse_editor_args(["Unity.exe", "-projectPath", "C:/p", "-accessToken", "SECRET"])
        self.assertNotIn("SECRET", repr(ea))


class CopyTest(KeeperTestBase):
    def test_appends_growth(self):
        path, sources = self.source()
        k = self.keeper()
        self.write(path, b"line1\n")
        k.poll(sources)
        self.write(path, b"line2\n", "ab")
        k.poll(sources)
        [dest] = self.dest_files()
        self.assertEqual(dest.read_bytes(), b"line1\nline2\n")
        self.assertRegex(dest.name, r"^Editor_20260930-120001\.log$")

    def test_truncation_starts_new_file(self):
        path, sources = self.source()
        k = self.keeper()
        self.write(path, b"first session " * 100)
        k.poll(sources)
        self.write(path, b"second\n")
        k.poll(sources)
        old, new = self.dest_files()
        self.assertEqual(old.read_bytes(), b"first session " * 100)
        self.assertEqual(new.read_bytes(), b"second\n")

    def test_rewrite_larger_with_same_head_is_detected(self):
        # Player.log は起動ごとに同じ文言で始まるので、縮まず先頭も一致したまま上書きされうる
        path, sources = self.source()
        k = self.keeper()
        head = b"Mono path[0] = 'C:/Game/Managed'\n" * 20
        self.write(path, head + b"run A: short\n")
        k.poll(sources)
        second = head + b"run B: this run wrote a lot more before the next poll\n" * 5
        self.write(path, second)
        k.poll(sources)
        old, new = self.dest_files()
        self.assertEqual(old.read_bytes(), head + b"run A: short\n")
        self.assertEqual(new.read_bytes(), second)

    def test_tail_is_recovered_from_prev_after_rename(self):
        path, sources = self.source()
        k = self.keeper()
        self.write(path, b"old part 1\n")
        k.poll(sources)
        # 最後の監視の後に書かれ、そのまま Unity の再起動で -prev へ退避された
        self.write(path, b"old tail\n", "ab")
        os.replace(path, self.src_dir / "Editor-prev.log")
        self.write(path, b"new run\n")
        k.poll(sources)
        old, new = self.dest_files()
        self.assertEqual(old.read_bytes(), b"old part 1\nold tail\n")
        self.assertEqual(new.read_bytes(), b"new run\n")

    def test_missing_file_finishes_with_prev_tail(self):
        path, sources = self.source()
        k = self.keeper()
        self.write(path, b"a\n")
        k.poll(sources)
        self.write(path, b"b\n", "ab")
        os.replace(path, self.src_dir / "Editor-prev.log")
        k.poll(sources)
        [dest] = self.dest_files()
        self.assertEqual(dest.read_bytes(), b"a\nb\n")
        self.assertEqual(k.tracks, {})

    def test_restart_resumes_without_duplication(self):
        path, sources = self.source()
        k = self.keeper()
        self.write(path, b"before restart\n")
        k.poll(sources)
        del k
        self.write(path, b"after restart\n", "ab")
        self.keeper().poll(sources)
        [dest] = self.dest_files()
        self.assertEqual(dest.read_bytes(), b"before restart\nafter restart\n")

    def test_rotation_while_stopped_is_detected_on_restart(self):
        path, sources = self.source()
        k = self.keeper()
        self.write(path, b"session 1 " * 10)
        k.poll(sources)
        del k
        self.write(path, b"session 2 is longer " * 10)
        self.keeper().poll(sources)
        self.assertEqual(len(self.dest_files()), 2)

    def test_same_second_rotation_gets_unique_name(self):
        path, sources = self.source()
        k = ulk.Keeper(self.cfg, now=lambda: datetime(2026, 9, 30, 12, 0, 0))
        self.write(path, b"one\n" * 10)
        k.poll(sources)
        self.write(path, b"two\n")
        k.poll(sources)
        names = [p.name for p in self.dest_files()]
        self.assertEqual(names, ["Editor_20260930-120000-2.log", "Editor_20260930-120000.log"])

    def test_overlapping_restart_leaves_hole(self):
        # 新しいエディタが -logFile を空にして書き始めた後も、終了中の古いエディタが前回の末尾の位置へ書く。
        # 間は NUL の穴になり、新しいエディタはそこを先頭から埋めていく（実測）
        path, sources = self.source()
        k = self.keeper()
        old = b"old session line\n" * 1000
        self.write(path, old)
        k.poll(sources)
        new1 = b"new session start\n" * 10
        old_tail = b"old editor shutting down\n"
        with open(path, "r+b") as f:
            f.truncate(0)
            f.write(new1)
            f.seek(len(old))
            f.write(old_tail)
        k.poll(sources)
        new2 = b"new session keeps going\n" * 20
        with open(path, "r+b") as f:
            f.seek(len(new1))
            f.write(new2)
        k.poll(sources)
        old_dest, new_dest = self.dest_files()
        self.assertEqual(old_dest.read_bytes(), old + old_tail)
        self.assertEqual(new_dest.read_bytes(), new1 + new2)

    def test_old_tail_after_long_zeroed_gap_is_recovered(self):
        # 古いエディタは最後の監視の後にも書き、上書きでそこが NUL になる。末尾はその後ろに書き足される
        path, sources = self.source()
        k = self.keeper()
        old = b"old session line\n" * 1000
        self.write(path, old)
        k.poll(sources)
        lost = 1000  # 最後の監視から上書きまでに書かれ、上書きで消えた分（穴の長さ以上）
        new1 = b"new session start\n" * 10
        old_tail = b"old editor shutting down\n"
        with open(path, "r+b") as f:
            f.truncate(0)
            f.write(new1)
            f.seek(len(old) + lost)
            f.write(old_tail)
        k.poll(sources)
        old_dest, new_dest = self.dest_files()
        self.assertEqual(old_dest.read_bytes(), old + old_tail)
        self.assertEqual(new_dest.read_bytes(), new1)

    def test_hole_across_read_boundary_is_not_copied(self):
        path, sources = self.source()
        k = self.keeper()
        saved = ulk.READ_CHUNK
        ulk.READ_CHUNK = 1024
        try:
            head = b"a" * 1000  # 穴は 1000 から始まり、最初の読み取り（1024 バイト）の末尾に 24 バイトだけかかる
            fill = b"b" * 2000
            with open(path, "wb") as f:
                f.write(head)
                f.seek(len(head) + len(fill))
                f.write(b"later\n")
            k.poll(sources)
            with open(path, "r+b") as f:
                f.seek(len(head))
                f.write(fill)
            k.poll(sources)
        finally:
            ulk.READ_CHUNK = saved
        [dest] = self.dest_files()
        self.assertEqual(dest.read_bytes(), head + fill + b"later\n")

    def test_short_nul_run_is_copied(self):
        path, sources = self.source()
        k = self.keeper()
        data = b"before" + b"\0" * 16 + b"after\n"
        self.write(path, data)
        k.poll(sources)
        [dest] = self.dest_files()
        self.assertEqual(dest.read_bytes(), data)

    def test_empty_file_is_not_started(self):
        path, sources = self.source()
        self.write(path, b"")
        self.keeper().poll(sources)
        self.assertFalse((self.dest / "proj").exists())


class PruneTest(KeeperTestBase):
    def test_oldest_are_deleted_and_active_is_kept(self):
        self.cfg["max_total_mb"] = 1
        group = self.dest / "g"
        group.mkdir(parents=True)
        mb = 1024 * 1024
        old = [group / f"old{i}.log" for i in range(3)]
        for i, p in enumerate(old):
            self.write(p, b"x" * (mb // 2))
            os.utime(p, (1000 + i, 1000 + i))
        k = self.keeper()
        path, sources = self.source()
        self.write(path, b"y" * (mb // 4))
        k.poll(sources)
        k.prune()
        remaining = sorted(p.name for p in group.iterdir())
        self.assertEqual(remaining, ["old2.log"])
        self.assertEqual(len(self.dest_files()), 1)
        self.assertTrue((self.dest / ulk.KEEPER_DIR / "state.json").exists())

    def test_tracked_but_stale_dest_is_deleted(self):
        # 二度と起動しない製品の Player.log は追跡が続くが、保存ファイルは古くなれば消せる
        self.cfg["max_total_mb"] = 1
        k = self.keeper()
        path, sources = self.source()
        self.write(path, b"z" * (1024 * 1024 + 1))
        k.poll(sources)
        [dest] = self.dest_files()
        os.utime(dest, (1000, 1000))
        k.prune()
        self.assertEqual(self.dest_files(), [])
        self.assertIn(path, k.tracks)


class DiscoverTest(KeeperTestBase):
    def make(self, *parts, data=b"x"):
        p = self.root.joinpath(*parts)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.write(p, data)
        return p

    def test_sources(self):
        editor_log = self.make("Unity", "Editor", "Editor.log")
        project = self.root / "My Proj"
        log_file = self.make("My Proj", "Logs", "Editor.log")
        self.make("My Proj", "Logs", "Editor.log-mppm4a0879a2.txt")
        self.make("My Proj", "Logs", "AssetImportWorker0.log")
        self.make("LocalLow", "DefaultCompany", "tnxr_main", "Player.log")
        self.make("LocalLow", "Waffle_Limes", "tnxr_main", "Player.log")
        self.make("LocalLow", "Valve", "SteamVR Tutorial", "Player.log")
        self.cfg["player_exclude"] = ["valve/*"]
        editor = "C:/Program Files/Unity/Editor/Unity.exe"
        procs = [
            ulk.ProcInfo(editor, [editor, "-projectpath", str(project), "-logFile", str(log_file),
                                  "-accessToken", "SECRET"]),
            ulk.ProcInfo(editor, [editor, "-adb2", "-batchMode", "-projectPath", str(project),
                                  "-logFile", "Logs/AssetImportWorker0.log"]),
        ]
        projects = set()
        found = ulk.discover(self.cfg, projects, procs, editor_log=editor_log, player_root=self.root / "LocalLow")
        got = sorted((s.group, s.kind) for s in found.values())
        self.assertEqual(got, [
            ("My Proj", "Editor"),
            ("My Proj", "Editor-mppm4a0879a2"),
            ("_default", "Editor"),
            ("tnxr_main", "Player-DefaultCompany"),
            ("tnxr_main", "Player-Waffle_Limes"),
        ])
        self.assertEqual(projects, {os.path.abspath(project)})

    def make_build(self, folder, name, unity=True):
        exe = self.make(folder, f"{name}.exe")
        self.make(folder, f"{name}_Data", "app.info", data=b"DefaultCompany\nzombie2d")
        if unity:
            self.make(folder, "UnityPlayer.dll")
        return str(exe)

    def discover_procs(self, procs):
        return ulk.discover(self.cfg, set(), procs, editor_log=self.root / "none.log",
                            player_root=self.root / "none")

    def test_player_with_logfile(self):
        exe = self.make_build("build-dev", "zombie2d")
        log_file = self.make("scratch", "player1101_hit_1.log")
        # ヘッドレスの計測は -batchmode で起動するが、Player は対象にする
        found = self.discover_procs([ulk.ProcInfo(exe, [exe, "-batchmode", "-logFile", str(log_file)])])
        self.assertEqual([(s.group, s.kind) for s in found.values()], [("zombie2d", "Player-player1101_hit_1")])

    def test_non_unity_app_with_logfile_is_ignored(self):
        exe = self.make_build("other", "tool", unity=False)
        log_file = self.make("scratch", "tool.log")
        self.assertEqual(self.discover_procs([ulk.ProcInfo(exe, [exe, "-logFile", str(log_file)])]), {})

    def test_player_logfile_respects_exclude(self):
        exe = self.make_build("build-dev", "zombie2d")
        log_file = self.make("scratch", "p.log")
        self.cfg["player_exclude"] = ["defaultcompany/*"]
        self.assertEqual(self.discover_procs([ulk.ProcInfo(exe, [exe, "-logFile", str(log_file)])]), {})

    def test_known_project_keeps_mppm_after_editor_exits(self):
        project = self.root / "p"
        self.make("p", "Logs", "Editor.log-mppmabc.txt")
        found = ulk.discover(self.cfg, {str(project)}, [], editor_log=self.root / "none.log",
                             player_root=self.root / "none")
        self.assertEqual([s.kind for s in found.values()], ["Editor-mppmabc"])


if __name__ == "__main__":
    unittest.main()
