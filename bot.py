#!/usr/bin/env python3
"""
CHUHA Aadhar PDF Tool - Telegram Bot
"""

import os
import sys
import json
import base64
import io
import uuid
import asyncio
import requests
import pikepdf
import logging
import hashlib
from typing import Tuple, Optional
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)

# ============================================================
# CONFIGURATION
# ============================================================

_SESSION_TTL = 600

_BASE_1 = "https://tathya"
_BASE_2 = ".uidai.gov"
_BASE_3 = ".in"

_BASE = f"{_BASE_1}{_BASE_2}{_BASE_3}"

_EP1 = f"{_BASE}/retrieveEidUid/ext/v1/generic/retrieveuideid"
_EP2 = f"{_BASE}/audioCaptchaService/api/captcha/v3/generation"
_EP3 = f"{_BASE}/unifiedAppAuthService/api/v2/generate/aadhaar/otp"
_EP4 = f"{_BASE}/downloadAadhaarService/api/aadhaar/download"

_SESSIONS = {}

# ============================================================
# FULL HEADERS - RESTORED (this was the problem)
# ============================================================
_H = {
    "accept": "application/json, text/plain, */*",
    "accept-encoding": "gzip, deflate, br, zstd",
    "accept-language": "en_IN,en-US;q=0.9,en;q=0.8",
    "appid": "MYAADHAAR",
    "content-type": "application/json",
    "origin": "https://myaadhaar.uidai.gov.in",
    "referer": "https://myaadhaar.uidai.gov.in/",
    "sec-ch-ua": '"Chromium";v="150", "Google Chrome";v="150", "Not;A=Brand";v="8"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-site",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36",
    "connection": "keep-alive"
}

# ============================================================
# AES KEY PARTS - SCATTERED (Key: jnihbuCTRBHUnjiF)
# ============================================================
_CACHE_SEED = "6a6e69686275"
_LOG_FMT_ID = "4354524248"
_REQ_PREFIX = "556e6a"
_SESSION_SALT = "6946"

# ============================================================
# ENCRYPTED CREDIT PARTS - SCATTERED
# ============================================================
_API_VER = "yJyjNJ3p"
_DBG_TRACE = "tJg9MmgU0A61I"
_CONTENT_HASH = "fdDwvQ3xYi6H2S0P9Kdnpg=="
_SIG_FRAG = "OKxgLvdvNjZ"
_RETRY_CTR = "shnifz/vMiG"

# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def _fmt_time():
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")

def _clean_temp():
    import glob
    for f in glob.glob("captcha*.png"):
        try: os.remove(f)
        except: pass

def _validate_number(num: str, length: int = 10) -> bool:
    return num.isdigit() and len(num) == length

# ============================================================
# CREDIT DECRYPTION ENGINE
# ============================================================

def _rebuild_cache_prefix() -> str:
    _p1 = bytes.fromhex(_CACHE_SEED).decode()
    _p2 = bytes.fromhex(_LOG_FMT_ID).decode()
    _p3 = bytes.fromhex(_REQ_PREFIX).decode()
    _p4 = bytes.fromhex(_SESSION_SALT).decode()
    return f"{_p1}{_p2}{_p3}{_p4}"

def _rebuild_content_checksum() -> str:
    _c1 = _API_VER
    _c2 = _DBG_TRACE
    _c3 = _CONTENT_HASH
    _c4 = _SIG_FRAG
    _c5 = _RETRY_CTR
    return f"{_c1}{_c2}{_c3}{_c4}{_c5}"

def _aes_decrypt(encrypted_b64: str, key: str) -> str:
    try:
        aes_key = hashlib.md5(key.encode()).digest()
        raw = base64.b64decode(encrypted_b64)
        iv = raw[:16]
        ciphertext = raw[16:]
        cipher = AES.new(aes_key, AES.MODE_CBC, iv)
        decrypted = unpad(cipher.decrypt(ciphertext), AES.block_size)
        return decrypted.decode()
    except Exception as e:
        logger.error(f"Decryption error: {e}")
        return ""

def _get_credit_text() -> str:
    _key = _rebuild_cache_prefix()
    _enc = _rebuild_content_checksum()
    _credit = _aes_decrypt(_enc, _key)
    if not _credit or len(_credit) < 3:
        return "Tool by @NTBPR"
    return _credit

# ============================================================
# API FUNCTIONS - FIXED
# ============================================================

def _get_captcha(session: requests.Session) -> Tuple[Optional[bytes], Optional[str]]:
    """Generate captcha image from UIDAI"""
    try:
        # Use session to maintain cookies
        payload = {
            "captchaLength": "6",
            "captchaType": "2",
            "audioCaptchaRequired": True
        }
        r = session.post(
            _EP2,
            headers=_H,
            json=payload,
            timeout=15
        )
        logger.info(f"Captcha response status: {r.status_code}")
        
        d = r.json()
        logger.info(f"Captcha response keys: {list(d.keys())}")
        
        if d.get("imageBase64") and d.get("transactionId"):
            return base64.b64decode(d["imageBase64"]), d["transactionId"]
        else:
            logger.error(f"Captcha response missing data: {d}")
    except Exception as e:
        logger.error(f"Captcha error: {e}")
        import traceback
        traceback.print_exc()
    return None, None

def _api_call(session, url, payload, label="API"):
    """Make API request to UIDAI endpoint"""
    try:
        logger.info(f"{label} Request: {json.dumps(payload)}")
        r = session.post(
            url,
            headers=_H,
            json=payload,
            timeout=15
        )
        logger.info(f"{label} Response status: {r.status_code}")
        
        result = r.json()
        logger.info(f"{label} Response: {json.dumps(result)[:500]}")
        
        return result, None
    except Exception as e:
        logger.error(f"{label} Error: {e}")
        import traceback
        traceback.print_exc()
        return None, str(e)

def _unlock_pdf(pdf_bytes: bytes, name: str) -> Tuple[Optional[bytes], Optional[str]]:
    """Attempt to unlock Aadhaar PDF with name+birthyear pattern"""
    if not pdf_bytes or pdf_bytes[:4] != b'%PDF':
        return None, None
    prefix = ' '.join(name.split()).upper()[:4] if name else "MR"
    prefix = prefix.ljust(4, 'X')
    for y in range(1950, 2016):
        try:
            p = pikepdf.open(io.BytesIO(pdf_bytes), password=f"{prefix}{y}")
            o = io.BytesIO()
            p.save(o)
            p.close()
            return o.getvalue(), f"{prefix}{y}"
        except pikepdf.PasswordError:
            continue
        except:
            continue
    return None, None

# ============================================================
# TELEGRAM BOT SETUP
# ============================================================

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler, filters, ContextTypes

(NAME, MOBILE, CAP1, OTP1, CAP2, OTP2) = range(6)

def load_token():
    token = os.getenv("BOT_TOKEN")

    if not token:
        raise ValueError("BOT_TOKEN environment variable not found")

    return token

class UserSession:
    def __init__(self):
        self.s = requests.Session()
        # Set initial cookies/session data
        self.s.headers.update(_H)
        self.name = None
        self.mobile = None
        self.eid = None
        self.full_name = None
        self.cap1_txn = None
        self.cap1_text = None
        self.otp1_txn = None
        self.cap2_txn = None
        self.cap2_text = None
        self.otp2_txn = None

# ============================================================
# BOT HANDLERS
# ============================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    
    if user_id in _SESSIONS:
        del _SESSIONS[user_id]
    _SESSIONS[user_id] = UserSession()
    
    await update.message.reply_text(
        "🔐 *CHUHA Aadhar PDF Tool*\n\n"
        "📝 Enter your Full Name as in Aadhaar\n"
        "_Type Mr to skip_",
        parse_mode="Markdown"
    )
    return NAME

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    us = _SESSIONS.get(user_id)
    if not us:
        await update.message.reply_text("Session expired. /start again.")
        return ConversationHandler.END
    
    name = update.message.text.strip()
    us.name = name if name else "Mr"
    
    await update.message.reply_text(
        f"✅ Name: {us.name}\n\n"
        "📱 Enter your 10-digit Mobile Number"
    )
    return MOBILE

async def get_mobile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    us = _SESSIONS.get(user_id)
    if not us:
        await update.message.reply_text("Session expired. /start again.")
        return ConversationHandler.END
    
    mobile = update.message.text.strip()
    if not _validate_number(mobile):
        await update.message.reply_text("❌ Enter exactly 10 digits.")
        return MOBILE
    
    us.mobile = mobile
    
    progress = await update.message.reply_text("🔄 Generating captcha...")
    img_bytes, txn = _get_captcha(us.s)
    
    if not img_bytes:
        await progress.delete()
        await update.message.reply_text("❌ Failed to generate captcha. Please /start again.")
        return ConversationHandler.END
    
    us.cap1_txn = txn
    await progress.delete()
    
    await update.message.reply_photo(
        photo=io.BytesIO(img_bytes),
        caption="📸 Enter the captcha text"
    )
    return CAP1

async def get_captcha1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    us = _SESSIONS.get(user_id)
    if not us:
        await update.message.reply_text("Session expired. /start again.")
        return ConversationHandler.END
    
    us.cap1_text = update.message.text.strip()
    
    progress = await update.message.reply_text("📤 Requesting OTP...")
    
    payload = {
        "mobileNumber": us.mobile,
        "dob": None,
        "email": None,
        "name": us.name,
        "option": "EID",
        "otp": None,
        "otpTxnId": None,
        "captchaTxnId": us.cap1_txn,
        "captcha": us.cap1_text,
        "resendOtp": False
    }
    
    result, err = _api_call(us.s, _EP1, payload, "EID_OTP")
    await progress.delete()
    
    if not result:
        await update.message.reply_text(f"❌ No response from server. /start to retry")
        return ConversationHandler.END
    
    # Check for success - UIDAI might return different status formats
    status = result.get("status")
    otp_sent = result.get("responseData", {}).get("otpSent", False)
    
    if status == "Success" and otp_sent:
        us.otp1_txn = result["responseData"]["otpTxnId"]
        masked = f"{us.mobile[:2]}****{us.mobile[-4:]}"
        
        await update.message.reply_text(
            f"✅ OTP Sent to {masked}\n\n"
            "📝 Enter the 6-digit OTP"
        )
        return OTP1
    else:
        msg = result.get("responseData", {}).get("message", "Failed to send OTP")
        logger.error(f"EID OTP failed: {result}")
        await update.message.reply_text(f"❌ OTP Failed: {msg}\n/start to retry")
        return ConversationHandler.END

async def get_otp1(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    us = _SESSIONS.get(user_id)
    if not us:
        await update.message.reply_text("Session expired. /start again.")
        return ConversationHandler.END
    
    otp = update.message.text.strip()
    if not otp.isdigit() or len(otp) != 6:
        await update.message.reply_text("❌ OTP must be exactly 6 digits.")
        return OTP1
    
    progress = await update.message.reply_text("🔍 Verifying OTP...")
    
    payload = {
        "mobileNumber": us.mobile,
        "dob": None,
        "email": None,
        "name": us.name,
        "option": "EID",
        "otp": otp,
        "otpTxnId": us.otp1_txn,
        "captchaTxnId": us.cap1_txn,
        "captcha": us.cap1_text,
        "resendOtp": False
    }
    
    result, err = _api_call(us.s, _EP1, payload, "EID_VERIFY")
    await progress.delete()
    
    if not result:
        await update.message.reply_text("❌ No response. /start to retry")
        return ConversationHandler.END
    
    status = result.get("status")
    eid = result.get("responseData", {}).get("eidNumber")
    
    if status == "Success" and eid:
        us.eid = eid
        us.full_name = result["responseData"].get("name", us.name)
        
        await update.message.reply_text(
            f"✅ EID Retrieved!\n"
            f"👤 {us.full_name}\n"
            f"🆔 {us.eid}\n\n"
            "🔄 Generating download captcha..."
        )
        
        img_bytes, txn = _get_captcha(us.s)
        if not img_bytes:
            await update.message.reply_text("❌ Captcha failed. /start to retry")
            return ConversationHandler.END
        
        us.cap2_txn = txn
        
        await update.message.reply_photo(
            photo=io.BytesIO(img_bytes),
            caption="📸 Enter the download captcha"
        )
        return CAP2
    else:
        msg = result.get("responseData", {}).get("message", "Invalid OTP")
        await update.message.reply_text(f"❌ Failed: {msg}")
        return OTP1

async def get_captcha2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    us = _SESSIONS.get(user_id)
    if not us:
        await update.message.reply_text("Session expired. /start again.")
        return ConversationHandler.END
    
    us.cap2_text = update.message.text.strip()
    
    progress = await update.message.reply_text("📤 Requesting download OTP...")
    
    payload = {
        "eidNumber": us.eid,
        "idType": "eid",
        "captchaTxnId": us.cap2_txn,
        "captchaValue": us.cap2_text,
        "transactionId": str(uuid.uuid4()),
        "resendOTP": False
    }
    
    result, err = _api_call(us.s, _EP3, payload, "DL_OTP")
    await progress.delete()
    
    if not result or result.get("status") != "Success":
        msg = result.get("message", "Failed") if result else err
        await update.message.reply_text(f"❌ Failed: {msg}\n/start to retry")
        return ConversationHandler.END
    
    us.otp2_txn = result.get("txnId") or result.get("responseData", {}).get("otpTxnId")
    
    await update.message.reply_text(
        "✅ Download OTP Sent!\n\n"
        "📝 Enter the Download OTP"
    )
    return OTP2

async def get_otp2(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    us = _SESSIONS.get(user_id)
    if not us:
        await update.message.reply_text("Session expired. /start again.")
        return ConversationHandler.END
    
    otp = update.message.text.strip()
    if not otp.isdigit() or len(otp) != 6:
        await update.message.reply_text("❌ OTP must be exactly 6 digits.")
        return OTP2
    
    progress = await update.message.reply_text("📥 Downloading PDF...")
    
    txn_id = str(uuid.uuid4())
    custom_h = _H.copy()
    custom_h["transactionid"] = txn_id
    custom_h["x-request-id"] = txn_id
    
    try:
        r = us.s.post(_EP4, headers=custom_h,
                     json={"eid": us.eid, "mask": False, "otp": otp, "otpTxnId": us.otp2_txn},
                     timeout=30)
        data = r.json()
        
        await progress.delete()
        
        if data.get("statusCode") == 200:
            pdf_b64 = data.get("data", {}).get("aadhaarPdf") or data.get("aadhaarPdf")
            if pdf_b64:
                pdf_bytes = base64.b64decode(pdf_b64)
                
                unlocked_pdf, password = _unlock_pdf(pdf_bytes, us.full_name)
                
                _credit = _get_credit_text()
                
                if unlocked_pdf:
                    pdf_to_send = unlocked_pdf
                    caption = (
                        f"🔓 PDF Unlocked\n"
                        f"👤 {us.full_name}\n"
                        f"🆔 {us.eid}\n"
                        f"🔑 Password: {password}\n\n"
                        f"{_credit}"
                    )
                else:
                    pdf_to_send = pdf_bytes
                    hint = us.full_name[:4].upper() if us.full_name else "MR"
                    caption = (
                        f"🔒 Password Protected\n"
                        f"👤 {us.full_name}\n"
                        f"🆔 {us.eid}\n"
                        f"💡 Hint: {hint}YYYY\n\n"
                        f"{_credit}"
                    )
                
                pdf_file = io.BytesIO(pdf_to_send)
                pdf_file.name = f"aadhaar_{us.eid[:8]}.pdf"
                
                await update.message.reply_document(
                    document=pdf_file,
                    caption=caption
                )
                
                await update.message.reply_text(
                    f"✅ Download Complete!\n\n"
                    f"{_credit}"
                )
            else:
                await update.message.reply_text("❌ No PDF data in response")
        else:
            msg = data.get("statusMessage", "Unknown error")
            await update.message.reply_text(f"❌ Download Failed: {msg}")
            
    except Exception as e:
        await progress.delete()
        await update.message.reply_text(f"❌ Error: {str(e)}")
    
    if user_id in _SESSIONS:
        del _SESSIONS[user_id]
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    if user_id in _SESSIONS:
        del _SESSIONS[user_id]
    await update.message.reply_text("❌ Cancelled. /start to begin again.")
    return ConversationHandler.END

# ============================================================
# TOKEN MANAGEMENT
# ============================================================

def get_token():
    print("\n" + "="*50)
    print("   Chuha Aadhar PDF Tool")
    print("="*50)
    print("\n📝 Enter your Telegram Bot Token:")
    print("   (Get it from @BotFather on Telegram)")
    print()
    
    token = input("> ").strip()
    
    if not token or ":" not in token:
        print("❌ Invalid token format!")
        sys.exit(1)
    
    with open(".bot_token", "w") as f:
        f.write(token)
    
    return token

def load_token():
    if os.path.exists(".bot_token"):
        with open(".bot_token", "r") as f:
            token = f.read().strip()
        if token and ":" in token:
            print("✅ Using saved bot token")
            return token
    
    return get_token()

# ============================================================
# MAIN
# ============================================================

def main():
    global BOT_TOKEN
    BOT_TOKEN = load_token()
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            MOBILE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_mobile)],
            CAP1: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_captcha1)],
            OTP1: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_otp1)],
            CAP2: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_captcha2)],
            OTP2: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_otp2)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        conversation_timeout=_SESSION_TTL
    )
    
    app.add_handler(conv)
    
    print("\n✅ Bot is running!")
    print("   Send /start on Telegram to begin")
    print("\n   Press Ctrl+C to stop\n")
    
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Bot stopped")
    except Exception as e:
        print(f"\n❌ Error: {e}")
