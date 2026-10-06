import logging
import socket

from os import environ
from unittest.mock import Mock, patch

import pytest

from sanic.app import Sanic
from sanic.application.constants import Mode
from sanic.worker.loader import AppLoader
from sanic.worker.multiplexer import WorkerMultiplexer
from sanic.worker.process import Worker, WorkerProcess
from sanic.worker.serve import worker_serve


@pytest.fixture
def mock_app():
    app = Mock()
    server_info = Mock()
    server_info.settings = {"app": app}
    app.state.workers = 1
    app.listeners = {"main_process_ready": []}
    app.get_motd_data.return_value = ({"packages": ""}, {})
    app.state.server_info = [server_info]
    return app


def args(app, **kwargs):
    params = {**kwargs}
    params.setdefault("host", "127.0.0.1")
    params.setdefault("port", 9999)
    params.setdefault("app_name", "test_config_app")
    params.setdefault("monitor_publisher", None)
    params.setdefault("app_loader", AppLoader(factory=lambda: app))
    return params


def test_config_app(mock_app: Mock):
    with patch("sanic.worker.serve._serve_http_1"):
        worker_serve(**args(mock_app, config={"FOO": "BAR"}))
    mock_app.update_config.assert_called_once_with({"FOO": "BAR"})


def test_bad_process(mock_app: Mock, caplog):
    environ["SANIC_WORKER_NAME"] = (
        f"{Worker.WORKER_PREFIX}-{WorkerProcess.SERVER_LABEL}-FOO"
    )

    message = "No restart publisher found in worker process"
    with pytest.raises(RuntimeError, match=message):
        worker_serve(**args(mock_app))

    message = "No worker state found in worker process"
    publisher = Mock()
    with caplog.at_level(logging.ERROR):
        worker_serve(**args(mock_app, monitor_publisher=publisher))

    assert ("sanic.error", logging.ERROR, message) in caplog.record_tuples
    publisher.send.assert_called_once_with("__TERMINATE_EARLY__")

    del environ["SANIC_WORKER_NAME"]


def test_has_multiplexer(app: Sanic):
    environ["SANIC_WORKER_NAME"] = (
        f"{Worker.WORKER_PREFIX}-{WorkerProcess.SERVER_LABEL}-FOO"
    )

    Sanic.register_app(app)
    with patch("sanic.worker.serve._serve_http_1"):
        worker_serve(
            **args(app, monitor_publisher=Mock(), worker_state=Mock())
        )
    assert isinstance(app.multiplexer, WorkerMultiplexer)

    del environ["SANIC_WORKER_NAME"]


@patch("sanic.mixins.startup.WorkerManager")
def test_serve_app_implicit(wm: Mock, app):
    app.prepare()
    Sanic.serve()
    wm.call_args[0] == app.state.workers


@patch("sanic.mixins.startup.WorkerManager")
def test_serve_app_explicit(wm: Mock, mock_app):
    Sanic.serve(mock_app)
    wm.call_args[0] == mock_app.state.workers


@patch("sanic.mixins.startup.WorkerManager")
def test_serve_app_loader(wm: Mock, mock_app):
    Sanic.serve(app_loader=AppLoader(factory=lambda: mock_app))
    wm.call_args[0] == mock_app.state.workers
    # Sanic.serve(factory=lambda: mock_app)


@patch("sanic.mixins.startup.WorkerManager")
def test_serve_app_factory(wm: Mock, mock_app):
    Sanic.serve(factory=lambda: mock_app)
    wm.call_args[0] == mock_app.state.workers


@patch("sanic.mixins.startup.WorkerManager")
@pytest.mark.parametrize("config", (True, False))
def test_serve_with_inspector(
    WorkerManager: Mock, mock_app: Mock, config: bool
):
    Inspector = Mock()
    mock_app.config.INSPECTOR = config
    mock_app.inspector_class = Inspector
    inspector = Mock()
    Inspector.return_value = inspector
    WorkerManager.return_value = WorkerManager

    Sanic.serve(mock_app)

    if config:
        Inspector.assert_called_once()
        WorkerManager.manage.assert_called_once_with(
            "Inspector", inspector, {}, transient=False
        )
    else:
        Inspector.assert_not_called()
        WorkerManager.manage.assert_not_called()


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("", 0))
        return sock.getsockname()[1]


@pytest.fixture
def two_apps():
    app_one = Sanic("test_serve_one")
    app_two = Sanic("test_serve_two")
    yield app_one, app_two
    Sanic._app_registry.clear()


@patch("sanic.mixins.startup.WorkerManager")
def test_serve_builds_passthru_for_each_app(WorkerManager: Mock, two_apps):
    app_one, app_two = two_apps
    app_one.prepare(host="127.0.0.1", port=_free_port(), dev=True, verbosity=1)
    app_two.prepare(
        host="127.0.0.1",
        port=_free_port(),
        verbosity=2,
        access_log=False,
    )

    Sanic.serve(primary=app_one)

    kwargs = WorkerManager.call_args[0][2]
    passthru = kwargs["passthru"]
    assert set(passthru.keys()) == {"test_serve_one", "test_serve_two"}

    one = passthru["test_serve_one"]
    assert one["state"]["mode"] is Mode.DEBUG
    assert one["state"]["verbosity"] == 1
    assert one["auto_reload"] is True
    assert one["config"]["ACCESS_LOG"] is True
    assert "shared_ctx" in one

    two = passthru["test_serve_two"]
    assert two["state"]["mode"] is Mode.PRODUCTION
    assert two["state"]["verbosity"] == 2
    assert two["auto_reload"] is False
    assert two["config"]["ACCESS_LOG"] is False
    assert "shared_ctx" in two


def test_worker_serve_hydrates_each_app_with_own_passthru(app: Sanic):
    other = Sanic("test_hydration_secondary")
    passthru = {
        app.name: {
            "auto_reload": False,
            "state": {"verbosity": 1, "mode": Mode.DEBUG},
            "config": {"ACCESS_LOG": True, "NOISY_EXCEPTIONS": False},
            "shared_ctx": {},
        },
        other.name: {
            "auto_reload": True,
            "state": {"verbosity": 3, "mode": Mode.DEBUG},
            "config": {"ACCESS_LOG": False, "NOISY_EXCEPTIONS": True},
            "shared_ctx": {"foo": "bar"},
        },
    }

    with patch("sanic.worker.serve._serve_http_1"):
        worker_serve(**args(app, passthru=passthru))

    assert app.state.mode is Mode.DEBUG
    assert app.state.verbosity == 1
    assert app.state.auto_reload is False
    assert app.config.ACCESS_LOG is True
    assert app.config.NOISY_EXCEPTIONS is False

    assert other.state.mode is Mode.DEBUG
    assert other.state.verbosity == 3
    assert other.state.auto_reload is True
    assert other.config.ACCESS_LOG is False
    assert other.config.NOISY_EXCEPTIONS is True
    assert other.shared_ctx.foo == "bar"


def test_worker_serve_without_passthru(app: Sanic):
    with patch("sanic.worker.serve._serve_http_1"):
        worker_serve(**args(app))
    assert app.state.mode is Mode.PRODUCTION
