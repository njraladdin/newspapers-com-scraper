/**
 * Newspapers.com Scraper Pipeline:
 * 
 * 1. Input: keyword, date range, location
 * 2. Search newspapers.com for matching articles
 * 3. For each article found:
 *    - Get the page ID
 *    - Count how many times the keyword appears on that page
 * 4. Output: JSON/CSV files with:
 *    - Newspaper title, date, location
 *    - Page number and URL
 *    - Number of keyword matches
 * 
 * Example: 
 * Input: "elon musk twitter", 2023, US
 * Output: List of 2023 US newspaper articles mentioning "elon musk twitter"
 */

const puppeteerExtra = require('puppeteer-extra');
const StealthPlugin = require('puppeteer-extra-plugin-stealth');
const axios = require('axios');
const pLimit = require('p-limit');
const { URLSearchParams } = require('url');
const EventEmitter = require('events');
const os = require('os');

puppeteerExtra.use(StealthPlugin());

// Get the OS-specific Chrome path
const osPlatform = os.platform();
const executablePath = osPlatform.startsWith('win') 
    ? "C://Program Files//Google//Chrome//Application//chrome.exe" 
    : "/usr/bin/google-chrome";

class NewspaperScraperError extends Error {
    constructor(message) {
        super(message);
        this.name = 'NewspaperScraperError';
    }
}

class CloudflareError extends NewspaperScraperError {
    constructor() {
        super('Cloudflare challenge detected');
    }
}

// Add a new error class for retryable errors
class RetryableError extends NewspaperScraperError {
    constructor(message) {
        super(message);
        this.name = 'RetryableError';
    }
}

class NewspaperScraper extends EventEmitter {
    constructor(options = {}) {
        super();
        // Default configuration with option to override
        this.config = {
            concurrentPages: 1,
            resultsPerPage: 50,
            maxConcurrentRequests: 20,
            browser: {
                headless: false,
                userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36',
                ...options.browser
            },
            proxy: {
                enabled: false,
                host: null,
                port: 9008,
                username: null,
                password: null,
                ...options.proxy
            },
            logger: {
                level: 'info', // 'error', 'warn', 'info', 'debug', 'silent'
                custom: null,  // Custom logger implementation
            },
            ...options
        };
        
        this.stats = {
            startTime: Date.now(),
            pageTimes: []
        };
        this.browser = null;
    }

    log(level, message, ...args) {
        if (this.config.logger.level === 'silent') return;
        
        const levels = ['error', 'warn', 'info', 'debug'];
        if (levels.indexOf(level) > levels.indexOf(this.config.logger.level)) return;

        if (this.config.logger.custom) {
            this.config.logger.custom[level]?.(message, ...args);
        } else {
            console[level]?.(message, ...args);
        }
    }

    // Initialize browser
    async setupBrowser() {
        const browserArgs = [
            '--no-sandbox',
            '--disable-gpu',
            '--enable-webgl',
            '--window-size=1920,1080',
            '--disable-dev-shm-usage',
            '--disable-setuid-sandbox',
            '--no-first-run',
            '--no-default-browser-check',
            '--password-store=basic',
            '--disable-blink-features=AutomationControlled',
            '--disable-features=IsolateOrigins,site-per-process',
            '--lang=en',
            '--disable-web-security'
        ];

        if (this.config.proxy.enabled) {
            browserArgs.push(`--proxy-server=http://${this.config.proxy.host}:${this.config.proxy.port}`);
        }

        this.browser = await puppeteerExtra.launch({
            headless: this.config.browser.headless,
            executablePath: executablePath,
            args: browserArgs,
            ignoreDefaultArgs: ['--enable-automation', '--enable-blink-features=AutomationControlled'],
            defaultViewport: null
        });

        // Set default configurations for all new pages
        this.browser.on('targetcreated', async (target) => {
            const page = await target.page();
            if (page) {
                await page.setUserAgent(this.config.browser.userAgent);
                await page.setDefaultTimeout(30000);
                await page.setDefaultNavigationTimeout(30000);
            }
        });
    }

    // Add a helper method to create authenticated pages
    async createPage() {
        const page = await this.browser.newPage();
        if (this.config.proxy.enabled) {
            await page.authenticate({
                username: this.config.proxy.username,
                password: this.config.proxy.password
            });
        }
        return page;
    }

    // Build search parameters
    buildSearchParams(keyword, date, location) {
        const params = {
            keyword,
            start: "*",
            "entity-types": "page,obituary,marriage,birth,enslavement",
            product: "1",
            sort: "score-desc",
            count: this.config.resultsPerPage.toString(),
            "facet-year": "1000",
            "facet-country": "200",
            "facet-region": "300",
            "facet-county": "260",
            "facet-city": "150",
            "facet-entity": "6",
            "facet-publication": "5",
            "include-publication-metadata": "true"
        };

        if (date) {
            if (Array.isArray(date) && date.length === 2) {
                params["date-start"] = date[0].toString();
                params["date-end"] = date[1].toString();
            } else if (Array.isArray(date) && date.length === 1) {
                params.date = date[0].toString();
                params["facet-year-month"] = "12";
                params["facet-year-month-day"] = "365";
                params["disable-multi-select-facets"] = "true";
            }
        }

        if (location) {
            if (location.length === 2) {
                params.country = location.toLowerCase();
            } else if (location.startsWith("us-")) {
                params.region = location;
            }
        }

        return params;
    }

    // Count keywords on a single page
    async countKeywordOnSinglePage(pageId, keyword, maxRetries = 5) {
        const url = `https://www.newspapers.com/api/search/hits?images=${pageId}&terms=${keyword}`;
        const headers = { 'User-Agent': this.config.browser.userAgent };
        
        for (let attempt = 0; attempt < maxRetries; attempt++) {
            try {
                const response = await axios.get(url, { headers, timeout: 10000 });
                if (Array.isArray(response.data?.[0])) {
                    return [pageId, response.data[0].length];
                }
                return [pageId, "ERROR"];
            } catch (e) {
                if (attempt < maxRetries - 1) {
                    await new Promise(resolve => setTimeout(resolve, 1000 + Math.random() * 2000));
                }
            }
        }
        return [pageId, "ERROR"];
    }

    // Scrape a single search results page
    async scrapeSinglePage(pageNum, params, keyword) {
        let retries = 0;
        const maxRetries = 3;
        let page = null;

        while (retries < maxRetries) {
            try {
                page = await this.createPage();
                const url = `https://www.newspapers.com/api/search/query?${new URLSearchParams(params)}`;
                this.log('info', `Fetching search results page ${pageNum} (Attempt ${retries + 1}/${maxRetries})`);

                const response = await page.goto(url, { waitUntil: 'networkidle2' });

                if (await page.$('text="Verifying you are human"')) {
                    throw new CloudflareError();
                }

                const result = await response.json();
                const records = result.records || [];

                if (!records.length) {
                    throw new RetryableError("No records found");
                }

                this.log('info', `Page ${pageNum} received ${records.length} records.`);

                const recordsWithMatches = await this.countKeywordsOnAllPages(records, keyword);
                return {
                    records_with_matches: recordsWithMatches,
                    recordCount: result.recordCount || 0,
                    nextStart: result.nextStart
                };

            } catch (e) {
                this.log('error', `Error on attempt ${retries + 1}:`, e.message);
                retries++;

                // Always close the page after an error
                if (page) {
                    await page.close().catch(() => {});
                    page = null;
                }

                // If we have retries left and it's a retryable error, wait and try again
                if (retries < maxRetries && (e instanceof RetryableError || e instanceof CloudflareError)) {
                    await new Promise(resolve => setTimeout(resolve, Math.random() * 3000 + 2000));
                    continue;
                }

                // If it's not retryable or we're out of retries, give up
                this.log('error', `Failed to fetch page ${pageNum} after ${retries} attempts.`);
                throw e;
            } finally {
                if (page) {
                    await page.close().catch(() => {});
                }
            }
        }
    }

    // Main scraping method
    async scrapeNewspapers(keyword, maxPages = null, date = null, location = null) {
        if (!keyword || typeof keyword !== 'string') {
            throw new NewspaperScraperError('Keyword must be a non-empty string');
        }
        
        if (maxPages !== null && (!Number.isInteger(maxPages) || maxPages < 1)) {
            throw new NewspaperScraperError('maxPages must be null or a positive integer');
        }

        if (date && !Array.isArray(date)) {
            throw new NewspaperScraperError('date must be an array of [year] or [startYear, endYear]');
        }

        this.log('info', `Starting newspaper scraping for keyword: '${keyword}', date: ${date}, location: ${location}`);
        
        try {
            await this.setupBrowser();
            const params = this.buildSearchParams(keyword, date, location);
            let pageCount = 0;
            let totalPages = 1;

            while (true) {
                const batchStartTime = Date.now();
                const tasks = [];

                for (let i = 0; i < this.config.concurrentPages; i++) {
                    if (maxPages && pageCount >= maxPages) break;
                    tasks.push(this.scrapeSinglePage(pageCount + 1, params, keyword));
                    pageCount++;
                }

                const batchResults = await Promise.all(tasks);
                this.stats.pageTimes.push((Date.now() - batchStartTime) / 1000 / tasks.length);

                const validResults = batchResults.filter(result => result !== null);
                if (!validResults.length) break;

                for (const result of validResults) {
                    // Emit each article as it's found
                    for (const article of result.records_with_matches) {
                        const formattedArticle = {
                            title: article.publication.name,
                            pageNumber: article.page.pageNumber,
                            date: article.page.date,
                            location: article.publication.location,
                            keywordMatches: article.keyword_match_count,
                            url: article.page.viewerUrl
                        };
                        
                        this.emit('article', formattedArticle);
                    }

                    if (result.nextStart) {
                        params.start = result.nextStart;
                    }
                }

                if (validResults[0]) {
                    totalPages = Math.ceil(validResults[0].recordCount / this.config.resultsPerPage);
                    
                    // Emit progress
                    this.emit('progress', {
                        current: pageCount,
                        total: totalPages,
                        percentage: (pageCount/totalPages) * 100,
                        stats: {
                            timeElapsed: (Date.now() - this.stats.startTime) / 1000,
                            avgPageTime: this.stats.pageTimes.reduce((a, b) => a + b) / this.stats.pageTimes.length
                        }
                    });
                }

                if ((maxPages && pageCount >= maxPages) || pageCount >= totalPages) {
                    break;
                }
            }
        } finally {
            if (this.browser) {
                await this.browser.close();
            }
            this.emit('complete', this.stats);
        }
    }

    // Cleanup method
    async close() {
        if (this.browser) {
            await this.browser.close();
            this.browser = null;
        }
    }

    // Move this inside the class
    async countKeywordsOnAllPages(searchResults, keyword) {
        this.log('info', `Processing ${searchResults.length} pages for keyword counts`);

        const limit = pLimit(this.config.maxConcurrentRequests);
        
        const counts = await Promise.all(
            searchResults
                .filter(record => record.page?.id)
                .map(record => 
                    // Now we can use this.countKeywordOnSinglePage
                    limit(() => this.countKeywordOnSinglePage(record.page.id, keyword))
                )
        );

        let successCount = 0;
        counts.forEach(([pageId, count]) => {
            const record = searchResults.find(r => r.page?.id === pageId);
            if (record) {
                record.keyword_match_count = count;
                if (count !== "ERROR") successCount++;
            }
        });

        const successRate = (successCount / searchResults.length) * 100;
        this.log('info', `Finished counting keywords on all pages. Success rate: ${successRate.toFixed(2)}%`);
        return searchResults;
    }
}

module.exports = NewspaperScraper; 