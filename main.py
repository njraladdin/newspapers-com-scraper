import asyncio
import aiohttp
from playwright.async_api import async_playwright
import json
import csv
from urllib.parse import urlencode
import math
from typing import Optional, List, Union
import os
import traceback
import random
import requests
from aiohttp import ClientError, ClientResponseError
import time 
from dotenv import load_dotenv

CONCURRENT_PAGES = 10
RESULTS_PER_PAGE = 50
KEYWORD_MATCHES_MAX_CONCURRENT_REQUESTS = 20
START_TIME = time.time()
PAGE_TIMES = []

load_dotenv()

PROXY_SETTINGS = {
    'host': os.getenv('PROXY_HOST'),
    'port': 9008,
    'username': os.getenv('PROXY_USER'),
    'password': os.getenv('PROXY_PASS')
}

print(PROXY_SETTINGS)

USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36'

async def get_keyword_match_count(image_id, keyword, max_retries=5):
    url = f"https://www.newspapers.com/api/search/hits?images={image_id}&terms={keyword}"
    headers = {'User-Agent': USER_AGENT}
    port = random.randint(9000, 9010)
    proxy = f"http://{PROXY_SETTINGS['username']}:{PROXY_SETTINGS['password']}@{PROXY_SETTINGS['host']}:{port}"

    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, proxy=proxy, timeout=10) as response:
                    response.raise_for_status()
                    data = await response.json()

                    if isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                        match_count = len(data[0])
                        return image_id, match_count
                    else:
                        print(f"Unexpected response format for image {image_id}")
                        return image_id, "ERROR"

        except aiohttp.ClientError as e:
            #print(f"Client error for image {image_id} (Attempt {attempt + 1}/{max_retries}): {str(e)}")
            continue
        except Exception as e:
            print(f"General error for image {image_id} (Attempt {attempt + 1}/{max_retries}): {str(e)}")

        if attempt < max_retries - 1:
            await asyncio.sleep(random.uniform(1, 3))  # Exponential backoff with jitter

    print(f"Max retries reached for image {image_id}")
    return image_id, "ERROR"

async def get_keyword_matches_for_search_results(search_results, keyword):
    print(f"Getting keyword matches for {len(search_results)} search results")

    tasks = []
    semaphore = asyncio.Semaphore(KEYWORD_MATCHES_MAX_CONCURRENT_REQUESTS)  # Limit to 10 concurrent requests

    async def bounded_get_keyword_match_count(image_id, keyword):
        async with semaphore:
            return await get_keyword_match_count(image_id, keyword)

    for record in search_results:
        if 'page' in record and 'id' in record['page']:
            task = bounded_get_keyword_match_count(record['page']['id'], keyword)
            tasks.append(task)

    results = await asyncio.gather(*tasks)

    keyword_match_counts = []
    successful_requests = 0
    for record, (image_id, match_count) in zip(search_results, results):
        if 'page' in record and 'id' in record['page'] and record['page']['id'] == image_id:
            record['keyword_match_count'] = match_count
            keyword_match_counts.append(match_count)
            if match_count != "ERROR":
                successful_requests += 1

    success_rate = (successful_requests / len(search_results)) * 100 if search_results else 0
    print(f"Got {len(search_results)} keyword matches : {keyword_match_counts}. Success rate: {success_rate:.2f}%")
    return search_results



async def scrape_newspapers(
    keyword: str,
    output_file: str,
    max_pages: Optional[int] = None,
    date: Optional[Union[List[int], None]] = None,
    location: Optional[str] = None
) -> List[dict]:
    print(f"Starting newspaper scraping for keyword: '{keyword}', date: {date}, location: {location}")
    
    all_records = []
    page_count = 0
    total_pages = 1  # Placeholder until we get actual total pages
    last_start_value = "*"  # Initialize with "*" for the first page

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            viewport={'width': 1920, 'height': 1080},
            device_scale_factor=1,
            is_mobile=False,
            has_touch=False,
            java_script_enabled=True,
            locale="en-US",
            timezone_id="America/New_York",
            proxy={ 
                "server": f"http://{PROXY_SETTINGS['host']}:{PROXY_SETTINGS['port']}",
                "username": PROXY_SETTINGS['username'],
                "password": PROXY_SETTINGS['password']
            }
        )

        await context.route("**/*", lambda route: route.continue_())

        while True:
            batch_start_time = time.time()
            tasks = []
            for _ in range(CONCURRENT_PAGES):
                if max_pages and page_count >= max_pages:
                    break

                params = {
                    "keyword": keyword,
                    "start": last_start_value,
                    "entity-types": "page,obituary,marriage,birth,enslavement",
                    "product": "1",
                    "sort": "score-desc",
                    "count": str(RESULTS_PER_PAGE),
                    "facet-year": "1000",
                    "facet-country": "200",
                    "facet-region": "300",
                    "facet-county": "260",
                    "facet-city": "150",
                    "facet-entity": "6",
                    "facet-publication": "5",
                    "include-publication-metadata": "true"
                }

                if date:
                    if len(date) == 2:  # Date range
                        params["date-start"] = str(date[0])
                        params["date-end"] = str(date[1])
                    elif len(date) == 1:  # Specific year
                        params["date"] = str(date[0])
                        params["facet-year-month"] = "12"
                        params["facet-year-month-day"] = "365"
                        params["disable-multi-select-facets"] = "true"
                if location:
                    if len(location) == 2:  # Assuming it's a country code
                        params["country"] = location.lower()
                    elif location.startswith("us-"):  # US state code
                        params["region"] = location
                    else:
                        print(f"Warning: Unrecognized location format '{location}'. Proceeding without location filter.")
                
                tasks.append(scrape_single_page(context, page_count + 1, params, keyword))
                page_count += 1

            batch_results = await asyncio.gather(*tasks)

            batch_end_time = time.time()
            batch_duration = batch_end_time - batch_start_time
            PAGE_TIMES.extend([batch_duration / len(tasks)] * len(tasks))

            valid_results = [result for result in batch_results if result is not None]
            
            if not valid_results:
                print("No valid results in this batch. Stopping scraping.")
                break

            for result in valid_results:
                all_records.extend(result['records_with_matches'])
                if 'nextStart' in result:
                    last_start_value = result['nextStart']

            if valid_results:
                record_count = valid_results[0]['recordCount']
                total_pages = math.ceil(record_count / RESULTS_PER_PAGE)
                print(f"Total records found: {record_count}")
                print(f"Estimated total pages: {total_pages}")

            progress_percentage = (page_count / total_pages) * 100 if total_pages > 0 else 0
            print(f"Progress: Page {page_count} / {total_pages} ({progress_percentage:.2f}% complete)")
            print(f"Total records processed so far: {len(all_records)}")

            if max_pages and page_count >= max_pages:
                break

            if page_count >= total_pages:
                break

            if last_start_value is None:
                print("Reached the end of results.")
                break

            print(f"Batch completed. Total records collected: {len(all_records)}")

        await browser.close()

    if not all_records:
        print("No records found after scraping all pages.")
        return []

    return format_and_save_records(all_records, output_file, len(all_records))


async def scrape_single_page(context, page_num, params, keyword):
    retries = 0
    max_retries = 3
    page = None
    
    while retries < max_retries:
        try:
            if page is None:
                page = await context.new_page()

            url = f"https://www.newspapers.com/api/search/query?{urlencode(params)}"
            print(f"Fetching search results page {page_num} (Attempt {retries + 1}/{max_retries})")
            
            await asyncio.sleep(random.uniform(1, 3))
            response = await page.goto(url, wait_until="domcontentloaded")

            # Check for Cloudflare challenge
            if await page.locator("text=Verifying you are human").count() > 0:
                raise Exception("Cloudflare challenge detected")

            result = await response.json()
            records = result.get('records', [])
            
            if not records:
                raise Exception("No records found")

            print(f"Page {page_num} received {len(records)} records.")
            
            # Process keyword matches
            records_with_matches = await get_keyword_matches_for_search_results(records, keyword)
            return {
                'records_with_matches': records_with_matches,
                'recordCount': result.get('recordCount', 0),
                'nextStart': result.get('nextStart')
            }

        except Exception as e:
            retries += 1
            error_message = str(e)
            
            if "Cloudflare challenge detected" in error_message:
                print(f"Cloudflare challenge on page {page_num}. Retry {retries}/{max_retries}.")
                await context.clear_cookies()
            elif "No records found" in error_message:
                print(f"No records found on page {page_num}. Retry {retries}/{max_retries}.")
            elif "JSON" in error_message:
                print(f"Failed to decode JSON on page {page_num}. Retry {retries}/{max_retries}.")
            else:
                print(f"Error in scraping page {page_num}: {error_message}. Retry {retries}/{max_retries}.")

            if page:
                await page.close()
                page = None

            if retries < max_retries:
                await asyncio.sleep(random.uniform(2, 5))  # Wait before retrying
            else:
                print(f"Failed to fetch page {page_num} after {max_retries} retries.")
                return None

    return None  # This line should never be reached, but it's here for completeness








def format_and_save_records(all_records, output_file, total_records):
    if not all_records:
        print("No records to save.")
        return []

    formatted_records = [{
        "Newspaper title": record['publication']['name'],
        "Page number": record['page']['pageNumber'],
        "Date": record['page']['date'],
        "Location": record['publication']['location'],
        "Number of keyword matches on the page": record['keyword_match_count'],
        "Viewer URL": record['page']['viewerUrl']
    } for record in all_records]

    os.makedirs('output', exist_ok=True)

    # Save as JSON
    json_file = os.path.join('output', f"{output_file}.json")
    print(f"Saving {len(formatted_records)} records to {json_file}")
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(formatted_records, f, ensure_ascii=False, indent=4)

    # Save as CSV
    if formatted_records:
        csv_file = os.path.join('output', f"{output_file}.csv")
        print(f"Saving {len(formatted_records)} records to {csv_file}")
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=formatted_records[0].keys())
            writer.writeheader()
            writer.writerows(formatted_records)
    else:
        print("No records to save to CSV.")
    
    print(f"Total records scraped: {total_records}")
    return formatted_records

async def main():
    print("Starting script execution")
    
    try:
        result = await scrape_newspapers(
            keyword="elon musk twitter",
            output_file="elon_musk_results",
            date=[2023],
            location="us",
            max_pages=None
        )
        print(f"Total records scraped: {len(result)}")
        print("Scraping completed")
    except Exception as e:
        print(f"An error occurred in main: {str(e)}")
        print(traceback.format_exc())
    
    # Add timing information
    end_time = time.time()
    total_duration = end_time - START_TIME
    avg_page_duration = sum(PAGE_TIMES) / len(PAGE_TIMES) if PAGE_TIMES else 0
    
    print("\n--- Scraping Statistics ---")
    print(f"Total execution time: {total_duration:.2f} seconds")
    print(f"Total pages scraped: {len(PAGE_TIMES)}")
    print(f"Average time per page (50 results): {avg_page_duration:.2f} seconds")
    print(f"Total records scraped: {len(result)}")
    print(f"Records per second: {len(result) / total_duration:.2f}")
    print(f"Pages per minute: {(len(PAGE_TIMES) / total_duration) * 60:.2f}")
    print("---------------------------")

if __name__ == "__main__":
    asyncio.run(main())