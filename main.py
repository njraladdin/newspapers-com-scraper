import asyncio
import aiohttp
from playwright.async_api import async_playwright
import json
import csv
from urllib.parse import urlencode
import math
from typing import Optional, List, Union
import os

RESULTS_PER_PAGE = 10
MAX_CONCURRENT_REQUESTS = 5

async def get_keyword_match_count(session, image_id, keyword, headers):
    url = f"https://www.newspapers.com/api/search/hits?images={image_id}&terms={keyword}"
    try:
        async with session.get(url, headers=headers) as response:
            if response.status == 200:
                data = await response.json()
                if isinstance(data, list) and len(data) > 0 and isinstance(data[0], list):
                    return image_id, len(data[0])
            else:
                print(f"Error fetching keyword match count for image {image_id}: HTTP Status {response.status}")
            return image_id, 0
    except Exception as e:
        print(f"Error fetching keyword match count for image {image_id}: {str(e)}")
        return image_id, 0

async def get_keyword_matches_for_search_results(search_results, keyword, headers):
    print(f"Getting keyword matches for {len(search_results)} search results")
    async with aiohttp.ClientSession() as session:
        tasks = [get_keyword_match_count(session, record['page']['id'], keyword, headers) 
                 for record in search_results if 'page' in record and 'id' in record['page']]

        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
        async def bounded_fetch(coro):
            async with semaphore:
                return await coro

        results = await asyncio.gather(*(bounded_fetch(task) for task in tasks))

    match_dict = dict(results)
    for record in search_results:
        if 'page' in record and 'id' in record['page']:
            record['keyword_match_count'] = match_dict.get(record['page']['id'], 0)

    print(f"Finished getting keyword matches for {len(search_results)} search results")
    return search_results

async def scrape_newspapers(
    keyword: str,
    output_file: str,
    max_pages: Optional[int] = None,
    date: Optional[Union[List[int], None]] = None,
    location: Optional[str] = None
) -> List[dict]:
    """
    Scrape newspapers based on keyword, optional date range, and optional location.
    """
    print(f"Starting newspaper scraping for keyword: '{keyword}', date: {date}, location: {location}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        base_url = "https://www.newspapers.com/api/search/query"
        params = {
            "keyword": keyword,
            "entity-types": "page,obituary,marriage,birth,enslavement",
            "product": "1",
            "sort": "score-desc",
            "start": "*",
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

        headers = {
            'accept': 'application/json, text/plain, */*',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
        }

        await context.set_extra_http_headers(headers)

        all_records = []
        page_count = 0
        total_records = 0

        while True:
            url = f"{base_url}?{urlencode(params)}"
            print(f"Fetching search results page {page_count + 1}")
            response = await page.goto(url)
            result = await response.json()
            
            records = result.get('records', [])
            record_count = result.get('recordCount', 0)
            total_pages = math.ceil(record_count / RESULTS_PER_PAGE)
            print(f"Received {len(records)} search results. Total record count: {record_count}")
            print(f"Estimated total pages: {total_pages}")
            
            records_with_matches = await get_keyword_matches_for_search_results(records, keyword, headers)
            
            all_records.extend(records_with_matches)
            
            page_count += 1
            total_records += len(records)
            
            progress_percentage = (page_count / total_pages) * 100 if total_pages > 0 else 0
            print(f"Progress: Page {page_count} / {total_pages} ({progress_percentage:.2f}% complete)")
            print(f"Total records processed so far: {total_records}")
            
            if not records or not result.get('nextStart') or (max_pages and page_count >= max_pages):
                print("Reached end of pagination or max pages limit")
                break
            
            params['start'] = result['nextStart']
            await asyncio.sleep(1)

        await browser.close()

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
    csv_file = os.path.join('output', f"{output_file}.csv")
    print(f"Saving {len(formatted_records)} records to {csv_file}")
    with open(csv_file, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=formatted_records[0].keys())
        writer.writeheader()
        writer.writerows(formatted_records)
    
    print(f"Total records scraped: {total_records}")
    print(f"Results saved to {json_file} and {csv_file}")

    return formatted_records

async def main():
    print("Starting script execution")
    
    result = await scrape_newspapers(
        keyword="elon musk twitter",
        output_file="elon_musk_results",
        max_pages=2,
        date=[2020, 2023],
        location="us"  # Changed to "us" as an example of a country code
    )
    
    print(f"Total records scraped: {len(result)}")
    print("Scraping completed")
    print("Script execution finished")

if __name__ == "__main__":
    asyncio.run(main())