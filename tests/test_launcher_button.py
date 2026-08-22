"""The dashboard's "start kaspion" button only works if the kaspion:// handler that the
launchers register stays wired to the same scheme the page opens."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_scheme_is_registered_by_both_launchers_and_used_by_the_page():
    mac = (ROOT / "kaspion.command").read_text()
    assert "CFBundleURLSchemes:0 string kaspion" in mac
    assert "osacompile" in mac and "lsregister" in mac

    win = (ROOT / "kaspion.bat").read_text()
    assert r"HKCU\Software\Classes\kaspion\shell\open\command" in win
    assert "URL Protocol" in win

    js = (ROOT / "kaspion" / "assets" / "app.js").read_text()
    assert "kaspion://" in js
    assert "downgo" in (ROOT / "kaspion" / "assets" / "app.html").read_text()


def test_handler_registration_cannot_abort_the_launch():
    """kaspion.command runs under `set -e`, which DOES fire on the last command of an
    `&&` chain. Without the trailing `|| true` a machine where lsregister returns
    nonzero never reaches the exec, so the dashboard simply never starts."""
    mac = (ROOT / "kaspion.command").read_text()
    chain = mac.split("osacompile", 1)[1].split("\nfi", 1)[0]
    assert "|| true" in chain


def test_the_applet_is_launchable_by_double_click_not_only_by_url():
    """Kaspion.app is what a person actually clicks — it carries the icon and the name.
    Built with only `on open location` it answered kaspion:// URLs but did nothing at
    all when double-clicked: it launched, found no `on run`, and quit. Both entry points
    must exist, and kaspion.command must rebuild a stale bundle rather than keep one."""
    mac = (ROOT / "kaspion.command").read_text()
    assert "on run" in mac and "on open location" in mac
    assert '-ot "$0"' in mac, "a stale Kaspion.app must be rebuilt when this file changes"
