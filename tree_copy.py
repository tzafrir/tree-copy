#!/usr/bin/env python3.10
"""
tree_sidebar.py — file tree sidebar for tmux

Usage:
    python3 tree_sidebar.py [directory]

Keys:
    ↑ / ↓           Navigate items
    Shift+↑ / ↓     Jump between sibling directories (moves to parent when out of bounds)
    Enter           Toggle directory open/close
    o               Open file with glow (pager)
    c               Copy relative path to clipboard
    C               Copy absolute path to clipboard
    q / Escape      Quit
"""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DirectoryTree, Footer

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer


class FileTree(DirectoryTree):
    BINDINGS = [
        Binding("enter",      "select_cursor",  "Toggle",     show=True),
        Binding("space",      "select_cursor",  "Toggle",     show=True),
        Binding("shift+up",   "jump_prev_dir",  "Prev dir",   show=True),
        Binding("shift+down", "jump_next_dir",  "Next dir",   show=True),
        Binding("o",          "open_glow",      "Open (glow)", show=True),
        Binding("e",          "edit_nano",      "Edit (nano)", show=True),
        Binding("c",          "copy_rel_path",  "Copy rel",   show=True),
        Binding("C",          "copy_abs_path",  "Copy abs",   show=True),
        Binding("z",          "zoom_pane",      "Zoom",       show=True),
        Binding("q",          "quit_app",       "Quit",       show=True),
        Binding("escape",     "quit_app",       "Quit",       show=False),
    ]

    # ------------------------------------------------------------------
    # Gitignore
    # ------------------------------------------------------------------

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._ignored: set[str] = set()

    def on_mount(self) -> None:
        # Check root's children after initial load
        self.set_timer(0.4, lambda: self._update_ignored(self.root))

    def on_tree_node_expanded(self, event) -> None:
        self.set_timer(0.05, lambda: self._update_ignored(event.node))

    def _update_ignored(self, node) -> None:
        paths = [p for c in node.children if (p := self._node_path(c))]
        if not paths:
            return
        newly = self._check_gitignore(paths)
        if newly - self._ignored:
            self._ignored.update(newly)
            self.refresh()

    @staticmethod
    def _check_gitignore(paths: list[Path]) -> set[str]:
        try:
            result = subprocess.run(
                ["git", "check-ignore", "--stdin"],
                input="\n".join(str(p) for p in paths),
                capture_output=True, text=True,
            )
            return set(result.stdout.splitlines())
        except Exception:
            return set()

    def render_label(self, node, base_style, style):
        label = super().render_label(node, base_style, style)
        p = self._node_path(node)
        if p and str(p) in self._ignored:
            label.stylize("color(240)")
        return label

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _node_path(self, node) -> Path | None:
        """Safely extract Path from a tree node regardless of Textual version."""
        if node is None or node.data is None:
            return None
        data = node.data
        if isinstance(data, Path):
            return data
        if hasattr(data, "path"):
            return Path(data.path)
        return None

    def _copy(self, text: str) -> None:
        """Write text to the system clipboard (cross-platform) and tmux buffer."""
        import os, platform
        data = text.encode()
        copied = False

        if os.environ.get("WSL_DISTRO_NAME"):                      # WSL2
            copied = self._run_copy(["clip.exe"], data)
        elif platform.system() == "Darwin":                        # macOS
            copied = self._run_copy(["pbcopy"], data)
        elif os.environ.get("WAYLAND_DISPLAY"):                    # Linux Wayland
            copied = self._run_copy(["wl-copy"], data)
        elif os.environ.get("DISPLAY"):                            # Linux X11
            copied = (self._run_copy(["xclip", "-selection", "clipboard"], data)
                      or self._run_copy(["xsel", "--clipboard", "--input"], data))

        if not copied:                                             # tmux-only fallback
            self._run_copy(["tmux", "set-buffer", text.encode()], data)

        # Always also set tmux buffer (convenient for paste-into-pane)
        try:
            subprocess.run(["tmux", "set-buffer", text], capture_output=True)
        except Exception:
            pass

    @staticmethod
    def _run_copy(cmd: list, data: bytes) -> bool:
        try:
            subprocess.run(cmd, input=data, check=True, capture_output=True)
            return True
        except Exception:
            return False

    def _sibling_dirs(self, node) -> list:
        """Return all directory siblings at the same level as node."""
        if node.parent is None:
            return []
        return [
            c for c in node.parent.children
            if (p := self._node_path(c)) and p.is_dir()
        ]

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _is_web(self) -> bool:
        try:
            from textual.drivers.web_driver import WebDriver
            return isinstance(self.app._driver, WebDriver)
        except Exception:
            return False

    @staticmethod
    def _find_viewer() -> list[str]:
        """Return the best available file viewer command."""
        import shutil
        if shutil.which("glow"):
            return ["glow", "-p"]
        return ["less"]

    @staticmethod
    def _find_editor() -> list[str]:
        """Return editor from TREE_COPY_EDITOR env, falling back to nano or vi."""
        import shutil
        custom = os.environ.get("TREE_COPY_EDITOR")
        if custom:
            return custom.split()
        for ed in ("nano", "vi"):
            if shutil.which(ed):
                return [ed]
        return ["vi"]

    def action_open_glow(self) -> None:
        path = self._node_path(self.cursor_node)
        if path and path.is_file():
            if self._is_web():
                self.app.notify("Not available in browser mode", severity="warning")
                return
            with self.app.suspend():
                subprocess.run([*self._find_viewer(), str(path)])

    def action_edit_nano(self) -> None:
        path = self._node_path(self.cursor_node)
        if path and path.is_file():
            if self._is_web():
                self.app.notify("Not available in browser mode", severity="warning")
                return
            with self.app.suspend():
                subprocess.run([*self._find_editor(), str(path)])

    def action_copy_rel_path(self) -> None:
        path = self._node_path(self.cursor_node)
        if not path:
            return
        try:
            text = str(path.relative_to(Path.cwd()))
        except ValueError:
            text = str(path)
        self._copy(text)
        self.app.notify(f"Copied: {text}")

    def action_copy_abs_path(self) -> None:
        path = self._node_path(self.cursor_node)
        if not path:
            return
        text = str(path.resolve())
        self._copy(text)
        self.app.notify(f"Copied: {text}")

    def action_select_cursor(self) -> None:
        node = self.cursor_node
        # Root node (parent is None): never allow collapsing
        if node is not None and node.parent is None and node.is_expanded:
            return
        super().action_select_cursor()

    def action_zoom_pane(self) -> None:
        if os.environ.get("TMUX"):
            subprocess.run(["tmux", "resize-pane", "-Z"], capture_output=True)

    def action_quit_app(self) -> None:
        self.app.exit()

    def action_jump_prev_dir(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        dirs = self._sibling_dirs(node)
        path = self._node_path(node)
        is_dir = path is not None and path.is_dir()

        if not dirs:
            # No sibling dirs — move up to parent
            if node.parent:
                self.move_cursor(node.parent)
            return

        if is_dir and node in dirs:
            idx = dirs.index(node)
            if idx > 0:
                self.move_cursor(dirs[idx - 1])
            else:
                # Already at first sibling dir — go to parent
                if node.parent:
                    self.move_cursor(node.parent)
        else:
            # On a file: find the nearest dir *before* this node among siblings
            all_children = list(node.parent.children)
            cur_pos = all_children.index(node)
            prev_dirs = [d for d in dirs if all_children.index(d) < cur_pos]
            if prev_dirs:
                self.move_cursor(prev_dirs[-1])
            elif node.parent:
                self.move_cursor(node.parent)

    def action_jump_next_dir(self) -> None:
        node = self.cursor_node
        if node is None:
            return
        dirs = self._sibling_dirs(node)
        path = self._node_path(node)
        is_dir = path is not None and path.is_dir()

        if not dirs:
            if node.parent:
                self.move_cursor(node.parent)
            return

        if is_dir and node in dirs:
            idx = dirs.index(node)
            if idx < len(dirs) - 1:
                self.move_cursor(dirs[idx + 1])
            else:
                # Already at last sibling dir — go to parent
                if node.parent:
                    self.move_cursor(node.parent)
        else:
            all_children = list(node.parent.children)
            cur_pos = all_children.index(node)
            next_dirs = [d for d in dirs if all_children.index(d) > cur_pos]
            if next_dirs:
                self.move_cursor(next_dirs[0])
            elif node.parent:
                self.move_cursor(node.parent)


class SidebarApp(App):
    CSS = """
    FileTree {
        width: 1fr;
        height: 1fr;
        border: none;
        scrollbar-gutter: stable;
    }
    Footer {
        height: 1;
    }
    """

    # Dirs to ignore when watching (noise with no useful signal)
    _WATCH_IGNORE = {"__pycache__", ".git", ".mypy_cache", ".ruff_cache", "node_modules"}

    _STATE_FILE = Path.home() / ".local" / "share" / "tree-copy" / "state.json"

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self._pending_paths: set[Path] = set()
        self._refresh_timer = None
        self._observer: Observer | None = None
        self._restore_expanded: set[str] = set()
        self._saved_cursor: str | None = None
        self._load_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        try:
            data = json.loads(self._STATE_FILE.read_text())
            saved = data.get(str(self.root), {})
            self._restore_expanded = set(saved.get("expanded", []))
            self._saved_cursor = saved.get("cursor")
        except Exception:
            pass

    def _save_state(self) -> None:
        try:
            tree = self.query_one(FileTree)
            expanded: list[str] = []

            def walk(node):
                if node.is_expanded:
                    p = tree._node_path(node)
                    if p:
                        expanded.append(str(p))
                for child in node.children:
                    walk(child)

            walk(tree.root)
            cursor_path = tree._node_path(tree.cursor_node)

            data: dict = {}
            try:
                data = json.loads(self._STATE_FILE.read_text())
            except Exception:
                pass

            data[str(self.root)] = {
                "expanded": expanded,
                "cursor": str(cursor_path) if cursor_path else None,
            }
            self._STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            self._STATE_FILE.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def on_tree_node_expanded(self, event) -> None:
        """Cascade expansion to restore saved state."""
        if not self._restore_expanded:
            return
        # Give DirectoryTree a moment to populate the node's children
        self.set_timer(0.1, lambda: self._expand_children(event.node))

    def _expand_children(self, node) -> None:
        tree = self.query_one(FileTree)
        for child in node.children:
            p = tree._node_path(child)
            if p and str(p) in self._restore_expanded:
                child.expand()

    def _restore_state(self) -> None:
        """Kick off cascade expansion from root's already-loaded children."""
        tree = self.query_one(FileTree)
        for child in tree.root.children:
            p = tree._node_path(child)
            if p and str(p) in self._restore_expanded:
                child.expand()
        if self._saved_cursor:
            self.set_timer(1.2, self._restore_cursor)

    def _restore_cursor(self) -> None:
        tree = self.query_one(FileTree)
        target = Path(self._saved_cursor)

        def walk(node):
            if tree._node_path(node) == target:
                tree.move_cursor(node)
                return True
            for child in node.children:
                if walk(child):
                    return True
            return False

        walk(tree.root)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        app = self

        class Handler(FileSystemEventHandler):
            def on_any_event(self, event):
                src = Path(event.src_path)
                if any(part in app._WATCH_IGNORE for part in src.parts):
                    return
                changed = src if src.is_dir() else src.parent
                app.call_from_thread(app._queue_refresh, changed)
                if hasattr(event, "dest_path") and event.dest_path:
                    dest = Path(event.dest_path)
                    dest_dir = dest if dest.is_dir() else dest.parent
                    app.call_from_thread(app._queue_refresh, dest_dir)

        self._observer = Observer()
        self._observer.schedule(Handler(), str(self.root), recursive=True)
        self._observer.start()

        signal.signal(signal.SIGTERM, lambda s, f: (self._cleanup_marker(), sys.exit(0)))
        self.set_interval(30, self._save_state)
        self.set_timer(0.5, self._restore_state)
        self._create_marker()

    def on_unmount(self) -> None:
        self._save_state()
        self._cleanup_marker()
        if self._observer:
            self._observer.stop()
            self._observer.join()

    @staticmethod
    def _marker_path() -> Path | None:
        pane = os.environ.get("TMUX_PANE")
        return Path(f"/tmp/tree-copy-{pane}") if pane else None

    def _create_marker(self) -> None:
        m = self._marker_path()
        if m:
            m.touch()

    def _cleanup_marker(self) -> None:
        m = self._marker_path()
        if m:
            try:
                m.unlink(missing_ok=True)
            except Exception:
                pass

    def _queue_refresh(self, path: Path) -> None:
        """Debounce filesystem events and batch reloads (runs on main thread)."""
        self._pending_paths.add(path)
        if self._refresh_timer is not None:
            self._refresh_timer.stop()
        self._refresh_timer = self.set_timer(0.3, self._flush_refresh)

    def _flush_refresh(self) -> None:
        """Reload tree nodes for all queued changed paths."""
        tree = self.query_one(FileTree)
        for path in self._pending_paths:
            node = self._find_node(tree, path)
            if node is not None and node.is_expanded:
                tree.reload_node(node)
        self._pending_paths.clear()
        self._refresh_timer = None

    def _find_node(self, tree: "FileTree", path: Path):
        """Walk loaded tree nodes to find the one matching path."""
        def walk(node):
            if tree._node_path(node) == path:
                return node
            for child in node.children:
                found = walk(child)
                if found:
                    return found
            return None
        return walk(tree.root)

    _HIDDEN_COMMANDS = {"Screenshot", "Maximize", "Minimize"}

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        for cmd in super().get_system_commands(screen):
            if cmd.title not in self._HIDDEN_COMMANDS:
                yield cmd

    def compose(self) -> ComposeResult:
        yield FileTree(self.root)
        yield Footer()


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        prog="tree-copy",
        description="Keyboard-driven file tree sidebar for tmux.",
    )
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Root directory to browse (default: current directory)",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Serve the app in a browser via textual-serve",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port for --serve mode (default: 8000)",
    )
    args = parser.parse_args()
    root = Path(args.directory).resolve()
    if not root.is_dir():
        parser.error(f"{root} is not a directory")

    if args.serve:
        try:
            from textual_serve.server import Server
        except ImportError:
            parser.error("textual-serve is required: pip install textual-serve")
        cmd = f"{sys.executable} {Path(__file__).resolve()} {root}"
        server = Server(command=cmd, host="localhost", port=args.port)
        print(f"Serving at http://localhost:{args.port}")
        server.serve()
    else:
        SidebarApp(root).run()


if __name__ == "__main__":
    main()
