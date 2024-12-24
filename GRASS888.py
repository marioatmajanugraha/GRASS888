import asyncio
import random
import ssl
import json
import time
import uuid
import requests
from loguru import logger
from websockets_proxy import Proxy, proxy_connect
from fake_useragent import UserAgent
import os
from colorama import Fore, Style
import websockets

successful_proxies = []
failed_proxies = []
error_count = 0  # Tambahkan penghitung error

def clean_proxy(proxy):
    """
    Membersihkan proxy agar tidak memiliki skema duplikat.
    """
    if proxy.startswith(("http://", "https://", "socks4://", "socks5://")):
        return proxy
    return f"http://{proxy}"  # Default ke http:// jika tidak ada skema

async def connect_to_wss(socks5_proxy, user_id):
    global successful_proxies, failed_proxies, error_count  # Declare global here
    user_agent = UserAgent(os=['windows', 'macos', 'linux'], browsers='chrome')
    random_user_agent = user_agent.random
    device_id = str(uuid.uuid3(uuid.NAMESPACE_DNS, socks5_proxy))

    while True:
        try:
            await asyncio.sleep(random.randint(1, 10) / 10)
            custom_headers = {
                "User-Agent": random_user_agent,
            }
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

            urilist = ["wss://proxy2.wynd.network:4444/", "wss://proxy2.wynd.network:4650/"]
            uri = random.choice(urilist)
            server_hostname = "proxy2.wynd.network"
            proxy = Proxy.from_url(clean_proxy(socks5_proxy))

            async with proxy_connect(uri, proxy=proxy, ssl=ssl_context, server_hostname=server_hostname,
                                     extra_headers=custom_headers) as websocket:
                logger.info(Fore.GREEN + f"Proxy {clean_proxy(socks5_proxy)} tersambung ke WSS" + Style.RESET_ALL)

                if socks5_proxy not in successful_proxies:
                    successful_proxies.append(socks5_proxy)

                async def send_ping():
                    while True:
                        try:
                            send_message = json.dumps(
                                {"id": str(uuid.uuid4()), "version": "1.0.0", "action": "PING", "data": {}})
                            await websocket.send(send_message)
                            await asyncio.sleep(5)
                        except websockets.exceptions.ConnectionClosedError:
                            logger.error(Fore.RED + "Kesalahan koneksi saat mengirim PING" + Style.RESET_ALL)
                            break
                        except Exception as e:
                            logger.error(Fore.RED + f"Kesalahan saat mengirim PING: {e}" + Style.RESET_ALL)
                            break

                asyncio.create_task(send_ping())

                while True:
                    try:
                        response = await websocket.recv()
                        message = json.loads(response)
                        logger.info(Fore.CYAN + f"Pesan diterima: {message}" + Style.RESET_ALL)
                        if message.get("action") == "AUTH":
                            auth_response = {
                                "id": message["id"],
                                "origin_action": "AUTH",
                                "result": {
                                    "browser_id": device_id,
                                    "user_id": user_id,
                                    "user_agent": custom_headers['User-Agent'],
                                    "timestamp": int(time.time()),
                                    "device_type": "desktop",
                                    "version": "4.29.0",
                                }
                            }
                            await websocket.send(json.dumps(auth_response))
                        elif message.get("action") == "PONG":
                            pong_response = {"id": message["id"], "origin_action": "PONG"}
                            await websocket.send(json.dumps(pong_response))
                    except websockets.exceptions.ConnectionClosedError:
                        logger.error(Fore.RED + f"Proxy {clean_proxy(socks5_proxy)} mengalami kesalahan koneksi" + Style.RESET_ALL)
                        break
                    except Exception as e:
                        logger.error(Fore.RED + f"Kesalahan saat menerima pesan: {e}" + Style.RESET_ALL)
                        break
        except Exception as e:
            logger.error(Fore.RED + f"Kesalahan saat mencoba terhubung: {e}, Proxy: {clean_proxy(socks5_proxy)}" + Style.RESET_ALL)
            if socks5_proxy not in failed_proxies:
                failed_proxies.append(socks5_proxy)
            error_count += 1  # Increment the error count
            if error_count >= 10:
                logger.error(Fore.YELLOW + "Jumlah proxy error mencapai 10. Mengambil proxy baru..." + Style.RESET_ALL)
                return "restart"  # Mengembalikan sinyal untuk restart
            break

async def fetch_proxies():
    url = "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            raw_proxies = response.text.splitlines()
            proxies = [clean_proxy(proxy) for proxy in raw_proxies]
            logger.info(Fore.YELLOW + "Daftar proxy baru diambil dan dibersihkan" + Style.RESET_ALL)
            return proxies[:50]  # Batasi hingga 50 proxy
        else:
            logger.error(Fore.RED + "Gagal mengambil proxy gratis" + Style.RESET_ALL)
    except requests.RequestException as e:
        logger.error(Fore.RED + f"Kesalahan saat mengambil proxy: {e}" + Style.RESET_ALL)
    return []

async def main():
    global successful_proxies, failed_proxies, error_count  # Declare global here

    try:
        with open('userid.txt', 'r') as file:
            user_ids = file.read().splitlines()
    except FileNotFoundError:
        logger.error(Fore.RED + "File userid.txt tidak ditemukan" + Style.RESET_ALL)
        return

    while True:
        proxies = await fetch_proxies()

        if not proxies:
            logger.error(Fore.RED + "Tidak ada proxy yang tersedia" + Style.RESET_ALL)
            return

        # Gabungkan proxy yang berhasil
        proxies = list(set(proxies) | set(successful_proxies))  # Gabungkan dengan proxy yang berhasil

        tasks = []
        for user_id in user_ids:
            for proxy in proxies:
                if proxy not in failed_proxies:
                    tasks.append(asyncio.ensure_future(connect_to_wss(proxy, user_id)))

        try:
            results = await asyncio.gather(*tasks)  # Jalankan semua task
            if "restart" in results:  # Cek jika restart diperlukan
                logger.info(Fore.YELLOW + "Melakukan restart dan mengambil proxy baru..." + Style.RESET_ALL)
                successful_proxies = []  # Reset proxy berhasil
                failed_proxies = []  # Reset proxy gagal
                error_count = 0  # Reset penghitung error
        except Exception as e:
            logger.error(Fore.RED + f"Kesalahan saat menjalankan task: {e}" + Style.RESET_ALL)

if __name__ == '__main__':
    asyncio.run(main())
