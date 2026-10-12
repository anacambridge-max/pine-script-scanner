from types import SimpleNamespace
from unittest.mock import Mock

from worker.scanner_worker import ScannerWorker
from worker.upstox_feed import UpstoxV3Feed


def test_wait_timeout_does_not_replace_healthy_feed():
    worker = ScannerWorker.__new__(ScannerWorker)
    worker.running = True
    feed = SimpleNamespace(wait_until_closed=Mock(side_effect=[False, False, True]))
    worker.feed = feed
    assert worker._wait_for_feed_close() is True
    assert worker.feed is feed
    assert feed.wait_until_closed.call_count == 3


def test_shutdown_stops_waiting_without_reconnecting():
    worker = ScannerWorker.__new__(ScannerWorker)
    worker.running = False
    worker.feed = SimpleNamespace(wait_until_closed=Mock())
    assert worker._wait_for_feed_close() is False
    worker.feed.wait_until_closed.assert_not_called()


def test_reconnect_preserves_history_and_disconnects_old_transport():
    feed = UpstoxV3Feed.__new__(UpstoxV3Feed)
    old_transport = Mock()
    new_transport = Mock()
    feed.streamer = old_transport
    feed._build_streamer = Mock(return_value=new_transport)
    feed._bars = {"TEST": {"bar": "history"}}
    feed.last_data_at = 100
    feed.rebuild_streamer()
    old_transport.disconnect.assert_called_once()
    assert feed.streamer is new_transport
    assert feed._bars == {"TEST": {"bar": "history"}}
    assert feed.last_data_at == 0
