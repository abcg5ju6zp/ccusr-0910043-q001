# import logging

# from unittest.mock import Mock

# import pytest

# from sanic import Sanic
# from sanic.response import text
# from sanic.server.async_server import AsyncioServer
# from sanic.signals import Event
# from sanic.touchup.schemes.ode import OptionalDispatchEvent


# try:
#     from unittest.mock import AsyncMock
# except ImportError:
#     from tests.asyncmock import AsyncMock  # type: ignore


# @pytest.fixture
# def app_one():
#     app = Sanic("One")

#     @app.get("/one")
#     async def one(request):
#         return text("one")

#     return app


# @pytest.fixture
# def app_two():
#     app = Sanic("Two")

#     @app.get("/two")
#     async def two(request):
#         return text("two")

#     return app


# @pytest.fixture(autouse=True)
# def clean():
#     Sanic._app_registry = {}
#     yield


# def test_serve_same_app_multiple_tuples(app_one, run_multi):
#     app_one.prepare(port=23456)
#     app_one.prepare(port=23457)

#     logs = run_multi(app_one)
#     assert (
#         "sanic.root",
#         logging.INFO,
#         "Goin' Fast @ http://127.0.0.1:23456",
#     ) in logs
#     assert (
#         "sanic.root",
#         logging.INFO,
#         "Goin' Fast @ http://127.0.0.1:23457",
#     ) in logs


# def test_serve_multiple_apps(app_one, app_two, run_multi):
#     app_one.prepare(port=23456)
#     app_two.prepare(port=23457)

#     logs = run_multi(app_one)
#     assert (
#         "sanic.root",
#         logging.INFO,
#         "Goin' Fast @ http://127.0.0.1:23456",
#     ) in logs
#     assert (
#         "sanic.root",
#         logging.INFO,
#         "Goin' Fast @ http://127.0.0.1:23457",
#     ) in logs


# def test_listeners_on_secondary_app(app_one, app_two, run_multi):
#     app_one.prepare(port=23456)
#     app_two.prepare(port=23457)

#     before_start = AsyncMock()
#     after_start = AsyncMock()
#     before_stop = AsyncMock()
#     after_stop = AsyncMock()

#     app_two.before_server_start(before_start)
#     app_two.after_server_start(after_start)
#     app_two.before_server_stop(before_stop)
#     app_two.after_server_stop(after_stop)

#     run_multi(app_one)

#     before_start.assert_awaited_once()
#     after_start.assert_awaited_once()
#     before_stop.assert_awaited_once()
#     after_stop.assert_awaited_once()


# @pytest.mark.parametrize(
#     "events",
#     (
#         (Event.HTTP_LIFECYCLE_BEGIN,),
#         (Event.HTTP_LIFECYCLE_BEGIN, Event.HTTP_LIFECYCLE_COMPLETE),
#         (
#             Event.HTTP_LIFECYCLE_BEGIN,
#             Event.HTTP_LIFECYCLE_COMPLETE,
#             Event.HTTP_LIFECYCLE_REQUEST,
#         ),
#     ),
# )
# def test_signal_synchronization(app_one, app_two, run_multi, events):
#     app_one.prepare(port=23456)
#     app_two.prepare(port=23457)

#     for event in events:
#         app_one.signal(event)(AsyncMock())

#     run_multi(app_one)

#     assert len(app_two.signal_router.routes) == len(events) + 1

#     signal_handlers = {
#         signal.handler
#         for signal in app_two.signal_router.routes
#         if signal.name.startswith("http")
#     }

#     assert len(signal_handlers) == 1
#     assert list(signal_handlers)[0] is OptionalDispatchEvent.noop


# def test_warning_main_process_listeners_on_secondary(
#     app_one, app_two, run_multi
# ):
#     app_two.main_process_start(AsyncMock())
#     app_two.main_process_stop(AsyncMock())
#     app_one.prepare(port=23456)
#     app_two.prepare(port=23457)

#     log = run_multi(app_one)

#     message = (
#         f"Sanic found 2 listener(s) on "
#         "secondary applications attached to the main "
#         "process. These will be ignored since main "
#         "process listeners can only be attached to your "
#         "primary application: "
#         f"{repr(app_one)}"
#     )

#     assert ("sanic.error", logging.WARNING, message) in log


# def test_no_applications():
#     Sanic._app_registry = {}
#     message = "Did not find any applications."
#     with pytest.raises(RuntimeError, match=message):
#         Sanic.serve()


# def test_oserror_warning(app_one, app_two, run_multi, capfd):
#     orig = AsyncioServer.__await__
#     AsyncioServer.__await__ = Mock(side_effect=OSError("foo"))
#     app_one.prepare(port=23456, workers=2)
#     app_two.prepare(port=23457, workers=2)

#     run_multi(app_one)

#     captured = capfd.readouterr()
#     assert (
#         "An OSError was detected on startup. The encountered error was: foo"
#     ) in captured.err

#     AsyncioServer.__await__ = orig


# def test_running_multiple_offset_warning(app_one, app_two, run_multi, capfd):
#     app_one.prepare(port=23456, workers=2)
#     app_two.prepare(port=23457)

#     run_multi(app_one)

#     captured = capfd.readouterr()
#     assert (
#         f"The primary application {repr(app_one)} is running "
#         "with 2 worker(s). All "
#         "application instances will run with the same number. "
#         f"You requested {repr(app_two)} to run with "
#         "1 worker(s), which will be ignored "
#         "in favor of the primary application."
#     ) in captured.err


# def test_running_multiple_secondary(app_one, app_two, run_multi, capfd):
#     app_one.prepare(port=23456, workers=2)
#     app_two.prepare(port=23457)

#     before_start = AsyncMock()
#     app_two.before_server_start(before_start)
#     run_multi(app_one)

#     before_start.await_count == 2


import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from pathlib import Path

import pytest

import sanic


MULTI_APP_SCRIPT = """
import sys

from sanic import Sanic
from sanic.response import json

app_one = Sanic("MultiOne")
app_two = Sanic("MultiTwo")


@app_one.get("/state")
async def one_state(request):
    return json({"app": app_one.name, "debug": app_one.debug})


@app_two.get("/state")
async def two_state(request):
    return json({"app": app_two.name, "debug": app_two.debug})


@app_two.get("/boom")
async def boom(request):
    raise Exception("boom")


for app in (app_one, app_two):

    @app.before_server_start
    async def before_start(app):
        print(f"BEFORE_START {app.name}", flush=True)

    @app.after_server_start
    async def after_start(app):
        print(f"AFTER_START {app.name}", flush=True)

    @app.before_server_stop
    async def before_stop(app):
        print(f"BEFORE_STOP {app.name}", flush=True)

    @app.after_server_stop
    async def after_stop(app):
        print(f"AFTER_STOP {app.name}", flush=True)


if __name__ == "__main__":
    app_one.prepare(
        host="127.0.0.1", port=int(sys.argv[1]), dev=sys.argv[3] == "1"
    )
    app_two.prepare(
        host="127.0.0.1", port=int(sys.argv[2]), dev=sys.argv[4] == "1"
    )
    Sanic.serve(primary=app_one)
"""


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("", 0))
        return sock.getsockname()[1]


def _fetch(url: str, timeout: float = 5):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _wait_for(url: str, proc: subprocess.Popen, timeout: float = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return True
        except Exception:
            if proc.poll() is not None:
                return False
            time.sleep(0.25)
    return False


@pytest.mark.parametrize("primary_dev", (True, False))
@pytest.mark.parametrize("secondary_dev", (True, False))
def test_serve_multiple_apps_with_mixed_modes(
    tmp_path: Path, primary_dev: bool, secondary_dev: bool
):
    script = tmp_path / "multi_app.py"
    script.write_text(MULTI_APP_SCRIPT)
    port_one = _free_port()
    port_two = _free_port()
    log_path = tmp_path / "server.log"

    env = dict(os.environ)
    # Make sure the subprocess imports the same sanic as the test suite
    repo_root = str(Path(sanic.__file__).parent.parent)
    env["PYTHONPATH"] = os.pathsep.join(
        [repo_root, *env.get("PYTHONPATH", "").split(os.pathsep)]
    )

    with open(log_path, "w") as log:
        proc = subprocess.Popen(
            [
                sys.executable,
                "-u",
                str(script),
                str(port_one),
                str(port_two),
                "1" if primary_dev else "0",
                "1" if secondary_dev else "0",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
        try:
            url_one = f"http://127.0.0.1:{port_one}/state"
            url_two = f"http://127.0.0.1:{port_two}/state"
            assert _wait_for(url_one, proc), "primary app did not come up"
            assert _wait_for(url_two, proc), "secondary app did not come up"

            # Each application runs with the mode it was prepared with
            status, data = _fetch(url_one)
            assert status == 200
            assert data == {"app": "MultiOne", "debug": primary_dev}
            status, data = _fetch(url_two)
            assert status == 200
            assert data == {"app": "MultiTwo", "debug": secondary_dev}

            # The exception path works and the server stays up
            status, _ = _fetch(f"http://127.0.0.1:{port_two}/boom")
            assert status == 500
            status, data = _fetch(url_two)
            assert status == 200
            assert data == {"app": "MultiTwo", "debug": secondary_dev}

            # Let the worker settle past its ack window before signaling
            # so the shutdown does not race worker startup
            time.sleep(3)
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait()
                raise

    # Clean shutdown: the main process exited on its own
    assert proc.returncode == 0

    output = log_path.read_text()
    # Lifecycle listeners ran for both applications
    for event in ("BEFORE_START", "AFTER_START", "BEFORE_STOP", "AFTER_STOP"):
        for name in ("MultiOne", "MultiTwo"):
            assert f"{event} {name}" in output
    # The builtin HTTP lifecycle signals did not fail to dispatch
    assert "Could not find signal" not in output
    assert "protocol.connection_task uncaught" not in output
