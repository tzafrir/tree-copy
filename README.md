# tree-copy

A keyboard-driven file tree sidebar for tmux, built with [Textual](https://github.com/Textualize/textual).

Browse your project, jump between directories, copy paths, and preview files — without leaving the terminal.

## Features

- Navigate the file tree with arrow keys
- Jump between sibling directories with `Shift+↑/↓`
- Copy relative or absolute paths to clipboard
- Preview files with [glow](https://github.com/charmbracelet/glow)
- Root folder stays open (non-collapsible)

## Requirements

- Python 3.10+
- [glow](https://github.com/charmbracelet/glow) (for file preview)

## Install

```bash
pip install tree-copy
```

Or from source:

```bash
pip install .
```

## Usage

```bash
tree-copy [directory]   # defaults to current directory
```

As a tmux split pane, add to `~/.tmux.conf`:

```bash
bind-key e split-window -hb -l 35 "tree-copy #{pane_current_path}"
```

## Keybindings

| Key | Action |
|-----|--------|
| `↑` / `↓` | Navigate |
| `Shift+↑` / `Shift+↓` | Jump between sibling directories; moves to parent at bounds |
| `Enter` / `Space` | Toggle directory open/close |
| `o` | Preview file with glow |
| `e` | Edit file with nano |
| `c` | Copy relative path to clipboard |
| `C` | Copy absolute path to clipboard |
| `q` / `Esc` | Quit |

## License

[MIT](LICENSE)
