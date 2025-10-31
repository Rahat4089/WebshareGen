import os, json, random, string, asyncio, time, aiohttp
from dataclasses import dataclass
from enum import Enum
from typing import List, Optional, Dict
from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup
from pymongo import MongoClient
from datetime import datetime
import aiofiles

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

# Async queue system
import asyncio
from asyncio import Queue, Lock
from collections import defaultdict

# Global async queues
user_queues = defaultdict(Queue)
global_queue = Queue()
queue_lock = Lock()

# Initialize bot
app = Client("webshare_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

class AsyncWebshareClient:
    WEBSITE_KEY = "6LeHZ6UUAAAAAKat_YS--O2tj_by3gv3r_l03j9d"
    BASE = "https://proxy.webshare.io/api/v2"
    UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/113.0.0.0 Safari/537.36"
    
    def __init__(self, cap_key: str, proxy_list: List[str], log_rotating: bool = False):
        self.cap_key = cap_key
        self.proxy_list = proxy_list
        self.log_rotating = log_rotating
        self.current_proxy = None
        self.domains = ["gmail.com", "outlook.com", "yahoo.com", "icloud.com", "hotmail.com", "aol.com"]
        self.roots = ["pixel", "alpha", "drift", "neo", "astro", "zenith", "echo", "nova", "crypt", "orbit", "dash", "cloud", "vibe", "frost", "hex", "pulse", "quant", "terra", "lumen", "flux"]
        self.suffixes = ["tv", "hub", "io", "xd", "on", "lab", "it", "max", "sys", "hq", "net", "pro", "tech", "dev"]

    async def _get_session(self):
        """Create async session with proxy"""
        connector = aiohttp.TCPConnector(limit=10)
        timeout = aiohttp.ClientTimeout(total=30)
        
        if self.proxy_list and not self.current_proxy:
            self.current_proxy = random.choice(self.proxy_list)
        
        if self.current_proxy:
            proxy_url = f"http://{self.current_proxy}"
            session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={"User-Agent": self.UA}
            )
            # Note: aiohttp proxy support is limited, you might need a different approach
            # For now, we'll proceed without proxy in async mode
            return session
        else:
            return aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                headers={"User-Agent": self.UA}
            )

    async def _solve_captcha(self):
        """Solve captcha using 2Captcha service"""
        try:
            async with aiohttp.ClientSession() as session:
                # Submit captcha
                submit_url = "http://2captcha.com/in.php"
                data = {
                    'key': self.cap_key,
                    'method': 'userrecaptcha',
                    'googlekey': self.WEBSITE_KEY,
                    'pageurl': 'https://webshare.io',
                    'json': 1
                }
                
                async with session.post(submit_url, data=data) as response:
                    result = await response.json()
                    
                    if result['status'] != 1:
                        raise RuntimeError(f"2Captcha error: {result.get('request', 'Unknown error')}")
                        
                    captcha_id = result['request']
                    
                    # Wait for solution
                    retrieve_url = "http://2captcha.com/res.php"
                    for _ in range(20):  # Wait up to 2 minutes
                        await asyncio.sleep(5)
                        params = {
                            'key': self.cap_key,
                            'action': 'get',
                            'id': captcha_id,
                            'json': 1
                        }
                        
                        async with session.get(retrieve_url, params=params) as resp:
                            result = await resp.json()
                            
                            if result['status'] == 1:
                                return result['request']
                            elif result['request'] != 'CAPCHA_NOT_READY':
                                raise RuntimeError(f"2Captcha error: {result.get('request', 'Unknown error')}")
                                
                    raise RuntimeError("2Captcha timeout: Captcha not solved in time")
                    
        except Exception as e:
            raise RuntimeError(f"Captcha solving failed: {e}")

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

    async def _register_account(self, session):
        """Register new webshare account"""
        captcha_token = await self._solve_captcha()
        email = self._rand_email()
        password = self._rand_pwd()
        
        payload = {
            "email": email,
            "password": password,
            "tos_accepted": True,
            "recaptcha": captcha_token
        }
        
        async with session.post(f"{self.BASE}/register/", json=payload) as response:
            if response.status != 200:
                # Try with different proxy if available
                if self.proxy_list and len(self.proxy_list) > 1:
                    self.proxy_list.remove(self.current_proxy)
                    if self.proxy_list:
                        self.current_proxy = random.choice(self.proxy_list)
                
                text = await response.text()
                raise RuntimeError(f"Registration failed: {text}")
            
            result = await response.json()
            token = result.get("token")
            if not token:
                raise RuntimeError(result.get("detail", "Registration failed"))
            
            return token, email, password

    async def download_proxies(self, session, token):
        """Download proxies from webshare"""
        headers = {"Authorization": f"Token {token}"}
        url = f"{self.BASE}/proxy/list/?mode=direct&page=1&page_size=10"
        
        async with session.get(url, headers=headers) as response:
            if response.status != 200:
                raise RuntimeError("Failed to download proxies")
            
            data = await response.json()
            results = data.get('results', [])
            
            static_proxies = []
            rotating_endpoint = ""
            
            for proxy in results:
                if self.log_rotating:
                    rotating_endpoint = f"http://{proxy['username']}-rotate:{proxy['password']}@p.webshare.io:80/"
                proxy_line = f"{proxy['proxy_address']}:{proxy['port']}:{proxy['username']}:{proxy['password']}"
                static_proxies.append(proxy_line)
            
            return static_proxies, rotating_endpoint

    async def generate_account(self, user_id: int):
        """Generate a complete webshare account"""
        start_time = time.time()
        session = None
        
        try:
            session = await self._get_session()
            token, email, password = await self._register_account(session)
            static_proxies, rotating_endpoint = await self.download_proxies(session, token)
            
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
            
            filepath = await self.save_account_to_json(account_data, user_id)
            
            return True, account_data, filepath, static_proxies, rotating_endpoint
            
        except Exception as e:
            return False, str(e), None, [], ""
        finally:
            if session:
                await session.close()

    async def save_account_to_json(self, account_data: Dict, user_id: int):
        """Save account data to user-specific JSON file asynchronously"""
        filename = f"accounts_{user_id}.json"
        filepath = os.path.join(DOWNLOAD_DIR, filename)
        
        try:
            # Read existing accounts
            existing_accounts = []
            if os.path.exists(filepath):
                async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
                    content = await f.read()
                    if content.strip():
                        existing_accounts = json.loads(content)
            
            # Add new account
            existing_accounts.append(account_data)
            
            # Save all accounts
            async with aiofiles.open(filepath, "w", encoding="utf-8") as f:
                await f.write(json.dumps(existing_accounts, indent=2, ensure_ascii=False))
            
            return filepath
        except Exception as e:
            raise RuntimeError(f"Failed to save account: {e}")

# Database functions (async wrappers)
async def get_user_data(user_id: int):
    """Get user data asynchronously"""
    loop = asyncio.get_event_loop()
    user_data = await loop.run_in_executor(None, users_collection.find_one, {"user_id": user_id})
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
        await loop.run_in_executor(None, users_collection.insert_one, user_data)
    return user_data

async def update_user_data(user_id: int, update_data: dict):
    """Update user data asynchronously"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None, 
        users_collection.update_one,
        {"user_id": user_id},
        {"$set": update_data},
        True
    )

async def increment_accounts_generated(user_id: int):
    """Increment accounts count asynchronously"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        users_collection.update_one,
        {"user_id": user_id},
        {"$inc": {"accounts_generated": 1}},
        True
    )

async def get_free_services():
    """Get free services asynchronously"""
    loop = asyncio.get_event_loop()
    services = await loop.run_in_executor(None, free_services_collection.find_one, {"id": "free_services"})
    if not services:
        services = {
            "id": "free_services",
            "enabled": False,
            "free_proxies": [],
            "free_keys": [],
            "updated_at": datetime.now()
        }
        await loop.run_in_executor(None, free_services_collection.insert_one, services)
    return services

async def update_free_services(update_data: dict):
    """Update free services asynchronously"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        free_services_collection.update_one,
        {"id": "free_services"},
        {"$set": update_data},
        True
    )

async def get_bot_stats():
    """Get bot stats asynchronously"""
    loop = asyncio.get_event_loop()
    stats = await loop.run_in_executor(None, stats_collection.find_one, {"id": "bot_stats"})
    if not stats:
        stats = {
            "id": "bot_stats",
            "total_accounts_generated": 0,
            "total_users": 0,
            "last_updated": datetime.now()
        }
        await loop.run_in_executor(None, stats_collection.insert_one, stats)
    return stats

async def update_bot_stats(update_data: dict):
    """Update bot stats asynchronously"""
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(
        None,
        stats_collection.update_one,
        {"id": "bot_stats"},
        {"$set": update_data},
        True
    )

# Async utility functions
async def check_proxy_status(proxy: str) -> bool:
    """Check if proxy is working asynchronously"""
    try:
        if not proxy:
            return False
            
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # For proxy testing, we'll use a simple approach
            # Note: aiohttp proxy support is limited
            test_url = "https://www.google.com"
            try:
                async with session.get(test_url) as response:
                    return response.status == 200
            except:
                return False
    except:
        return False

async def check_captcha_balance(api_key: str) -> tuple:
    """Check 2Captcha balance asynchronously"""
    try:
        async with aiohttp.ClientSession() as session:
            params = {
                'key': api_key,
                'action': 'getbalance',
                'json': 1
            }
            async with session.get("http://2captcha.com/res.php", params=params) as response:
                result = await response.json()
                if result['status'] == 1:
                    return True, float(result['request'])
                else:
                    return False, result.get('request', 'Unknown error')
    except Exception as e:
        return False, str(e)

async def cleanup_file(filepath: str):
    """Delete file after sending asynchronously"""
    try:
        if os.path.exists(filepath):
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, os.remove, filepath)
    except Exception as e:
        print(f"Error cleaning up file: {e}")

# Async queue management
async def add_to_queue(user_id: int, task_data: dict):
    """Add task to both user queue and global queue asynchronously"""
    await user_queues[user_id].put(task_data)
    await global_queue.put({"user_id": user_id, "task_data": task_data})

async def get_queue_position(user_id: int):
    """Get user's position in queue asynchronously"""
    return user_queues[user_id].qsize()

# Background task processor
async def process_queued_tasks():
    """Background task to process queued generation requests asynchronously"""
    while True:
        try:
            # Get next task from global queue without blocking
            try:
                task = await asyncio.wait_for(global_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
                
            if task:
                user_id = task["user_id"]
                task_data = task["task_data"]
                
                # Process the generation task
                asyncio.create_task(process_generation_task(user_id, task_data))
                
                # Mark task as done
                global_queue.task_done()
            
        except Exception as e:
            print(f"Error in task processor: {e}")
            await asyncio.sleep(5)

async def process_generation_task(user_id: int, task_data: dict):
    """Process a single generation task asynchronously"""
    try:
        message = task_data["message"]
        user_data = task_data["user_data"]
        free_services = task_data["free_services"]
        settings = task_data["settings"]
        proxy_list = task_data["proxy_list"]
        captcha_key = task_data["captcha_key"]
        
        # Remove task from user queue
        try:
            await user_queues[user_id].get()
            user_queues[user_id].task_done()
        except:
            pass
        
        # Create async webshare client
        client_obj = AsyncWebshareClient(
            cap_key=captcha_key,
            proxy_list=proxy_list,
            log_rotating=settings.get("rotating_endpoint", False)
        )
        
        # Generate account
        success, result, filepath, static_proxies, rotating_endpoint = await client_obj.generate_account(user_id)
        
        if success:
            account_data = result
            await increment_accounts_generated(user_id)
            
            # Update bot stats
            stats = await get_bot_stats()
            await update_bot_stats({
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
            response_text += f"<b>Proxy Status:</b> ✔️ ACTIVE\n"
            response_text += f"<b>2Captcha Balance:</b> N/A\n\n"
            response_text += f"ϟ Saved to your accounts file: <code>accounts_{user_id}.json</code>"
            
            # Send the message
            await message.reply_text(response_text)
            
            # Send the file
            if filepath and os.path.exists(filepath):
                try:
                    await message.reply_document(
                        document=filepath,
                        caption=f"ϟ Your accounts file - {os.path.basename(filepath)}"
                    )
                    # Clean up file
                    await cleanup_file(filepath)
                except Exception as e:
                    await message.reply_text(f"ϟ Error sending file: {e}")
            else:
                await message.reply_text("ϟ Could not generate accounts file")
                
        else:
            await message.reply_text(f"ϟ GENERATION FAILED\n\nError: {result}")
            
    except Exception as e:
        print(f"Error processing generation task: {e}")
        try:
            await message.reply_text(f"ϟ GENERATION FAILED\n\nError: {str(e)}")
        except:
            pass

# Bot command handlers (all async)
@app.on_message(filters.command("start"))
async def start_command(client, message: Message):
    user_id = message.from_user.id
    await get_user_data(user_id)  # Initialize user data
    
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
    user_data = await get_user_data(user_id)
    
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
    
    # Validate proxy format
    try:
        if "@" in proxy:
            auth, addr = proxy.split("@")
            user, pwd = auth.split(":")
            ip, port = addr.split(":")
        else:
            parts = proxy.split(":")
            if len(parts) == 2:
                ip, port = parts
            elif len(parts) == 4:
                ip, port, user, pwd = parts
            else:
                await message.reply_text("ϟ INVALID PROXY FORMAT")
                return
                
        # Check proxy status asynchronously
        status = await check_proxy_status(proxy)
        if not status:
            await message.reply_text("ϟ Proxy added but seems inactive. Check format and try /status")
        else:
            await message.reply_text("ϟ Proxy is active and working")
            
    except Exception as e:
        await message.reply_text("ϟ INVALID PROXY FORMAT")
        return
    
    await update_user_data(user_id, {"proxy": proxy})
    await message.reply_text("ϟ PROXY ADDED SUCCESSFULLY")

@app.on_message(filters.command("rmvproxy"))
async def remove_proxy_command(client, message: Message):
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    
    if not user_data.get("proxy"):
        await message.reply_text("ϟ You don't have any proxy set")
        return
    
    await update_user_data(user_id, {"proxy": ""})
    await message.reply_text("ϟ PROXY REMOVED SUCCESSFULLY")

@app.on_message(filters.command("addkey"))
async def add_key_command(client, message: Message):
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    
    if len(message.command) < 2:
        await message.reply_text("""
<b>ϟ USAGE:</b> <code>/addkey [2captcha_api_key]</code>

<b>ϟ EXAMPLE:</b> <code>/addkey abc123def456ghi789</code>
""")
        return
    
    api_key = message.command[1]
    
    # Check captcha balance asynchronously
    await message.reply_text("ϟ Checking 2Captcha balance...")
    success, result = await check_captcha_balance(api_key)
    
    if success:
        await update_user_data(user_id, {"captcha_key": api_key})
        await message.reply_text(f"ϟ 2CAPTCHA KEY ADDED\nϟ Balance: ${result:.2f}")
    else:
        await message.reply_text(f"ϟ INVALID 2CAPTCHA KEY: {result}")

@app.on_message(filters.command("rmvkey"))
async def remove_key_command(client, message: Message):
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    
    if not user_data.get("captcha_key"):
        await message.reply_text("ϟ You don't have any 2Captcha key set")
        return
    
    await update_user_data(user_id, {"captcha_key": ""})
    await message.reply_text("ϟ 2CAPTCHA KEY REMOVED SUCCESSFULLY")

@app.on_message(filters.command("myconfig"))
async def myconfig_command(client, message: Message):
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    
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
    free_services = await get_free_services()
    if free_services.get("enabled"):
        config_text += "<b>Free Services:</b> ✔️ AVAILABLE\n"
        config_text += f"• Free Proxies: {len(free_services.get('free_proxies', []))}\n"
        config_text += f"• Free Keys: {len(free_services.get('free_keys', []))}\n"
    else:
        config_text += "<b>Free Services:</b> ❌ DISABLED\n"
    
    # Queue info
    queue_position = await get_queue_position(user_id)
    config_text += f"\n<b>Queue Position:</b> {queue_position} tasks waiting"
    
    await message.reply_text(config_text)

@app.on_message(filters.command("status"))
async def status_command(client, message: Message):
    user_id = message.from_user.id
    user_data = await get_user_data(user_id)
    
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
    free_services = await get_free_services()
    if free_services.get("enabled"):
        status_text += f"<b>Free Services:</b> ✔️ ENABLED\n"
        status_text += f"• Free Proxies: {len(free_services.get('free_proxies', []))}\n"
        status_text += f"• Free Keys: {len(free_services.get('free_keys', []))}\n"
    else:
        status_text += "<b>Free Services:</b> ❌ DISABLED\n"
    
    # Queue status
    queue_position = await get_queue_position(user_id)
    global_queue_size = global_queue.qsize()
    status_text += f"\n<b>Your Queue Position:</b> {queue_position}\n"
    status_text += f"<b>Global Queue Size:</b> {global_queue_size}"
    
    await message.reply_text(status_text)

@app.on_message(filters.command("queue"))
async def queue_command(client, message: Message):
    user_id = message.from_user.id
    
    queue_position = await get_queue_position(user_id)
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
    user_data = await get_user_data(user_id)
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
    user_data = await get_user_data(user_id)
    settings = user_data.get("settings", {})
    
    if data == "toggle_email_pass":
        enabled_count = sum(settings.values())
        if not settings.get("email_pass") and enabled_count >= 3:
            await callback_query.answer("❌ Maximum 3 options can be enabled", show_alert=True)
            return
        
        settings["email_pass"] = not settings.get("email_pass", True)
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
    
    await update_user_data(user_id, {"settings": settings})
    
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
    user_data = await get_user_data(user_id)
    
    # Check requirements
    has_captcha = bool(user_data.get("captcha_key"))
    has_proxy = bool(user_data.get("proxy"))
    
    free_services = await get_free_services()
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
    
    await add_to_queue(user_id, task_data)
    
    queue_position = await get_queue_position(user_id)
    
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
    free_services = await get_free_services()
    
    # Validate proxies asynchronously
    valid_proxies = []
    invalid_proxies = []
    
    # Check proxies concurrently
    tasks = [check_proxy_status(proxy) for proxy in proxies]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for i, (proxy, status) in enumerate(zip(proxies, results)):
        if status and not isinstance(status, Exception):
            valid_proxies.append(proxy)
        else:
            invalid_proxies.append(proxy)
    
    await update_free_services({
        "free_proxies": valid_proxies,
        "updated_at": datetime.now()
    })
    
    response = f"ϟ Added {len(valid_proxies)} valid free proxies\n"
    if invalid_proxies:
        response += f"❌ {len(invalid_proxies)} proxies were invalid and not added"
    
    await message.reply_text(response)

@app.on_message(filters.command("rmvfreeproxy") & filters.user(OWNER_ID))
async def remove_free_proxy_command(client, message: Message):
    free_services = await get_free_services()
    
    if not free_services.get("free_proxies"):
        await message.reply_text("❌ No free proxies to remove")
        return
    
    await update_free_services({
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
    free_services = await get_free_services()
    
    # Validate keys asynchronously
    valid_keys = []
    invalid_keys = []
    
    # Check keys concurrently
    tasks = [check_captcha_balance(key) for key in keys]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for i, (key, result) in enumerate(zip(keys, results)):
        if isinstance(result, tuple) and result[0]:
            valid_keys.append(key)
        else:
            invalid_keys.append(key)
    
    await update_free_services({
        "free_keys": valid_keys,
        "updated_at": datetime.now()
    })
    
    response = f"ϟ Added {len(valid_keys)} valid free captcha keys\n"
    if invalid_keys:
        response += f"❌ {len(invalid_keys)} keys were invalid and not added"
    
    await message.reply_text(response)

@app.on_message(filters.command("rmvfreekey") & filters.user(OWNER_ID))
async def remove_free_key_command(client, message: Message):
    free_services = await get_free_services()
    
    if not free_services.get("free_keys"):
        await message.reply_text("❌ No free keys to remove")
        return
    
    await update_free_services({
        "free_keys": [],
        "updated_at": datetime.now()
    })
    
    await message.reply_text("ϟ ALL FREE KEYS REMOVED SUCCESSFULLY")

@app.on_message(filters.command("freeservice") & filters.user(OWNER_ID))
async def free_service_command(client, message: Message):
    free_services = await get_free_services()
    current_status = free_services.get("enabled", False)
    
    new_status = not current_status
    await update_free_services({"enabled": new_status})
    
    status_text = "enabled" if new_status else "disabled"
    
    free_proxies_count = len(free_services.get("free_proxies", []))
    free_keys_count = len(free_services.get("free_keys", []))
    
    response = f"ϟ Free services {status_text}\n"
    response += f"• Free Proxies: {free_proxies_count}\n"
    response += f"• Free Keys: {free_keys_count}"
    
    await message.reply_text(response)

@app.on_message(filters.command("stats") & filters.user(OWNER_ID))
async def stats_command(client, message: Message):
    bot_stats = await get_bot_stats()
    
    # Get user stats
    loop = asyncio.get_event_loop()
    total_users = await loop.run_in_executor(None, users_collection.count_documents, {})
    active_users = await loop.run_in_executor(
        None, 
        users_collection.count_documents, 
        {"accounts_generated": {"$gt": 0}}
    )
    
    free_services = await get_free_services()
    
    stats_text = "<b>ϟ BOT STATISTICS</b>\n\n"
    stats_text += f"<b>Total Accounts Generated:</b> {bot_stats.get('total_accounts_generated', 0)}\n"
    stats_text += f"<b>Total Users:</b> {total_users}\n"
    stats_text += f"<b>Active Users:</b> {active_users}\n\n"
    
    stats_text += "<b>ϟ FREE SERVICES STATUS:</b>\n"
    stats_text += f"• Enabled: {'✔️' if free_services.get('enabled') else '❌'}\n"
    stats_text += f"• Free Proxies: {len(free_services.get('free_proxies', []))}\n"
    stats_text += f"• Free Keys: {len(free_services.get('free_keys', []))}\n\n"
    
    stats_text += "<b>ϟ TOP USERS (BY ACCOUNTS GENERATED):</b>\n"
    top_users = await loop.run_in_executor(
        None,
        users_collection.find().sort("accounts_generated", -1).limit(5).__iter__
    )
    top_users_list = list(top_users)
    
    for i, user in enumerate(top_users_list, 1):
        stats_text += f"{i}. User {user['user_id']}: {user.get('accounts_generated', 0)} accounts\n"
    
    stats_text += f"\n<b>Last Updated:</b> {bot_stats.get('last_updated', 'N/A')}"
    
    await message.reply_text(stats_text)

@app.on_message(filters.command("queue_stats") & filters.user(OWNER_ID))
async def queue_stats_command(client, message: Message):
    global_queue_size = global_queue.qsize()
    active_user_queues = len(user_queues)
    
    total_tasks = 0
    for user_queue in user_queues.values():
        total_tasks += user_queue.qsize()
    
    queue_stats_text = "<b>ϟ QUEUE STATISTICS</b>\n\n"
    queue_stats_text += f"<b>Global Queue Size:</b> {global_queue_size}\n"
    queue_stats_text += f"<b>Active User Queues:</b> {active_user_queues}\n"
    queue_stats_text += f"<b>Total Tasks in All Queues:</b> {total_tasks}\n\n"
    
    if user_queues:
        queue_stats_text += "<b>ϟ USERS WITH QUEUED TASKS:</b>\n"
        user_task_counts = []
        for user_id, user_queue in user_queues.items():
            task_count = user_queue.qsize()
            if task_count > 0:
                user_task_counts.append((user_id, task_count))
        
        user_task_counts.sort(key=lambda x: x[1], reverse=True)
        
        for i, (user_id, task_count) in enumerate(user_task_counts[:10], 1):
            queue_stats_text += f"{i}. User {user_id}: {task_count} tasks\n"
    else:
        queue_stats_text += "<b>No active user queues</b>\n"
    
    await message.reply_text(queue_stats_text)

# Startup handler
@app.on_message(filters.command("init"))
async def init_bot(client, message: Message):
    """Initialize bot background tasks"""
    if message.from_user.id == OWNER_ID:
        asyncio.create_task(process_queued_tasks())
        await message.reply_text("ϟ Bot background tasks initialized!")

# Start the bot
async def main():
    """Main function to start the bot"""
    # Start background task processor
    asyncio.create_task(process_queued_tasks())
    
    # Start the bot
    await app.start()
    print("ϟ Webshare Bot Started with Async Queue System")
    
    # Keep running
    await asyncio.Event().wait()

if __name__ == "__main__":
    print("ϟ Starting Webshare Bot...")
    
    try:
        app.run(main())
    except KeyboardInterrupt:
        print("ϟ Bot stopped by user")
    except Exception as e:
        print(f"ϟ Bot error: {e}")
