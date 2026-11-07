"""Run: python test_screencast.py"""
import threading
import time
import urllib.error
import urllib.request

import screencast

state = screencast.State()
state.latest = screencast.grab_jpeg()
assert state.latest[:2] == b"\xff\xd8", "frame is not a JPEG"

server = screencast.make_server(0, "123456", state)
threading.Thread(target=server.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{server.server_address[1]}"


def get(path):
    try:
        with urllib.request.urlopen(base + path) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, b""


status, body = get("/123456")
assert status == 200 and b"/123456/frame.jpg" in body
status, body = get("/123456/frame.jpg?1")
assert status == 200 and body == state.latest
for path in ("/", "/000000", "/000000/frame.jpg", "/frame.jpg"):
    assert get(path)[0] == 404, f"{path} must not expose the screen"

# A still screen is held back until HOLD_SECONDS, a changed one goes out at once.
started = time.monotonic()
assert get("/123456/frame.jpg")[1] == state.latest
assert time.monotonic() - started >= screencast.HOLD_SECONDS - 0.1, "unchanged frame was resent at once"

threading.Timer(0.2, lambda: setattr(state, "latest", b"changed")).start()
started = time.monotonic()
assert get("/123456/frame.jpg")[1] == b"changed"
assert time.monotonic() - started < 1, "changed frame was held back"

# A reloaded page gets a frame right away.
get("/123456")
started = time.monotonic()
assert get("/123456/frame.jpg")[1] == b"changed"
assert time.monotonic() - started < 1, "reloaded page waited for a frame"

state.latest = None
assert get("/123456/frame.jpg")[0] == 503
print("ok")
