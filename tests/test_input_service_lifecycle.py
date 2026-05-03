import queue
import time

from services.input_service import InputService


class _FakeWindowManager:
    ttr_window_ids = []

    def get_active_window(self):
        return None

    def get_window_ids(self):
        return []

    def assign_windows(self):
        pass


def _service():
    return InputService(
        window_manager=_FakeWindowManager(),
        get_enabled_toons=lambda: [False] * 4,
        get_movement_modes=lambda: ["Default"] * 4,
        get_event_queue_func=queue.Queue,
    )


def test_start_does_not_block_on_backend_setup(monkeypatch):
    svc = _service()

    def slow_backend_setup():
        time.sleep(0.25)

    monkeypatch.setattr(svc, "_apply_backend_setting", slow_backend_setup)

    start = time.perf_counter()
    svc.start()
    elapsed = time.perf_counter() - start

    try:
        assert elapsed < 0.1
    finally:
        svc.stop(wait=True)


def test_stop_without_wait_does_not_join_worker(monkeypatch):
    svc = _service()

    def slow_release():
        time.sleep(0.25)

    monkeypatch.setattr(svc, "release_all_keys", slow_release)
    svc.start()

    start = time.perf_counter()
    svc.stop()
    elapsed = time.perf_counter() - start

    try:
        assert elapsed < 0.1
    finally:
        svc.stop(wait=True)
