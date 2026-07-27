import os
import sys
import time
import requests
import logging
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
import jdatetime
from typing import Dict, Optional, Tuple
from dotenv import load_dotenv

# ============================================
# بارگذاری تنظیمات
# ============================================
load_dotenv()

# تنظیمات لاگ
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================
# توکن‌ها و آیدی‌ها (از .env)
# ============================================
TELEGRAM_BOT_1_TOKEN = os.getenv("TELEGRAM_BOT_1_TOKEN", "")
TELEGRAM_BOT_1_CHAT_ID = os.getenv("TELEGRAM_BOT_1_CHAT_ID", "")
BALE_BOT_1_TOKEN = os.getenv("BALE_BOT_1_TOKEN", "")
BALE_BOT_1_CHAT_ID = os.getenv("BALE_BOT_1_CHAT_ID", "")

TELEGRAM_BOT_2_TOKEN = os.getenv("TELEGRAM_BOT_2_TOKEN", "")
TELEGRAM_BOT_2_CHAT_ID = os.getenv("TELEGRAM_BOT_2_CHAT_ID", "")
BALE_BOT_2_TOKEN = os.getenv("BALE_BOT_2_TOKEN", "")
BALE_BOT_2_CHAT_ID = os.getenv("BALE_BOT_2_CHAT_ID", "")

# ============================================
# توابع کمکی
# ============================================

def get_persian_datetime() -> Tuple[str, str]:
    """دریافت تاریخ و زمان شمسی"""
    now = datetime.now(timezone.utc)
    iran_now = now.astimezone(timezone(timedelta(hours=3, minutes=30)))
    jalali = jdatetime.datetime.fromgregorian(datetime=iran_now)
    
    weekdays = {
        0: "دوشنبه", 1: "سه‌شنبه", 2: "چهارشنبه",
        3: "پنجشنبه", 4: "جمعه", 5: "شنبه", 6: "یکشنبه"
    }
    months = {
        1: "فروردین", 2: "اردیبهشت", 3: "خرداد",
        4: "تیر", 5: "مرداد", 6: "شهریور",
        7: "مهر", 8: "آبان", 9: "آذر",
        10: "دی", 11: "بهمن", 12: "اسفند"
    }
    
    weekday_name = weekdays.get(jalali.weekday(), "")
    month_name = months.get(jalali.month, "")
    date_str = f"{weekday_name} {jalali.day} {month_name} {jalali.year}"
    time_str = iran_now.strftime("%H:%M")
    
    return date_str, time_str


def parse_price(text: str) -> Optional[float]:
    """تمیز کردن و تبدیل متن به عدد"""
    if not text:
        return None
    cleaned = text.replace(",", "").replace("٬", "").strip()
    cleaned = ''.join(c for c in cleaned if c.isdigit() or c == '.')
    try:
        return float(cleaned)
    except ValueError:
        return None


# ============================================
# دریافت قیمت از TGJU
# ============================================

def fetch_tgju_price(url: str) -> Optional[float]:
    """دریافت قیمت از سایت TGJU"""
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Accept-Language": "fa,en-US;q=0.7,en;q=0.3"
        }
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # روش‌های مختلف برای پیدا کردن قیمت
        selectors = [
            "span#last-price-value",
            "[data-col='info.last_trade.PDrCotVal']",
            "table.table-condensed tbody tr td.text-left",
            ".fs-txt-black .value",
            "span[data-last-price]",
            ".price-value",
            ".last-price",
        ]
        
        for selector in selectors:
            element = soup.select_one(selector)
            if element and element.get_text(strip=True):
                price = parse_price(element.get_text(strip=True))
                if price and price > 1000:
                    # قیمت‌ها در TGJU به ریال هستند
                    return price / 10
        
        # اگر با سلكتور پیدا نشد، همه متن رو جستجو کن
        all_text = soup.get_text()
        numbers = [parse_price(n) for n in all_text.split() if parse_price(n) and parse_price(n) > 10000]
        if numbers:
            return max(numbers) / 10
        
        return None
        
    except Exception as e:
        logger.error(f"خطا در دریافت از {url}: {e}")
        return None


def get_all_tgju_prices() -> Dict[str, Optional[float]]:
    """دریافت همه قیمت‌ها از TGJU"""
    urls = {
        'gold_18': "https://www.tgju.org/profile/geram18",
        'gold_24': "https://www.tgju.org/profile/geram24",
        'silver_999': "https://www.tgju.org/profile/silver_999",
        'dollar': "https://www.tgju.org/profile/price_dollar_rl",
        'gold_ounce': "https://www.tgju.org/profile/ons",
        'silver_ounce': "https://www.tgju.org/profile/silver",
    }
    
    results = {}
    for name, url in urls.items():
        results[name] = fetch_tgju_price(url)
        if results[name]:
            logger.info(f"✅ {name}: {results[name]:,.0f}")
        else:
            logger.warning(f"⚠️ {name}: دریافت نشد")
    
    return results


# ============================================
# دریافت قیمت از Nobitex
# ============================================

NOBITEX_API_URL = "https://apiv2.nobitex.ir/market/stats"


def fetch_nobitex_price(src_currency: str, dst_currency: str = "rls") -> Optional[float]:
    """دریافت قیمت از API نوبیتکس"""
    try:
        params = {'srcCurrency': src_currency, 'dstCurrency': dst_currency}
        response = requests.get(NOBITEX_API_URL, params=params, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        if data.get('status') == 'ok':
            stats = data.get('stats', {})
            pair_key = f"{src_currency}-{dst_currency}"
            if pair_key in stats:
                latest = stats[pair_key].get('latest')
                if latest:
                    # قیمت‌ها به ریال هستند
                    return float(latest) / 10
        
        return None
        
    except Exception as e:
        logger.error(f"خطا در دریافت {src_currency}/{dst_currency}: {e}")
        return None


def get_all_nobitex_prices() -> Dict[str, Optional[float]]:
    """دریافت همه قیمت‌های ارز دیجیتال از نوبیتکس"""
    symbols = {
        'btc': 'بیت‌کوین',
        'eth': 'اتر',
        'usdt': 'تتر',
        'xaut': 'تتر گلد',
    }
    
    results = {}
    for symbol, name in symbols.items():
        results[symbol] = fetch_nobitex_price(symbol)
        if results[symbol]:
            logger.info(f"✅ {name} ({symbol}): {results[symbol]:,.0f}")
        else:
            logger.warning(f"⚠️ {name} ({symbol}): دریافت نشد")
    
    return results


# ============================================
# ارسال پیام به تلگرام
# ============================================

def send_telegram(token: str, chat_id: str, message: str) -> bool:
    """ارسال پیام به تلگرام"""
    if not token or not chat_id:
        logger.warning("⚠️ توکن یا آیدی تلگرام تنظیم نشده")
        return False
    
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        response = requests.post(url, json={
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML',
            'disable_web_page_preview': True
        }, timeout=15)
        
        if response.status_code == 200:
            logger.info("✅ پیام به تلگرام ارسال شد")
            return True
        else:
            logger.error(f"❌ خطا در تلگرام: {response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ خطا در ارسال به تلگرام: {e}")
        return False


# ============================================
# ارسال پیام به بله
# ============================================

def send_bale(token: str, chat_id: str, message: str) -> bool:
    """ارسال پیام به بله"""
    if not token or not chat_id:
        logger.warning("⚠️ توکن یا آیدی بله تنظیم نشده")
        return False
    
    url = f"https://tapi.bale.ai/bot{token}/sendMessage"
    try:
        response = requests.post(url, json={
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML'
        }, timeout=15)
        
        if response.status_code == 200:
            logger.info("✅ پیام به بله ارسال شد")
            return True
        else:
            logger.error(f"❌ خطا در بله: {response.text}")
            return False
    except Exception as e:
        logger.error(f"❌ خطا در ارسال به بله: {e}")
        return False


# ============================================
# ساخت پیام ربات ۱ (طلا و نقره)
# ============================================

def format_bot1_message(data: Dict) -> str:
    """ساخت پیام برای ربات طلا و نقره"""
    persian_date, persian_time = get_persian_datetime()
    
    message = f"""📊 <b>گزارش قیمت طلا و نقره</b>
📅 <b>{persian_date}</b> | 🕒 <b>{persian_time}</b>

<b>💰 قیمت‌های طلا:</b>
• طلا ۱۸ عیار: <b>{data.get('gold_18', 0):,.0f} تومان</b>
• طلا ۲۴ عیار: <b>{data.get('gold_24', 0):,.0f} تومان</b>
• انس طلا: <b>${data.get('gold_ounce', 0):,.2f}</b>

<b>🪙 قیمت‌های نقره:</b>
• نقره ۹۹۹: <b>{data.get('silver_999', 0):,.0f} تومان</b>
• انس نقره: <b>${data.get('silver_ounce', 0):,.2f}</b>

<b>💵 دلار:</b> <b>{data.get('dollar', 0):,.0f} تومان</b>
<b>🪙 تتر:</b> <b>{data.get('usdt', 0):,.0f} تومان</b>
"""
    return message


# ============================================
# ساخت پیام ربات ۲ (ارزهای دیجیتال)
# ============================================

def format_bot2_message(data: Dict) -> str:
    """ساخت پیام برای ربات ارزهای دیجیتال"""
    persian_date, persian_time = get_persian_datetime()
    
    message = f"""🚀 <b>گزارش قیمت ارزهای دیجیتال</b>
📅 <b>{persian_date}</b> | 🕒 <b>{persian_time}</b>

<b>🪙 قیمت‌ها:</b>
• بیت‌کوین: <b>{data.get('btc', 0):,.0f} تومان</b>
• اتر: <b>{data.get('eth', 0):,.0f} تومان</b>
• تتر: <b>{data.get('usdt', 0):,.0f} تومان</b>
• تتر گلد: <b>{data.get('xaut', 0):,.0f} تومان</b>
"""
    
    # محاسبه آربیتراژ تتر
    if data.get('usdt') and data.get('dollar'):
        diff = ((data['usdt'] - data['dollar']) / data['dollar']) * 100
        message += f"\n<b>📊 آربیتراژ تتر/دلار:</b> <b>{diff:+.2f}%</b>"
    
    return message


# ============================================
# تابع اصلی
# ============================================

def main():
    logger.info("🚀 شروع دریافت داده‌ها...")
    
    # دریافت همه داده‌ها
    tgju_data = get_all_tgju_prices()
    nobitex_data = get_all_nobitex_prices()
    
    # ترکیب داده‌ها
    all_data = {**tgju_data, **nobitex_data}
    
    # بررسی داده‌های ضروری
    if not all_data.get('gold_18') or not all_data.get('dollar'):
        logger.error("❌ داده‌های ضروری دریافت نشدند")
        return
    
    # ساخت پیام‌ها
    bot1_message = format_bot1_message(all_data)
    bot2_message = format_bot2_message(all_data)
    
    # ارسال به ربات ۱ (طلا و نقره)
    logger.info("📤 ارسال به ربات ۱ (طلا و نقره)...")
    if TELEGRAM_BOT_1_TOKEN and TELEGRAM_BOT_1_CHAT_ID:
        send_telegram(TELEGRAM_BOT_1_TOKEN, TELEGRAM_BOT_1_CHAT_ID, bot1_message)
    if BALE_BOT_1_TOKEN and BALE_BOT_1_CHAT_ID:
        send_bale(BALE_BOT_1_TOKEN, BALE_BOT_1_CHAT_ID, bot1_message)
    
    # ارسال به ربات ۲ (ارزهای دیجیتال)
    logger.info("📤 ارسال به ربات ۲ (ارزهای دیجیتال)...")
    if TELEGRAM_BOT_2_TOKEN and TELEGRAM_BOT_2_CHAT_ID:
        send_telegram(TELEGRAM_BOT_2_TOKEN, TELEGRAM_BOT_2_CHAT_ID, bot2_message)
    if BALE_BOT_2_TOKEN and BALE_BOT_2_CHAT_ID:
        send_bale(BALE_BOT_2_TOKEN, BALE_BOT_2_CHAT_ID, bot2_message)
    
    logger.info("✅ اجرا با موفقیت کامل شد")


if __name__ == "__main__":
    main()
