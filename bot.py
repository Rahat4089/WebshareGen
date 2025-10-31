import os, json, random, string, threading, time, concurrent.futures, queue
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict
import requests, colorama
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.handlers import MessageHandler
from pymongo import MongoClient
import asyncio
from datetime import datetime
import shutil

# Initialize colorama
colorama.init()

# Create download directory
DOWNLOAD_DIR = "downloads"
if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

# MongoDB configuration
MONGO_URI = "mongodb+srv://animepahe:animepahe@animepahe.o8zgy.mongodb.net/?retryWrites=true&w=majority&appName=animepahe"
mongo_client = MongoClient(MONGO_URI)
db = mongo_client["webshare_bot"]
users_collection = db["users"]
settings_collection = db["settings"]
free_services_collection = db["free_services"]
stats_collection = db["stats"]

# Bot configuration
API_ID = 23933044
API_HASH = "6df11147cbec7d62a323f0f498c8c03a"
BOT_TOKEN = "8363090329:AAF1AnPvvGr1VlZIovbuPShGy-WCMuiSLns"
OWNER_ID = 7125341830

# Queue system
user_queues = {}  # User-specific queues
global_queue = queue.Queue()  # Global queue
queue_lock = threading.Lock()

# Initialize bot
app = Client("webshare_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

class log:
    def log(msg: str, color: str = "reset"):
        msg = str(msg)
        codes = {
            "reset": "\033[0m",
            "red": "\033[91m",
            "green": "\033[92m",
            "yellow": "\033[93m",
            "blue": "\033[94m",
            "purple": "\033[95m",
            "cyan": "\033[96m",
            "white": "\033[97m"
        }
        print(f"{codes.get(color, codes['reset'])}{msg}{codes['reset']}")

class ProxyFormat(Enum):
    USER_PASS_AT_IP_PORT = "user:pass@ip:port"
    USER_PASS_IP_PORT = "user:pass:ip:port"
    IP_PORT_USER_PASS = "ip:port:user:pass"

class ProxyConverter:
    @staticmethod
    def parse(proxy: str, cur: str, out: str) -> Optional[str]:
        try:
            if cur == ProxyFormat.USER_PASS_AT_IP_PORT.value:
                up, ip_port = proxy.split("@")
                user, pwd = up.split(":")
                ip, port = ip_port.split(":")
            elif cur == ProxyFormat.USER_PASS_IP_PORT.value:
                user, pwd, ip, port = proxy.split(":")
            elif cur == ProxyFormat.IP_PORT_USER_PASS.value:
                ip, port, user, pwd = proxy.split(":")
            else:
                return None
            if out == ProxyFormat.USER_PASS_AT_IP_PORT.value:
                return f"{user}:{pwd}@{ip}:{port}"
            if out == ProxyFormat.USER_PASS_IP_PORT.value:
                return f"{user}:{pwd}:{ip}:{port}"
            if out == ProxyFormat.IP_PORT_USER_PASS.value:
                return f"{ip}:{port}:{user}:{pwd}"
        except ValueError:
            return None
        return None

@dataclass
class ProxyConf:
    address: str
    port: str
    user: Optional[str] = None
    pwd: Optional[str] = None

class TwoCaptchaSolver:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "http://2captcha.com"
        
    def get_balance(self) -> float:
        """Check 2Captcha balance"""
        try:
            params = {
                'key': self.api_key,
                'action': 'getbalance',
                'json': 1
            }
            response = requests.get(f"{self.base_url}/res.php", params=params, timeout=10)
            result = response.json()
            if result['status'] == 1:
                return float(result['request'])
            else:
                raise RuntimeError(f"Failed to get balance: {result.get('request', 'Unknown error')}")
        except Exception as e:
            raise RuntimeError(f"Balance check failed: {e}")
        
    def solve_recaptcha_v2(self, site_key: str, page_url: str) -> str:
        # Submit captcha
        submit_url = f"{self.base_url}/in.php"
        data = {
            'key': self.api_key,
            'method': 'userrecaptcha',
            'googlekey': site_key,
            'pageurl': page_url,
            'json': 1
        }
        
        response = requests.post(submit_url, data=data)
        result = response.json()
        
        if result['status'] != 1:
            raise RuntimeError(f"2Captcha error: {result.get('request', 'Unknown error')}")
            
        captcha_id = result['request']
        
        # Wait for solution
        retrieve_url = f"{self.base_url}/res.php"
        for _ in range(20):  # Wait up to 2 minutes
            time.sleep(5)
            params = {
                'key': self.api_key,
                'action': 'get',
                'id': captcha_id,
                'json': 1
            }
            
            response = requests.get(retrieve_url, params=params)
            result = response.json()
            
            if result['status'] == 1:
                return result['request']
            elif result['request'] != 'CAPCHA_NOT_READY':
                raise RuntimeError(f"2Captcha error: {result.get('request', 'Unknown error')}")
                
        raise RuntimeError("2Captcha timeout: Captcha not solved in time")

class AccountManager:
    @staticmethod
    def save_account_to_json(account_data: Dict, user_id: int):
        """Save account data to user-specific JSON file"""
        filename = f"accounts_{user_id}.json"
        filepath = os.path.join(DOWNLOAD_DIR, filename)
        
        with threading.Lock():
            # Load existing accounts if file exists
            existing_accounts = []
            if os.path.exists(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read().strip()
                        if content:
                            existing_accounts = json.loads(content)
                except (json.JSONDecodeError, Exception):
                    existing_accounts = []
            
            # Add new account
            existing_accounts.append(account_data)
            
            # Save all accounts
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(existing_accounts, f, indent=2, ensure_ascii=False)
        
        return filepath

class WebshareClient:
    WEBSITE_KEY = "6LeHZ6UUAAAAAKat_YS--O2tj_by3gv3r_l03j9d"
    BASE = "https://proxy.webshare.io/api/v2"
    UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"
    TIMEOUT = (5, 20)

    def __init__(self, proxyless: bool, cap_key: str, pool: List[str], fmt: str, log_rotating: bool = False, max_pool: int = 64):
        self.proxyless = proxyless
        self.cap_key = cap_key
        self.proxies = pool
        self.fmt = fmt or "ip:port:username:password"
        self.log_rotating = log_rotating
        self.session = self._sess(max_pool)
        self.ckey: Optional[str] = None
        self.used = False
        self.cur_proxy: Optional[str] = None
        self.domains = ["gmail.com", "outlook.com", "yahoo.com", "icloud.com", "hotmail.com", "aol.com"]
        self.roots = ["pixel", "alpha", "drift", "neo", "astro", "zenith", "echo", "nova", "crypt", "orbit", "dash", "cloud", "vibe", "frost", "hex", "pulse", "quant", "terra", "lumen", "flux"]
        self.suffixes = ["tv", "hub", "io", "xd", "on", "lab", "it", "max", "sys", "hq", "net", "pro", "tech", "dev"]
        self.lock = threading.Lock()
        
        self.captcha_solver = TwoCaptchaSolver(self.cap_key)

    def _sess(self, max_pool):
        s = requests.Session()
        s.headers["User-Agent"] = self.UA
        ad = HTTPAdapter(pool_connections=max_pool, pool_maxsize=max_pool, max_retries=Retry(total=2, backoff_factor=0.2))
        s.mount("https://", ad)
        s.mount("http://", ad)
        if not self.proxyless:
            self._pick_proxy(s)
        return s

    def _pick_proxy(self, s=None):
        s = s or self.session
        if not self.proxies:
            s.proxies = {}
            return
        self.cur_proxy = random.choice(self.proxies)
        cfg = self._parse(self.cur_proxy)
        pstr = self._fmt(cfg)
        s.proxies = {"https": f"http://{pstr}", "http": f"http://{pstr}"}

    @staticmethod
    def _parse(p: str) -> ProxyConf:
        if "@" in p:
            auth, addr = p.split("@")
            user, pwd = auth.split(":")
            ip, prt = addr.split(":")
            return ProxyConf(ip, prt, user, pwd)
        pts = p.split(":")
        if len(pts) == 2:
            return ProxyConf(pts[0], pts[1])
        if len(pts) == 4:
            return ProxyConf(pts[0], pts[1], pts[2], pts[3])
        raise ValueError("bad proxy")

    @staticmethod
    def _fmt(c: ProxyConf):
        return f"{c.user}:{c.pwd}@{c.address}:{c.port}" if c.user and c.pwd else f"{c.address}:{c.port}"

    def _solve(self):
        return self.captcha_solver.solve_recaptcha_v2(self.WEBSITE_KEY, "https://webshare.io")

    def _rand_email(self):
        base = random.choice(self.roots)
        suf = random.choice(self.suffixes)
        num = str(random.randint(10, 999)) if random.random() < 0.4 else ""
        return f"{base}{suf}{num}@{random.choice(self.domains)}"

    def _rand_pwd(self):
        chars = (random.choices(string.ascii_lowercase, k=random.randint(4, 6)) + 
                random.choices(string.ascii_uppercase, k=random.randint(2, 4)) + 
                random.choices(string.digits, k=random.randint(2, 4)) + 
                random.choices("!@#$%^&*", k=random.randint(1, 2)))
        random.shuffle(chars)
        return "".join(chars)

    def _register(self):
        if not self.ckey or self.used:
            self.ckey = self._solve()
            self.used = False
        
        email = self._rand_email()
        password = self._rand_pwd()
        
        js = {"email": email, "password": password, "tos_accepted": True, "recaptcha": self.ckey}
        r = self.session.post(f"{self.BASE}/register/", json=js, timeout=self.TIMEOUT)
        res = r.json()
        self.used = True
        self.ckey = None
        
        tok = res.get("token")
        if not tok:
            if "throttle" in res.get("detail", "") and self.cur_proxy in self.proxies:
                self.proxies.remove(self.cur_proxy)
            raise RuntimeError(res.get("detail", "Registration failed"))
        
        return tok, email, password

    def download_proxies(self, tok):
        """Download proxies and return formatted data"""
        self.session.headers["Authorization"] = f"Token {tok}"
        url = 'https://proxy.webshare.io/api/v2/proxy/list/?mode=direct&page=1&page_size=10'
        
        try:
            response = self.session.get(url)
            results = response.json()['results']
            
            static_proxies = []
            rotating_endpoint = ""
            
            for proxy in results:
                if self.log_rotating:
                    rotating_endpoint = f"http://{proxy['username']}-rotate:{proxy['password']}@p.webshare.io:80/"
                # Always collect static proxies regardless of rotating setting
                proxy_line = f"{proxy['proxy_address']}:{proxy['port']}:{proxy['username']}:{proxy['password']}"
                static_proxies.append(proxy_line)
            
            return static_proxies, rotating_endpoint
                
        except Exception as e:
            log.log(f"Error downloading proxies: {e}", "red")
            return [], ""

    def generate_once(self, user_id: int):
        start_time = time.time()
        try:
            tok, email, password = self._register()
            
            static_proxies, rotating_endpoint = self.download_proxies(tok)
            
            account_data = {
                "Email": email,
                "Pass": password,
                "generated_at": datetime.now().isoformat(),
                "time_taken": round(time.time() - start_time, 2)
            }
            
            if rotating_endpoint:
                account_data["rotating_endpoint"] = rotating_endpoint
            
            if static_proxies:
                account_data["Proxies"] = static_proxies
            
            filepath = AccountManager.save_account_to_json(account_data, user_id)
            
            return True, account_data, filepath, static_proxies, rotating_endpoint
            
        except requests.RequestException as e:
            if self.cur_proxy in self.proxies:
                self.proxies.remove(self.cur_proxy)
            return False, str(e), None, [], ""
        except Exception as e:
            return False, str(e), None, [], ""
        finally:
            if not self.proxyless:
                self._pick_proxy()

# Database functions
def get_user_data(user_id: int):
    user_data = users_collection.find_one({"user_id": user_id})
    if not user_data:
        user_data = {
            "user_id": user_id,
            "proxy": "",
            "captcha_key": "",
            "settings": {
                "email_pass": True,
                "proxy": False,
                "rotating_endpoint": False
            },
            "created_at": datetime.now(),
            "accounts_generated": 0
        }
        users_collection.insert_one(user_data)
    return user_data

def update_user_data(user_id: int, update_data: dict):
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": update_data},
        upsert=True
    )

def increment_accounts_generated(user_id: int):
    users_collection.update_one(
        {"user_id": user_id},
        {"$inc": {"accounts_generated": 1}},
        upsert=True
    )

def get_free_services():
    services = free_services_collection.find_one({"id": "free_services"})
    if not services:
        services = {
            "id": "free_services",
            "enabled": False,
            "free_proxies": [],
            "free_keys": [],
            "updated_at": datetime.now()
        }
        free_services_collection.insert_one(services)
    return services

def update_free_services(update_data: dict):
    free_services_collection.update_one(
        {"id": "free_services"},
        {"$set": update_data},
        upsert=True
    )

def get_bot_stats():
    stats = stats_collection.find_one({"id": "bot_stats"})
    if not stats:
        stats = {
            "id": "bot_stats",
            "total_accounts_generated": 0,
            "total_users": 0,
            "last_updated": datetime.now()
        }
        stats_collection.insert_one(stats)
    return stats

def update_bot_stats(update_data: dict):
    stats_collection.update_one(
        {"id": "bot_stats"},
        {"$set": update_data},
        upsert=True
    )

# Queue management functions
def get_user_queue(user_id: int):
    """Get or create user-specific queue"""
    with queue_lock:
        if user_id not in user_queues:
            user_queues[user_id] = queue.Queue()
        return user_queues[user_id]

def add_to_queue(user_id: int, task_data: dict):
    """Add task to both user queue and global queue"""
    user_queue = get_user_queue(user_id)
    user_queue.put(task_data)
    global_queue.put({"user_id": user_id, "task_data": task_data})

def get_queue_position(user_id: int):
    """Get user's position in queue"""
    user_queue = get_user_queue(user_id)
    return user_queue.qsize()

def process_next_task():
    """Process next task from global queue"""
    try:
        task = global_queue.get_nowait()
        return task
    except queue.Empty:
        return None

# Utility functions
async def check_proxy_status(proxy: str) -> bool:
    """Check if proxy is working"""
    try:
        if not proxy:
            return False
            
        # Test proxy with a simple request
        test_url = "https://www.google.com"
        proxies = {
            "http": f"http://{proxy}",
            "https": f"http://{proxy}"
        }
        
        response = requests.get(test_url, proxies=proxies, timeout=10)
        return response.status_code == 200
    except:
        return False

async def check_captcha_balance(api_key: str) -> tuple:
    """Check 2Captcha balance and return (success, balance/error)"""
    try:
        solver = TwoCaptchaSolver(api_key)
        balance = solver.get_balance()
        return True, balance
    except Exception as e:
        return False, str(e)

async def cleanup_file(filepath: str):
    """Delete file after sending"""
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except Exception as e:
        log.log(f"Error cleaning up file: {e}", "red")

# Background task processor
async def process_queued_tasks():
    """Background task to process queued generation requests"""
    while True:
        try:
            task = process_next_task()
            if task:
                user_id = task["user_id"]
                task_data = task["task_data"]
                
                # Process the generation task
                await process_generation_task(user_id, task_data)
            
            await asyncio.sleep(1)  # Small delay to prevent busy waiting
        except Exception as e:
            log.log(f"Error in task processor: {e}", "red")
            await asyncio.sleep(5)

async def process_generation_task(user_id: int, task_data: dict):
    """Process a single generation task"""
    try:
        message = task_data["message"]
        user_data = task_data["user_data"]
        free_services = task_data["free_services"]
        settings = task_data["settings"]
        proxy_list = task_data["proxy_list"]
        captcha_key = task_data["captcha_key"]
        
        # Check proxy status
        proxy_status = "❌ INACTIVE"
        if proxy_list:
            proxy_status = "✔️ ACTIVE" if await check_proxy_status(proxy_list[0]) else "❌ INACTIVE"
        
        # Check captcha balance
        captcha_balance = "N/A"
        if captcha_key:
            success, balance = await check_captcha_balance(captcha_key)
            if success:
                captcha_balance = f"${balance:.2f}"
        
        # Generate account
        client_obj = WebshareClient(
            proxyless=False,
            cap_key=captcha_key,
            pool=proxy_list,
            fmt="ip:port:username:password",
            log_rotating=settings.get("rotating_endpoint", False)
        )
        
        success, result, filepath, static_proxies, rotating_endpoint = client_obj.generate_once(user_id)
        
        if success:
            account_data = result
            increment_accounts_generated(user_id)
            
            # Update bot stats
            stats = get_bot_stats()
            update_bot_stats({
                "total_accounts_generated": stats.get("total_accounts_generated", 0) + 1,
                "last_updated": datetime.now()
            })
            
            response_text = "ϟ ACCOUNT GENERATED SUCCESSFULLY\n\n"
            
            if settings.get("email_pass"):
                response_text += f"<b>Email:</b> <code>{account_data['Email']}</code>\n"
                response_text += f"<b>Password:</b> <code>{account_data['Pass']}</code>\n\n"
            
            if settings.get("rotating_endpoint") and rotating_endpoint:
                response_text += f"<b>Rotating Endpoint:</b>\n<code>{rotating_endpoint}</code>\n\n"
            
            if settings.get("proxy") and static_proxies:
                response_text += f"<b>Static Proxies ({len(static_proxies)}):</b>\n"
                for proxy in static_proxies:
                    response_text += f"<code>{proxy}</code>\n"
                response_text += "\n"
            
            response_text += f"<b>Time Taken:</b> {account_data['time_taken']}s\n"
            response_text += f"<b>Proxy Status:</b> {proxy_status}\n"
            response_text += f"<b>2Captcha Balance:</b> {captcha_balance}\n\n"
            response_text += f"ϟ Saved to your accounts file: <code>accounts_{user_id}.json</code>"
            
            # Send the message first
            await message.reply_text(response_text)
            
            # Then send the file
            if filepath and os.path.exists(filepath):
                try:
                    await message.reply_document(
                        document=filepath,
                        caption=f"ϟ Your accounts file - {os.path.basename(filepath)}"
                    )
                    # Clean up file after sending
                    await cleanup_file(filepath)
                except Exception as e:
                    await message.reply_text(f"ϟ Error sending file: {e}")
            else:
                await message.reply_text("ϟ Could not generate accounts file")
                
        else:
            await message.reply_text(f"ϟ GENERATION FAILED\n\nError: {result}")
            
    except Exception as e:
        log.log(f"Error processing generation task: {e}", "red")
        try:
            await message.reply_text(f"ϟ GENERATION FAILED\n\nError: {str(e)}")
        except:
            pass

# Bot command handlers
@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    user_id = message.from_user.id
    get_user_data(user_id)  # Initialize user data
    
    # Create keyboard with ϟ button
    keyboard = [
        [InlineKeyboardButton("ϟ", url="https://t.me/still_alivenow")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    welcome_text = """
<b>ϟ WEBSHARE ACCOUNT GENERATOR BOT</b>

<b>ϟ FEATURES:</b>
• Create Webshare.io accounts with 1GB proxy traffic
• Support for both static and rotating proxies
• 2Captcha integration for automatic captcha solving
• Manage your proxies and API keys
• Real-time status checking
• Automatic file download and cleanup
• User-based and global queue system

<b>ϟ AVAILABLE COMMANDS:</b>
/addproxy - Add your proxy
/rmvproxy - Remove your proxy  
/addkey - Add 2Captcha API key
/rmvkey - Remove API key
/settings - Configure account settings
/generate - Create new account
/status - Check proxy & captcha status
/myconfig - View current configuration
/queue - Check your queue position

<b>ϟ ADMIN COMMANDS:</b>
/freeproxy - Add free proxies
/freekey - Add free captcha keys  
/freeservice - Toggle free services
/rmvfreeproxy - Remove free proxies
/rmvfreekey - Remove free keys
/stats - View bot statistics
/queue_stats - View global queue stats
"""
    
    await message.reply_text(welcome_text, reply_markup=reply_markup)

@app.on_message(filters.command("addproxy"))
async def add_proxy_command(client, message: Message):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    
    if len(message.command) < 2:
        await message.reply_text("""
<b>ϟ USAGE:</b> <code>/addproxy [proxy]</code>

<b>ϟ PROXY FORMATS:</b>
• <code>ip:port</code>
• <code>user:pass@ip:port</code> 
• <code>user:pass:ip:port</code>
• <code>ip:port:user:pass</code>

<b>ϟ EXAMPLE:</b> <code>/addproxy 123.456.789:8080:user:pass</code>
""")
        return
    
    proxy = message.command[1]
    
    # Check proxy format and status
    try:
        # Test proxy format by parsing
        if "@" in proxy:
            auth, addr = proxy.split("@")
            user, pwd = auth.split(":")
            ip, port = addr.split(":")
        else:
            parts = proxy.split(":")
            if len(parts) == 2:
                ip, port = parts
                user, pwd = "", ""
            elif len(parts) == 4:
                ip, port, user, pwd = parts
            else:
                await message.reply_text("ϟ INVALID PROXY FORMAT")
                return
                
        # Check proxy status
        status = await check_proxy_status(proxy)
        if not status:
            await message.reply_text("ϟ Proxy added but seems inactive. Check format and try /status")
        else:
            await message.reply_text("ϟ Proxy is active and working")
            
    except Exception as e:
        await message.reply_text("ϟ INVALID PROXY FORMAT")
        return
    
    update_user_data(user_id, {"proxy": proxy})
    await message.reply_text("ϟ PROXY ADDED SUCCESSFULLY")

@app.on_message(filters.command("rmvproxy"))
async def remove_proxy_command(client, message: Message):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    
    if not user_data.get("proxy"):
        await message.reply_text("ϟ You don't have any proxy set")
        return
    
    update_user_data(user_id, {"proxy": ""})
    await message.reply_text("ϟ PROXY REMOVED SUCCESSFULLY")

@app.on_message(filters.command("addkey"))
async def add_key_command(client, message: Message):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    
    if len(message.command) < 2:
        await message.reply_text("""
<b>ϟ USAGE:</b> <code>/addkey [2captcha_api_key]</code>

<b>ϟ EXAMPLE:</b> <code>/addkey abc123def456ghi789</code>
""")
        return
    
    api_key = message.command[1]
    
    # Check captcha balance
    await message.reply_text("ϟ Checking 2Captcha balance...")
    success, result = await check_captcha_balance(api_key)
    
    if success:
        update_user_data(user_id, {"captcha_key": api_key})
        await message.reply_text(f"ϟ 2CAPTCHA KEY ADDED\nϟ Balance: ${result:.2f}")
    else:
        await message.reply_text(f"ϟ INVALID 2CAPTCHA KEY: {result}")

@app.on_message(filters.command("rmvkey"))
async def remove_key_command(client, message: Message):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    
    if not user_data.get("captcha_key"):
        await message.reply_text("ϟ You don't have any 2Captcha key set")
        return
    
    update_user_data(user_id, {"captcha_key": ""})
    await message.reply_text("ϟ 2CAPTCHA KEY REMOVED SUCCESSFULLY")

@app.on_message(filters.command("myconfig"))
async def myconfig_command(client, message: Message):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    
    config_text = "<b>ϟ YOUR CURRENT CONFIGURATION</b>\n\n"
    
    # Proxy info
    proxy = user_data.get("proxy", "")
    if proxy:
        proxy_status = await check_proxy_status(proxy)
        config_text += f"<b>Proxy:</b> <code>{proxy}</code>\n"
        config_text += f"<b>Proxy Status:</b> {'✔️ ACTIVE' if proxy_status else '❌ INACTIVE'}\n\n"
    else:
        config_text += "<b>Proxy:</b> ❌ NOT SET\n\n"
    
    # Captcha key info
    captcha_key = user_data.get("captcha_key", "")
    if captcha_key:
        success, result = await check_captcha_balance(captcha_key)
        if success:
            config_text += f"<b>2Captcha Key:</b> ✔️ ACTIVE\n"
            config_text += f"<b>Balance:</b> ${result:.2f}\n\n"
        else:
            config_text += f"<b>2Captcha Key:</b> ❌ INVALID\n\n"
    else:
        config_text += "<b>2Captcha Key:</b> ❌ NOT SET\n\n"
    
    # Settings info
    settings = user_data.get("settings", {})
    config_text += "<b>ϟ ENABLED SETTINGS:</b>\n"
    config_text += f"• Email:Pass - {'✔️' if settings.get('email_pass') else '❌'}\n"
    config_text += f"• Static Proxies - {'✔️' if settings.get('proxy') else '❌'}\n"
    config_text += f"• Rotating Endpoint - {'✔️' if settings.get('rotating_endpoint') else '❌'}\n\n"
    
    # Free services info
    free_services = get_free_services()
    if free_services.get("enabled"):
        config_text += "<b>Free Services:</b> ✔️ AVAILABLE\n"
        config_text += f"• Free Proxies: {len(free_services.get('free_proxies', []))}\n"
        config_text += f"• Free Keys: {len(free_services.get('free_keys', []))}\n"
    else:
        config_text += "<b>Free Services:</b> ❌ DISABLED\n"
    
    # Queue info
    queue_position = get_queue_position(user_id)
    config_text += f"\n<b>Queue Position:</b> {queue_position} tasks waiting"
    
    await message.reply_text(config_text)

@app.on_message(filters.command("status"))
async def status_command(client, message: Message):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    
    status_text = "<b>ϟ CURRENT STATUS</b>\n\n"
    
    # Proxy status
    proxy = user_data.get("proxy", "")
    if proxy:
        status_text += "ϟ Checking proxy status...\n"
        proxy_status = await check_proxy_status(proxy)
        status_text += f"<b>Proxy:</b> {'✔️ ACTIVE' if proxy_status else '❌ INACTIVE'}\n"
    else:
        status_text += "<b>Proxy:</b> ❌ NOT SET\n"
    
    # Captcha key status
    captcha_key = user_data.get("captcha_key", "")
    if captcha_key:
        status_text += "ϟ Checking 2Captcha balance...\n"
        success, result = await check_captcha_balance(captcha_key)
        if success:
            status_text += f"<b>2Captcha:</b> ✔️ ACTIVE (${result:.2f})\n"
        else:
            status_text += f"<b>2Captcha:</b> ❌ INVALID\n"
    else:
        status_text += "<b>2Captcha:</b> ❌ NOT SET\n"
    
    # Free services status
    free_services = get_free_services()
    if free_services.get("enabled"):
        status_text += f"<b>Free Services:</b> ✔️ ENABLED\n"
        status_text += f"• Free Proxies: {len(free_services.get('free_proxies', []))}\n"
        status_text += f"• Free Keys: {len(free_services.get('free_keys', []))}\n"
    else:
        status_text += "<b>Free Services:</b> ❌ DISABLED\n"
    
    # Queue status
    queue_position = get_queue_position(user_id)
    global_queue_size = global_queue.qsize()
    status_text += f"\n<b>Your Queue Position:</b> {queue_position}\n"
    status_text += f"<b>Global Queue Size:</b> {global_queue_size}"
    
    await message.reply_text(status_text)

@app.on_message(filters.command("queue"))
async def queue_command(client, message: Message):
    user_id = message.from_user.id
    
    queue_position = get_queue_position(user_id)
    global_queue_size = global_queue.qsize()
    
    queue_text = "<b>ϟ QUEUE INFORMATION</b>\n\n"
    queue_text += f"<b>Your Position:</b> {queue_position} tasks waiting\n"
    queue_text += f"<b>Global Queue Size:</b> {global_queue_size} tasks\n\n"
    
    if queue_position == 0:
        queue_text += "ϟ You're next in line. Your task will be processed soon."
    elif queue_position == 1:
        queue_text += "ϟ You have 1 task ahead of you. Please wait..."
    else:
        queue_text += f"ϟ You have {queue_position} tasks ahead of you. Please be patient."
    
    await message.reply_text(queue_text)

@app.on_message(filters.command("settings"))
async def settings_command(client, message: Message):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    settings = user_data.get("settings", {})
    
    keyboard = [
        [
            InlineKeyboardButton(
                f"{'✔️' if settings.get('email_pass') else '❌'} Email:Pass", 
                callback_data="toggle_email_pass"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'✔️' if settings.get('proxy') else '❌'} Static Proxies", 
                callback_data="toggle_proxy"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'✔️' if settings.get('rotating_endpoint') else '❌'} Rotating Endpoint", 
                callback_data="toggle_rotating"
            )
        ],
        [
            InlineKeyboardButton("ϟ", url="https://t.me/still_alivenow"),
            InlineKeyboardButton("« Back", callback_data="back_to_main")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    settings_text = """
<b>ϟ ACCOUNT SETTINGS</b>

Choose what to include in your generated accounts:
• <b>Email:Pass</b> - Account credentials
• <b>Static Proxies</b> - List of static proxies  
• <b>Rotating Endpoint</b> - Single rotating proxy endpoint

<b>Note:</b> At least one option must be enabled. Maximum 3 options can be enabled.
"""
    
    await message.reply_text(settings_text, reply_markup=reply_markup)

@app.on_callback_query()
async def handle_callback(client, callback_query):
    user_id = callback_query.from_user.id
    data = callback_query.data
    user_data = get_user_data(user_id)
    settings = user_data.get("settings", {})
    
    if data == "toggle_email_pass":
        enabled_count = sum(settings.values())
        if not settings.get("email_pass") and enabled_count >= 3:
            await callback_query.answer("❌ Maximum 3 options can be enabled", show_alert=True)
            return
        
        settings["email_pass"] = not settings.get("email_pass", True)
        # Ensure at least one option is enabled
        if not any(settings.values()):
            settings["email_pass"] = True
            await callback_query.answer("❌ At least one option must be enabled", show_alert=True)
    
    elif data == "toggle_proxy":
        enabled_count = sum(settings.values())
        if not settings.get("proxy") and enabled_count >= 3:
            await callback_query.answer("❌ Maximum 3 options can be enabled", show_alert=True)
            return
        
        settings["proxy"] = not settings.get("proxy", False)
        if not any(settings.values()):
            settings["proxy"] = True
            await callback_query.answer("❌ At least one option must be enabled", show_alert=True)
    
    elif data == "toggle_rotating":
        enabled_count = sum(settings.values())
        if not settings.get("rotating_endpoint") and enabled_count >= 3:
            await callback_query.answer("❌ Maximum 3 options can be enabled", show_alert=True)
            return
        
        settings["rotating_endpoint"] = not settings.get("rotating_endpoint", False)
        if not any(settings.values()):
            settings["rotating_endpoint"] = True
            await callback_query.answer("❌ At least one option must be enabled", show_alert=True)
    
    elif data == "back_to_main":
        await callback_query.message.delete()
        await start_command(client, callback_query.message)
        return
    
    update_user_data(user_id, {"settings": settings})
    
    # Update the settings message
    keyboard = [
        [
            InlineKeyboardButton(
                f"{'✔️' if settings.get('email_pass') else '❌'} Email:Pass", 
                callback_data="toggle_email_pass"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'✔️' if settings.get('proxy') else '❌'} Static Proxies", 
                callback_data="toggle_proxy"
            )
        ],
        [
            InlineKeyboardButton(
                f"{'✔️' if settings.get('rotating_endpoint') else '❌'} Rotating Endpoint", 
                callback_data="toggle_rotating"
            )
        ],
        [
            InlineKeyboardButton("ϟ", url="https://t.me/still_alivenow"),
            InlineKeyboardButton("« Back", callback_data="back_to_main")
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await callback_query.message.edit_reply_markup(reply_markup)
    await callback_query.answer("Settings updated")

@app.on_message(filters.command("generate"))
async def generate_command(client, message: Message):
    user_id = message.from_user.id
    user_data = get_user_data(user_id)
    
    # Check requirements
    has_captcha = bool(user_data.get("captcha_key"))
    has_proxy = bool(user_data.get("proxy"))
    
    free_services = get_free_services()
    free_enabled = free_services.get("enabled", False)
    has_free_captcha = free_enabled and bool(free_services.get("free_keys"))
    has_free_proxy = free_enabled and bool(free_services.get("free_proxies"))
    
    if not has_captcha and not has_free_captcha:
        await message.reply_text("""
<b>ϟ MISSING 2CAPTCHA KEY</b>

You need to:
1. Add a 2Captcha key: <code>/addkey [your_key]</code>
2. Or wait for admin to enable free services

Check your status: <code>/status</code>
""")
        return
    
    if not has_proxy and not has_free_proxy:
        await message.reply_text("""
<b>ϟ MISSING PROXY</b>

You need to:
1. Add a proxy: <code>/addproxy [your_proxy]</code>
2. Or wait for admin to enable free services

Check your status: <code>/status</code>
""")
        return
    
    # Get settings
    settings = user_data.get("settings", {})
    if not any(settings.values()):
        await message.reply_text("❌ Please enable at least one option in /settings")
        return
    
    # Prepare configuration
    proxy_list = []
    if user_data.get("proxy"):
        proxy_list.append(user_data["proxy"])
    
    # Add free proxies if available
    if free_services.get("enabled"):
        proxy_list.extend(free_services.get("free_proxies", []))
    
    # Use free key if no personal key
    captcha_key = user_data.get("captcha_key", "")
    if not captcha_key and free_services.get("enabled") and free_services.get("free_keys"):
        captcha_key = random.choice(free_services.get("free_keys", []))
    
    # Add task to queue
    task_data = {
        "message": message,
        "user_data": user_data,
        "free_services": free_services,
        "settings": settings,
        "proxy_list": proxy_list,
        "captcha_key": captcha_key
    }
    
    add_to_queue(user_id, task_data)
    
    queue_position = get_queue_position(user_id)
    
    await message.reply_text(f"""
<b>ϟ TASK ADDED TO QUEUE</b>

Your account generation task has been queued
<b>Position in queue:</b> {queue_position}

You can check your queue status with <code>/queue</code>
The bot will notify you when your task is processed.
""")

# Admin commands
@app.on_message(filters.command("freeproxy") & filters.user(OWNER_ID))
async def free_proxy_command(client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("""
<b>ϟ USAGE:</b> <code>/freeproxy [proxy1] [proxy2] ...</code>

<b>ϟ EXAMPLE:</b> <code>/freeproxy 1.1.1.1:8080 2.2.2.2:9090@user:pass</code>
""")
        return
    
    proxies = message.command[1:]
    free_services = get_free_services()
    
    # Validate proxies
    valid_proxies = []
    invalid_proxies = []
    
    for proxy in proxies:
        if await check_proxy_status(proxy):
            valid_proxies.append(proxy)
        else:
            invalid_proxies.append(proxy)
    
    update_free_services({
        "free_proxies": valid_proxies,
        "updated_at": datetime.now()
    })
    
    response = f"ϟ Added {len(valid_proxies)} valid free proxies\n"
    if invalid_proxies:
        response += f"❌ {len(invalid_proxies)} proxies were invalid and not added"
    
    await message.reply_text(response)

@app.on_message(filters.command("rmvfreeproxy") & filters.user(OWNER_ID))
async def remove_free_proxy_command(client, message: Message):
    free_services = get_free_services()
    
    if not free_services.get("free_proxies"):
        await message.reply_text("❌ No free proxies to remove")
        return
    
    update_free_services({
        "free_proxies": [],
        "updated_at": datetime.now()
    })
    
    await message.reply_text("ϟ ALL FREE PROXIES REMOVED SUCCESSFULLY")

@app.on_message(filters.command("freekey") & filters.user(OWNER_ID))
async def free_key_command(client, message: Message):
    if len(message.command) < 2:
        await message.reply_text("""
<b>ϟ USAGE:</b> <code>/freekey [key1] [key2] ...</code>

<b>ϟ EXAMPLE:</b> <code>/freekey abc123 def456 ghi789</code>
""")
        return
    
    keys = message.command[1:]
    free_services = get_free_services()
    
    # Validate keys
    valid_keys = []
    invalid_keys = []
    
    for key in keys:
        success, _ = await check_captcha_balance(key)
        if success:
            valid_keys.append(key)
        else:
            invalid_keys.append(key)
    
    update_free_services({
        "free_keys": valid_keys,
        "updated_at": datetime.now()
    })
    
    response = f"ϟ Added {len(valid_keys)} valid free captcha keys\n"
    if invalid_keys:
        response += f"❌ {len(invalid_keys)} keys were invalid and not added"
    
    await message.reply_text(response)

@app.on_message(filters.command("rmvfreekey") & filters.user(OWNER_ID))
async def remove_free_key_command(client, message: Message):
    free_services = get_free_services()
    
    if not free_services.get("free_keys"):
        await message.reply_text("❌ No free keys to remove")
        return
    
    update_free_services({
        "free_keys": [],
        "updated_at": datetime.now()
    })
    
    await message.reply_text("ϟ ALL FREE KEYS REMOVED SUCCESSFULLY")

@app.on_message(filters.command("freeservice") & filters.user(OWNER_ID))
async def free_service_command(client, message: Message):
    free_services = get_free_services()
    current_status = free_services.get("enabled", False)
    
    new_status = not current_status
    update_free_services({"enabled": new_status})
    
    status_text = "enabled" if new_status else "disabled"
    
    # Add free services info
    free_proxies_count = len(free_services.get("free_proxies", []))
    free_keys_count = len(free_services.get("free_keys", []))
    
    response = f"ϟ Free services {status_text}\n"
    response += f"• Free Proxies: {free_proxies_count}\n"
    response += f"• Free Keys: {free_keys_count}"
    
    await message.reply_text(response)

@app.on_message(filters.command("stats") & filters.user(OWNER_ID))
async def stats_command(client, message: Message):
    # Get bot stats
    bot_stats = get_bot_stats()
    
    # Get user stats
    total_users = users_collection.count_documents({})
    active_users = users_collection.count_documents({"accounts_generated": {"$gt": 0}})
    
    # Get free services stats
    free_services = get_free_services()
    
    stats_text = "<b>ϟ BOT STATISTICS</b>\n\n"
    stats_text += f"<b>Total Accounts Generated:</b> {bot_stats.get('total_accounts_generated', 0)}\n"
    stats_text += f"<b>Total Users:</b> {total_users}\n"
    stats_text += f"<b>Active Users:</b> {active_users}\n\n"
    
    stats_text += "<b>ϟ FREE SERVICES STATUS:</b>\n"
    stats_text += f"• Enabled: {'✔️' if free_services.get('enabled') else '❌'}\n"
    stats_text += f"• Free Proxies: {len(free_services.get('free_proxies', []))}\n"
    stats_text += f"• Free Keys: {len(free_services.get('free_keys', []))}\n\n"
    
    stats_text += "<b>ϟ TOP USERS (BY ACCOUNTS GENERATED):</b>\n"
    top_users = users_collection.find().sort("accounts_generated", -1).limit(5)
    for i, user in enumerate(top_users, 1):
        stats_text += f"{i}. User {user['user_id']}: {user.get('accounts_generated', 0)} accounts\n"
    
    stats_text += f"\n<b>Last Updated:</b> {bot_stats.get('last_updated', 'N/A')}"
    
    await message.reply_text(stats_text)

@app.on_message(filters.command("queue_stats") & filters.user(OWNER_ID))
async def queue_stats_command(client, message: Message):
    """Show global queue statistics for admin"""
    global_queue_size = global_queue.qsize()
    active_user_queues = len(user_queues)
    
    total_tasks = 0
    for user_queue in user_queues.values():
        total_tasks += user_queue.qsize()
    
    queue_stats_text = "<b>ϟ QUEUE STATISTICS</b>\n\n"
    queue_stats_text += f"<b>Global Queue Size:</b> {global_queue_size}\n"
    queue_stats_text += f"<b>Active User Queues:</b> {active_user_queues}\n"
    queue_stats_text += f"<b>Total Tasks in All Queues:</b> {total_tasks}\n\n"
    
    # Show top users with most queued tasks
    if user_queues:
        queue_stats_text += "<b>ϟ USERS WITH QUEUED TASKS:</b>\n"
        user_task_counts = []
        for user_id, user_queue in user_queues.items():
            task_count = user_queue.qsize()
            if task_count > 0:
                user_task_counts.append((user_id, task_count))
        
        # Sort by task count (descending)
        user_task_counts.sort(key=lambda x: x[1], reverse=True)
        
        for i, (user_id, task_count) in enumerate(user_task_counts[:10], 1):  # Top 10
            queue_stats_text += f"{i}. User {user_id}: {task_count} tasks\n"
    else:
        queue_stats_text += "<b>No active user queues</b>\n"
    
    await message.reply_text(queue_stats_text)

# Start the background task processor
async def main():
    """Main function to start the bot and background tasks"""
    # Start the background task processor
    asyncio.create_task(process_queued_tasks())
    
    # Start the bot
    await app.start()
    log.log("ϟ Webshare Bot Started with Queue System", "green")
    
    # Keep the bot running
    await asyncio.Event().wait()

if __name__ == "__main__":
    print("ϟ Webshare Bot Starting...")
    
    # Run the main function
    try:
        app.run(main())
    except KeyboardInterrupt:
        print("ϟ Bot stopped by user")
    except Exception as e:
        print(f"ϟ Bot error: {e}")
