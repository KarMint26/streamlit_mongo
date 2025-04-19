import streamlit as st
import pandas as pd
import plotly.express as px
from pymongo import MongoClient
from datetime import datetime
import subprocess
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# MongoDB connection
client = MongoClient("mongodb://localhost:27017/")
db = client["big_data"]
collection = db["news_woman"]


# Fungsi untuk mengambil data dari MongoDB
def fetch_data():
    data = list(collection.find())
    return pd.DataFrame(data)

# Fungsi untuk menjalankan scraper
def run_scraper():
    try:
        result = subprocess.run(["python", "scraper.py"], capture_output=True, text=True)
        logging.info("Scraping completed")
        return result.stdout + result.stderr
    except Exception as e:
        logging.error(f"Error running scraper: {e}")
        return str(e)

# Streamlit app
st.title("Visualisasi Data Kekerasan Perempuan Di indonesia")

# Tombol untuk trigger scraping
if st.button("Scrape Data Sekarang"):
    with st.spinner("Sedang melakukan scraping..."):
        output = run_scraper()
        st.text_area("Log Scraping", output, height=200)
        st.success("Scraping selesai!")

# Ambil data dari MongoDB
df = fetch_data()

if not df.empty:
    # Visualisasi 1: Jumlah berita per hari
    st.subheader("Jumlah Berita per Hari")
    df['date'] = pd.to_datetime(df['date'], errors='coerce')
    daily_count = df.groupby(df['date'].dt.date).size().reset_index(name='count')
    fig1 = px.line(daily_count, x='date', y='count', title="Tren Jumlah Berita per Hari")
    st.plotly_chart(fig1)

    # Visualisasi 2: Word cloud dari judul berita
    st.subheader("Word Cloud dari Judul Berita")
    from wordcloud import WordCloud
    import matplotlib.pyplot as plt
    text = " ".join(df['title'].dropna())
    wordcloud = WordCloud(width=800, height=400, background_color='white').generate(text)
    plt.figure(figsize=(10, 5))
    plt.imshow(wordcloud, interpolation='bilinear')
    plt.axis('off')
    st.pyplot(plt)

    # Visualisasi 3: Distribusi panjang konten
    st.subheader("Distribusi Panjang Konten Berita")
    df['content_length'] = df['content'].apply(lambda x: len(str(x)))
    fig2 = px.histogram(df, x='content_length', nbins=30, title="Distribusi Panjang Konten Berita")
    st.plotly_chart(fig2)

else:
    st.warning("Tidak ada data di database. Silakan jalankan scraping terlebih dahulu.")
