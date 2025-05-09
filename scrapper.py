import os
import requests
from pymongo import MongoClient
from datetime import datetime
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

API_KEY = os.getenv('API_KEY')
if not API_KEY:
    raise EnvironmentError("API_KEY tidak ditemukan di environment!")

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# MongoDB connection
try:
    client = MongoClient("mongodb+srv://srikandi_app:srikandi123%23%23@srikandi.fdnhjdm.mongodb.net/test?retryWrites=true&w=majority", serverSelectionTimeoutMS=5000)
    client.server_info()  # Test connection
    db = client["sr"]
    collection = db["woman_abuse"]
    logging.info("✅ Berhasil terhubung ke MongoDB")
except Exception as e:
    logging.error(f"❌ Gagal terhubung ke MongoDB: {e}")
    raise

def scrape_news():
    try:
        url = f"https://newsdata.io/api/1/news?apikey={API_KEY}&q=kekerasan+perempuan&language=id"
        headers = {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/91.0.4472.124 Safari/537.36'
            )
        }

        response = requests.get(url, headers=headers, timeout=30)
        logging.info(f"Status respons: {response.status_code}")
        response.raise_for_status()

        try:
            data = response.json()
        except ValueError:
            logging.error("❌ Gagal menguraikan JSON dari API")
            return

        articles = data.get('results', [])
        logging.info(f"✅ Ditemukan {len(articles)} artikel dari API")

        news_data = []
        keywords = [
            "kekerasan perempuan", "kdrt", "pemerkosaan", "pelecehan seksual",
            "pelecehan", "eksploitasi perempuan", "tindak kekerasan",
            "korban perempuan", "kasus perempuan", "perkosaan",
            "kekerasan seksual", "perempuan jadi korban", "femicide",
            "perdagangan manusia", "trafficking"
        ]

        for article in articles[:100]:  # Batasi 100 artikel
            try:
                title = article.get('title', '')
                description = article.get('description', '')
                link = article.get('link', '')

                if not title:
                    logging.info("Artikel tanpa judul, dilewati")
                    continue
                if not link:
                    logging.info(f"Artikel tanpa link, dilewati: {title}")
                    continue
                if collection.find_one({"link": link}):
                    logging.info(f"Duplikat, sudah ada di DB: {title}")
                    continue

                # Periksa kata kunci di judul dan deskripsi
                content_to_check = (title.lower() + " " + (description.lower() if description else ""))
                matching_keywords = [keyword for keyword in keywords if keyword in content_to_check]

                news_item = {
                    "title": title,
                    "link": link,
                    "date": article.get('pubDate', datetime.now().strftime('%Y-%m-%d')),
                    "content": description or 'No description',
                    "image": article.get('image_url', 'No image'),
                    "scraped_at": datetime.now(),
                    "keywords_found": matching_keywords
                }

                news_data.append(news_item)
                logging.info(f"✅ Artikel baru ditambahkan: {title}")

            except Exception as e:
                logging.error(f"❌ Gagal memproses artikel '{title}': {e}")
                continue

        if news_data:
            collection.insert_many(news_data)
            logging.info(f"✅ Menyimpan {len(news_data)} artikel baru ke MongoDB")
        else:
            logging.info("📭 Tidak ada artikel baru untuk disimpan")

    except requests.Timeout:
        logging.error("⏱️ Permintaan API melebihi waktu tunggu")
    except requests.RequestException as e:
        logging.error(f"❌ Gagal mengakses API: {e}")
    except Exception as e:
        logging.error(f"❌ Error saat scraping: {e}")

if __name__ == "__main__":
    scrape_news()