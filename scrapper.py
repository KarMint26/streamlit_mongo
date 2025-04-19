import requests
from pymongo import MongoClient
from datetime import datetime
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# MongoDB connection
try:
    client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=5000)
    db = client["big_data"]
    collection = db["news_woman"]
    logging.info("Connected to MongoDB")
except Exception as e:
    logging.error(f"Failed to connect to MongoDB: {e}")
    raise

def scrape_news():
    try:
        # URL API CNN Indonesia
        url = "https://berita-indo-api.vercel.app/v1/cnbc-news"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=30)  # Timeout 30 detik
        logging.info(f"Response status: {response.status_code}")
        response.raise_for_status()

        # Ambil data dari API
        data = response.json()
        articles = data.get('data', [])
        logging.info(f"Found {len(articles)} articles")

        news_data = []
        keywords = ["kekerasan", "perempuan", "wanita", "penyiksaan", "pelecehan", "penganiayaan", "kasus"]

        for article in articles[:100]:  # Batasi 100 artikel untuk debugging
            try:
                title = article.get('title', 'No title')
                logging.info(f"Processing article: {title}")

                # Filter berita terkait kekerasan terhadap perempuan
                if not any(keyword in title.lower() for keyword in keywords):
                    continue

                # Struktur data
                news_item = {
                    "title": title,
                    "link": article.get('link', 'No link'),
                    "date": article.get('isoDate', datetime.now().strftime('%Y-%m-%d')),
                    "content": article.get('description', 'No content'),
                    "image": article.get('image', {}).get('large', 'No image'),
                    "scraped_at": datetime.now()
                }

                # Cek duplikasi berdasarkan link
                if not collection.find_one({"link": news_item["link"]}):
                    news_data.append(news_item)
                else:
                    logging.info(f"Duplicate found, skipping: {title}")

            except Exception as e:
                logging.error(f"Error processing article: {e}")

        # Insert ke MongoDB
        if news_data:
            collection.insert_many(news_data)
            logging.info(f"Inserted {len(news_data)} new articles to MongoDB")
        else:
            logging.info("No new articles to insert")

    except requests.Timeout:
        logging.error("Request timed out")
        raise Exception("Error: Request ke API timeout")
    except requests.RequestException as e:
        logging.error(f"Error during API request: {e}")
        raise Exception(f"Error: Gagal mengakses API - {e}")
    except Exception as e:
        logging.error(f"Error during scraping: {e}")
        raise

if __name__ == "__main__":
    scrape_news()