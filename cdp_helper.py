"""
Chrome DevTools Protocol (CDP) helper for WeChat MP automation.
Connects to Chrome on port 9222 and provides high-level operations.
"""

import json
import asyncio
import base64
import subprocess
import urllib.request
from typing import Optional

CDP_PORT = 9222
MSG_ID = 100


def get_tabs(port: int = CDP_PORT) -> list[dict]:
    """List all Chrome tabs via CDP HTTP endpoint."""
    return json.loads(urllib.request.urlopen(f"http://localhost:{port}/json").read())


def find_tab(url_pattern: str, port: int = CDP_PORT) -> Optional[dict]:
    """Find first tab whose URL contains the given pattern."""
    for tab in get_tabs(port):
        if url_pattern in tab.get("url", ""):
            return tab
    return None


class CDPClient:
    """Async CDP WebSocket client for browser automation."""

    def __init__(self, ws_url: str):
        self._ws_url = ws_url
        self._ws = None
        self._id = 0

    async def __aenter__(self):
        import websockets
        self._ws = await websockets.connect(self._ws_url)
        return self

    async def __aexit__(self, *args):
        if self._ws:
            await self._ws.close()

    def _next_id(self) -> int:
        self._id += 1
        return self._id

    async def evaluate(self, js: str) -> any:
        """Execute JavaScript and return the result value."""
        msg = {"id": self._next_id(), "method": "Runtime.evaluate",
               "params": {"expression": js, "returnByValue": True}}
        await self._ws.send(json.dumps(msg))
        resp = json.loads(await self._ws.recv())
        result = resp.get("result", {}).get("result", {})
        return result.get("value")

    async def evaluate_json(self, js: str) -> any:
        """Execute JS that returns JSON, parse and return."""
        raw = await self.evaluate(js)
        if raw is None:
            return None
        if isinstance(raw, (dict, list, int, float, bool)):
            return raw
        return json.loads(raw)

    async def click_at(self, x: float, y: float, delay: float = 0.05):
        """Simulate a real mouse click at CSS coordinates."""
        await self._ws.send(json.dumps({"id": self._next_id(), "method": "Input.dispatchMouseEvent",
                                         "params": {"type": "mouseMoved", "x": x, "y": y}}))
        await self._ws.recv()
        await asyncio.sleep(0.1)
        await self._ws.send(json.dumps({"id": self._next_id(), "method": "Input.dispatchMouseEvent",
                                         "params": {"type": "mousePressed", "x": x, "y": y,
                                                    "button": "left", "clickCount": 1}}))
        await self._ws.recv()
        await asyncio.sleep(delay)
        await self._ws.send(json.dumps({"id": self._next_id(), "method": "Input.dispatchMouseEvent",
                                         "params": {"type": "mouseReleased", "x": x, "y": y,
                                                    "button": "left", "clickCount": 1}}))
        await self._ws.recv()

    async def click_element(self, selector: str) -> bool:
        """Find element by CSS selector, scroll into view, and click it."""
        coords = await self.evaluate_json(f"""
        (() => {{
            const el = document.querySelector('{selector}');
            if (!el) return null;
            el.scrollIntoView({{block: 'center'}});
            const r = el.getBoundingClientRect();
            return {{x: r.x + r.width/2, y: r.y + r.height/2}};
        }})()
        """)
        if not coords:
            return False
        await asyncio.sleep(0.3)
        await self.click_at(coords["x"], coords["y"])
        return True

    async def click_text(self, text: str, near_y: Optional[float] = None) -> bool:
        """Click a leaf element matching exact text, optionally closest to a Y coordinate."""
        results = await self.evaluate_json(f"""
        (() => {{
            const all = document.querySelectorAll('*');
            const matches = [];
            for (const el of all) {{
                if (el.children.length === 0 && el.textContent.trim() === '{text}') {{
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0 && r.height < 60) {{
                        matches.push({{x: r.x + r.width/2, y: r.y + r.height/2}});
                    }}
                }}
            }}
            return matches.length ? matches : null;
        }})()
        """)
        if not results:
            return False
        target = results[0]
        if near_y is not None and len(results) > 1:
            target = min(results, key=lambda c: abs(c["y"] - near_y))
        await self.click_at(target["x"], target["y"])
        return True

    async def type_text(self, text: str):
        """Insert text at current focus via CDP."""
        await self._ws.send(json.dumps({"id": self._next_id(), "method": "Input.insertText",
                                         "params": {"text": text}}))
        await self._ws.recv()

    async def set_input_value(self, selector: str, value: str):
        """Set value on an input/textarea, triggering React/Vue change events."""
        escaped = json.dumps(value)
        await self.evaluate(f"""
        (() => {{
            const el = document.querySelector('{selector}');
            if (!el) return 'element not found';
            const proto = el.tagName === 'TEXTAREA'
                ? window.HTMLTextAreaElement.prototype
                : window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
            setter.call(el, {escaped});
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
            el.dispatchEvent(new Event('change', {{ bubbles: true }}));
            return 'ok';
        }})()
        """)

    async def wait(self, seconds: float = 1.0):
        await asyncio.sleep(seconds)

    async def find_visible_buttons(self, *texts: str) -> list[dict]:
        """Find visible leaf elements matching any of the given texts."""
        text_conditions = " || ".join(f"text === '{t}'" for t in texts)
        return await self.evaluate_json(f"""
        (() => {{
            const results = [];
            const all = document.querySelectorAll('*');
            for (const el of all) {{
                const text = el.textContent.trim();
                if (el.children.length === 0 && ({text_conditions})) {{
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0 && r.height < 50) {{
                        results.push({{text, tag: el.tagName, x: r.x + r.width/2, y: r.y + r.height/2}});
                    }}
                }}
            }}
            return results.length ? results : null;
        }})()
        """)

    async def find_dialog_buttons(self, *texts: str) -> list[dict]:
        """Find visible buttons inside .weui-desktop-dialog."""
        text_conditions = " || ".join(f"text === '{t}'" for t in texts)
        return await self.evaluate_json(f"""
        (() => {{
            const results = [];
            const all = document.querySelectorAll('.weui-desktop-dialog *');
            for (const el of all) {{
                const text = el.textContent.trim();
                if (el.children.length === 0 && ({text_conditions})) {{
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0 && r.height < 50) {{
                        results.push({{text, tag: el.tagName, x: r.x + r.width/2, y: r.y + r.height/2}});
                    }}
                }}
            }}
            return results.length ? results : null;
        }})()
        """)

    async def get_clipboard(self) -> str:
        """Get system clipboard text via pbpaste."""
        return subprocess.run(["pbpaste"], capture_output=True, text=True).stdout

    async def get_element_rect(self, selector: str) -> Optional[dict]:
        """Get bounding rect of element."""
        return await self.evaluate_json(f"""
        (() => {{
            const el = document.querySelector('{selector}');
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {{x: r.x, y: r.y, w: r.width, h: r.height, cx: r.x + r.width/2, cy: r.y + r.height/2}};
        }})()
        """)

    async def navigate(self, url: str):
        """Navigate the tab to a new URL."""
        msg = {"id": self._next_id(), "method": "Page.navigate", "params": {"url": url}}
        await self._ws.send(json.dumps(msg))
        await self._ws.recv()

    async def bring_to_front(self):
        """Bring the tab to front."""
        msg = {"id": self._next_id(), "method": "Page.bringToFront"}
        await self._ws.send(json.dumps(msg))
        await self._ws.recv()

    async def dispatch_key_event(self, key: str, code: Optional[str] = None,
                                  key_code: int = 0, windows_virtual_key_code: int = 0):
        """Dispatch a raw keyDown/keyUp pair via CDP."""
        cd = code or key
        kv = windows_virtual_key_code or key_code
        for typ in ("keyDown", "keyUp"):
            msg = {"id": self._next_id(), "method": "Input.dispatchKeyEvent",
                   "params": {"type": typ, "key": key, "code": cd,
                              "keyCode": key_code, "windowsVirtualKeyCode": kv}}
            await self._ws.send(json.dumps(msg))
            await self._ws.recv()


# ── WeChat MP specific operations ──────────────────────────────────────────

async def ensure_editor_tab() -> CDPClient:
    """Find or create WeChat MP editor tab and return connected CDPClient."""
    tab = find_tab("appmsg_edit")
    if not tab:
        # Try to click "文章" on the home page
        home = find_tab("mp.weixin.qq.com/cgi-bin/home")
        if not home:
            raise RuntimeError("No WeChat MP home tab found. Open mp.weixin.qq.com first.")
        async with CDPClient(home["webSocketDebuggerUrl"]) as cdp:
            await cdp.click_element(".js_article_tags_label")
            # fallback: click via text
            # Actually need to click 文章 under 新的创作
            coords = await cdp.evaluate_json("""
            (() => {
                const el = document.querySelector('.new-creation__menu-item');
                if (!el) return null;
                el.scrollIntoView({block: 'center'});
                const r = el.getBoundingClientRect();
                return {x: r.x + r.width/2, y: r.y + r.height/2};
            })()
            """)
            if coords:
                await cdp.click_at(coords["x"], coords["y"])
                await cdp.wait(3)
        tab = find_tab("appmsg_edit")
        if not tab:
            raise RuntimeError("Failed to open editor tab.")
    return CDPClient(tab["webSocketDebuggerUrl"])
