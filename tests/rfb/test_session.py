import asyncio

import numpy as np
import pytest
from PIL import Image

from app.rfb.session import RFBSession, open_session
from tests.fakes.rfb_server import FakeRFBServer


@pytest.fixture
def screen(tmp_path):
    rgb = np.random.default_rng(0).integers(0, 256, (48, 64, 3), np.uint8)
    path = tmp_path / "screen.png"
    Image.fromarray(rgb).save(path)
    return path, rgb


async def test_fb_is_the_served_screen_after_connect(screen):
    png, rgb = screen
    async with FakeRFBServer(png, "secret") as srv:
        s = await open_session(srv.url, "secret")
        assert (s.w, s.h) == (64, 48)
        assert np.array_equal(s.fb[:, :, 2::-1], rgb)
        await s.close()


async def _until(cond, timeout=2.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while not cond() and loop.time() < end:
        await asyncio.sleep(0.01)


async def test_click_arrives_as_move_press_release(screen):
    async with FakeRFBServer(screen[0], "secret") as srv:
        s = await open_session(srv.url, "secret")
        await s.click(10, 20)
        await _until(lambda: len(srv.events) >= 3)
        assert srv.events == [("pointer", 0, 10, 20), ("pointer", 1, 10, 20), ("pointer", 0, 10, 20)]
        await s.close()


async def test_type_and_key_arrive_as_key_events(screen):
    async with FakeRFBServer(screen[0], "secret") as srv:
        s = await open_session(srv.url, "secret")
        await s.type("añ")
        await s.key("enter")
        await _until(lambda: len(srv.events) >= 6)
        assert srv.events == [("key", 1, 0x61), ("key", 0, 0x61), ("key", 1, 0xF1), ("key", 0, 0xF1),
                              ("key", 1, 0xFF0D), ("key", 0, 0xFF0D)]
        await s.close()


async def test_wrong_password_raises(screen):
    async with FakeRFBServer(screen[0], "secret") as srv:
        with pytest.raises(RuntimeError, match="auth"):
            await open_session(srv.url, "wrong")


async def test_joins_shared_and_asks_only_raw_and_copyrect(screen):
    async with FakeRFBServer(screen[0], "secret") as srv:
        s = await open_session(srv.url, "secret")
        assert srv.shared == 1
        assert srv.encodings == [0, 1]
        await s.close()


async def test_scripted_paint_and_clipboard_reach_the_session(screen):
    async with FakeRFBServer(screen[0], "secret") as srv:
        s = await open_session(srv.url, "secret")
        await srv.paint(5, 6, np.full((3, 4, 3), (255, 0, 0), np.uint8))
        await srv.push_clipboard("año")
        await _until(lambda: s.clipboard)
        assert s.fb[6:9, 5:9, 2::-1].tolist() == [[[255, 0, 0]] * 4] * 3
        assert s.clipboard == "año"
        await s.close()


async def test_send_clipboard_arrives_byte_for_byte_as_latin1(screen):
    text = ("Señor Muñoz, cédula 1.234.567; " * 7)[:200]
    async with FakeRFBServer(screen[0], "secret") as srv:
        s = await open_session(srv.url, "secret")
        await s.send_clipboard(text)
        await _until(lambda: srv.cut_texts)
        assert srv.cut_texts == [text]
        await s.close()


async def test_wait_clipboard_returns_the_next_server_cut_text(screen):
    async with FakeRFBServer(screen[0], "secret") as srv:
        s = await open_session(srv.url, "secret")
        waiter = asyncio.create_task(s.wait_clipboard(2))
        await asyncio.sleep(0.05)
        await srv.push_clipboard("Nombre\tCédula\nAna\t123")
        assert await waiter == "Nombre\tCédula\nAna\t123"
        assert s.clipboard == "Nombre\tCédula\nAna\t123"
        await s.close()


async def test_wait_clipboard_is_none_after_timeout(screen):
    async with FakeRFBServer(screen[0], "secret") as srv:
        s = await open_session(srv.url, "secret")
        assert await s.wait_clipboard(0.1) is None
        await s.close()


async def _two_phase_paint(srv):
    """SIGECOM-style paint: a rectangle now, a second one 300 ms later elsewhere."""
    await srv.paint(0, 0, np.zeros((4, 4, 3), np.uint8))
    await asyncio.sleep(0.3)
    await srv.paint(40, 30, np.zeros((4, 4, 3), np.uint8))


async def test_settle_with_expect_waits_for_the_second_paint(screen):
    async with FakeRFBServer(screen[0], "secret") as srv:
        s = await open_session(srv.url, "secret")
        await s.click(1, 1)
        painter = asyncio.create_task(_two_phase_paint(srv))
        took = await s.settle(quiet=0.2, timeout=2, expect=(43, 33, 50, 40))
        assert painter.done() and 0.45 < took < 1.0
        await s.close()


async def test_settle_without_expect_returns_after_the_first_quiet_gap(screen):
    async with FakeRFBServer(screen[0], "secret") as srv:
        s = await open_session(srv.url, "secret")
        await s.click(1, 1)
        painter = asyncio.create_task(_two_phase_paint(srv))
        took = await s.settle(quiet=0.2, timeout=2)
        assert not painter.done() and took < 0.3
        await painter
        await s.close()


async def test_settle_returns_elapsed_at_timeout_when_the_region_never_changes(screen):
    async with FakeRFBServer(screen[0], "secret") as srv:
        s = await open_session(srv.url, "secret")
        await s.click(1, 1)
        await srv.paint(0, 0, np.zeros((4, 4, 3), np.uint8))
        took = await s.settle(quiet=0.1, timeout=0.5, expect=(40, 30, 50, 40))
        assert 0.5 <= took < 0.7
        await s.close()


async def test_dropped_socket_reconnects_restores_fb_and_the_next_click_arrives(screen):
    async with FakeRFBServer(screen[0], "secret") as srv:
        s = await open_session(srv.url, "secret")
        srv.fb[:] = 7  # the desktop changes while the client is away
        await srv.drop()
        await _until(lambda: (s.fb == 7).all(), timeout=5)
        assert (s.fb == 7).all()
        assert srv.connections == 2
        await s.click(3, 4)
        await _until(lambda: len(srv.events) >= 3)
        assert srv.events[-3:] == [("pointer", 0, 3, 4), ("pointer", 1, 3, 4), ("pointer", 0, 3, 4)]
        await s.close()


async def test_click_on_a_dropped_socket_waits_for_the_reconnect_and_arrives(screen):
    async with FakeRFBServer(screen[0], "secret") as srv:
        s = await open_session(srv.url, "secret")
        await srv.drop()
        await s.click(3, 4)
        await _until(lambda: len(srv.events) >= 3)
        assert srv.events == [("pointer", 0, 3, 4), ("pointer", 1, 3, 4), ("pointer", 0, 3, 4)]
        await s.close()


async def test_call_raises_after_two_failed_reconnects(screen):
    async with FakeRFBServer(screen[0], "secret") as srv:
        s = RFBSession(backoff=0.05)
        await s.connect(srv.url, "secret")
        srv.refuse = True
        await srv.drop()
        with pytest.raises(ConnectionError, match="2x"):
            await asyncio.wait_for(s.click(1, 1), 3)
        await s.close()


async def test_idle_session_sends_an_incremental_request_within_the_keepalive(screen):
    async with FakeRFBServer(screen[0], "secret") as srv:
        s = RFBSession(keepalive=0.1)
        await s.connect(srv.url, "secret")
        await asyncio.sleep(0.05)
        seen = len(srv.requests)  # the reader's own request after the first frame is already in
        await _until(lambda: len(srv.requests) >= seen + 2, timeout=0.35)
        assert [r[0] for r in srv.requests[seen:seen + 2]] == [1, 1]
        await s.close()


async def test_close_stops_the_keepalive_and_does_not_reconnect(screen):
    async with FakeRFBServer(screen[0], "secret") as srv:
        s = RFBSession(keepalive=0.05)
        await s.connect(srv.url, "secret")
        await s.close()
        seen = len(srv.requests)
        await asyncio.sleep(0.2)
        assert srv.connections == 1 and len(srv.requests) == seen
