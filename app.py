import streamlit as st
import pandas as pd
import plotly.express as px
from pymongo import MongoClient
from datetime import datetime
import logging
from pymongo.errors import ConnectionFailure
import re # Untuk membersihkan teks
import string # Untuk membersihkan teks
from collections import Counter # Untuk menghitung frekuensi kata
from wordcloud import WordCloud # Untuk membuat word cloud
import matplotlib.pyplot as plt # Untuk menampilkan word cloud
import nltk # Untuk pemrosesan bahasa alami
import os # Diperlukan oleh NLTK

# --- Streamlit Page Config (MUST BE FIRST Streamlit command) ---
st.set_page_config(page_title="Dashboard Kekerasan Perempuan", layout="wide", initial_sidebar_state="expanded")

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Biarkan NLTK menggunakan path defaultnya ---
logging.info(f"Using default NLTK data paths: {nltk.data.path}")
# -----------------------------------------

# --- Initial NLTK Check (Optional) ---
@st.cache_resource
def initial_nltk_check():
    """Performs an initial check for NLTK data."""
    try:
        nltk.data.find('corpora/stopwords')
        logging.info("Initial check: NLTK stopwords found.")
    except LookupError:
        logging.warning("Initial check: NLTK stopwords not found. Will attempt download if needed.")
    try:
        nltk.data.find('tokenizers/punkt')
        logging.info("Initial check: NLTK punkt tokenizer found.")
    except LookupError:
        logging.warning("Initial check: NLTK punkt tokenizer not found. Will attempt download if needed.")

initial_nltk_check()

# Global variable for MongoDB client
mongo_client = None

# MongoDB connection
@st.cache_resource
def init_mongo():
    """Initializes MongoDB connection."""
    global mongo_client
    try:
        mongo_client = MongoClient("mongodb://localhost:27017/", serverSelectionTimeoutMS=5000)
        mongo_client.server_info()
        db = mongo_client["sr"]
        logging.info("✅ Successfully connected to MongoDB")
        return db
    except ConnectionFailure as e:
        st.error(f"❌ Gagal terhubung ke MongoDB: {e}")
        logging.error(f"MongoDB connection error: {e}")
        return None
    except Exception as e:
        st.error(f"❌ Error saat menghubungkan ke MongoDB: {e}")
        logging.error(f"Unexpected MongoDB connection error: {e}")
        return None

# Fungsi untuk mengambil data dari MongoDB
@st.cache_data(ttl=300)
def fetch_data():
    """Fetches data from MongoDB and performs initial processing."""
    db = init_mongo()
    if db is None:
        return pd.DataFrame()
    try:
        collection = db["woman_abuse"]
        # !! Ambil 'source' dari MongoDB !!
        data = list(collection.find({}, {"title": 1, "date": 1, "content": 1, "keywords_found": 1, "source": 1, "_id": 0}))
        df = pd.DataFrame(data)

        if df.empty:
             logging.warning("No data found in MongoDB collection.")
             return pd.DataFrame()

        logging.info(f"Data fetched: {len(df)} articles")

        # Konversi tanggal & hapus NaN
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df = df.dropna(subset=['date']) # Hapus baris jika tanggal tidak valid

        # Proses konten & title
        df['content'] = df['content'].fillna('')
        df['title'] = df['title'].fillna('').astype(str)

        # Proses source (isi NaN jika ada)
        df['source'] = df['source'].fillna('Dari Sumber Lain')

        # Pastikan keywords_found adalah list
        df['keywords_found'] = df['keywords_found'].apply(lambda x: x if isinstance(x, list) else [])

        return df
    except Exception as e:
        st.error(f"❌ Gagal mengambil atau memproses data dari MongoDB: {e}")
        logging.error(f"Error fetching/processing data: {e}", exc_info=True)
        return pd.DataFrame()

# Fungsi untuk memeriksa sampel data dari MongoDB
def check_sample_data():
    """Fetches a small sample of data for debugging."""
    db = init_mongo()
    if db is None:
        return {"error": "Tidak dapat terhubung ke MongoDB"}
    try:
        collection = db["woman_abuse"]
        # Ambil source juga di sampel
        sample = list(collection.find({}, {"title": 1, "keywords_found": 1, "content": 1, "source": 1, "_id": 0}).limit(5))
        logging.info(f"Sample data fetched: {len(sample)} articles")
        return sample if sample else {"message": "Tidak ada data di koleksi woman_abuse"}
    except Exception as e:
        logging.error(f"Error fetching sample data: {e}")
        return {"error": f"Gagal mengambil sampel data: {str(e)}"}

# --- Fungsi untuk Pemrosesan Teks dan Word Cloud ---
@st.cache_data(ttl=3600)
def get_word_frequencies(_df):
    """Processes text from title and content, removes stopwords, and returns word frequencies."""
    if _df.empty or ('title' not in _df.columns and 'content' not in _df.columns):
        return Counter()

    logging.info(f"NLTK data path inside get_word_frequencies: {nltk.data.path}")

    text = ' '.join(_df['title'].astype(str).tolist()) + ' ' + ' '.join(_df['content'].astype(str).tolist())
    text = text.lower()

    text = re.sub(r'http\S+|www\S+|https\S+', '', text, flags=re.MULTILINE)
    text = text.translate(str.maketrans('', '', string.punctuation))
    text = re.sub(r'\d+', '', text)
    text = ' '.join(text.split())

    tokens = []
    try:
        tokens = nltk.word_tokenize(text)
        logging.info("Tokenization successful using standard nltk.word_tokenize (default language).")
    except LookupError as e_lookup:
        logging.warning(f"NLTK LookupError during tokenization: {e_lookup}. Falling back to regex tokenizer.")
        tokens = re.findall(r'\b\w+\b', text)
        if 'fallback_warning_shown' not in st.session_state:
            st.warning("Tokenizer NLTK gagal dimuat. Menggunakan tokenizer sederhana (regex). Hasil mungkin kurang akurat.")
            st.session_state.fallback_warning_shown = True
    except Exception as e_nltk:
        logging.error(f"Unexpected error during NLTK tokenization: {e_nltk}", exc_info=True)
        logging.warning("Falling back to regex tokenizer due to unexpected NLTK error.")
        tokens = re.findall(r'\b\w+\b', text)
        if 'fallback_warning_shown' not in st.session_state:
            st.warning(f"Error NLTK Tokenizer ({e_nltk}). Menggunakan tokenizer sederhana (regex).")
            st.session_state.fallback_warning_shown = True

    if not tokens:
        logging.error("Tokenization resulted in empty list.")
        return Counter()

    stop_words_id = set()
    try:
        stop_words_id = set(nltk.corpus.stopwords.words('indonesian'))
        logging.info("Indonesian stopwords loaded successfully.")
    except LookupError:
        logging.warning("LookupError for 'stopwords'. Attempting download inside function...")
        try:
            with st.spinner("Mengunduh data stopwords NLTK (indonesian)..."):
                nltk.download('stopwords', quiet=False)
            logging.info("'stopwords' downloaded successfully inside function. Retrying load...")
            stop_words_id = set(nltk.corpus.stopwords.words('indonesian'))
            logging.info("Indonesian stopwords loaded successfully after download.")
        except Exception as download_err:
            error_message = str(download_err)
            logging.error(f"Failed during/after 'stopwords' download attempt: {error_message}", exc_info=True)
            if 'stopwords_error_shown' not in st.session_state:
                 st.error(f"Gagal memproses stopwords NLTK: {error_message}. Stopwords tidak akan dihapus.")
                 st.session_state.stopwords_error_shown = True
    except Exception as e_stopwords:
        logging.error(f"Unexpected error loading stopwords: {e_stopwords}", exc_info=True)
        if 'stopwords_error_shown' not in st.session_state:
            st.error(f"Gagal memuat stopwords: {e_stopwords}. Stopwords tidak akan dihapus.")
            st.session_state.stopwords_error_shown = True

    custom_stopwords = {
        'detik', 'cnn', 'indonesia', 'com', 'artikel', 'berita', 'antara', 'liputan6', 'kompas',
        'mengatakan', 'menyebutkan', 'ujar', 'kata', 'menurut', 'yakni', 'tersebut', 'selasa',
        'rabu', 'kamis', 'jumat', 'sabtu', 'minggu', 'senin', 'januari', 'februari', 'maret',
        'april', 'mei', 'juni', 'juli', 'agustus', 'september', 'oktober', 'november', 'desember',
        'wib', 'pukul', 'tahun', 'lalu', 'usai', 'saat', 'akan', 'agar', 'oleh', 'pada', 'ke',
        'dari', 'di', 'itu', 'ini', 'yang', 'dan', 'rp', 'ada', 'adalah', 'atau', 'jadi', 'juga',
        'no', 'description'
    }
    stop_words_id.update(custom_stopwords)

    filtered_tokens = [
        word for word in tokens if word.isalpha() and word not in stop_words_id and len(word) > 2
    ]

    word_counts = Counter(filtered_tokens)
    if '' in word_counts:
        del word_counts['']
    if None in word_counts:
         del word_counts[None]

    logging.info(f"Processed {len(tokens)} tokens, found {len(word_counts)} unique relevant words.")
    return word_counts

def generate_wordcloud_image(word_counts):
    """Generates a WordCloud image from word frequencies."""
    if not word_counts:
        return None
    try:
        wc = WordCloud(
             width=1200,
             height=600,
             background_color=None,
             mode="RGBA",
             max_words=200,
             colormap='plasma',
             ).generate_from_frequencies(word_counts)
        return wc
    except Exception as e:
        logging.error(f"Error generating word cloud: {e}")
        st.error(f"Gagal membuat Word Cloud: {e}")
        return None

# --- Streamlit App Layout ---
st.title("📊 Dashboard Analisis Berita Kekerasan Perempuan")
st.markdown(
    """
    Selamat datang di dashboard interaktif untuk menganalisis pemberitaan mengenai kekerasan terhadap perempuan
    yang bersumber dari Detik.com dan CNN Indonesia. Visualisasi di bawah ini membantu memahami tren,
    topik utama, dan karakteristik berita yang berhasil dikumpulkan.
    """
)
st.markdown("<br>", unsafe_allow_html=True)

# --- Sidebar ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/2991/2991197.png", width=80)
    st.header("Ringkasan Data")
    df = fetch_data()
    if not df.empty:
        st.metric("📰 Total Artikel Valid", len(df))
        if 'date' in df.columns and not df['date'].empty:
             min_date = df['date'].min()
             max_date = df['date'].max()
             st.metric("🗓️ Rentang Tanggal", f"{min_date.strftime('%d %b %Y')} - {max_date.strftime('%d %b %Y')}")
        else:
             st.warning("Kolom tanggal tidak ditemukan.")
    else:
        st.warning("Tidak ada data valid di database.")

    st.header("🛠️ Debugging")
    if st.button("Lihat Sampel Data Mentah"):
        with st.spinner("Mengambil sampel data..."):
            sample_data = check_sample_data()
        st.subheader("Sampel 5 Artikel dari MongoDB")
        st.json(sample_data, expanded=False)

    st.markdown("---")
    st.caption(f"Data terakhir diambil: {datetime.now().strftime('%d %b %Y, %H:%M:%S')} WIB")

# --- Main Content ---
if not df.empty:
    # --- Section 1: Distribusi Sumber Berita (Pengganti Tren) ---
    with st.container(border=True):
        st.subheader("📰 Distribusi Sumber Berita")
        st.markdown("Perbandingan jumlah artikel yang berasal dari masing-masing sumber berita.")
        if 'source' in df.columns:
            source_counts = df['source'].value_counts().reset_index()
            source_counts.columns = ['source', 'count']
            source_counts = source_counts.dropna(subset=['source', 'count']) # Pastikan tidak ada NaN

            if not source_counts.empty:
                fig_source = px.pie(
                    source_counts, names='source', values='count',
                    template='plotly_white',
                    color_discrete_sequence=px.colors.qualitative.Set2, # Palet warna berbeda
                    hole=0.4 # Donut chart
                )
                fig_source.update_layout(
                    title=None, # Hapus judul default
                    title_font_size=18, legend_title_text='Sumber Berita', legend_title_font_size=12,
                    plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                    legend=dict(orientation="h", yanchor="bottom", y=-0.15, xanchor="center", x=0.5) # Sesuaikan posisi legenda
                )
                fig_source.update_traces(
                    textposition='outside', # Teks di luar
                    textinfo='percent+label',
                    hovertemplate="<b>%{label}</b><br>Jumlah: %{value}<br>Persentase: %{percent}<extra></extra>"
                    )
                st.plotly_chart(fig_source, use_container_width=True)
            else:
                st.info("Tidak ada data sumber berita yang valid untuk ditampilkan.")
        else:
            st.warning("Kolom 'source' tidak ditemukan dalam data. Pastikan scraper menyimpannya.")

    st.markdown("<br>", unsafe_allow_html=True) # Spasi antar seksi

    # --- Section 2: Kata Kunci Awal ---
    with st.container(border=True):
        st.subheader("📊 Frekuensi Kata Kunci Awal (Hasil Scraper)")
        st.markdown("Distribusi kata kunci spesifik yang ditemukan oleh scraper dalam judul atau konten artikel.")
        if 'keywords_found' in df.columns:
            keywords_exploded = df['keywords_found'].explode()
            keywords_exploded = keywords_exploded.dropna().astype(str)
            if not keywords_exploded.empty:
                keywords_counts = keywords_exploded.value_counts().reset_index()
                keywords_counts.columns = ['keyword', 'count']
                keywords_counts = keywords_counts[keywords_counts['keyword'].astype(str).str.strip() != '']
                keywords_counts = keywords_counts.dropna(subset=['keyword', 'count'])

                if not keywords_counts.empty:
                    fig2 = px.bar(
                        keywords_counts.head(15), x='count', y='keyword',
                        orientation='h',
                        labels={'keyword': 'Kata Kunci', 'count': 'Jumlah Kemunculan'},
                        color='count', color_continuous_scale=px.colors.sequential.Tealgrn,
                        template='plotly_white',
                        text='count'
                    )
                    fig2.update_layout(
                        title=None,
                        title_font_size=18, xaxis_title_font_size=14, yaxis_title_font_size=14,
                        coloraxis_showscale=False, plot_bgcolor='rgba(240, 242, 246, 0.8)',
                        paper_bgcolor='rgba(0,0,0,0)',
                        yaxis={'categoryorder':'total ascending'}
                    )
                    fig2.update_traces(
                        textposition='outside',
                        hovertemplate="<b>%{y}</b><br>Jumlah: %{x}<extra></extra>"
                    )
                    st.plotly_chart(fig2, use_container_width=True)
                else:
                    st.info("Tidak ada kata kunci valid yang ditemukan untuk ditampilkan.")
            else:
                 st.info("Tidak ada kata kunci yang ditemukan setelah pemrosesan.")
        else:
            st.warning("Kolom 'keywords_found' tidak ditemukan.")

    st.markdown("<br>", unsafe_allow_html=True) # Spasi antar seksi

    # --- Section 3: Analisis Kata Penting ---
    with st.container(border=True):
        st.subheader("☁️ Analisis Kata Penting dari Teks Berita")
        st.markdown("Visualisasi kata-kata yang paling sering muncul dalam **judul dan konten** berita setelah menghapus kata umum (stopwords).")
        try:
             word_counts = get_word_frequencies(df)
        except Exception as e_freq:
             st.error(f"Terjadi error saat analisis frekuensi kata: {e_freq}")
             logging.error("Error during get_word_frequencies call", exc_info=True)
             word_counts = None

        if word_counts:
            col_wc, col_bar = st.columns([2, 3])

            with col_wc:
                st.markdown("**Word Cloud**")
                if word_counts:
                    wordcloud_image = generate_wordcloud_image(word_counts)
                    if wordcloud_image:
                        fig_wc, ax = plt.subplots(figsize=(10,5))
                        ax.imshow(wordcloud_image, interpolation='bilinear')
                        ax.axis('off')
                        fig_wc.patch.set_alpha(0.0)
                        ax.patch.set_alpha(0.0)
                        try:
                            st.pyplot(fig_wc, clear_figure=True)
                        except Exception as plt_err:
                            st.error(f"Gagal menampilkan Word Cloud: {plt_err}")
                            logging.error(f"Error displaying matplotlib figure: {plt_err}")
                    else:
                        st.warning("Tidak dapat membuat gambar Word Cloud.")
                else:
                    st.info("Tidak ada kata yang cukup signifikan untuk Word Cloud.")


            with col_bar:
                st.markdown("**Frekuensi Kata Teratas**")
                top_n = st.slider("Pilih jumlah kata teratas:", min_value=10, max_value=50, value=25, step=5, key="top_n_slider")
                top_words = word_counts.most_common(top_n)

                if top_words:
                    df_top_words = pd.DataFrame(top_words, columns=['Kata', 'Frekuensi'])
                    df_top_words = df_top_words.dropna(subset=['Kata', 'Frekuensi'])
                    df_top_words = df_top_words[df_top_words['Kata'].astype(str).str.strip() != '']

                    if not df_top_words.empty:
                        fig_bar_freq = px.bar(
                            df_top_words, x='Frekuensi', y='Kata', orientation='h',
                            labels={'Kata': 'Kata Penting', 'Frekuensi': 'Jumlah Kemunculan'},
                            template='plotly_white', color='Frekuensi',
                            color_continuous_scale=px.colors.sequential.OrRd,
                            text='Frekuensi'
                        )
                        fig_bar_freq.update_layout(
                            title=None,
                            title_font_size=18, xaxis_title_font_size=14, yaxis_title_font_size=14,
                            yaxis={'categoryorder':'total ascending'}, coloraxis_showscale=False,
                            plot_bgcolor='rgba(240, 242, 246, 0.8)', paper_bgcolor='rgba(0,0,0,0)',
                            margin=dict(l=10, r=10, t=30, b=10)
                        )
                        fig_bar_freq.update_traces(
                            textposition='outside',
                            hovertemplate="<b>%{y}</b><br>Jumlah: %{x}<extra></extra>"
                        )
                        st.plotly_chart(fig_bar_freq, use_container_width=True)
                    else:
                        st.info("Tidak ada kata valid yang cukup sering muncul setelah filter.")
                else:
                    st.info("Tidak ada kata yang cukup sering muncul.")
        else:
            st.info("Tidak ada data teks yang cukup untuk analisis kata, atau terjadi error saat pemrosesan teks.")

    # --- Hapus Section Distribusi Panjang Konten ---
    # st.markdown("<br>", unsafe_allow_html=True) # Spasi antar seksi
    # with st.container(border=True):
    #     st.subheader("🥧 Distribusi Kategori Panjang Konten")
    #     ... (kode untuk fig3 dihapus) ...

else:
    st.warning("⚠️ Tidak ada data valid yang ditemukan di database. Pastikan scraper telah berjalan dan berhasil menyimpan data.")
