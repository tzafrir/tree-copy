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

import subprocess
import sys
from pathlib import Path

from textual.app import App, ComposeResult, SystemCommand
from textual.screen import Screen
from typing import Iterable
from textual.binding import Binding
from textual.widgets import DirectoryTree, Footer


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
        Binding("q",          "quit_app",       "Quit",       show=True),
        Binding("escape",     "quit_app",       "Quit",       show=False),
    ]

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

    def action_open_glow(self) -> None:
        path = self._node_path(self.cursor_node)
        if path and path.is_file():
            with self.app.suspend():
                subprocess.run(["glow", "-p", str(path)])

    def action_edit_nano(self) -> None:
        path = self._node_path(self.cursor_node)
        if path and path.is_file():
            with self.app.suspend():
                subprocess.run(["nano", str(path)])

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

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root

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
    args = parser.parse_args()
    root = Path(args.directory).resolve()
    if not root.is_dir():
        parser.error(f"{root} is not a directory")
    SidebarApp(root).run()


if __name__ == "__main__":
    main()
