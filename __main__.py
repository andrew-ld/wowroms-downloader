# Copyright (C) 2019 andrew-ld <https://github.com/andrew-ld>
#
# This file is part of wowroms-downloader.
#
# wowroms-downloader is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# wowroms-downloader is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with wowroms-downloader. If not, see <http://www.gnu.org/licenses/>.

import gevent.monkey
gevent.monkey.patch_all()

import uvloop
uvloop.install()

import bs4
import os.path
import asyncio
import aiohttp
import itertools
import werkzeug.utils
import hashlib
import time
import ssl


ROOT_URL = ""; raise ValueError("EDIT ROOT_URL")
MAIN_PAGE = ROOT_URL + "/en/all-roms/list/consoles"
DL_API = ROOT_URL + "/en/emulators-roms/download/1/1"
DL_DIR = "roms/"


async def gen_dl_url(client):
    k = time.time()
    k = f"{k}{(13 - len(str(k))) * '0'}"
    t = hashlib.md5(k.encode("ascii")).hexdigest()

    url = f"{DL_API}?k={k}&t={t}"
    res = await (await client.get(url)).json()

    return res["link"]


async def bound_get_roms(url, client, sem):
    async with sem:
        return await get_roms(url, client)


async def bound_download_rom(url, client, sem):
    async with sem:
        await download_rom(url, client)


async def crawl_page(url, client):
    print(f"!parsing {url}")

    page = (await (await client.get(url)).read())\
        .decode("utf8", "ignore")
    return bs4.BeautifulSoup(page, "html.parser")


async def number_of_pages(url, client):
    page = await crawl_page(url, client)

    for e in page.find_all("a"):
        if not e.has_attr("class"):
            continue

        if "alphabetP" in e["class"]:
            if e.text == ">>":
                return int(e["href"].split("=")[-1])

    return 1


async def get_roms_from_page(url, client):
    roms = []
    page = await crawl_page(url, client)

    for e in page.find_all("a"):
        if not e.has_attr("class"):
            continue

        if "title-5" in e["class"]:
            roms.append(ROOT_URL + e["href"])

    return roms


async def get_roms(url, client):
    tasks = []
    pages = await number_of_pages(url, client)

    for i in range(1, pages + 1):
        tasks.append(get_roms_from_page(f"{url}?page={i}", client))

    roms = await asyncio.gather(*tasks)
    return [*itertools.chain(*roms)]


async def download_rom(url, client):
    surl = url.split("/")
    durl = "/".join(surl[0:-2]) + "/download-" + "/".join(surl[-2:])
    page = await crawl_page(durl, client)
    data = {}

    for e in page.find_all("input"):
        if not e.has_attr("type"):
            continue

        if e["type"] != "hidden":
            continue

        data[e["name"]] = e["value"]

    name = werkzeug.utils.secure_filename(data["file"])
    dl_url = await gen_dl_url(client)
    rom = await client.post(dl_url, data=data)

    with open(f"{DL_DIR}{name}", "ab") as file:
        print(f"!downloading {name}")

        async for data in rom.content.iter_any():
            file.write(data)


async def main(loop):
    conn = aiohttp.TCPConnector(
        limit=10, loop=loop,
        enable_cleanup_closed=True,
        force_close=True,
        ssl=ssl.SSLContext(5)
    )

    async with aiohttp.ClientSession(connector=conn) as client:
        page = await crawl_page(MAIN_PAGE, client)
        consoles = []

        for e in page.find_all("a"):
            if not e.has_attr("class"):
                continue

            if "title-5" in e["class"]:
                consoles.append(ROOT_URL + e["href"])

        sem = asyncio.Semaphore(3)
        tasks = []

        for cons in consoles:
            tasks.append(bound_get_roms(cons, client, sem))

        roms = await asyncio.gather(*tasks)
        roms = [*itertools.chain(*roms)]
        tasks = []

        for rom in roms:
            tasks.append(bound_download_rom(rom, client, sem))

        tasks = map(asyncio.ensure_future, tasks)
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    if not os.path.isdir(DL_DIR):
        os.mkdir(DL_DIR)

    _loop = asyncio.get_event_loop()
    _future = asyncio.ensure_future(main(_loop))
    _loop.run_until_complete(_future)
