import streamlit as st
import pandas as pd
import plotly.express as px
from pymongo import MongoClient
from datetime import datetime
import logging
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
            # Kategorikan panjang konten
            bins = [0, 200, 500, float('inf')]
            labels = ['Pendek (<200)', 'Sedang (200-500)', 'Panjang (>500)']
            df['content_length_category'] = pd.cut(df['content_length'], bins=bins, labels=labels, include_lowest=True)
        logging.info(f"Data fetched: {len(df)} articles")
        return df
    except Exception as e:
        st.error(f"Gagal mengambil data dari MongoDB: {e}")
        logging.error(f"Error fetching data: {e}")
        return pd.DataFrame()

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
st.set_page_config(page_title="Dashboard Kekerasan Perempuan", layout="wide")
st.title("📊 Dashboard Visualisasi Data Kekerasan Perempuan di Indonesia")
st.markdown(
    """
    Dashboard ini menampilkan analisis berita terkait kekerasan perempuan di Indonesia berdasarkan data dari NewsData.io.
    Gunakan visualisasi di bawah untuk memahami tren, distribusi kata kunci, dan karakteristik artikel.
    """
)
st.markdown("---")

# Sidebar untuk ringkasan dan debugging
with st.sidebar:
    st.header("Ringkasan Data")
    df = fetch_data()
    if not df.empty:
        st.metric("Total Artikel", len(df))
        st.metric("Rentang Tanggal", f"{df['date'].min().date()} - {df['date'].max().date()}")
    else:
        st.warning("Tidak ada data di database. Silakan jalankan 'python scraper.py' untuk mengisi data.")

    st.header("Debugging")
    if st.button("Tampilkan Sampel Data dari MongoDB"):
        sample_data = check_sample_data()
        st.write("Sampel 5 artikel dari MongoDB:")
        st.json(sample_data)

# Main content
if not df.empty:
    # Visualisasi 1: Tren Jumlah Berita per Hari (Line Chart)
    st.subheader("📈 Tren Jumlah Berita per Hari")
    daily_count = df.groupby(df['date'].dt.date).size().reset_index(name='count')
    fig1 = px.line(
        daily_count,
        x='date',
        y='count',
        title="Jumlah Berita Kekerasan Perempuan per Hari",
        labels={'date': 'Tanggal', 'count': 'Jumlah Berita'},
        template='plotly',
        color_discrete_sequence=['#1f77b4']
    )
    fig1.update_layout(
        showlegend=False,
        title_font_size=20,
        xaxis_title_font_size=14,
        yaxis_title_font_size=14,
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)'
    )
    st.plotly_chart(fig1, use_container_width=True)
    st.markdown("---")

    # Visualisasi 2: Distribusi Kata Kunci atau Panjang Konten (Bar Chart/Histogram)
    st.subheader("📊 Distribusi Kata Kunci atau Panjang Konten")
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
            color_continuous_scale='Viridis',
            template='plotly'
        )
        fig2.update_layout(
            showlegend=False,
            title_font_size=20,
            xaxis_title_font_size=14,
            yaxis_title_font_size=14,
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Kolom 'keywords_found' tidak ditemukan atau kosong. Menampilkan distribusi panjang konten.")
        logging.info("Keywords_found column missing or empty, showing content length distribution")
        fig2 = px.histogram(
            df,
            x='content_length',
            nbins=30,
            title="Distribusi Panjang Konten Berita",
            labels={'content_length': 'Panjang Konten (Karakter)', 'count': 'Jumlah Artikel'},
            color_discrete_sequence=['#ff7f0e'],
            template='plotly'
        )
        fig2.update_layout(
            showlegend=False,
            title_font_size=20,
            xaxis_title_font_size=14,
            yaxis_title_font_size=14,
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)'
        )
        st.plotly_chart(fig2, use_container_width=True)
    st.markdown("---")

    # Visualisasi 3: Pie Chart untuk Kategori Panjang Konten
    st.subheader("🥧 Distribusi Kategori Panjang Konten")
    length_category_counts = df['content_length_category'].value_counts().reset_index()
    length_category_counts.columns = ['category', 'count']
    fig3 = px.pie(
        length_category_counts,
        names='category',
        values='count',
        title="Proporsi Artikel Berdasarkan Panjang Konten",
        template='plotly',
        color_discrete_sequence=px.colors.sequential.RdBu
    )
    fig3.update_layout(
        title_font_size=20,
        legend_title_text='Kategori',
        legend_title_font_size=14,
        plot_bgcolor='rgba(0,0,0,0)',
        paper_bgcolor='rgba(0,0,0,0)'
    )
    st.plotly_chart(fig3, use_container_width=True)

else:
    st.warning("Tidak ada data di database. Silakan jalankan 'python scraper.py' untuk mengisi data.")

# Tutup koneksi MongoDB jika ada
if mongo_client is not None:
    mongo_client.close()