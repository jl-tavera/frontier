import asyncio

import numpy as np
import pytest
from PIL import Image

from app.rfb.session import open_session
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
