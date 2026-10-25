#!/usr/bin/env python3
"""
TechPowerUp NVIDIA VBIOS Database Downloader
============================================
Crawls and downloads all NVIDIA VBIOS files from TechPowerUp VGA Bios Collection:
  https://www.techpowerup.com/vgabios/?architecture=NVIDIA&page=1

Features:
  - Uses Camoufox (anti-detect headless browser) to bypass Cloudflare/bot challenges.
  - Extracts hardware IDs (Device ID, Subsystem ID), manufacturer, model, memory type/size,
    clocks, BIOS build date, MD5/SHA1 hashes, and BIOS internals.
  - Stores each ROM with hardware IDs in the filename and a matching .json metadata sidecar.
  - Maintains an index.jsonl database for easy grep/querying.
  - Fully resumable: checks existing ROMs and skips them.
  - Optional filtering by Device ID, vendor, or model.

Target storage directory:
  /home/twilight/Projects/nouveau-dkms/vbios_database/ (ignored by git)
"""

import sys
# Prevent local directory from shadowing installed camoufox package
sys.path = [p for p in sys.path if p not in ('/home/twilight', '')]

import argparse
import asyncio
import json
import os
import re
import signal
from pathlib import Path
from typing import Dict, List, Optional, Any

from bs4 import BeautifulSoup
from camoufox.async_api import AsyncCamoufox

BASE_URL = "https://www.techpowerup.com"
DEFAULT_OUTPUT_DIR = Path("/home/twilight/Projects/nouveau-dkms/vbios_database")

def sanitize_name(text: str) -> str:
    """Sanitize strings for filesystem names."""
    if not text:
        return "unknown"
    s = re.sub(r'[^\w\-.]+', '_', text.strip())
    s = re.sub(r'_+', '_', s)
    return s.strip('_')

def normalize_hex_id(raw: str) -> str:
    """Normalize hex IDs like '10DE 0422' or '0x10DE 0x0422' to '10de_0422'."""
    if not raw:
        return "unknown"
    tokens = re.findall(r'[0-9a-fA-F]{4}', raw)
    if tokens:
        return "_".join(t.lower() for t in tokens)
    return sanitize_name(raw).lower()

class VBIOSDownloader:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.output_dir = Path(args.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.output_dir / "index.jsonl"
        self.downloaded_ids = self._load_existing_ids()
        self.stop_requested = False
        self.stats = {"downloaded": 0, "skipped": 0, "failed": 0, "pages": 0}

    def _load_existing_ids(self) -> set:
        """Scan existing files to identify previously downloaded VBIOS IDs."""
        existing = set()
        for f in self.output_dir.glob("*.rom"):
            # Filename ends with _<vbios_id>.rom
            m = re.search(r'_(\d+)\.rom$', f.name)
            if m:
                existing.add(m.group(1))
        # Also check index.jsonl if present
        if self.index_file.exists():
            try:
                with open(self.index_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            data = json.loads(line)
                            if "vbios_id" in data:
                                existing.add(str(data["vbios_id"]))
            except Exception as e:
                print(f"[!] Warning reading index.jsonl: {e}")
        return existing

    def _record_index(self, metadata: Dict[str, Any]):
        """Append metadata record to index.jsonl."""
        try:
            with open(self.index_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(metadata, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[!] Warning writing to index.jsonl: {e}")

    async def get_page_count(self, page) -> int:
        """Extract total page count from pagination on page 1."""
        soup = BeautifulSoup(await page.content(), "html.parser")
        max_page = 1
        for a in soup.find_all("a", href=lambda h: h and "page=" in h):
            m = re.search(r'page=(\d+)', a["href"])
            if m:
                num = int(m.group(1))
                if num > max_page:
                    max_page = num
        return max_page

    async def parse_listing_page(self, page, page_num: int) -> List[Dict[str, str]]:
        """Parse list of VBIOS items from a listing page."""
        url = f"{BASE_URL}/vgabios/?architecture={self.args.architecture}&page={page_num}"
        print(f"[*] Fetching listing page {page_num}: {url}")
        
        for attempt in range(self.args.retries):
            try:
                await page.goto(url, wait_until="networkidle", timeout=30000)
                await page.wait_for_selector("table.bioslist", timeout=15000)
                break
            except Exception as e:
                print(f"  [!] Attempt {attempt+1}/{self.args.retries} failed for listing page {page_num}: {e}")
                if attempt + 1 == self.args.retries:
                    return []
                await asyncio.sleep(self.args.delay * 2)

        soup = BeautifulSoup(await page.content(), "html.parser")
        table = soup.find("table", class_="bioslist")
        if not table:
            print(f"  [-] No bioslist table found on page {page_num}")
            return []

        items = []
        for tr in table.find_all("tr")[1:]:  # skip header
            cols = tr.find_all("td")
            if not cols:
                continue
            
            # Find detail link
            detail_link = None
            for a in tr.find_all("a"):
                href = a.get("href", "")
                if "/vgabios/" in href and not href.endswith(".rom"):
                    detail_link = href
                    break
            
            if not detail_link:
                continue

            m = re.search(r'/vgabios/(\d+)', detail_link)
            vbios_id = m.group(1) if m else None
            if not vbios_id:
                continue

            # Basic listing column data
            mfg = cols[0].get_text(strip=True) if len(cols) > 0 else ""
            model = cols[1].get_text(strip=True) if len(cols) > 1 else ""
            date_compiled = cols[2].get_text(strip=True) if len(cols) > 2 else ""
            version = cols[3].get_text(strip=True) if len(cols) > 3 else ""
            bus = cols[4].get_text(strip=True) if len(cols) > 5 else ""

            items.append({
                "vbios_id": vbios_id,
                "detail_url": BASE_URL + detail_link if detail_link.startswith("/") else detail_link,
                "listing_manufacturer": mfg,
                "listing_model": model,
                "listing_version": version,
                "listing_date": date_compiled,
                "listing_bus": bus,
            })

        print(f"  [+] Page {page_num}: found {len(items)} VBIOS entries")
        return items

    async def process_detail_page(self, context, item: Dict[str, str]):
        """Scrape detail page, extract hardware IDs, and download the .rom file."""
        vbios_id = item["vbios_id"]
        detail_url = item["detail_url"]

        if vbios_id in self.downloaded_ids:
            # print(f"  [~] VBIOS ID {vbios_id} already exists, skipping.")
            self.stats["skipped"] += 1
            return

        page = await context.new_page()
        try:
            for attempt in range(self.args.retries):
                try:
                    await page.goto(detail_url, wait_until="networkidle", timeout=30000)
                    break
                except Exception as e:
                    if attempt + 1 == self.args.retries:
                        print(f"  [!] Failed to load detail page {detail_url}: {e}")
                        self.stats["failed"] += 1
                        return
                    await asyncio.sleep(self.args.delay)

            soup = BeautifulSoup(await page.content(), "html.parser")
            
            # Extract key-value pairs from tables
            data: Dict[str, Any] = {
                "vbios_id": vbios_id,
                "detail_url": detail_url,
                "listing_manufacturer": item.get("listing_manufacturer", ""),
                "listing_model": item.get("listing_model", ""),
                "listing_version": item.get("listing_version", ""),
            }

            for tr in soup.find_all("tr"):
                th = tr.find("th")
                td = tr.find("td")
                if th and td:
                    key = th.get_text(strip=True).rstrip(":").replace(" ", "_").lower()
                    val = td.get_text(strip=True)
                    data[key] = val

            # Check for BIOS internals table
            internals_table = soup.find("table", class_="biosinternals")
            if internals_table:
                data["bios_internals_raw"] = internals_table.get_text("\n", strip=True)

            # Hardware IDs
            mfg = data.get("manufacturer", item.get("listing_manufacturer", "Unknown"))
            model = data.get("model", item.get("listing_model", "Unknown"))
            dev_id_raw = data.get("device_id", "")
            subsys_id_raw = data.get("subsystem_id", "")

            dev_id_norm = normalize_hex_id(dev_id_raw)
            subsys_id_norm = normalize_hex_id(subsys_id_raw)

            # Apply filters if requested
            if self.args.filter_vendor and self.args.filter_vendor.lower() not in mfg.lower():
                return
            if self.args.filter_model and self.args.filter_model.lower() not in model.lower():
                return
            if self.args.filter_devid and self.args.filter_devid.lower() not in dev_id_norm:
                return

            # Construct safe filename: <mfg>_<model>_<devid>_<subsys>_<vbios_id>.rom
            safe_mfg = sanitize_name(mfg)
            safe_model = sanitize_name(model)
            base_filename = f"{safe_mfg}_{safe_model}_{dev_id_norm}_{subsys_id_norm}_{vbios_id}"
            rom_path = self.output_dir / f"{base_filename}.rom"
            json_path = self.output_dir / f"{base_filename}.json"

            # Check if Download Now button exists
            download_btn = await page.query_selector("text='Download Now'")
            if not download_btn:
                # Try finding link with .rom
                download_btn = await page.query_selector("a[href$='.rom']")
            
            if not download_btn:
                print(f"  [!] No download link found on {detail_url}")
                self.stats["failed"] += 1
                return

            # Download ROM
            async with page.expect_download(timeout=20000) as dl_info:
                await download_btn.click()
            download = await dl_info.value
            
            # Temporary download path
            temp_path = self.output_dir / f".temp_{vbios_id}.rom"
            await download.save_as(str(temp_path))

            # Verify ROM
            size = temp_path.stat().st_size
            if size == 0:
                print(f"  [!] Downloaded file {temp_path.name} is empty, skipping.")
                temp_path.unlink(missing_ok=True)
                self.stats["failed"] += 1
                return

            with open(temp_path, "rb") as f:
                header = f.read(2)
            if header != b"\x55\xaa":
                print(f"  [!] Warning: VBIOS {vbios_id} magic is {header.hex()} (expected 55aa).")

            # Finalize ROM file
            temp_path.rename(rom_path)

            # Save JSON sidecar
            data["rom_filename"] = rom_path.name
            data["rom_size_bytes"] = size
            data["device_id_normalized"] = dev_id_norm
            data["subsystem_id_normalized"] = subsys_id_norm

            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)

            self._record_index(data)
            self.downloaded_ids.add(vbios_id)
            self.stats["downloaded"] += 1

            print(f"  [✓] [{self.stats['downloaded']}] Downloaded: {rom_path.name} ({size} bytes) [Dev: {dev_id_norm}, Subsys: {subsys_id_norm}]")

        except Exception as e:
            print(f"  [!] Error processing {detail_url}: {e}")
            self.stats["failed"] += 1
        finally:
            await page.close()
            await asyncio.sleep(self.args.delay)

    async def run(self):
        """Main crawl and download loop."""
        print(f"===========================================================")
        print(f" TechPowerUp NVIDIA VBIOS Database Downloader")
        print(f" Architecture: {self.args.architecture}")
        print(f" Output dir:   {self.output_dir.resolve()}")
        print(f" Existing ROMs: {len(self.downloaded_ids)}")
        print(f"===========================================================")

        async with AsyncCamoufox(headless=self.args.headless) as browser:
            context = await browser.new_context(ignore_https_errors=True)
            nav_page = await context.new_page()

            # Determine end page if not specified
            end_page = self.args.end_page
            if end_page is None:
                print("[*] Detecting total number of pages...")
                url = f"{BASE_URL}/vgabios/?architecture={self.args.architecture}&page=1"
                try:
                    await nav_page.goto(url, wait_until="networkidle", timeout=30000)
                    await nav_page.wait_for_selector("table.bioslist", timeout=15000)
                    end_page = await self.get_page_count(nav_page)
                    print(f"[*] Detected {end_page} total listing pages.")
                except Exception as e:
                    print(f"[!] Could not detect page count ({e}), defaulting to 186.")
                    end_page = 186

            semaphore = asyncio.Semaphore(self.args.concurrency)

            async def bounded_worker(item):
                async with semaphore:
                    if self.stop_requested:
                        return
                    if self.args.limit and self.stats["downloaded"] >= self.args.limit:
                        return
                    await self.process_detail_page(context, item)

            for page_num in range(self.args.start_page, end_page + 1):
                if self.stop_requested:
                    print("\n[!] Stop requested by user.")
                    break
                if self.args.limit and self.stats["downloaded"] >= self.args.limit:
                    print(f"\n[+] Reached requested limit of {self.args.limit} ROMs.")
                    break

                items = await self.parse_listing_page(nav_page, page_num)
                self.stats["pages"] += 1

                # Filter out items already known
                unfetched = [item for item in items if item["vbios_id"] not in self.downloaded_ids]
                print(f"  [*] Processing {len(unfetched)} new items (out of {len(items)}) with concurrency={self.args.concurrency}...")

                # Process new items concurrently
                tasks = [bounded_worker(item) for item in unfetched]
                await asyncio.gather(*tasks)

                await asyncio.sleep(self.args.delay)

            await nav_page.close()

        print(f"\n===========================================================")
        print(f" Download Summary:")
        print(f"   Pages visited:    {self.stats['pages']}")
        print(f"   ROMs downloaded:  {self.stats['downloaded']}")
        print(f"   ROMs skipped:     {self.stats['skipped']}")
        print(f"   Failures:         {self.stats['failed']}")
        print(f"   Database dir:     {self.output_dir.resolve()}")
        print(f"===========================================================")

def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download NVIDIA VBIOS ROMs from TechPowerUp with Camoufox Cloudflare bypass."
    )
    parser.add_argument(
        "--start-page", type=int, default=1,
        help="Page number to begin crawling from (default: 1)"
    )
    parser.add_argument(
        "--end-page", type=int, default=None,
        help="Page number to stop crawling at (default: auto-detected)"
    )
    parser.add_argument(
        "--architecture", type=str, default="NVIDIA",
        help="Architecture filter (default: 'NVIDIA')"
    )
    parser.add_argument(
        "--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR),
        help=f"Directory to save ROMs and metadata (default: {DEFAULT_OUTPUT_DIR})"
    )
    parser.add_argument(
        "--concurrency", type=int, default=2,
        help="Concurrent detail page downloads (default: 2)"
    )
    parser.add_argument(
        "--delay", type=float, default=1.5,
        help="Polite delay in seconds between network requests (default: 1.5)"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Maximum number of ROMs to download in this run (optional)"
    )
    parser.add_argument(
        "--retries", type=int, default=3,
        help="Number of retries for failed page requests (default: 3)"
    )
    parser.add_argument(
        "--no-headless", action="store_false", dest="headless",
        help="Run browser with visible UI window instead of headless"
    )
    parser.add_argument(
        "--filter-vendor", type=str, default=None,
        help="Filter downloads by vendor/manufacturer name substring (e.g. 'ASUS', 'EVGA', 'Abit')"
    )
    parser.add_argument(
        "--filter-model", type=str, default=None,
        help="Filter downloads by GPU model name substring (e.g. '8400', '410M', 'GTX 460')"
    )
    parser.add_argument(
        "--filter-devid", type=str, default=None,
        help="Filter downloads by PCI Device ID (e.g. '0421', '0422', '10de_0422')"
    )
    return parser.parse_args()

def main():
    args = parse_arguments()
    downloader = VBIOSDownloader(args)

    def handle_sigint(signum, frame):
        print("\n[!] Ctrl+C detected. Gracefully wrapping up...")
        downloader.stop_requested = True

    signal.signal(signal.SIGINT, handle_sigint)
    signal.signal(signal.SIGTERM, handle_sigint)

    asyncio.run(downloader.run())

if __name__ == "__main__":
    main()
