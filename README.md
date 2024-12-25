# Newspaper.com Scraper

[![npm version](https://badge.fury.io/js/newspapers-com-scraper.svg)](https://badge.fury.io/js/newspapers-com-scraper)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![npm total downloads](https://img.shields.io/npm/dt/newspapers-com-scraper.svg)](https://www.npmjs.com/package/newspapers-com-scraper)

A Node.js scraper for extracting article data from Newspapers.com based on keywords, dates, and locations.

## What it Does

Searches Newspapers.com and extracts:

- Newspaper title
- Page number and URL
- Publication date
- Location
- Number of keyword matches on each page

[Sample Output](https://docs.google.com/spreadsheets/d/1uq366pyEfolITFZ9X507ogsQjssx_pL1bp1pGPIPtt4/edit?gid=0#gid=0)

## Requirements

- Node.js 14+
- Google Chrome browser
- GEONODE.com account (optional, for proxy support)

## Installation

```bash
# Using npm
npm install newspapers-com-scraper

# Using yarn
yarn add newspapers-com-scraper
```

## Basic Usage

```javascript
const NewspaperScraper = require('newspapers-com-scraper');

async function main() {
    const scraper = new NewspaperScraper();

    // Listen for articles
    scraper.on('article', (article) => {
        console.log(`Found: ${article.title} (${article.date})`);
    });

    await scraper.scrapeNewspapers(
        "elon musk",     // keyword
        10,              // max pages (null for all)
        [2023, 2024],    // date range
        "us"            // location
    );
}
```

## Events

The scraper emits three types of events:

```javascript
// 1. Article found
scraper.on('article', (article) => {
    console.log(article);
    // {
    //     title: "The Daily News",
    //     pageNumber: 4,
    //     date: "2023-05-15",
    //     location: "New York, NY",
    //     keywordMatches: 3,
    //     url: "https://www.newspapers.com/image/12345678/"
    // }
});

// 2. Progress update
scraper.on('progress', (progress) => {
    console.log(progress);
    // {
    //     current: 5,              // Current page
    //     total: 20,              // Total pages
    //     percentage: 25.0,       // Progress percentage
    //     stats: {
    //         timeElapsed: 45.2,  // Total seconds
    //         avgPageTime: 9.04   // Avg seconds per page
    //     }
    // }
});

// 3. Scraping complete
scraper.on('complete', (stats) => {
    console.log(stats);
    // {
    //     timeElapsed: 180.5,     // Total seconds
    //     pageTimes: [8.2, 9.1]   // Time per page
    // }
});
```

## Advanced Configuration

Full configuration example:

```javascript
const scraper = new NewspaperScraper({
    // Scraping settings
    concurrentPages: 2,        // Pages to scrape in parallel
    resultsPerPage: 50,        // Results per page (max 50)
    maxConcurrentRequests: 10, // Max parallel requests
    
    // Browser settings
    browser: {
        headless: false,       // Show browser
        userAgent: 'Mozilla/5.0...',
        executablePath: '/path/to/chrome' // Optional
    },
    
    // Proxy settings (optional)
    proxy: {
        enabled: false,
        host: 'proxy.host',
        port: 9008,
        username: 'user',
        password: 'pass'
    },
    
    // Logging
    logger: {
        level: 'info',        // 'error' | 'warn' | 'info' | 'debug' | 'silent'
        custom: null          // Custom logger
    }
});

// If using proxy, set up .env:
// PROXY_HOST=your_geonode_proxy_host
// PROXY_USER=your_geonode_username
// PROXY_PASS=your_geonode_password
```
See `examples/main.js` for a complete working example.

