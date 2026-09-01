"""TradingView BTC chart in a WebKitGTK widget. Falls back to a placeholder."""
from __future__ import annotations
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

_HTML = """<!doctype html><html><head><meta charset='utf-8'>
<style>html,body{margin:0;background:#000;color:#fff;font-family:sans-serif;height:100%;}</style>
</head><body>
<div class="tradingview-widget-container" style="height:100%;width:100%;">
  <div class="tradingview-widget-container__widget" style="height:100%;width:100%;"></div>
  <script type="text/javascript" src="https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js" async>
  {
    "symbol": "BINANCE:BTCUSDT",
    "interval": "240",
    "timezone": "Europe/Zurich",
    "theme": "dark",
    "style": "1",
    "autosize": true,
    "locale": "en",
    "backgroundColor": "rgba(0,0,0,1)",
    "gridColor": "rgba(255,255,255,0.05)",
    "hide_top_toolbar": false,
    "hide_side_toolbar": false,
    "allow_symbol_change": true,
    "withdateranges": true,
    "hide_volume": true,
    "save_image": false,
    "calendar": false,
    "studies": ["STD;Divergence%1Indicator"]
  }
  </script>
</div>
</body></html>"""


def _try_webview() -> Gtk.Widget | None:
    try:
        gi.require_version("WebKit", "6.0")
        from gi.repository import WebKit  # type: ignore
    except Exception:
        try:
            gi.require_version("WebKit2", "5.0")
            from gi.repository import WebKit2 as WebKit  # type: ignore
        except Exception:
            return None
    try:
        view = WebKit.WebView()
        view.load_html(_HTML, "https://tradingview.com/")
        view.set_hexpand(True); view.set_vexpand(True)
        return view
    except Exception as e:
        print(f"[xeneon-edge] WebKit init failed: {e}")
        return None


def make_chart_widget() -> Gtk.Widget:
    view = _try_webview()
    if view is not None:
        wrap = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        wrap.add_css_class("panel")
        wrap.append(view)
        return wrap
    # fallback placeholder
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    box.add_css_class("panel")
    box.set_vexpand(True); box.set_hexpand(True)
    title = Gtk.Label(label="BTC/USDT", xalign=0)
    title.add_css_class("panel-label")
    box.append(title)
    msg = Gtk.Label(
        label="Chart-Widget braucht WebKitGTK 6.0.\nInstalliere mit:\n\n  sudo dnf install webkitgtk6.0",
        xalign=0)
    msg.add_css_class("muted")
    msg.set_wrap(True)
    box.append(msg)
    return box
