import os
import time
import json
import threading
import asyncio
from typing import Optional

from fastapi import FastAPI, HTTPException, Security, WebSocket, WebSocketDisconnect, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseModel

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

# ================== الإعدادات ==================
API_KEY = os.getenv("API_KEY", "ضع-مفتاحاً-سرياً-طويلاً-هنا-32-حرفاً")
DEFAULT_REPLY = os.getenv("DEFAULT_REPLY", "هذا هو السكربت المطلوب ✅")
COOKIES_FILE = "cookies.json"

# ================== التطبيق ==================
app = FastAPI(title="TikTok Bot API")

# CORS - يسمح للوحة التحكم المحلية بالاتصال
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # آمن بما أن API Key يحمي كل الطلبات
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ================== حماية API Key ==================
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

async def verify_api_key(api_key: Optional[str] = Security(api_key_header)):
    if api_key is None or api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key

# ================== المتغيرات العامة ==================
bot_state = {
    "driver": None,
    "is_running": False,
    "auto_reply_enabled": True,
    "total_sent": 0,
    "processed_users": set(),
    "last_error": None,
    "started_at": None,
}

# ================== نماذج الطلبات ==================
class BulkMessageRequest(BaseModel):
    message: str
    recipients: list[str] = []  # فارغة = الكل

class AutoReplyToggle(BaseModel):
    enabled: bool

# ================== إعداد Chrome ==================
def create_driver():
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    return driver

# ================== تسجيل الدخول ==================
def load_cookies(driver):
    """تحميل الكوكيز المحفوظة لتسجيل الدخول التلقائي"""
    if not os.path.exists(COOKIES_FILE):
        raise Exception(
            "❌ ملف cookies.json غير موجود! "
            "اتبع خطوات تصدير الكوكيز المذكورة في التعليقات."
        )
    
    driver.get("https://www.tiktok.com")
    time.sleep(3)
    
    with open(COOKIES_FILE, "r", encoding="utf-8") as f:
        cookies = json.load(f)
    
    for cookie in cookies:
        # تيك توك لا يقبل بعض الحقول
        cookie.pop("sameSite", None)
        cookie.pop("storeId", None)
        try:
            driver.add_cookie(cookie)
        except Exception:
            pass
    
    driver.refresh()
    time.sleep(5)
    
    # التحقق من تسجيل الدخول
    if "login" in driver.current_url.lower():
        raise Exception("❌ فشل تسجيل الدخول. الكوكيز منتهية الصلاحية.")

# ================== دالة البوت الرئيسية ==================
def bot_loop():
    """حلقة البوت: مراقبة الرسائل الجديدة والرد التلقائي"""
    global bot_state
    
    try:
        driver = create_driver()
        bot_state["driver"] = driver
        load_cookies(driver)
        
        bot_state["is_running"] = True
        bot_state["started_at"] = time.time()
        print("✅ تم تشغيل البوت بنجاح")
        
        driver.get("https://www.tiktok.com/messages")
        time.sleep(5)
        
        while bot_state["is_running"]:
            try:
                # ==== منطق الرد التلقائي على أول رسالة ====
                if bot_state["auto_reply_enabled"]:
                    process_new_messages(driver)
                
                time.sleep(8)  # فحص كل 8 ثوانٍ
                
            except Exception as e:
                bot_state["last_error"] = str(e)
                print(f"⚠️ خطأ في الحلقة: {e}")
                time.sleep(15)
                # حاول العودة لصفحة الرسائل
                try:
                    driver.get("https://www.tiktok.com/messages")
                    time.sleep(5)
                except:
                    pass
    
    except Exception as e:
        bot_state["is_running"] = False
        bot_state["last_error"] = str(e)
        print(f"❌ فشل تشغيل البوت: {e}")


def process_new_messages(driver):
    """البحث عن رسائل غير مقروءة والرد عليها"""
    global bot_state
    
    # البحث عن محادثات غير مقروءة (لها نقطة زرقاء)
    try:
        unread = driver.find_elements(
            By.CSS_SELECTOR,
            "[data-e2e='conversation-item']"
        )
    except:
        return
    
    for conv in unread[:5]:  # فحص أول 5 محادثات فقط
        try:
            # اسم المستخدم
            try:
                username_el = conv.find_element(
                    By.CSS_SELECTOR, "[data-e2e='conversation-username']"
                )
                username = username_el.text.strip()
            except:
                continue
            
            if not username or username in bot_state["processed_users"]:
                continue
            
            # التحقق من وجود رسالة غير مقروءة
            try:
                badge = conv.find_element(
                    By.CSS_SELECTOR, "[data-e2e='unread-badge']"
                )
                if not badge:
                    continue
            except:
                pass  # قد لا يوجد badge، نجرب فتح المحادثة
            
            # فتح المحادثة
            conv.click()
            time.sleep(2)
            
            # التحقق من أن آخر رسالة من المستخدم (ليست منا)
            messages = driver.find_elements(
                By.CSS_SELECTOR, "[data-e2e='message-text']"
            )
            
            if not messages:
                continue
            
            # إذا كانت هناك رسالة واحدة فقط = أول رسالة
            is_first_message = len(messages) <= 2
            
            if is_first_message:
                # إرسال الرد
                send_message_in_chat(driver, DEFAULT_REPLY)
                bot_state["processed_users"].add(username)
                bot_state["total_sent"] += 1
                print(f"✅ رد تلقائي على: {username}")
                time.sleep(3)
        
        except Exception as e:
            print(f"⚠️ خطأ في معالجة محادثة: {e}")
            continue


def send_message_in_chat(driver, text):
    """إرسال رسالة داخل المحادثة المفتوحة حالياً"""
    try:
        # مربع الكتابة
        input_box = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "[data-e2e='message-input']")
            )
        )
        input_box.click()
        time.sleep(0.5)
        input_box.send_keys(text)
        time.sleep(0.5)
        input_box.send_keys(Keys.ENTER)
        return True
    except Exception as e:
        print(f"⚠️ فشل إرسال رسالة: {e}")
        return False


# ================== Endpoints ==================

@app.get("/")
async def root():
    return {"status": "TikTok Bot API is running", "docs": "/docs"}


@app.get("/api/status")
async def get_status(_: str = Security(verify_api_key)):
    """حالة البوت الحالية"""
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
    """إرسال رسالة جماعية لجميع المحادثات"""
    if not bot_state["driver"] or not bot_state["is_running"]:
        raise HTTPException(status_code=503, detail="البوت لا يعمل حالياً")
    
    driver = bot_state["driver"]
    sent_count = 0
    failed_count = 0
    
    def do_bulk_send():
        nonlocal sent_count, failed_count
        try:
            driver.get("https://www.tiktok.com/messages")
            time.sleep(5)
            
            # جلب كل المحادثات
            conversations = driver.find_elements(
                By.CSS_SELECTOR, "[data-e2e='conversation-item']"
            )
            
            total = len(conversations) if not request.recipients else len(request.recipients)
            
            for i, conv in enumerate(conversations):
                try:
                    # إذا حدد المستخدم قائمة أسماء معينة
                    if request.recipients:
                        try:
                            username_el = conv.find_element(
                                By.CSS_SELECTOR, "[data-e2e='conversation-username']"
                            )
                            username = username_el.text.strip()
                            if username not in request.recipients:
                                continue
                        except:
                            continue
                    
                    conv.click()
                    time.sleep(2)
                    
                    if send_message_in_chat(driver, request.message):
                        sent_count += 1
                        bot_state["total_sent"] += 1
                    else:
                        failed_count += 1
                    
                    time.sleep(1.5)  # تأخير لتجنب الحظر
                    
                except Exception as e:
                    failed_count += 1
                    print(f"⚠️ فشل إرسال لـ محادثة {i}: {e}")
                    continue
                    
        except Exception as e:
            print(f"❌ خطأ في الإرسال الجماعي: {e}")
    
    # تشغيل في الخلفية
    threading.Thread(target=do_bulk_send, daemon=True).start()
    
    return {
        "status": "تم بدء الإرسال الجماعي في الخلفية",
        "message_preview": request.message[:50],
    }


@app.post("/api/toggle-auto-reply")
async def toggle_auto_reply(request: AutoReplyToggle, _: str = Security(verify_api_key)):
    """تفعيل/تعطيل الرد التلقائي"""
    bot_state["auto_reply_enabled"] = request.enabled
    return {"enabled": bot_state["auto_reply_enabled"]}


@app.post("/api/restart-bot")
async def restart_bot(_: str = Security(verify_api_key)):
    """إعادة تشغيل البوت"""
    bot_state["is_running"] = False
    time.sleep(2)
    if bot_state["driver"]:
        try:
            bot_state["driver"].quit()
        except:
            pass
    
    # مسح الحالة
    bot_state["processed_users"] = set()
    bot_state["last_error"] = None
    bot_state["total_sent"] = 0
    
    # إعادة التشغيل
    threading.Thread(target=bot_loop, daemon=True).start()
    return {"status": "جاري إعادة التشغيل"}


# ================== WebSocket للحالة الحية ==================
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


# ================== تشغيل البوت عند البدء ==================
@app.on_event("startup")
async def startup():
    threading.Thread(target=bot_loop, daemon=True).start()
