import streamlit as st
import pandas as pd
import plotly.express as px
from pymongo import MongoClient
from datetime import datetime
import subprocess
import logging
from wordcloud import WordCloud
import matplotlib.pyplot as plt
from pymongo.errors import ConnectionFailure

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Global variable for MongoDB client
mongo_client = None

# MongoDB connection
@st.cache_resource
def init_mongo():
    global mongo_client
    try:
        mongo_client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=5000)
        mongo_client.server_info()  # Test connection
        db = mongo_client["sr"]
        return db
    except ConnectionFailure as e:
        st.error(f"Gagal terhubung ke MongoDB: {e}")
        logging.error(f"MongoDB connection error: {e}")
        return None

# Fungsi untuk mengambil data dari MongoDB
@st.cache_data(ttl=300)
def fetch_data():
    db = init_mongo()
    if db is None:
        return pd.DataFrame()
    try:
        collection = db["woman_abuse"]
        data = list(collection.find({}, {"title": 1, "date": 1, "content": 1, "keywords_found": 1, "_id": 0}))
        df = pd.DataFrame(data)
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'], errors='coerce')
            df['content_length'] = df['content'].apply(lambda x: len(str(x)) if pd.notnull(x) else 0)
        logging.info(f"Data fetched: {len(df)} articles")
        return df
    except Exception as e:
        st.error(f"Gagal mengambil data dari MongoDB: {e}")
        logging.error(f"Error fetching data: {e}")
        return pd.DataFrame()

# Fungsi untuk menjalankan scraper
def run_scraper():
    try:
        result = subprocess.run(["python", "scraper.py"], capture_output=True, text=True, timeout=300)
        logging.info("Scraping completed")
        return result.stdout + result.stderr
    except FileNotFoundError:
        logging.error("File scraper.py tidak ditemukan")
        return "Error: File scraper.py tidak ditemukan"
    except subprocess.TimeoutExpired:
        logging.error("Scraping timeout")
        return "Error: Scraping melebihi batas waktu"
    except Exception as e:
        logging.error(f"Error running scraper: {e}")
        return f"Error: {str(e)}"

# Fungsi untuk memeriksa sampel data dari MongoDB
def check_sample_data():
    db = init_mongo()
    if db is None:
        return "Tidak dapat terhubung ke MongoDB"
    try:
        collection = db["woman_abuse"]
        sample = list(collection.find({}, {"title": 1, "keywords_found": 1, "_id": 0}).limit(5))
        return sample
    except Exception as e:
        return f"Error: {str(e)}"

# Streamlit app
st.title("Visualisasi Data Kekerasan Perempuan di Indonesia")

# Tombol untuk trigger scraping
if st.button("Scrape Data Sekarang"):
    with st.spinner("Sedang melakukan scraping..."):
        output = run_scraper()
        st.text_area("Log Scraping", output, height=200)
        st.success("Scraping selesai!")
        st.cache_data.clear()  # Clear cache setelah scraping

# Opsi untuk memeriksa sampel data
if st.button("Tampilkan Sampel Data dari MongoDB"):
    sample_data = check_sample_data()
    st.write("Sampel 5 artikel dari MongoDB:")
    st.json(sample_data)

# Ambil data dari MongoDB
df = fetch_data()

if not df.empty:
    st.subheader("Ringkasan Data")
    st.write(f"Total artikel: {len(df)}")
    st.write(f"Rentang tanggal: {df['date'].min().date()} - {df['date'].max().date()}")

    # Visualisasi 1: Tren Jumlah Berita per Hari (Line Chart)
    st.subheader("Tren Jumlah Berita per Hari")
    daily_count = df.groupby(df['date'].dt.date).size().reset_index(name='count')
    fig1 = px.line(
        daily_count,
        x='date',
        y='count',
        title="Jumlah Berita Kekerasan Perempuan per Hari",
        labels={'date': 'Tanggal', 'count': 'Jumlah Berita'},
        template='plotly_white'
    )
    fig1.update_layout(showlegend=False)
    st.plotly_chart(fig1, use_container_width=True)

    # Visualisasi 2: Distribusi Kata Kunci atau Panjang Konten (Bar Chart/Histogram)
    st.subheader("Distribusi Kata Kunci atau Panjang Konten")
    if 'keywords_found' in df.columns and df['keywords_found'].notna().any():
        keywords = df['keywords_found'].explode().value_counts().reset_index()
        keywords.columns = ['keyword', 'count']
        fig2 = px.bar(
            keywords,
            x='keyword',
            y='count',
            title="Frekuensi Kata Kunci dalam Artikel",
            labels={'keyword': 'Kata Kunci', 'count': 'Jumlah Artikel'},
            color='count',
            color_continuous_scale='Blues',
            template='plotly_white'
        )
        fig2.update_layout(showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.warning("Kolom 'keywords_found' tidak ditemukan atau kosong. Menampilkan distribusi panjang konten sebagai gantinya.")
        logging.warning("Keywords_found column missing or empty, showing content length distribution")
        fig2 = px.histogram(
            df,
            x='content_length',
            nbins=30,
            title="Distribusi Panjang Konten Berita",
            labels={'content_length': 'Panjang Konten (Karakter)', 'count': 'Jumlah Artikel'},
            template='plotly_white'
        )
        st.plotly_chart(fig2, use_container_width=True)

    # Visualisasi 3: Word Cloud dari Judul Berita
    st.subheader("Word Cloud dari Judul Berita")
    try:
        text = " ".join(df['title'].dropna().astype(str))
        if text.strip():
            wordcloud = WordCloud(
                width=800,
                height=400,
                background_color='white',
                min_font_size=10,
                stopwords=['dan', 'di', 'ke', 'dari', 'yang', 'untuk']
            ).generate(text)
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.imshow(wordcloud, interpolation='bilinear')
            ax.axis('off')
            st.pyplot(fig)
        else:
            st.warning("Tidak ada teks judul yang valid untuk word cloud.")
            logging.warning("Empty or invalid title text for word cloud")
    except Exception as e:
        st.warning(f"Gagal membuat word cloud: {e}")
        logging.error(f"Word cloud generation failed: {e}")

else:
    st.warning("Tidak ada data di database. Silakan jalankan scraping terlebih dahulu.")

# Tutup koneksi MongoDB jika ada
if mongo_client is not None:
    mongo_client.close()