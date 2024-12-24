const NewspaperScraper = require('./scrapeNewspapers');
const fs = require('fs').promises;
const path = require('path');
const dotenv = require('dotenv');

// Load environment variables
dotenv.config();

async function main() {
    try {
        // Initialize scraper with all available options
        const scraper = new NewspaperScraper({
            // Core settings
            concurrentPages: 2,        // Number of pages to scrape simultaneously
            resultsPerPage: 50,        // Number of results per page (max 50)
            maxConcurrentRequests: 10,  // Max concurrent API requests for keyword counting
            
            // Browser configuration
            browser: {
                headless: false,        // Run browser in background
                userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
            },
            
            // Proxy configuration (optional)
            proxy: {
                enabled: false,        // Enable proxy support
                host: process.env.PROXY_HOST,
                port: process.env.PROXY_PORT || 9008,
                username: process.env.PROXY_USER,
                password: process.env.PROXY_PASS
            },

            // Logging configuration
            logger: {
                level: 'info'         // 'error' | 'warn' | 'info' | 'debug' | 'silent'
            }
        });

        // Handle found articles
        scraper.on('article', async (article) => {
            await fs.mkdir('output', { recursive: true });
            const filename = `article_${Date.now()}.json`;
            await fs.writeFile(
                path.join('output', filename),
                JSON.stringify(article, null, 2)
            );
            console.log(`Found article: ${article.title} (${article.date})`);
        });

        // Show progress and stats
        scraper.on('progress', ({current, total, percentage, stats}) => {
            console.log(`Progress: ${percentage.toFixed(2)}% (${current}/${total} pages)`);
            console.log(`Time elapsed: ${stats.timeElapsed.toFixed(2)}s`);
            console.log(`Average time per page: ${stats.avgPageTime.toFixed(2)}s`);
        });

        // Handle completion
        scraper.on('complete', (stats) => {
            console.log('Scraping complete!');
            console.log(`Total time: ${stats.timeElapsed.toFixed(2)} seconds`);
        });

        // Start scraping with all parameters
        await scraper.scrapeNewspapers(
            "elon musk twitter",  // keyword to search
            10,                   // limit to 10 pages (null for all pages)
            [2023, 2024],        // date range [start, end] or [specific year]
            "us"                 // location (e.g., "us", "us-ca", "gb")
        );

    } catch (error) {
        console.error('Scraping failed:', error);
    }
}

main(); 