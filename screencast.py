"""Stream this laptop's primary screen to TV browsers on the same Wi-Fi (video only, no audio)."""
import ctypes
import io
import secrets
import socket
import threading
import time
from ctypes import wintypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PIL import ImageDraw, ImageGrab

PORT = 8765
WIDTH = 1920  # Lower this (e.g. 1280) if the TVs stutter on a slow Wi-Fi.
QUALITY = 80
FPS = 12
IDLE_SECONDS = 3
HOLD_SECONDS = 2  # Longest a TV waits for a changed frame; shorter than IDLE_SECONDS so capture keeps running.

# Plain ES3 and image requests: old TV browsers run it, and a slow TV only drops frames instead of lagging behind.
PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Screen</title>
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}
img{position:absolute;left:0;top:0;width:100%;height:100%;object-fit:contain;visibility:hidden}</style></head>
<body><img id="a" alt=""><img id="b" alt=""><script>
// Replies are held until the slide changes, so load into the hidden image: the visible one must never blank meanwhile.
var front=document.getElementById('a'),back=document.getElementById('b'),last=new Date().getTime();
function next(){last=new Date().getTime();back.src='/TOKEN/frame.jpg?'+last;}
front.onload=back.onload=function(){
  back.style.visibility='visible';front.style.visibility='hidden';
  var t=front;front=back;back=t;
  setTimeout(next,10);
};
front.onerror=back.onerror=function(){setTimeout(next,1000);};
// A request lost on Wi-Fi fires neither event, so restart the loop.
setInterval(function(){if(new Date().getTime()-last>5000)next();},1000);
next();
</script></body></html>"""


class State:
    latest = None
    last_request = 0.0


def grab_jpeg():
    image = ImageGrab.grab()
    # ImageGrab leaves out the mouse pointer, so draw one.
    point = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(point))
    x, y = point.x, point.y
    scale = max(1, image.width // 1280)
    arrow = [(0, 0), (0, 24), (6, 18), (11, 28), (15, 26), (10, 17), (18, 17)]
    ImageDraw.Draw(image).polygon(
        [(x + dx * scale, y + dy * scale) for dx, dy in arrow], fill="white", outline="black"
    )
    image.thumbnail((WIDTH, WIDTH))
    output = io.BytesIO()
    image.save(output, "JPEG", quality=QUALITY)
    return output.getvalue()


def capture_loop(state):
    while True:
        if time.monotonic() - state.last_request > IDLE_SECONDS:
            time.sleep(0.2)
            continue
        started = time.monotonic()
        try:
            frame = grab_jpeg()
            if frame != state.latest:  # Keeps the same object while the slide is still, so TVs see no change.
                state.latest = frame
        except OSError:
            pass  # The lock screen can't be captured; keep the last frame until it's unlocked.
        time.sleep(max(0, 1 / FPS - (time.monotonic() - started)))


def make_server(port, token, state):
    page = PAGE.replace("TOKEN", token).encode()
    seen = set()
    sent = {}  # Last frame each TV received, by IP.

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def reply(self, status, content_type, body):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split("?")[0].rstrip("/")
            try:
                if path == f"/{token}":
                    if self.client_address[0] not in seen:
                        seen.add(self.client_address[0])
                        print(f"접속됨: {self.client_address[0]}", flush=True)
                    sent.pop(self.client_address[0], None)  # A reloaded page needs a frame right away.
                    self.reply(200, "text/html; charset=utf-8", page)
                elif path == f"/{token}/frame.jpg":
                    ip = self.client_address[0]
                    state.last_request = time.monotonic()
                    # Hold the reply until the slide changes: it goes out at once and a still slide uses little Wi-Fi.
                    deadline = state.last_request + HOLD_SECONDS
                    while (state.latest is None or state.latest is sent.get(ip)) and time.monotonic() < deadline:
                        time.sleep(0.01)
                    frame = state.latest
                    if frame:
                        sent[ip] = frame
                        self.reply(200, "image/jpeg", frame)
                    else:
                        self.reply(503, "text/plain", b"no frame yet")
                else:
                    self.reply(404, "text/plain", b"not found")
            except ConnectionError:
                self.close_connection = True  # The TV closed the page.

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer(("0.0.0.0", port), Handler)


def lan_ip():
    # connect() on UDP sends nothing; it only asks Windows which adapter is the default route.
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]


def main():
    ctypes.windll.user32.SetProcessDPIAware()  # Keeps pointer coordinates correct on scaled displays.
    state = State()
    # The screen is private: the code in the URL keeps other Wi-Fi users out and changes on every run.
    token = f"{secrets.randbelow(1_000_000):06d}"
    server = make_server(PORT, token, state)
    threading.Thread(target=capture_loop, args=(state,), daemon=True).start()
    print(f"\n  TV 브라우저 두 대에 이 주소를 입력하세요:\n\n    http://{lan_ip()}:{PORT}/{token}\n")
    print("  끝내려면 이 창을 닫으세요.\n", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
