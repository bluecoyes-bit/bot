from telethon.sync import TelegramClient
from telethon.errors.rpcerrorlist import PhoneNumberBannedError
from telethon.tl.functions.channels import JoinChannelRequest
import csv
import sys
import pickle
import random
import pyfiglet
import os
import pathlib
import datetime
from datetime import timedelta, timezone
import time
from colorama import init, Fore

init()

# UI Colors
lg, rs, r, w, cy, ye = Fore.LIGHTGREEN_EX, Fore.RESET, Fore.RED, Fore.WHITE, Fore.CYAN, Fore.YELLOW
info, error, success, INPUT, plus = lg+'('+w+'i'+lg+')'+rs, lg+'('+r+'!'+lg+')'+rs, w+'('+lg+'+'+w+')'+rs, lg+'('+cy+'~'+lg+')'+rs, lg+'('+w+'+'+lg+')'+rs
colors = [lg, w, r, cy]

def banner():
    f = pyfiglet.Figlet(font='slant')
    logo = f.renderText('Telegram')
    print(random.choice(colors) + logo + rs)
    print(f'  {r}Version: {w}1.4 {r}| Status: {lg}Fresh OTP (IST) Enabled{rs}\n')

def clr():
    os.system('cls' if os.name == 'nt' else 'clear')

# --- MAIN FLOW ---
clr()
banner()

# Loading accounts from vars.txt
BASE_DIR = pathlib.Path(__file__).parent.resolve()
VARS_FILE = BASE_DIR / 'vars.txt'
SESSION_DIR = BASE_DIR / 'sessions'

accounts = []
if VARS_FILE.exists():
    with open(VARS_FILE, 'rb') as f:
        while True:
            try:
                accounts.append(pickle.load(f))
            except EOFError:
                break
            except Exception:
                break  # don't loop forever on corrupt data

if not accounts:
    print(f"{error} {r}No accounts found in vars.txt!{rs}")
    sys.exit()

print(f"{lg}[1] {w}Start Group Adder")
print(f"{lg}[2] {w}Check OTP / Messages (Latest Only)")
print(f"{lg}[3] {w}Exit")
m_choice = input(f"\n{INPUT} Choose an option: ")

if m_choice == '2':
    print(f'\n{INPUT}{cy} Select an account to check OTP:{rs}')
    for i, acc in enumerate(accounts):
        print(f'{lg}({w}{i}{lg}) {acc[2]}')
    
    try:
        ind = int(input(f'\n{INPUT} Enter Index: '))
        selected = accounts[ind]
        api_id, api_hash, phone = int(selected[0]), str(selected[1]), str(selected[2])
        
        client = TelegramClient(str(SESSION_DIR / phone), api_id, api_hash)
        client.connect()
        
        if not client.is_user_authorized():
            print(f"\n{error} {r}Session is not authorized!{rs}")
        else:
            clr()
            banner()
            
            # --- CRITICAL FIX: Get Current Time in UTC ---
            # Hum sirf wo messages mangenge jo abhi ke baad aaye hon
            current_time_utc = datetime.datetime.now(timezone.utc)
            
            print(f"{info} {lg}Listening for NEW messages only...{rs}")
            print(f"{info} {cy}Waiting for OTP from Telegram Service (777000){rs}\n")
            
            last_msg_id = 0
            # 60 seconds tak loop chalega (30 iterations * 2s)
            for _ in range(30):
                # offset_date ensures only messages AFTER current_time_utc are fetched
                messages = client.get_messages(777000, limit=1, offset_date=current_time_utc, reverse=True)
                
                if messages:
                    msg = messages[0]
                    if msg.id != last_msg_id:
                        # IST Conversion (UTC + 5:30)
                        ist_date_obj = msg.date + timedelta(hours=5, minutes=30)
                        full_timestamp = ist_date_obj.strftime('%d-%m-%Y | %H:%M:%S')
                        
                        print(f"\n{lg}{'='*55}{rs}")
                        print(f"{ye}NEW MESSAGE RECEIVED (IST): {w}{full_timestamp}{rs}")
                        print(f"\n{w}{msg.message}{rs}")
                        print(f"{lg}{'='*55}{rs}")
                        
                        last_msg_id = msg.id
                        if "code" in msg.message.lower():
                            print(f"\n{success} {lg}Fresh OTP Detected Successfully!{rs}")
                            break
                
                print(f"{cy}.{rs}", end="", flush=True)
                time.sleep(2)
                
        client.disconnect()
        input(f"\n\n{plus} Press Enter to exit...")
        sys.exit()
    except Exception as e:
        print(f"\n{error} Error: {e}")
        sys.exit()

elif m_choice == '3':
    sys.exit()

# --- Rest of your original tsadder.py logic ---
print('\n' + info + lg + ' Continuing with Group Adder...' + rs)
# ... (Original joining/adding code)