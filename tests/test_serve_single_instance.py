"""Launching kaspion twice must join the running dashboard, not start a rival one.

Two servers on one DuckDB file is not cosmetic: DuckDB grants read-write to a single
process, so the second instance's first sync fails. It also lands on a fallback port,
which makes a double-click look like it did nothing while the browser sits on the old
URL — that is exactly how this was found.
"""
import socket

from kaspion import serve


def test_a_dead_port_is_not_mistaken_for_a_running_server():
    with socket.socket() as s:            # bind and close to get a port nobody holds
        s.bind(("127.0.0.1", 0))
        free_port = s.getsockname()[1]
    assert serve._already_serving(free_port) is False


def test_second_launch_joins_instead_of_binding(monkeypatch):
    opened = []
    monkeypatch.setattr(serve, "_already_serving", lambda port: True)
    monkeypatch.setattr(serve.webbrowser, "open", opened.append)
    monkeypatch.setattr(serve, "ThreadingHTTPServer",
                        lambda *a, **k: pytest_fail("bound a second server"))
    serve.main()
    assert opened == [f"http://{serve.HOST}:{serve.PORT}"]


def pytest_fail(msg):
    raise AssertionError(msg)
