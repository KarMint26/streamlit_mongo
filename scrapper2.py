import os
import requests
from bs4 import BeautifulSoup
from pymongo import MongoClient
from datetime import datetime
import logging
from dotenv import load_dotenv
import time
from urllib.parse import quote_plus, urljoin # urljoin sudah ada

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# MongoDB connection
try:
    # Pastikan MONGO_URI di file .env sudah benar
    MONGO_URI = os.getenv('MONGO_URI', "mongodb+srv://srikandi_app:srikandi123%23%23@srikandi.fdnhjdm.mongodb.net/")
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    # Test the connection
    client.server_info()
    db = client["sr"] # Ganti jika nama DB beda
    collection = db["woman_abuse"] # Ganti jika nama collection beda
    logging.info("✅ Berhasil terhubung ke MongoDB")
except Exception as e:
    logging.error(f"❌ Gagal terhubung ke MongoDB: {e}")
    # Mungkin ingin keluar dari skrip jika DB tidak bisa diakses
    raise SystemExit(f"Koneksi DB Gagal: {e}")

# Daftar kata kunci
KEYWORDS = [
    "kekerasan perempuan", "kdrt", "pemerkosaan", "pelecehan seksual",
    "pelecehan", "eksploitasi perempuan", "tindak kekerasan",
    "korban perempuan", "kasus perempuan", "perkosaan", "kekerasan seksual",
    "perempuan jadi korban", "femicide", "perdagangan manusia", "trafficking"
]

# Header User-Agent (Gunakan User-Agent yang umum)
HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36' # Contoh lain
    )
}

# --- Fungsi Scraper Detik.com (PERLU VERIFIKASI SELEKTOR) ---
def scrape_detik(keyword, max_articles_per_keyword=25): # Naikkan sedikit batas per keyword
    """Scrapes Detik.com search results for a given keyword."""
    base_url = "https://www.detik.com"
    # Format URL pencarian Detik bisa berubah, ini salah satu format umum
    search_url = f"{base_url}/search/searchall?query={quote_plus(keyword)}&sortby=time&page=1"
    articles_found = []
    logging.info(f"[Detik] Mencari: {keyword} di {search_url}")
    try:
        response = requests.get(search_url, headers=HEADERS, timeout=45)
        response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
        soup = BeautifulSoup(response.text, 'lxml')

        # Selektor Detik mungkin berubah. Coba cari <article> atau div.list-berita__item
        # Lebih baik spesifik jika memungkinkan, misal: soup.select('div.list-berita article')
        list_article_elements = soup.find_all('article')

        if not list_article_elements:
            logging.warning(f"[Detik] Tidak ada elemen artikel ditemukan (cek selektor <article>) untuk: {keyword}")
            return []

        logging.info(f"[Detik] Ditemukan {len(list_article_elements)} potensi elemen artikel untuk: {keyword}")
        count = 0
        for article in list_article_elements:
            if count >= max_articles_per_keyword: break
            try:
                # Cari link dan title di dalam struktur umum (misal h2/h3 di dalam div .media__text)
                media_body = article.find('div', class_='media__text')
                if not media_body: continue # Skip jika struktur dasar tidak ada

                title_tag = media_body.find(['h2', 'h3'], class_='media__title')
                link_tag = title_tag.find('a') if title_tag else None

                if not link_tag or not link_tag.has_attr('href') or not title_tag: continue # Skip jika link/title tidak ada

                link = link_tag['href']
                title = title_tag.get_text(strip=True)

                # Validasi Link Awal
                if not link or link.startswith('#') or not link.startswith('http'):
                    # Coba gabungkan jika link relatif (jarang di detik search, tapi antisipasi)
                    if link.startswith('/'):
                       link = urljoin(base_url, link)
                    else:
                       continue # Skip jika format tidak dikenal

                # Deskripsi
                description_tag = media_body.find('p', class_='media__desc')
                description = description_tag.get_text(strip=True) if description_tag else 'No description'

                # Tanggal
                date_tag = article.find('span', class_='media__date') # Cari di luar media_body jika perlu
                pub_date_str = date_tag.get_text(strip=True) if date_tag else datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                # Gambar
                image_container = article.find('div', class_='media__image')
                img_tag = image_container.find('img') if image_container else article.find('img')
                # Cek 'src' atau 'data-src' (untuk lazy loading)
                image_url = None
                if img_tag:
                    image_url = img_tag.get('data-src') or img_tag.get('src')
                if not image_url: image_url = 'No image'


                articles_found.append({
                    "title": title, "link": link, "date_str": pub_date_str,
                    "content": description, "image": image_url, "source": "Detik.com"
                })
                count += 1
            except AttributeError as ae:
                # Log error ini jika terjadi, mungkin ada elemen <article> yang strukturnya beda
                logging.debug(f"[Detik] AttributeError saat proses elemen: {ae}", exc_info=False)
                continue # Lanjut ke elemen berikutnya
            except Exception as e:
                logging.warning(f"[Detik] Gagal memproses satu elemen artikel: {e}", exc_info=False)
                continue # Lanjut ke elemen berikutnya

        logging.info(f"[Detik] Berhasil mengekstrak {len(articles_found)} artikel dari {count} elemen yang diproses untuk: {keyword}")
        return articles_found
    # Error Handling
    except requests.Timeout:
        logging.error(f"[Detik] Timeout saat mengakses: {search_url}")
        return []
    except requests.RequestException as e:
        logging.error(f"[Detik] Gagal mengakses: {search_url} - {e}")
        return []
    except Exception as e:
        logging.error(f"[Detik] Error tidak terduga saat scraping {keyword}: {e}", exc_info=True)
        return []


# --- Fungsi Scraper CNN Indonesia (PERLU VERIFIKASI SELEKTOR) ---
def scrape_cnn(keyword, max_articles_per_keyword=25):
    """Scrapes CNNIndonesia.com search results for a given keyword."""
    base_url = "https://www.cnnindonesia.com"
    search_url = f"{base_url}/search/?query={quote_plus(keyword)}"
    articles_found = []
    logging.info(f"[CNN] Mencari: {keyword} di {search_url}")
    try:
        response = requests.get(search_url, headers=HEADERS, timeout=45)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')

        # Selektor CNN bisa berubah, coba <article>
        list_article_elements = soup.find_all('article')

        if not list_article_elements:
            logging.warning(f"[CNN] Tidak ada elemen artikel ditemukan (cek selektor <article>) untuk: {keyword}")
            return []

        logging.info(f"[CNN] Ditemukan {len(list_article_elements)} potensi elemen artikel untuk: {keyword}")
        count = 0
        for article in list_article_elements:
            if count >= max_articles_per_keyword: break
            try:
                link_tag = article.find('a')
                if not link_tag or not link_tag.has_attr('href'): continue

                link = link_tag['href']
                # Validasi Link Awal (Sangat Penting untuk CNN karena banyak '#')
                if not link or link == '#' or link.strip() == '': continue

                # Perbaiki link relatif (penting!)
                link = urljoin(base_url, link)
                if not link.startswith('http'): continue # Lewati jika format masih aneh

                # Judul (Coba cari h2 di dalam link, atau teks link itu sendiri)
                title_tag = link_tag.find('h2') # Asumsi judul ada di h2 dalam link
                title = title_tag.get_text(strip=True) if title_tag else link_tag.get_text(strip=True) # Fallback ke teks link
                if not title: # Jika judul masih kosong, coba cari h2 di luar link tapi dalam article
                     title_tag_alt = article.find('h2')
                     title = title_tag_alt.get_text(strip=True) if title_tag_alt else 'No Title Found'

                # Deskripsi (CNN jarang ada deskripsi di search, cari <p> saja)
                description_tag = article.find('p')
                description = description_tag.get_text(strip=True) if description_tag else 'No description'

                # Tanggal (Cari span dengan class 'text-cnn_grey' atau 'date')
                date_tag = article.find('span', class_='text-cnn_grey') or article.find('span', class_='date')
                pub_date_str = date_tag.get_text(strip=True) if date_tag else datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                # Gambar (Cari img di dalam link atau article)
                img_tag = link_tag.find('img') or article.find('img')
                image_url = None
                if img_tag:
                    image_url = img_tag.get('data-src') or img_tag.get('src')
                if not image_url: image_url = 'No image'

                # Hanya tambahkan jika judul dan link valid
                if title != 'No Title Found' and link:
                    articles_found.append({
                        "title": title, "link": link, "date_str": pub_date_str,
                        "content": description, "image": image_url, "source": "CNN Indonesia"
                    })
                    count += 1
            except AttributeError as ae:
                logging.debug(f"[CNN] AttributeError saat proses elemen: {ae}", exc_info=False)
                continue
            except Exception as e:
                logging.warning(f"[CNN] Gagal memproses satu elemen artikel: {e}", exc_info=False)
                continue

        logging.info(f"[CNN] Berhasil mengekstrak {len(articles_found)} artikel dari {count} elemen yang diproses untuk: {keyword}")
        return articles_found
    # Error Handling
    except requests.Timeout:
        logging.error(f"[CNN] Timeout saat mengakses: {search_url}")
        return []
    except requests.RequestException as e:
        logging.error(f"[CNN] Gagal mengakses: {search_url} - {e}")
        return []
    except Exception as e:
        logging.error(f"[CNN] Error tidak terduga saat scraping {keyword}: {e}", exc_info=True)
        return []

# --- Fungsi Scraper Kompas.com (BARU - PERLU VERIFIKASI SELEKTOR) ---
def scrape_kompas(keyword, max_articles_per_keyword=25):
    """Scrapes Kompas.com search results for a given keyword."""
    base_url = "https://www.kompas.com"
    # Kompas mungkin menggunakan sub-domain atau path /search/
    search_url = f"https://search.kompas.com/search/?q={quote_plus(keyword)}&sort=desc" # Sort by newest
    articles_found = []
    logging.info(f"[Kompas] Mencari: {keyword} di {search_url}")
    try:
        response = requests.get(search_url, headers=HEADERS, timeout=45)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')

        # Selektor Kompas: Coba cari div.article__list (umumnya dipakai)
        list_article_elements = soup.find_all('div', class_='article__list')

        if not list_article_elements:
            # Coba alternatif jika struktur berubah, misal: soup.select('.latest--topic article')
            logging.warning(f"[Kompas] Tidak ada elemen artikel ditemukan (cek selektor div.article__list) untuk: {keyword}")
            return []

        logging.info(f"[Kompas] Ditemukan {len(list_article_elements)} potensi elemen artikel untuk: {keyword}")
        count = 0
        for article in list_article_elements:
            if count >= max_articles_per_keyword: break
            try:
                # Cari link dan title: h3.article__title a
                title_tag = article.find('h3', class_='article__title')
                link_tag = title_tag.find('a') if title_tag else None

                if not link_tag or not link_tag.has_attr('href') or not title_tag: continue

                link = link_tag['href']
                title = link_tag.get_text(strip=True) # Judul biasanya ada di dalam link

                # Validasi dan pastikan link absolut (Kompas sering pakai link absolut)
                if not link or link.startswith('#') or not link.startswith('http'): continue

                # Deskripsi: Mungkin tidak ada, coba p.article__lead (jika ada)
                description_tag = article.find('p', class_='article__lead')
                description = description_tag.get_text(strip=True) if description_tag else 'No description'

                # Tanggal: div.article__date
                date_tag = article.find('div', class_='article__date')
                pub_date_str = date_tag.get_text(strip=True) if date_tag else datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                # Gambar: div.article__asset img
                image_container = article.find('div', class_='article__asset')
                img_tag = image_container.find('img') if image_container else None
                image_url = None
                if img_tag:
                    image_url = img_tag.get('data-src') or img_tag.get('src') # Prioritaskan data-src
                if not image_url: image_url = 'No image'

                articles_found.append({
                    "title": title, "link": link, "date_str": pub_date_str,
                    "content": description, "image": image_url, "source": "Kompas.com"
                })
                count += 1
            except AttributeError as ae:
                logging.debug(f"[Kompas] AttributeError saat proses elemen: {ae}", exc_info=False)
                continue
            except Exception as e:
                logging.warning(f"[Kompas] Gagal memproses satu elemen artikel: {e}", exc_info=False)
                continue

        logging.info(f"[Kompas] Berhasil mengekstrak {len(articles_found)} artikel dari {count} elemen yang diproses untuk: {keyword}")
        return articles_found
    # Error Handling
    except requests.Timeout:
        logging.error(f"[Kompas] Timeout saat mengakses: {search_url}")
        return []
    except requests.RequestException as e:
        logging.error(f"[Kompas] Gagal mengakses: {search_url} - {e}")
        return []
    except Exception as e:
        logging.error(f"[Kompas] Error tidak terduga saat scraping {keyword}: {e}", exc_info=True)
        return []

# --- Fungsi Scraper Tribunnews.com (BARU - PERLU VERIFIKASI SELEKTOR) ---
def scrape_tribun(keyword, max_articles_per_keyword=25):
    """Scrapes Tribunnews.com search results for a given keyword."""
    base_url = "https://www.tribunnews.com"
    # Format URL pencarian Tribun
    search_url = f"{base_url}/search?q={quote_plus(keyword)}"
    articles_found = []
    logging.info(f"[Tribun] Mencari: {keyword} di {search_url}")
    try:
        # Tribun kadang butuh timeout lebih lama
        response = requests.get(search_url, headers=HEADERS, timeout=60)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')

        # Selektor Tribun: Coba cari elemen list <li> di dalam <ul id='lists'>
        list_container = soup.find('ul', id='lists')
        if not list_container:
             logging.warning(f"[Tribun] Container utama (ul#lists) tidak ditemukan untuk: {keyword}. Coba cari div.lst-berita")
             # Alternatif: coba cari div.lst-berita li (struktur lain yang mungkin)
             list_container_alt = soup.find('div', class_='lst-berita')
             if list_container_alt:
                 list_article_elements = list_container_alt.find_all('li', recursive=False)
             else:
                 logging.warning("[Tribun] Alternatif container (div.lst-berita) juga tidak ditemukan.")
                 return []
        else:
            list_article_elements = list_container.find_all('li', recursive=False) # Ambil li langsung di bawah ul

        if not list_article_elements:
            logging.warning(f"[Tribun] Tidak ada elemen artikel (li) ditemukan di dalam container yang teridentifikasi untuk: {keyword}")
            return []

        logging.info(f"[Tribun] Ditemukan {len(list_article_elements)} potensi elemen artikel untuk: {keyword}")
        count = 0
        for article in list_article_elements:
            if count >= max_articles_per_keyword: break
            try:
                # Link dan Title: Coba cari di h3 a
                title_tag = article.find('h3')
                link_tag = title_tag.find('a') if title_tag else None

                if not link_tag or not link_tag.has_attr('href') or not title_tag: continue

                link = link_tag['href']
                title = link_tag.get_text(strip=True) # Ambil teks dari link

                # Validasi dan pastikan link absolut (Tribun sering pakai link absolut di search)
                if not link or link.startswith('#') or not link.startswith('http'): continue

                # Deskripsi: Coba div.grey.sumari atau p
                description_tag = article.find('div', class_='grey sumari') or article.find('p')
                description = description_tag.get_text(strip=True) if description_tag else 'No description'

                # Tanggal: Cari tag <time> (mungkin punya class 'grey') atau span.grey
                date_tag = article.find('time', class_='grey') or article.find('time') or article.find('span', class_='grey')
                pub_date_str = date_tag.get_text(strip=True) if date_tag else datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                # Gambar: Cari img, mungkin di dalam div.fr.mt5 atau langsung
                # Tribun sering pakai class 'fr' atau 'img-ovh'
                image_container = article.find('div', class_='fr') or article.find('div', class_='img-ovh')
                img_tag = image_container.find('img') if image_container else article.find('img')
                image_url = None
                if img_tag:
                    image_url = img_tag.get('data-src') or img_tag.get('src')
                if not image_url: image_url = 'No image'


                articles_found.append({
                    "title": title, "link": link, "date_str": pub_date_str,
                    "content": description, "image": image_url, "source": "Tribunnews.com"
                })
                count += 1
            except AttributeError as ae:
                logging.debug(f"[Tribun] AttributeError saat proses elemen: {ae}", exc_info=False)
                continue
            except Exception as e:
                logging.warning(f"[Tribun] Gagal memproses satu elemen artikel: {e}", exc_info=False)
                continue

        logging.info(f"[Tribun] Berhasil mengekstrak {len(articles_found)} artikel dari {count} elemen yang diproses untuk: {keyword}")
        return articles_found
    # Error Handling
    except requests.Timeout:
        logging.error(f"[Tribun] Timeout saat mengakses: {search_url}")
        return []
    except requests.RequestException as e:
        logging.error(f"[Tribun] Gagal mengakses: {search_url} - {e}")
        return []
    except Exception as e:
        logging.error(f"[Tribun] Error tidak terduga saat scraping {keyword}: {e}", exc_info=True)
        return []

# --- Fungsi Scraper Suara.com (BARU - PERLU VERIFIKASI SELEKTOR) ---
def scrape_suara(keyword, max_articles_per_keyword=25):
    """Scrapes Suara.com search results for a given keyword."""
    base_url = "https://www.suara.com"
    search_url = f"{base_url}/search?q={quote_plus(keyword)}"
    articles_found = []
    logging.info(f"[Suara] Mencari: {keyword} di {search_url}")
    try:
        response = requests.get(search_url, headers=HEADERS, timeout=45)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'lxml')

        # Selektor Suara: Coba cari <article class="item"> atau div.item
        list_article_elements = soup.find_all('article', class_='item')
        if not list_article_elements:
            # Alternatif: Coba cari div.widget-content article
            container_alt = soup.find('div', class_='widget-content')
            if container_alt:
                list_article_elements = container_alt.find_all('article')
            else:
                logging.warning(f"[Suara] Tidak ada elemen artikel ditemukan (cek selektor article.item atau div.widget-content article) untuk: {keyword}")
                return []


        logging.info(f"[Suara] Ditemukan {len(list_article_elements)} potensi elemen artikel untuk: {keyword}")
        count = 0
        for article in list_article_elements:
            if count >= max_articles_per_keyword: break
            try:
                # Link dan Title: Cari di h4.item-title a atau h2.post-title a
                title_tag = article.find(['h4', 'h2'], class_=['item-title', 'post-title'])
                link_tag = title_tag.find('a') if title_tag else None

                if not link_tag or not link_tag.has_attr('href') or not title_tag: continue

                link = link_tag['href']
                title = link_tag.get_text(strip=True) # Judul ada di dalam link

                # Validasi dan pastikan link absolut
                link = urljoin(base_url, link) # Penting karena Suara bisa pakai relatif
                if not link or link.startswith('#') or not link.startswith('http'): continue

                # Deskripsi: p.item-desc atau div.post-excerpt
                description_tag = article.find('p', class_='item-desc') or article.find('div', class_='post-excerpt')
                description = description_tag.get_text(strip=True) if description_tag else 'No description'

                # Tanggal: span.item-date atau div.post-date
                date_tag = article.find(['span', 'div'], class_=['item-date', 'post-date'])
                pub_date_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S') # Default
                if date_tag:
                    # Suara sering punya format " | Selasa, 02 Mei 2025 | 15:00 WIB"
                    date_text = date_tag.get_text(strip=True)
                    parts = date_text.split('|')
                    if len(parts) > 1:
                        pub_date_str = parts[-1].strip() # Ambil bagian terakhir setelah '|'
                    else:
                         pub_date_str = date_text # Ambil teks apa adanya jika tidak ada '|'


                # Gambar: figure.item-img img atau div.post-thumb img
                image_container = article.find(['figure', 'div'], class_=['item-img', 'post-thumb'])
                img_tag = image_container.find('img') if image_container else None
                # Suara sering pakai data-src untuk lazy loading
                image_url = None
                if img_tag:
                    image_url = img_tag.get('data-src') or img_tag.get('src')
                if not image_url: image_url = 'No image'


                articles_found.append({
                    "title": title, "link": link, "date_str": pub_date_str,
                    "content": description, "image": image_url, "source": "Suara.com"
                })
                count += 1
            except AttributeError as ae:
                logging.debug(f"[Suara] AttributeError saat proses elemen: {ae}", exc_info=False)
                continue
            except Exception as e:
                logging.warning(f"[Suara] Gagal memproses satu elemen artikel: {e}", exc_info=False)
                continue

        logging.info(f"[Suara] Berhasil mengekstrak {len(articles_found)} artikel dari {count} elemen yang diproses untuk: {keyword}")
        return articles_found
    # Error Handling
    except requests.Timeout:
        logging.error(f"[Suara] Timeout saat mengakses: {search_url}")
        return []
    except requests.RequestException as e:
        logging.error(f"[Suara] Gagal mengakses: {search_url} - {e}")
        return []
    except Exception as e:
        logging.error(f"[Suara] Error tidak terduga saat scraping {keyword}: {e}", exc_info=True)
        return []


# --- Fungsi Utama (Modifikasi untuk memanggil semua scraper dan filter) ---
def main_scrape(max_total_articles=100): # Target total artikel BARU yang ingin disimpan
    """Main function to orchestrate scraping from multiple sources and saving."""
    final_news_data_to_save = [] # List untuk menampung artikel BARU yang valid
    processed_links = set()      # Set untuk melacak link yang sudah ada atau sudah diproses

    try:
        # Ambil link yang sudah ada di DB untuk menghindari duplikasi
        existing_links = set(item['link'] for item in collection.find({}, {'link': 1}))
        processed_links.update(existing_links)
        logging.info(f"Ditemukan {len(existing_links)} link yang sudah ada di database. Link ini akan dilewati.")
    except Exception as e:
        logging.error(f"Gagal mengambil link dari DB: {e}. Melanjutkan tanpa cek duplikat awal.")
        # Jika DB gagal, setidaknya kita masih bisa scrape, tapi mungkin ada duplikat

    # --- Tentukan scraper yang akan dijalankan ---
    scrapers = {
        "Detik.com": scrape_detik,
        "CNN Indonesia": scrape_cnn,
        "Kompas.com": scrape_kompas,
        "Tribunnews.com": scrape_tribun,
        "Suara.com": scrape_suara
    }
    num_sources = len(scrapers)
    # Perkiraan berapa banyak yang diambil per sumber per keyword agar tidak terlalu banyak request
    max_articles_per_keyword_per_source = 30 # Ambil lebih banyak, nanti difilter

    articles_collected_count = 0 # Lacak jumlah artikel BARU yang valid ditemukan

    logging.info(f"Memulai scraping untuk {len(KEYWORDS)} keywords di {num_sources} sumber berita. Target: {max_total_articles} artikel baru.")

    # Loop utama per keyword
    for keyword in KEYWORDS:
        if articles_collected_count >= max_total_articles:
            logging.info(f"Target {max_total_articles} artikel baru tercapai. Menghentikan proses scraping.")
            break # Hentikan jika target sudah tercapai

        logging.info(f"===== Memproses Keyword: '{keyword}' =====")
        keyword_start_time = time.time()
        articles_found_this_keyword = 0

        # Loop per sumber berita
        for source_name, scraper_func in scrapers.items():
            if articles_collected_count >= max_total_articles: break # Cek lagi sebelum scrape sumber baru

            logging.debug(f"[{source_name}] Mulai scrape untuk keyword: '{keyword}'")
            # Panggil fungsi scraper yang sesuai
            results = scraper_func(keyword, max_articles_per_keyword=max_articles_per_keyword_per_source)

            if not results:
                logging.info(f"[{source_name}] Tidak ada hasil ditemukan atau gagal scrape untuk keyword: '{keyword}'")
                time.sleep(2) # Jeda singkat meski gagal
                continue # Lanjut ke sumber berikutnya

            logging.info(f"[{source_name}] Ditemukan {len(results)} artikel mentah. Memulai penyaringan...")

            # Filter hasil dari sumber ini untuk keyword ini
            newly_added_count_source = 0
            for article in results:
                if articles_collected_count >= max_total_articles: break # Cek lagi di dalam loop artikel

                link = article.get('link')
                title = article.get('title', '')
                content = article.get('content', '') # Deskripsi/konten singkat

                # 1. Cek Link valid dan belum diproses/ada di DB
                if not link or link in processed_links:
                    # logging.debug(f"[{source_name}] Link duplikat atau tidak valid dilewati: {link}")
                    continue

                # 2. Cek Relevansi Keyword (di judul atau konten) - case insensitive
                # Pastikan keyword ada di teks artikel
                content_to_check = (title.lower() + " " + content.lower())
                # Cek apakah keyword saat ini ada di konten (bisa diperluas ke semua KEYWORDS jika perlu)
                if keyword.lower() not in content_to_check:
                     # Cek juga keyword lain jika ingin lebih luas, tapi fokus ke keyword pencarian lebih baik
                     # matching_keywords = [kw for kw in KEYWORDS if kw.lower() in content_to_check]
                     # if not matching_keywords:
                     #    logging.debug(f"[{source_name}] Artikel tidak relevan (keyword '{keyword}' tidak ditemukan): {title[:60]}...")
                     #    continue
                     logging.debug(f"[{source_name}] Artikel tidak relevan (keyword '{keyword}' tidak ditemukan): {title[:60]}...")
                     continue


                # 3. Jika relevan dan belum ada, format dan tambahkan
                news_item = {
                    "title": title,
                    "link": link,
                    "date": article.get('date_str', datetime.now().strftime('%Y-%m-%d %H:%M:%S')), # Gunakan date_str dari scrape
                    "content": content,
                    "image": article.get('image'),
                    "source": source_name, # Gunakan nama sumber dari loop
                    "scraped_at": datetime.now(),
                    "keywords_found": [keyword] # Tandai keyword yang memicu penemuan ini
                }
                final_news_data_to_save.append(news_item) # Tambahkan ke list utama
                processed_links.add(link) # Tandai link ini sudah diproses (termasuk yang dari DB)
                articles_collected_count += 1 # Hitung artikel BARU yang valid
                newly_added_count_source += 1
                logging.info(f"✅ [{source_name}] Artikel baru valid ({articles_collected_count}/{max_total_articles}): {title[:60]}...")

            logging.info(f"[{source_name}] Selesai filter. Menambahkan {newly_added_count_source} artikel baru dari sumber ini.")
            time.sleep(3) # Jeda antar sumber berita

        # Log setelah selesai memproses satu keyword di semua sumber
        keyword_end_time = time.time()
        logging.info(f"===== Selesai Keyword: '{keyword}'. Ditemukan {articles_found_this_keyword} artikel baru yang relevan. Waktu: {keyword_end_time - keyword_start_time:.2f} detik. Total artikel baru terkumpul: {articles_collected_count} =====")
        time.sleep(5) # Jeda lebih lama antar keyword

    # --- Simpan Semua Data BARU yang Terkumpul ke MongoDB ---
    if final_news_data_to_save:
        logging.info(f"Total {len(final_news_data_to_save)} artikel baru akan disimpan ke MongoDB...")
        try:
            # Gunakan insert_many untuk efisiensi
            result = collection.insert_many(final_news_data_to_save, ordered=False) # ordered=False agar tidak berhenti jika 1 gagal (misal karena duplikat race condition)
            logging.info(f"✅ Berhasil menyimpan {len(result.inserted_ids)} artikel baru ke database.")
        except Exception as e:
            logging.error(f"❌ Gagal menyimpan data ke MongoDB: {e}")
            # Pertimbangkan menyimpan ke file cadangan jika DB gagal
            try:
                import json
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_file = f'failed_inserts_{timestamp}.json'
                with open(backup_file, 'w', encoding='utf-8') as f:
                    # Konversi datetime ke string untuk JSON serialization
                    def default_serializer(o):
                        if isinstance(o, datetime):
                            return o.isoformat()
                        raise TypeError(f"Object of type {o.__class__.__name__} is not JSON serializable")
                    json.dump(final_news_data_to_save, f, default=default_serializer, indent=2, ensure_ascii=False)
                logging.info(f"Data gagal simpan telah dicadangkan ke {backup_file}")
            except Exception as backup_e:
                logging.error(f"Gagal menyimpan backup ke file JSON: {backup_e}")

    else:
        logging.info("📭 Tidak ada artikel baru yang relevan untuk disimpan setelah memproses semua keyword.")


if __name__ == "__main__":
    start_time = time.time()
    # Set target TOTAL artikel BARU yang ingin Anda dapatkan dari proses scraping ini
    main_scrape(max_total_articles=150)
    end_time = time.time()
    logging.info(f"Proses scraping keseluruhan selesai dalam {end_time - start_time:.2f} detik.")