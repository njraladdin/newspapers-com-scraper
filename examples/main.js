const NewspaperScraper = require('../lib/NewspaperScraper');
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
            // Save each article to a file (optional)
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
            console.log(`Total time: ${(stats.timeElapsed / 1000).toFixed(2)} seconds`);
        });

        // Start retrieving with the new API name
        await scraper.retrieve({
            keyword: "elon musk twitter",  // Required: search term
            limit: 500,                    // Optional: limit total results
            dateRange: [2020, 2024],       // Optional: date range [start, end] or [specific year]
            location: "us"                 // Optional: location code (e.g., "us", "us-ca", "gb")
        });

    } catch (error) {
        console.error('Scraping failed:', error);
    }
}

main(); 