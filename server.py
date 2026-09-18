import os
import time
import json
import threading
import asyncio
import subprocess
from typing import Optional

from fastapi import FastAPI, HTTPException, Security, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from playwright.sync_api import sync_playwright, Page

# ================== الإعدادات ==================
API_KEY = os.getenv("API_KEY", "ضع-مفتاحاً-سرياً-طويلاً-هنا")
DEFAULT_REPLY = os.getenv("DEFAULT_REPLY", "هذا هو السكربت المطلوب ✅")
COOKIES_FILE = "cookies.json"

# ================== التطبيق ==================
app = FastAPI(title="TikTok Bot API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: Optional[str] = Security(api_key_header)):
    if api_key is None or api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key

# ================== حالة البوت ==================
bot_state = {
    "playwright": None,
    "browser": None,
    "context": None,
    "page": None,
    "is_running": False,
    "auto_reply_enabled": True,
    "total_sent": 0,
    "processed_users": set(),
    "last_error": None,
    "started_at": None,
}

# ================== النماذج ==================
class BulkMessageRequest(BaseModel):
    message: str
    recipients: list[str] = []

class AutoReplyToggle(BaseModel):
    enabled: bool

# ================== تسجيل الدخول بالكوكيز ==================
def load_cookies(context):
    if not os.path.exists(COOKIES_FILE):
        raise Exception("❌ ملف cookies.json غير موجود. ارفعه إلى Render.")

    with open(COOKIES_FILE, "r", encoding="utf-8") as f:
        cookies = json.load(f)

    pw_cookies = []
    for c in cookies:
        cookie = {
            "name": c.get("name"),
            "value": c.get("value"),
            "domain": c.get("domain", ".tiktok.com"),
            "path": c.get("path", "/"),
        }
        if c.get("expirationDate"):
            cookie["expires"] = int(c["expirationDate"])
        if c.get("secure") is not None:
            cookie["secure"] = bool(c["secure"])
        if c.get("httpOnly") is not None:
            cookie["httpOnly"] = bool(c["httpOnly"])

        same_site = c.get("sameSite")
        if same_site in ("Strict", "Lax", "None"):
            cookie["sameSite"] = same_site
        else:
            cookie["sameSite"] = "Lax"

        pw_cookies.append(cookie)

    context.add_cookies(pw_cookies)

# ================== دالة البوت ==================
def bot_loop():
    global bot_state
    try:
        pw = sync_playwright().start()
        bot_state["playwright"] = pw

        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        bot_state["browser"] = browser

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
            locale="ar-SA",
        )
        bot_state["context"] = context

        context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        page = context.new_page()
        page.goto("https://www.tiktok.com", wait_until="domcontentloaded", timeout=60000)
        time.sleep(3)

        load_cookies(context)

        page.goto("https://www.tiktok.com/messages", wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)

        if "login" in page.url.lower():
            raise Exception("❌ فشل تسجيل الدخول، الكوكيز منتهية الصلاحية")

        bot_state["page"] = page
        bot_state["is_running"] = True
        bot_state["started_at"] = time.time()
        print("✅ البوت يعمل")

        while bot_state["is_running"]:
            try:
                if bot_state["auto_reply_enabled"]:
                    process_new_messages(page)
                time.sleep(8)
            except Exception as e:
                bot_state["last_error"] = str(e)
                print(f"⚠️ خطأ في الحلقة: {e}")
                time.sleep(15)
                try:
                    page.goto("https://www.tiktok.com/messages", wait_until="domcontentloaded", timeout=60000)
                    time.sleep(5)
                except Exception:
                    pass

    except Exception as e:
        bot_state["is_running"] = False
        bot_state["last_error"] = str(e)
        print(f"❌ فشل تشغيل البوت: {e}")

# ================== معالجة الرسائل ==================
def process_new_messages(page: Page):
    global bot_state
    try:
        conversations = page.query_selector_all("[data-e2e='conversation-item']")
    except Exception:
        return

    for conv in conversations[:5]:
        try:
            username_el = conv.query_selector("[data-e2e='conversation-username']")
            if not username_el:
                continue
            username = username_el.inner_text().strip()

            if not username or username in bot_state["processed_users"]:
                continue

            conv.click()
            page.wait_for_timeout(2000)

            messages = page.query_selector_all("[data-e2e='message-text']")

            if len(messages) <= 2:
                if send_message_in_chat(page, DEFAULT_REPLY):
                    bot_state["processed_users"].add(username)
                    bot_state["total_sent"] += 1
                    print(f"✅ رد تلقائي على: {username}")
                    page.wait_for_timeout(3000)
        except Exception as e:
            print(f"⚠️ خطأ في معالجة محادثة: {e}")
            continue

# ================== إرسال رسالة ==================
def send_message_in_chat(page: Page, text: str) -> bool:
    try:
        input_box = page.wait_for_selector(
            "[data-e2e='message-input']",
            timeout=10000,
            state="visible"
        )
        if not input_box:
            return False
        input_box.click()
        page.wait_for_timeout(500)
        input_box.fill(text)
        page.wait_for_timeout(500)
        input_box.press("Enter")
        return True
    except Exception as e:
        print(f"⚠️ فشل إرسال رسالة: {e}")
        return False

# ================== Endpoints ==================
@app.get("/")
async def root():
    return {"status": "TikTok Bot API running", "docs": "/docs"}

@app.get("/api/status")
async def get_status(_: str = Security(verify_api_key)):
    uptime = 0
    if bot_state["started_at"]:
        uptime = int(time.time() - bot_state["started_at"])

    return {
        "is_running": bot_state["is_running"],
        "auto_reply_enabled": bot_state["auto_reply_enabled"],
        "total_sent": bot_state["total_sent"],
        "processed_count": len(bot_state["processed_users"]),
        "uptime_seconds": uptime,
        "last_error": bot_state["last_error"],
    }

@app.post("/api/send-bulk")
async def send_bulk(request: BulkMessageRequest, _: str = Security(verify_api_key)):
    if not bot_state["page"] or not bot_state["is_running"]:
        raise HTTPException(status_code=503, detail="البوت لا يعمل حالياً")

    page = bot_state["page"]

    def do_bulk_send():
        try:
            page.goto("https://www.tiktok.com/messages", wait_until="domcontentloaded", timeout=60000)
            time.sleep(5)

            conversations = page.query_selector_all("[data-e2e='conversation-item']")

            for i, conv in enumerate(conversations):
                try:
                    if request.recipients:
                        username_el = conv.query_selector("[data-e2e='conversation-username']")
                        if not username_el:
                            continue
                        username = username_el.inner_text().strip()
                        if username not in request.recipients:
                            continue

                    conv.click()
                    page.wait_for_timeout(2000)

                    if send_message_in_chat(page, request.message):
                        bot_state["total_sent"] += 1

                    page.wait_for_timeout(1500)
                except Exception as e:
                    print(f"⚠️ فشل إرسال {i}: {e}")
                    continue
        except Exception as e:
            print(f"❌ خطأ في الإرسال الجماعي: {e}")

    threading.Thread(target=do_bulk_send, daemon=True).start()

    return {
        "status": "تم بدء الإرسال الجماعي في الخلفية",
        "message_preview": request.message[:50],
    }

@app.post("/api/toggle-auto-reply")
async def toggle_auto_reply(request: AutoReplyToggle, _: str = Security(verify_api_key)):
    bot_state["auto_reply_enabled"] = request.enabled
    return {"enabled": bot_state["auto_reply_enabled"]}

@app.post("/api/restart-bot")
async def restart_bot(_: str = Security(verify_api_key)):
    bot_state["is_running"] = False
    time.sleep(2)
    try:
        if bot_state["browser"]:
            bot_state["browser"].close()
    except Exception:
        pass
    try:
        if bot_state["playwright"]:
            bot_state["playwright"].stop()
    except Exception:
        pass

    bot_state["processed_users"] = set()
    bot_state["last_error"] = None
    bot_state["total_sent"] = 0
    bot_state["is_running"] = False

    threading.Thread(target=bot_loop, daemon=True).start()
    return {"status": "جاري إعادة التشغيل"}

@app.websocket("/ws/status")
async def websocket_status(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            await websocket.send_json({
                "is_running": bot_state["is_running"],
                "auto_reply_enabled": bot_state["auto_reply_enabled"],
                "total_sent": bot_state["total_sent"],
                "processed_count": len(bot_state["processed_users"]),
                "last_error": bot_state["last_error"],
            })
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        pass
    except Exception:
        pass

# ================== Startup ==================
@app.on_event("startup")
async def startup():
    threading.Thread(target=bot_loop, daemon=True).start()
