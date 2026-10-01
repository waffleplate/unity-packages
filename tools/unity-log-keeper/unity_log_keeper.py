#!/usr/bin/env python3
"""unity-log-keeper: Unity の Editor / Player ログを上書き前に写し取り、日時付きファイルで残す常駐ツール。

使い方は同じフォルダの README.md を参照。標準ライブラリだけで動く（導入を clone だけで済ませるため）。
"""

from __future__ import annotations

import argparse
import fnmatch
import glob
import json
import logging
import logging.handlers
import os
import plistlib
import subprocess
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

TOOL_NAME = "unity-log-keeper"
LAUNCHD_LABEL = "io.github.waffleplate.unity-log-keeper"
IS_WINDOWS = sys.platform == "win32"
IS_MAC = sys.platform == "darwin"

# 同じファイルが書き続けられているかの判定に使う。先頭だけでは足りない: Player.log は起動のたびに
# 同じ文言（Mono path 等）で始まるので、前回写し終えた位置の直前も照合する
HEAD_BYTES = 256
ANCHOR_BYTES = 64
READ_CHUNK = 1 << 20

# 新しいエディタが -logFile を空にして書き始めた後も、終了処理中の古いエディタは自分の書き込み位置
# （前回の末尾）へ書き続ける。間は NUL で埋まった穴になり、新しいエディタはそこを先頭から埋めていく。
# 穴を写して先へ進むと、新しい起動の出力が穴を越えるまで一切写せなくなる（実測: 100MB の穴）。
# ログ本文に NUL が短く混ざることはあるので、この長さ以上の連続だけを穴とみなす
HOLE = b"\0" * 512
# 前の Unity が終わりきるまでの猶予。実測では新しいエディタの起動から 7 秒後まで書いていた
TAIL_WATCH_SEC = 120.0

KEEPER_DIR = "_keeper"
DEFAULT_EDITOR_GROUP = "_default"
PRUNE_INTERVAL_SEC = 60.0
# この時間内に書き込んだ保存ファイルは消さない。書き込み中のものを消すと次の監視で作り直され、それを繰り返す
ACTIVE_GRACE_SEC = 600.0
KEEPER_LOG_MAX_BYTES = 1 << 20
KEEPER_LOG_BACKUPS = 3

log = logging.getLogger(TOOL_NAME)


# ---------------------------------------------------------------------------
# 設定
# ---------------------------------------------------------------------------

def default_base_dirs() -> tuple[Path, Path]:
    """(設定ファイルのフォルダ, 保存先) の既定値。"""
    home = Path.home()
    if IS_WINDOWS:
        base = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local")) / TOOL_NAME
        return base, base / "logs"
    if IS_MAC:
        return home / "Library" / "Application Support" / TOOL_NAME, home / "Library" / "Logs" / TOOL_NAME
    return home / ".config" / TOOL_NAME, home / ".local" / "state" / TOOL_NAME / "logs"


def default_config_path() -> Path:
    return default_base_dirs()[0] / "config.json"


def default_config() -> dict:
    return {
        "dest_dir": str(default_base_dirs()[1]),
        "max_total_mb": 5120,
        "interval_sec": 2.0,
        # プロセス一覧の取得は Windows で PowerShell を起動するので、ファイルの監視より間隔を空ける
        "discover_interval_sec": 10.0,
        "player_include": ["*"],
        "player_exclude": [],
        "extra_globs": [],
    }


def load_config(path: Path) -> dict:
    cfg = default_config()
    if path.exists():
        with open(path, encoding="utf-8") as f:
            user = json.load(f)
        unknown = sorted(set(user) - set(cfg))
        if unknown:
            log.warning("[WARN][LogKeeper] 設定に未知のキーがあります（無視します）: %s", ", ".join(unknown))
        cfg.update({k: v for k, v in user.items() if k in cfg})
    cfg["dest_dir"] = os.path.expandvars(os.path.expanduser(cfg["dest_dir"]))
    return cfg


# ---------------------------------------------------------------------------
# 監視対象の発見
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Source:
    path: str
    group: str  # 保存先のサブフォルダ（プロジェクト名 or 製品名）
    kind: str   # 保存ファイル名の接頭辞


@dataclass(frozen=True)
class EditorArgs:
    project_path: str | None
    log_file: str | None


@dataclass(frozen=True)
class ProcInfo:
    exe: str
    argv: list[str]


def _arg_value(argv: list[str], flag: str) -> str | None:
    """起動引数からフラグの値を取り出す（Unity のフラグは大文字小文字を区別しない）。

    起動引数には Hub が渡す -accessToken 等の認証情報が含まれるので、ここで取り出した値以外を
    呼び出し側へ渡さない（ログにも残さない）。
    """
    lowered = [a.lower() for a in argv]
    if flag not in lowered:
        return None
    i = lowered.index(flag)
    if i + 1 >= len(argv):
        return None
    v = argv[i + 1]
    # "-logFile -" は標準出力へ出す指定。値が無く次のフラグが来る場合も同様にファイルは無い
    if v.startswith("-"):
        return None
    return v


def parse_editor_args(argv: list[str]) -> EditorArgs | None:
    # アセットインポートのワーカー（-adb2 -batchMode）は相対パスの自前ログを持つだけで対象外
    if "-batchmode" in (a.lower() for a in argv):
        return None
    return EditorArgs(_arg_value(argv, "-projectpath"), _arg_value(argv, "-logfile"))


def is_unity_editor(exe: str) -> bool:
    name = os.path.basename(exe)
    return name.lower() == "unity.exe" or name == "Unity"


def unity_player_data_dir(exe: str) -> Path | None:
    """exe が Unity でビルドした Player なら、そのデータフォルダを返す。

    Unity のビルドは必ず Windows で <名前>_Data と UnityPlayer.dll を、macOS で .app の中に
    UnityPlayer.dylib を持つ。パスや製品名を埋め込まずに Player を見分けられる
    """
    p = Path(exe)
    if p.suffix.lower() == ".exe":
        data = p.with_name(p.stem + "_Data")
        if data.is_dir() and (p.parent / "UnityPlayer.dll").is_file():
            return data
        return None
    if p.parent.name == "MacOS" and p.parent.parent.name == "Contents":
        contents = p.parent.parent
        if (contents / "Frameworks" / "UnityPlayer.dylib").is_file():
            return contents / "Resources" / "Data"
    return None


def read_app_info(data_dir: Path) -> tuple[str, str] | None:
    """Player の (会社名, 製品名)。Unity がデータフォルダの app.info に 2 行で書いている。"""
    try:
        lines = (data_dir / "app.info").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    return (lines[0], lines[1]) if len(lines) >= 2 else None


def _split_windows_cmdline(cmdline: str) -> list[str]:
    # 引用符や \" の扱いを自前で真似ると外すので、Windows 自身の分割規則をそのまま使う
    import ctypes
    from ctypes import wintypes

    fn = ctypes.windll.shell32.CommandLineToArgvW
    fn.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_int)]
    fn.restype = ctypes.POINTER(wintypes.LPWSTR)
    free = ctypes.windll.kernel32.LocalFree
    free.argtypes = [ctypes.c_void_p]
    argc = ctypes.c_int()
    argv = fn(cmdline, ctypes.byref(argc))
    if not argv:
        return []
    try:
        return [argv[i] for i in range(argc.value)]
    finally:
        free(ctypes.cast(argv, ctypes.c_void_p))


def _windows_unity_procs() -> list[ProcInfo]:
    # エディタに加え、-logFile 付きで起動した Player を拾う（Player の判定は呼び出し側でファイルを見て行う）
    script = (
        "[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
        "@(Get-CimInstance Win32_Process -Filter \"Name='Unity.exe' OR CommandLine LIKE '%-logfile%'\" |"
        " Where-Object { $_.ExecutablePath -and $_.CommandLine } |"
        " Select-Object ExecutablePath,CommandLine) | ConvertTo-Json -Compress"
    )
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if proc.returncode != 0:
        # 出力には起動引数（認証情報を含む）が載りうるので、終了コードだけを残す
        log.warning("[WARN][LogKeeper] Unity プロセスの一覧取得に失敗しました（終了コード %d）", proc.returncode)
        return []
    text = proc.stdout.decode("utf-8", "replace").strip()
    if not text:
        return []
    items = json.loads(text)
    if isinstance(items, dict):  # 1 件だけのとき ConvertTo-Json は配列にしない
        items = [items]
    return [ProcInfo(i["ExecutablePath"], _split_windows_cmdline(i["CommandLine"])) for i in items]


def _mac_proc_argv(pid: int) -> list[str]:
    # ps の args 列は空白入りのパスを区切れないので、カーネルから argv をそのまま読む
    import ctypes
    import ctypes.util

    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    ctl_kern, kern_argmax, kern_procargs2 = 1, 8, 49
    argmax = ctypes.c_int()
    size = ctypes.c_size_t(ctypes.sizeof(argmax))
    mib = (ctypes.c_int * 2)(ctl_kern, kern_argmax)
    if libc.sysctl(mib, 2, ctypes.byref(argmax), ctypes.byref(size), None, 0) != 0:
        return []
    buf = ctypes.create_string_buffer(argmax.value)
    size = ctypes.c_size_t(argmax.value)
    mib3 = (ctypes.c_int * 3)(ctl_kern, kern_procargs2, pid)
    if libc.sysctl(mib3, 3, buf, ctypes.byref(size), None, 0) != 0:
        return []
    raw = buf.raw[: size.value]
    argc = int.from_bytes(raw[:4], sys.byteorder)
    rest = raw[4:]
    rest = rest[rest.find(b"\0"):].lstrip(b"\0")  # 実行ファイルのパスと詰め物を飛ばす
    return [p.decode("utf-8", "replace") for p in rest.split(b"\0")[:argc]]


def _mac_unity_procs() -> list[ProcInfo]:
    # macOS の ps の comm 列は実行ファイルのフルパスを返す
    proc = subprocess.run(["ps", "-axo", "pid=,comm="], capture_output=True, text=True, timeout=60)
    result = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        exe = parts[1]
        if is_unity_editor(exe) or unity_player_data_dir(exe) is not None:
            argv = _mac_proc_argv(int(parts[0]))
            if argv:
                result.append(ProcInfo(exe, argv))
    return result


def list_unity_procs() -> list[ProcInfo]:
    try:
        if IS_WINDOWS:
            return _windows_unity_procs()
        if IS_MAC:
            return _mac_unity_procs()
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        log.warning("[WARN][LogKeeper] Unity プロセスの一覧取得に失敗しました: %s", type(e).__name__)
    return []


def default_editor_log() -> Path:
    if IS_WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA", "")) / "Unity" / "Editor" / "Editor.log"
    return Path.home() / "Library" / "Logs" / "Unity" / "Editor.log"


def player_log_root() -> Path:
    if IS_WINDOWS:
        return Path.home() / "AppData" / "LocalLow"
    return Path.home() / "Library" / "Logs"


def sanitize(name: str) -> str:
    bad = '<>:"/\\|?*'
    s = "".join("_" if (c in bad or ord(c) < 32) else c for c in name).strip().rstrip(".")
    return s or "_"


def _matches(key: str, patterns: list[str]) -> bool:
    k = key.lower()
    return any(fnmatch.fnmatchcase(k, p.lower()) for p in patterns)


def _add_logfile_player(cfg: dict, proc: ProcInfo, data_dir: Path, add) -> None:
    """-logFile 付きで起動した Player。LocalLow の Player.log には何も書かれない。"""
    # エディタと違い -batchmode も対象にする（ヘッドレスの計測はこの形で起動する）
    log_file = _arg_value(proc.argv, "-logfile")
    # -logFile が無ければ LocalLow の Player.log 側で拾う。相対パスは起動側の作業フォルダが分からず解決できない
    if not log_file or not os.path.isabs(log_file):
        return
    info = read_app_info(data_dir)
    company, product = info if info else ("*", Path(proc.exe).stem)
    key = f"{company}/{product}"
    if not _matches(key, cfg["player_include"]) or _matches(key, cfg["player_exclude"]):
        return
    # ログ名は起動した側が付けたもの（例: player1101_hit_1）なので、そのまま種別に残して見分けられるようにする
    add(Path(log_file), product, f"Player-{Path(log_file).stem}")


def discover(
    cfg: dict,
    projects: set[str],
    procs: list[ProcInfo],
    *,
    editor_log: Path,
    player_root: Path,
) -> dict[str, Source]:
    """監視対象を列挙する。projects は見つけたプロジェクトを蓄積する（MPPM の探索に使う）。"""
    found: dict[str, Source] = {}

    def add(path: Path, group: str, kind: str) -> None:
        p = os.path.normcase(os.path.abspath(path))
        found.setdefault(p, Source(p, sanitize(group), sanitize(kind)))

    if editor_log.is_file():
        # 既定の場所は全プロジェクトが共有するので、どのプロジェクトのものかは決められない
        add(editor_log, DEFAULT_EDITOR_GROUP, "Editor")

    mppm_globs: list[tuple[str, str]] = []
    for proc in procs:
        data_dir = unity_player_data_dir(proc.exe)
        if data_dir is not None:
            _add_logfile_player(cfg, proc, data_dir, add)
            continue
        if not is_unity_editor(proc.exe):
            continue
        ea = parse_editor_args(proc.argv)
        if ea is None or not ea.project_path:
            continue
        project = os.path.abspath(ea.project_path)
        projects.add(project)
        # 相対パスの -logFile は起動側の作業フォルダが分からず解決できない
        if ea.log_file and os.path.isabs(ea.log_file):
            add(Path(ea.log_file), os.path.basename(project), "Editor")
            mppm_globs.append((glob.escape(ea.log_file) + "-mppm*.txt", os.path.basename(project)))

    for project in sorted(projects):
        if not os.path.isdir(project):
            continue
        logs = os.path.join(glob.escape(project), "Logs", "Editor.log-mppm*.txt")
        mppm_globs.append((logs, os.path.basename(project)))
    for pattern, group in mppm_globs:
        for p in glob.glob(pattern):
            # 例: Editor.log-mppm4a0879a2.txt → Editor-mppm4a0879a2
            suffix = Path(p).name.rsplit("-mppm", 1)[1].rsplit(".", 1)[0]
            add(Path(p), group, f"Editor-mppm{suffix}")

    for p in glob.glob(os.path.join(glob.escape(str(player_root)), "*", "*", "Player.log")):
        product_dir = Path(p).parent
        company, product = product_dir.parent.name, product_dir.name
        key = f"{company}/{product}"
        if not _matches(key, cfg["player_include"]) or _matches(key, cfg["player_exclude"]):
            continue
        # 製品名は会社をまたいで重複しうる（DefaultCompany/foo と MyCompany/foo）ので種別に会社名を入れる。
        # フォルダは製品名にして、同名プロジェクトの Editor ログと並ぶようにする
        add(Path(p), product, f"Player-{company}")

    for pattern in cfg["extra_globs"]:
        for p in glob.glob(os.path.expandvars(os.path.expanduser(pattern))):
            if os.path.isfile(p):
                add(Path(p), Path(p).parent.name, Path(p).stem)

    return found


# ---------------------------------------------------------------------------
# 写し取り
# ---------------------------------------------------------------------------

@dataclass
class Track:
    group: str
    kind: str
    dest: str
    file_id: int = 0
    offset: int = 0
    head: bytes = b""
    anchor: bytes = b""

    def to_json(self) -> dict:
        return {
            "group": self.group, "kind": self.kind, "dest": self.dest, "file_id": self.file_id,
            "offset": self.offset, "head": self.head.hex(), "anchor": self.anchor.hex(),
        }

    @classmethod
    def from_json(cls, d: dict) -> Track:
        return cls(d["group"], d["kind"], d["dest"], d.get("file_id", 0), d.get("offset", 0),
                   bytes.fromhex(d.get("head", "")), bytes.fromhex(d.get("anchor", "")))


@dataclass
class Tail:
    """上書き・退避の後に、終わりきっていない前の Unity が書き足す末尾を前の保存ファイルへ拾う。"""
    path: str    # 読むファイル（同じファイル、または退避先の -prev）
    source: str  # 元の監視パス
    file_id: int
    offset: int
    dest: str
    until: float
    anchor: bytes = b""


def prev_path(path: str) -> str | None:
    """Unity が起動時に前回分を退避する先（Editor.log → Editor-prev.log）。"""
    stem, ext = os.path.splitext(path)
    if os.path.basename(stem).lower() in ("editor", "player") and ext.lower() == ".log":
        return f"{stem}-prev{ext}"
    return None


class Keeper:
    def __init__(self, cfg: dict, now=datetime.now):
        self.cfg = cfg
        self.dest_root = Path(cfg["dest_dir"])
        self.keeper_dir = self.dest_root / KEEPER_DIR
        self.state_path = self.keeper_dir / "state.json"
        self.now = now
        self.tracks: dict[str, Track] = {}
        self.tails: list[Tail] = []
        self.projects: set[str] = set()
        self._dirty = False
        self._last_prune = float("-inf")
        self._warned: set[str] = set()
        self.keeper_dir.mkdir(parents=True, exist_ok=True)
        self._load_state()

    # --- 状態の保存 -----------------------------------------------------------

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            with open(self.state_path, encoding="utf-8") as f:
                data = json.load(f)
            self.tracks = {k: Track.from_json(v) for k, v in data.get("tracks", {}).items()}
            self.projects = set(data.get("projects", []))
            log.info("[INFO][LogKeeper] 前回の状態を読み込みました: 追跡中 %d 件", len(self.tracks))
        except (OSError, ValueError, KeyError) as e:
            # 壊れていたら最初から写し直す（重複は出るが欠落よりよい）
            log.warning("[WARN][LogKeeper] 状態ファイルを読めないので破棄します: %s", e)
            self.tracks, self.projects = {}, set()

    def mark_dirty(self) -> None:
        self._dirty = True

    def save_state(self) -> None:
        if not self._dirty:
            return
        data = {"version": 1, "projects": sorted(self.projects),
                "tracks": {k: t.to_json() for k, t in self.tracks.items()}}
        tmp = self.state_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, self.state_path)
        self._dirty = False

    # --- 監視 -----------------------------------------------------------------

    def poll(self, sources: dict[str, Source]) -> None:
        # 発見の対象から外れても、追跡中のものは消えるまで見続ける（最後の書き込みを取りこぼさない）
        for path in sorted(set(sources) | set(self.tracks)):
            try:
                self._poll_one(path, sources.get(path))
            except OSError as e:
                self._warn_once(f"os:{path}", "[WARN][LogKeeper] 読めません: %s (%s)", path, e)
        # 新しい追跡を先に進めておく。前の末尾の位置まで新しい起動が埋めたら、そこはもう前の分ではない
        self._poll_tails()
        self._prune_if_due()
        self.save_state()

    def _poll_one(self, path: str, src: Source | None) -> None:
        tr = self.tracks.get(path)
        # ファイルは読むたびに開いて閉じる。開いたままにすると、Unity の起動時に行う
        # Player.log → Player-prev.log のリネームを妨げる（Windows は共有モードに削除を含まないため）
        try:
            f = open(path, "rb")
        except FileNotFoundError:
            if tr is not None:
                self._finish(path, tr, "ファイルが消えた")
            return
        with f:
            st = os.fstat(f.fileno())
            head = f.read(min(HEAD_BYTES, st.st_size))
            if tr is not None and not self._same_file(f, st, head, tr):
                self._finish(path, tr, "上書きされた", truncated=bool(st.st_ino and st.st_ino == tr.file_id))
                tr = None
            if tr is None:
                if st.st_size == 0:
                    return
                if src is None:
                    return  # 発見の対象から外れたファイルは新たに写し始めない
                tr = self._start(path, src, st)
            self._copy(f, st.st_size, tr)
            # 覚える先頭は写し終えた範囲に限る。その先は穴（NUL）で、後から埋まって変わりうる
            head = head[: tr.offset]
            if len(tr.head) < HEAD_BYTES and len(head) > len(tr.head):
                tr.head = head
                self._dirty = True

    def _same_file(self, f, st: os.stat_result, head: bytes, tr: Track) -> bool:
        if tr.file_id and st.st_ino and st.st_ino != tr.file_id:
            return False
        if st.st_size < tr.offset:
            return False
        n = min(len(head), len(tr.head))
        if head[:n] != tr.head[:n]:
            return False
        if tr.anchor:
            f.seek(tr.offset - len(tr.anchor))
            if f.read(len(tr.anchor)) != tr.anchor:
                return False
        return True

    def _start(self, path: str, src: Source, st: os.stat_result) -> Track:
        folder = self.dest_root / src.group
        folder.mkdir(parents=True, exist_ok=True)
        stamp = self.now().strftime("%Y%m%d-%H%M%S")
        dest = folder / f"{src.kind}_{stamp}.log"
        n = 2
        while True:
            try:
                open(dest, "xb").close()
                break
            except FileExistsError:
                dest = folder / f"{src.kind}_{stamp}-{n}.log"
                n += 1
        tr = Track(src.group, src.kind, str(dest), file_id=st.st_ino)
        self.tracks[path] = tr
        self._dirty = True
        log.info("[INFO][LogKeeper] 写し始め: %s → %s", path, dest)
        return tr

    def _copy(self, f, size: int, tr: Track | Tail) -> int:
        """offset から size まで写す。穴に当たったらその手前で止め、埋まるのを待つ。"""
        if size <= tr.offset:
            return 0
        f.seek(tr.offset)
        copied = 0
        with open(tr.dest, "ab") as out:
            while tr.offset < size:
                chunk = f.read(min(READ_CHUNK, size - tr.offset))
                if not chunk:
                    break
                hole = chunk.find(HOLE)
                if hole >= 0:
                    chunk = chunk[:hole]
                elif tr.offset + len(chunk) < size and chunk.endswith(b"\0"):
                    # 読み取りの区切りに穴がまたがると、手前の NUL を写してしまう。末尾の NUL は次の読み取りへ回す
                    trimmed = chunk.rstrip(b"\0")
                    if trimmed:
                        chunk = trimmed
                        f.seek(tr.offset + len(chunk))
                out.write(chunk)
                tr.offset += len(chunk)
                tr.anchor = (tr.anchor + chunk)[-ANCHOR_BYTES:]
                copied += len(chunk)
                if hole >= 0:
                    self._once(f"hole:{tr.dest}", logging.INFO,
                               "[INFO][LogKeeper] 未書き込みの領域（NUL）に当たったので、埋まるまで待ちます: %s (offset=%d)",
                               tr.dest, tr.offset)
                    break
        if copied:
            self._dirty = True
        return copied

    def _finish(self, path: str, tr: Track, reason: str, truncated: bool = False) -> None:
        recovered, renamed = self._recover_from_prev(path, tr)
        log.info("[INFO][LogKeeper] 写し終わり（%s）: %s → %s, %d バイト（-prev から補完 %d バイト）",
                 reason, path, tr.dest, tr.offset, recovered)
        del self.tracks[path]
        self._dirty = True
        if renamed or truncated:
            self.tails.append(Tail(prev_path(path) if renamed else path, path, tr.file_id, tr.offset, tr.dest,
                                   time.monotonic() + TAIL_WATCH_SEC, tr.anchor))

    def _recover_from_prev(self, path: str, tr: Track) -> tuple[int, bool]:
        """退避された前回分が追跡中のファイルそのものなら、最後の監視以降に書かれた末尾を拾う。

        戻り値は (補完したバイト数, 退避先が追跡中のファイルだったか)。
        """
        prev = prev_path(path)
        if prev is None or not tr.file_id:
            return 0, False
        try:
            with open(prev, "rb") as f:
                st = os.fstat(f.fileno())
                if st.st_ino != tr.file_id:
                    return 0, False
                head = f.read(min(HEAD_BYTES, st.st_size))
                if not self._same_file(f, st, head, tr):
                    return 0, False
                return self._copy(f, st.st_size, tr), True
        except FileNotFoundError:
            return 0, False

    def _poll_tails(self) -> None:
        t_now = time.monotonic()
        for t in list(self.tails):
            new = self.tracks.get(t.source)
            # 同じファイルを新しい起動が前回の末尾まで埋めたら、そこから先は新しい起動の出力
            caught_up = t.path == t.source and new is not None and new.offset >= t.offset
            if t_now > t.until or caught_up:
                self.tails.remove(t)
                continue
            try:
                with open(t.path, "rb") as f:
                    st = os.fstat(f.fileno())
                    if st.st_ino != t.file_id:
                        self.tails.remove(t)
                        continue
                    self._skip_leading_nuls(f, st.st_size, t)
                    n = self._copy(f, st.st_size, t)
            except OSError:
                self.tails.remove(t)
                continue
            if n:
                log.info("[INFO][LogKeeper] 前の起動が終了処理中に書いた末尾を補完: %s に %d バイト", t.dest, n)

    @staticmethod
    def _skip_leading_nuls(f, size: int, t: Tail) -> None:
        """前の起動は、最後の監視から上書きまでに書いた分の後ろ（上書き時点のファイル末尾）へ書き足す。
        その間は上書きで消えて NUL になっており、取り戻せない。次の文字まで読み飛ばす。
        """
        pos = t.offset
        f.seek(pos)
        while pos < size:
            chunk = f.read(min(READ_CHUNK, size - pos))
            if not chunk:
                return
            skipped = len(chunk) - len(chunk.lstrip(b"\0"))
            if skipped < len(chunk):
                t.offset = pos + skipped
                return
            pos += len(chunk)
        # 末尾まで NUL なら、前の起動はまだ書いていない。位置は動かさず次の監視で見直す

    # --- 容量上限 -------------------------------------------------------------

    def _prune_if_due(self) -> None:
        t = time.monotonic()
        if t - self._last_prune < PRUNE_INTERVAL_SEC:
            return
        self._last_prune = t
        self.prune()

    def prune(self) -> None:
        limit = int(self.cfg["max_total_mb"]) * 1024 * 1024
        # 保護は「追跡中か」ではなく「最近書いたか」で決める。追跡は元のファイルが残る限り続くので
        # （二度と起動しない製品の Player.log など）、追跡中を守ると上限を小さくしても消せなくなる
        recent = time.time() - ACTIVE_GRACE_SEC
        files = []
        total = 0
        for root, dirs, names in os.walk(self.dest_root):
            if Path(root) == self.dest_root and KEEPER_DIR in dirs:
                dirs.remove(KEEPER_DIR)
            for name in names:
                p = os.path.join(root, name)
                try:
                    st = os.stat(p)
                except OSError:
                    continue
                files.append((st.st_mtime, st.st_size, p))
                total += st.st_size
        if total <= limit:
            return
        for mtime, size, p in sorted(files):
            if total <= limit:
                break
            if mtime >= recent:
                break  # 以降はすべて最近書いたもの
            try:
                os.remove(p)
            except OSError as e:
                self._warn_once(f"rm:{p}", "[WARN][LogKeeper] 削除できません: %s (%s)", p, e)
                continue
            total -= size
            log.info("[INFO][LogKeeper] 容量上限のため削除: %s (%d バイト)", p, size)
        if total > limit:
            self._warn_once("over-limit", "[WARN][LogKeeper] 直近に書いたファイルだけで容量上限を超えています（%d MB）",
                            total // (1024 * 1024))

    def _warn_once(self, key: str, msg: str, *args) -> None:
        self._once(key, logging.WARNING, msg, *args)

    def _once(self, key: str, level: int, msg: str, *args) -> None:
        if key in self._warned:
            return
        self._warned.add(key)
        log.log(level, msg, *args)


# ---------------------------------------------------------------------------
# 実行
# ---------------------------------------------------------------------------

def setup_logging(keeper_dir: Path) -> None:
    keeper_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(message)s")
    handlers: list[logging.Handler] = [logging.handlers.RotatingFileHandler(
        keeper_dir / "keeper.log", maxBytes=KEEPER_LOG_MAX_BYTES, backupCount=KEEPER_LOG_BACKUPS, encoding="utf-8")]
    # pythonw で起動したときは stderr が無い
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    for h in handlers:
        h.setFormatter(fmt)
        log.addHandler(h)
    log.setLevel(logging.INFO)


def acquire_lock(path: Path):
    """二重起動を防ぐ。手動の実行と常駐が同時に写すと保存ファイルが二重になる。"""
    f = open(path, "a+b")
    try:
        if IS_WINDOWS:
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def cmd_run(cfg: dict, once: bool) -> int:
    keeper_dir = Path(cfg["dest_dir"]) / KEEPER_DIR
    setup_logging(keeper_dir)
    lock = acquire_lock(keeper_dir / "lock")
    if lock is None:
        log.error("[ERROR][LogKeeper] 既に起動しています（%s）", keeper_dir / "lock")
        return 1
    keeper = Keeper(cfg)
    log.info("[INFO][LogKeeper] 開始: 保存先=%s 上限=%sMB 間隔=%ss", cfg["dest_dir"], cfg["max_total_mb"],
             cfg["interval_sec"])
    sources: dict[str, Source] = {}
    last_discover = float("-inf")
    # プロセス一覧の取得は別スレッドで行う。エディタの起動中は CIM の問い合わせが数十秒止まることがあり
    # （実測でタイムアウト）、その間ファイルの監視まで止めると、上書き直前の末尾を取りこぼす
    executor = ThreadPoolExecutor(max_workers=1)
    pending: Future | None = None
    try:
        while True:
            try:
                if pending is None and time.monotonic() - last_discover >= float(cfg["discover_interval_sec"]):
                    pending = executor.submit(list_unity_procs)
                    last_discover = time.monotonic()
                if pending is not None and (pending.done() or once):
                    # 先に外しておく。result() が例外を投げても次の周回で取り直せるように
                    done, pending = pending, None
                    procs = done.result()
                    known_projects = len(keeper.projects)
                    sources = discover(cfg, keeper.projects, procs,
                                       editor_log=default_editor_log(), player_root=player_log_root())
                    if len(keeper.projects) != known_projects:
                        keeper.mark_dirty()
                keeper.poll(sources)
            except Exception:  # 常駐なので 1 回の失敗で止めない
                log.exception("[ERROR][LogKeeper] 監視中に例外")
            if once:
                return 0
            time.sleep(float(cfg["interval_sec"]))
    except KeyboardInterrupt:
        log.info("[INFO][LogKeeper] 停止")
        return 0
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
        keeper.save_state()
        lock.close()


def _ps_quote(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"


def _run_args(config_arg: str | None) -> list[str]:
    args = [str(Path(__file__).resolve()), "run"]
    if config_arg:
        args += ["--config", str(Path(config_arg).resolve())]
    return args


def cmd_install(config_arg: str | None) -> int:
    if IS_WINDOWS:
        # コンソール窓を出さないため pythonw を使う
        pyw = Path(sys.executable).with_name("pythonw.exe")
        exe = str(pyw if pyw.exists() else Path(sys.executable))
        argument = " ".join(f'"{a}"' for a in _run_args(config_arg))
        # 既定の設定は「72 時間で強制終了」「バッテリー駆動で起動しない・停止する」なので常駐向けに外す
        script = f"""
$ErrorActionPreference = 'Stop'
$user = "$env:USERDOMAIN\\$env:USERNAME"
$action = New-ScheduledTaskAction -Execute {_ps_quote(exe)} -Argument {_ps_quote(argument)}
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName {_ps_quote(TOOL_NAME)} -Action $action -Trigger $trigger -Settings $settings `
  -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName {_ps_quote(TOOL_NAME)}
"""
        return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script]).returncode
    if IS_MAC:
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
        plist_path.parent.mkdir(parents=True, exist_ok=True)
        with open(plist_path, "wb") as f:
            plistlib.dump({
                "Label": LAUNCHD_LABEL,
                "ProgramArguments": [sys.executable, *_run_args(config_arg)],
                "RunAtLoad": True,
                "KeepAlive": True,
                "ProcessType": "Background",
            }, f)
        domain = f"gui/{os.getuid()}"
        subprocess.run(["launchctl", "bootout", f"{domain}/{LAUNCHD_LABEL}"], capture_output=True)
        return subprocess.run(["launchctl", "bootstrap", domain, str(plist_path)]).returncode
    print("この OS の常駐登録には対応していません", file=sys.stderr)
    return 1


def cmd_uninstall() -> int:
    if IS_WINDOWS:
        script = f"""
$ErrorActionPreference = 'Stop'
Stop-ScheduledTask -TaskName {_ps_quote(TOOL_NAME)} -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName {_ps_quote(TOOL_NAME)} -Confirm:$false
"""
        return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script]).returncode
    if IS_MAC:
        plist_path = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
        subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LAUNCHD_LABEL}"])
        plist_path.unlink(missing_ok=True)
        return 0
    print("この OS の常駐登録には対応していません", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=TOOL_NAME, description=__doc__.splitlines()[0])
    parser.add_argument("--config", help=f"設定ファイル（既定: {default_config_path()}）")
    sub = parser.add_subparsers(dest="command", required=True)
    p_run = sub.add_parser("run", help="常駐して写し取る")
    p_run.add_argument("--once", action="store_true", help="1 回だけ監視して終わる")
    sub.add_parser("install", help="ログオン時に常駐するよう登録し、起動する")
    sub.add_parser("uninstall", help="常駐を止め、登録を消す")
    sub.add_parser("show-config", help="実際に使う設定を表示する")
    # run だけはサブコマンドの後ろに --config を書けるようにする（常駐登録が組み立てる形）
    p_run.add_argument("--config", dest="run_config", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    config_arg = getattr(args, "run_config", None) or args.config
    config_path = Path(config_arg) if config_arg else default_config_path()
    if args.command == "run":
        return cmd_run(load_config(config_path), args.once)
    if args.command == "install":
        return cmd_install(config_arg)
    if args.command == "uninstall":
        return cmd_uninstall()
    if args.command == "show-config":
        print(json.dumps({"config_path": str(config_path), **load_config(config_path)},
                         ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
