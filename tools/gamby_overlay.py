#!/usr/bin/env python3
"""
Transparent GTK overlay window that displays a build-status image.

Usage:
    gamby_overlay.py <happy.png> <sad.png> <state_file>

The state file is polled every 500 ms for one of three values:
  happy  - show the happy image (default)
  sad    - switch to the sad image
  done   - close the window and exit
"""

import sys
import os

def main():
    if len(sys.argv) != 4:
        print(f"Usage: {sys.argv[0]} <happy.png> <sad.png> <state_file>", file=sys.stderr)
        sys.exit(1)

    happy_path, sad_path, state_file = sys.argv[1], sys.argv[2], sys.argv[3]

    try:
        import gi
        gi.require_version("Gtk", "3.0")
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import Gtk, Gdk, GdkPixbuf, GLib
    except Exception as e:
        print(f"gamby_overlay: GTK not available ({e}), skipping overlay", file=sys.stderr)
        sys.exit(1)

    class OverlayWindow(Gtk.Window):
        def __init__(self):
            super().__init__(type=Gtk.WindowType.POPUP)
            self.current_state = "happy"

            self.set_decorated(False)
            self.set_keep_above(True)
            self.set_skip_taskbar_hint(True)
            self.set_skip_pager_hint(True)
            self.set_accept_focus(False)
            self.set_app_paintable(True)

            # Request RGBA visual so the window background can be transparent.
            screen = self.get_screen()
            visual = screen.get_rgba_visual()
            if visual and screen.is_composited():
                self.set_visual(visual)

            # Transparent background via CSS.
            css = b"window { background-color: rgba(0,0,0,0); }"
            provider = Gtk.CssProvider()
            provider.load_from_data(css)
            Gtk.StyleContext.add_provider_for_screen(
                screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )

            self.img_widget = Gtk.Image()
            self.add(self.img_widget)

            self._load(happy_path)
            self.show_all()
            self._reposition()

            GLib.timeout_add(500, self._poll)

        def _load(self, path):
            try:
                pb = GdkPixbuf.Pixbuf.new_from_file(path)
                self.img_widget.set_from_pixbuf(pb)
                self.resize(pb.get_width(), pb.get_height())
                self._reposition()
            except Exception as e:
                print(f"gamby_overlay: cannot load {path}: {e}", file=sys.stderr)

        def _reposition(self):
            screen = self.get_screen()
            sw, sh = screen.get_width(), screen.get_height()
            ww, wh = self.get_size()
            pos = os.environ.get("GAMBY_OVERLAY_POSITION", "bottom-right")
            margin = 30
            taskbar = 60
            if "right" in pos:
                x = sw - ww - margin
            else:
                x = margin
            if "bottom" in pos:
                y = sh - wh - taskbar
            else:
                y = margin
            self.move(x, y)

        def _poll(self):
            try:
                with open(state_file) as fh:
                    state = fh.read().strip()
            except OSError:
                return True

            if state == "done":
                Gtk.main_quit()
                return False

            if state != self.current_state:
                self.current_state = state
                self._load(sad_path if state == "sad" else happy_path)

            return True

    win = OverlayWindow()
    Gtk.main()


if __name__ == "__main__":
    main()
