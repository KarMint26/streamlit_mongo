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

# --- Streamlit Page Config (HARUS menjadi perintah Streamlit pertama) ---
st.set_page_config(
    page_title="Dashboard Kekerasan Perempuan",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# --- Konfigurasi NLTK Data Path (untuk robust NLTK handling) ---
@st.cache_resource
def configure_nltk_path():
    """Konfigurasi path untuk NLTK data, prioritaskan folder lokal."""
    local_nltk_data_path = os.path.join(os.getcwd(), "nltk_data")
    if not os.path.exists(local_nltk_data_path):
        try:
            os.makedirs(local_nltk_data_path)
            logging.info(f"Folder nltk_data dibuat di: {local_nltk_data_path}")
        except OSError as e:
            logging.error(f"Gagal membuat folder nltk_data di {local_nltk_data_path}: {e}")
            # Tidak menampilkan st.warning di sini, biarkan NLTK menggunakan default path jika gagal
            return
    if local_nltk_data_path not in nltk.data.path:
        nltk.data.path.insert(0, local_nltk_data_path)
        logging.info(f"Path lokal '{local_nltk_data_path}' ditambahkan ke NLTK data path.")
    logging.info(f"NLTK akan mencari data di: {nltk.data.path}")
    st.session_state.nltk_path_configured = True

if 'nltk_path_configured' not in st.session_state:
    configure_nltk_path()

# --- Download NLTK resources (Dibuat lebih "diam") ---
@st.cache_resource
def download_nltk_resources():
    """Downloads NLTK stopwords and punkt if not found to the configured paths."""
    resources_to_check = {
        "corpora/stopwords": "stopwords",
        "tokenizers/punkt": "punkt"
    }
    download_occurred_local = False # Mengganti nama variabel agar tidak konflik
    local_nltk_data_path = os.path.join(os.getcwd(), "nltk_data")
    can_write_to_local = os.path.exists(local_nltk_data_path) and os.access(local_nltk_data_path, os.W_OK)

    logging.info(f"NLTK Downloader paths: {nltk.data.path}")

    for resource_path, resource_name in resources_to_check.items():
        try:
            if not st.session_state.get('force_nltk_redownload_flag', False): # Ganti nama flag
                nltk.data.find(resource_path)
                logging.info(f"NLTK resource '{resource_name}' ditemukan.")
                if resource_name == "punkt":
                    try:
                        nltk.data.find('tokenizers/punkt/PY3/indonesian.pickle')
                        logging.info("Model 'punkt' untuk bahasa Indonesia juga terverifikasi ada.")
                    except LookupError:
                        logging.warning(f"Model 'indonesian.pickle' TIDAK ditemukan di paket '{resource_name}'. Tokenizer akan fallback jika 'indonesian' diminta.")
                continue
            else:
                logging.info(f"Mode force_redownload untuk '{resource_name}'.")
                raise LookupError(f"Force redownload for {resource_name}.")
        except LookupError:
            logging.warning(f"NLTK resource '{resource_name}' tidak ditemukan/diminta unduh ulang. Mencoba mengunduh...")
            try:
                downloader_options = {'quiet': True} # quiet=True untuk mengurangi output
                if can_write_to_local:
                    downloader_options['download_dir'] = local_nltk_data_path
                if st.session_state.get('force_nltk_redownload_flag', False):
                    downloader_options['force'] = True
                    if 'download_dir' not in downloader_options and can_write_to_local:
                         downloader_options['download_dir'] = local_nltk_data_path
                
                nltk.download(resource_name, **downloader_options)
                logging.info(f"NLTK resource '{resource_name}' berhasil diunduh/diproses.")
                download_occurred_local = True
            except Exception as e:
                logging.error(f"Gagal mengunduh NLTK resource '{resource_name}': {e}", exc_info=True)
                # Tidak menampilkan st.error ke UI, biarkan aplikasi mencoba lanjut
    
    if 'force_nltk_redownload_flag' in st.session_state:
        del st.session_state['force_nltk_redownload_flag'] # Reset flag
    
    if download_occurred_local and 'nltk_resources_downloaded_this_session' not in st.session_state: # Ganti nama flag
        st.session_state.nltk_resources_downloaded_this_session = True
        logging.info("Resource NLTK telah diunduh/diverifikasi dalam sesi ini.")
        # Tidak st.rerun agar UI lebih stabil saat startup awal

download_nltk_resources()


# Global variable for MongoDB client
mongo_client = None

# MongoDB connection
@st.cache_resource
def init_mongo():
    global mongo_client
    if mongo_client is not None:
        try:
            mongo_client.server_info()
            return mongo_client["sr"]
        except ConnectionFailure:
            logging.warning("Existing MongoDB connection lost. Reconnecting.")
            mongo_client = None
    try:
        MONGO_URI = os.getenv('MONGO_URI', "mongodb://localhost:27017/")
        mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        mongo_client.server_info()
        db = mongo_client["sr"]
        logging.info("✅ Berhasil terhubung ke MongoDB")
        return db
    except ConnectionFailure as e:
        st.error(f"❌ Gagal terhubung ke MongoDB: {e}.")
        logging.error(f"MongoDB connection error: {e}")
    except Exception as e:
        st.error(f"❌ Error tidak terduga saat menghubungkan ke MongoDB: {e}")
        logging.error(f"Unexpected MongoDB connection error: {e}")
    return None

# Fungsi untuk mengambil data dari MongoDB
@st.cache_data(ttl=300)
def fetch_data():
    db = init_mongo()
    if db is None: return pd.DataFrame()
    try:
        collection = db["woman_abuse"]
        data = list(collection.find({}, {"title": 1, "date": 1, "content": 1, "keywords_found": 1, "source": 1, "_id": 0}))
        df = pd.DataFrame(data)
        if df.empty:
            logging.warning("Tidak ada data di MongoDB 'woman_abuse'.")
            return pd.DataFrame()
        df['date'] = pd.to_datetime(df['date'], errors='coerce')
        df.dropna(subset=['date'], inplace=True)
        df['content'] = df['content'].fillna('').astype(str)
        df['title'] = df['title'].fillna('').astype(str)
        df['source'] = df['source'].fillna('Sumber Tidak Diketahui').astype(str).replace('', 'Sumber Tidak Diketahui')
        df['keywords_found'] = df['keywords_found'].apply(lambda x: x if isinstance(x, list) else [])
        return df
    except Exception as e:
        st.error(f"❌ Gagal mengambil/memproses data dari MongoDB: {e}")
        logging.error(f"Error fetching/processing data: {e}", exc_info=True)
    return pd.DataFrame()

def check_sample_data():
    db = init_mongo()
    if db is None: return {"error": "Tidak dapat terhubung ke MongoDB"}
    try:
        collection = db["woman_abuse"]
        sample = list(collection.find({}, {"title": 1, "keywords_found": 1, "content": 1, "source": 1, "date":1, "_id": 1}).limit(5))
        if sample:
            for item in sample:
                if '_id' in item: item['_id'] = str(item['_id'])
                if 'date' in item and isinstance(item['date'], datetime): item['date'] = item['date'].isoformat()
            return sample
        return {"message": "Tidak ada data di koleksi woman_abuse"}
    except Exception as e:
        logging.error(f"Error fetching sample data: {e}")
    return {"error": f"Gagal mengambil sampel data: {str(e)}"}

# --- Fungsi untuk Pemrosesan Teks dan Word Cloud ---
@st.cache_data(ttl=3600)
def get_word_frequencies(_df):
    if _df.empty or ('title' not in _df.columns and 'content' not in _df.columns):
        return Counter()

    text_corpus = ' '.join(_df['title'].astype(str).tolist()) + ' ' + ' '.join(_df['content'].astype(str).tolist())
    text_corpus = text_corpus.lower()
    text_corpus = re.sub(r'http\S+|www\S+|https\S+', '', text_corpus, flags=re.MULTILINE)
    text_corpus = text_corpus.translate(str.maketrans('', '', string.punctuation))
    text_corpus = re.sub(r'\d+', '', text_corpus)
    text_corpus = ' '.join(text_corpus.split())

    tokens = []
    final_tokenizer_method = "NLTK (default)" # Default jika semua percobaan gagal

    # 1. Coba 'indonesian'
    try:
        logging.info("Mencoba tokenisasi dengan NLTK (indonesian).")
        tokens = nltk.word_tokenize(text_corpus, language='indonesian')
        final_tokenizer_method = "NLTK (indonesian)"
        logging.info("Tokenisasi berhasil menggunakan NLTK (indonesian).")
    except LookupError:
        logging.warning("NLTK LookupError untuk model punkt 'indonesian'. Mencoba 'malay'.")
        # 2. Coba 'malay' jika 'indonesian' gagal
        try:
            logging.info("Mencoba tokenisasi dengan NLTK (malay).")
            tokens = nltk.word_tokenize(text_corpus, language='malay')
            final_tokenizer_method = "NLTK (malay)"
            logging.info("Tokenisasi berhasil menggunakan NLTK (malay).")
        except LookupError:
            logging.warning("NLTK LookupError untuk model punkt 'malay'. Mencoba NLTK default (kemungkinan english).")
            # 3. Coba NLTK default (tanpa parameter language) jika 'malay' gagal
            try:
                logging.info("Mencoba tokenisasi dengan NLTK default (tanpa parameter bahasa).")
                tokens = nltk.word_tokenize(text_corpus) 
                final_tokenizer_method = "NLTK (default/english)"
                logging.info("Tokenisasi berhasil menggunakan NLTK default.")
            except Exception as e_default_nltk: 
                logging.error(f"Error saat tokenisasi NLTK default: {e_default_nltk}. Fallback ke regex.")
                tokens = re.findall(r'\b\w+\b', text_corpus)
                final_tokenizer_method = "Regex Fallback (NLTK default error)"
        except Exception as e_malay_nltk: 
            logging.error(f"Error saat tokenisasi NLTK (malay): {e_malay_nltk}. Fallback ke NLTK default.")
            try:
                tokens = nltk.word_tokenize(text_corpus)
                final_tokenizer_method = "NLTK (default/english)"
                logging.info("Tokenisasi berhasil menggunakan NLTK default setelah error pada 'malay'.")
            except Exception as e_final_fallback:
                logging.error(f"Error saat tokenisasi NLTK default (setelah error malay): {e_final_fallback}. Fallback ke regex.")
                tokens = re.findall(r'\b\w+\b', text_corpus)
                final_tokenizer_method = "Regex Fallback (NLTK default error)"
    except Exception as e_indonesian_nltk: 
        logging.error(f"Error saat tokenisasi NLTK (indonesian): {e_indonesian_nltk}. Fallback ke NLTK default.")
        try:
            tokens = nltk.word_tokenize(text_corpus)
            final_tokenizer_method = "NLTK (default/english)"
            logging.info("Tokenisasi berhasil menggunakan NLTK default setelah error pada 'indonesian'.")
        except Exception as e_final_fallback_after_id_error:
            logging.error(f"Error saat tokenisasi NLTK default (setelah error indonesian): {e_final_fallback_after_id_error}. Fallback ke regex.")
            tokens = re.findall(r'\b\w+\b', text_corpus)
            final_tokenizer_method = "Regex Fallback (NLTK default error)"

    if not tokens: 
        logging.warning("Tokenisasi menghasilkan daftar kosong setelah semua upaya NLTK. Menggunakan regex.")
        tokens = re.findall(r'\b\w+\b', text_corpus)
        final_tokenizer_method = "Regex (Final Fallback)"
        if not tokens: 
            logging.error("Tokenisasi regex juga menghasilkan daftar kosong.")
            return Counter()

    # Stopwords - Prioritaskan 'indonesian'
    stop_words_set = set()
    stopwords_language_to_try = 'indonesian'
    final_stopwords_method = "Hanya Custom" 
    try:
        stop_words_set = set(nltk.corpus.stopwords.words(stopwords_language_to_try))
        logging.info(f"Stopwords untuk '{stopwords_language_to_try}' berhasil dimuat.")
        final_stopwords_method = f"NLTK ({stopwords_language_to_try})"
    except LookupError: 
        logging.warning(f"LookupError: NLTK tidak punya stopwords untuk '{stopwords_language_to_try}'. Hanya custom stopwords yang akan digunakan.")
        # Tidak ada st.warning ke UI
    except Exception as e_stopwords:
        logging.error(f"Error memuat stopwords '{stopwords_language_to_try}': {e_stopwords}", exc_info=True)
        # Tidak ada st.error ke UI
    
    custom_stopwords = {
        'detik', 'cnn', 'indonesia', 'com', 'artikel', 'berita', 'antara', 'liputan6', 'kompas', 'tribunnews', 'suara',
        'mengatakan', 'menyebutkan', 'ujar', 'kata', 'menurut', 'yakni', 'tersebut', 'selasa', 'dilansir', 'dikutip',
        'rabu', 'kamis', 'jumat', 'sabtu', 'minggu', 'senin', 'januari', 'februari', 'maret', 'tribun', 'news',
        'april', 'mei', 'juni', 'juli', 'agustus', 'september', 'oktober', 'november', 'desember',
        'wib', 'wit', 'wita', 'pukul', 'tahun', 'lalu', 'usai', 'saat', 'akan', 'agar', 'oleh', 'pada', 'ke',
        'dari', 'di', 'itu', 'ini', 'yang', 'dan', 'rp', 'ada', 'adalah', 'atau', 'jadi', 'juga', 'pun', 'kah',
        'no', 'description', 'baca', 'simak', 'klik', 'hal', 'lain', 'pihak', 'terkait', 'kasus'
    }
    final_stop_words = stop_words_set.union(custom_stopwords)

    filtered_tokens = [
        word for word in tokens if word.isalpha() and word not in final_stop_words and len(word) > 2
    ]
    word_counts = Counter(filtered_tokens)

    if '' in word_counts: del word_counts['']
    if None in word_counts: del word_counts[None]

    logging.info(f"Diproses {len(tokens)} token (tokenizer: {final_tokenizer_method}), ditemukan {len(word_counts)} kata unik relevan (stopwords: {final_stopwords_method}).")
    return word_counts

def generate_wordcloud_image(word_counts):
    if not word_counts: return None
    try:
        wc = WordCloud(width=1000, height=500, background_color=None, mode="RGBA", max_words=150, colormap='viridis', random_state=42)
        wc.generate_from_frequencies(dict(word_counts))
        return wc
    except Exception as e:
        logging.error(f"Error generating word cloud: {e}", exc_info=True)
        st.error(f"Gagal membuat Word Cloud: {e}") 
    return None

# --- Streamlit App Layout ---
st.title("📊 Dashboard Analisis Berita Kekerasan terhadap Perempuan")
st.markdown(
    """
    Selamat datang di dashboard interaktif untuk menganalisis pemberitaan mengenai kekerasan terhadap perempuan.
    Visualisasi di bawah ini membantu memahami tren, topik utama, dan karakteristik berita yang berhasil dikumpulkan dari berbagai sumber media online.
    """
)
st.markdown("---")

# --- Sidebar ---
with st.sidebar:
    st.image("https://srikandi-app.my.id/static/assets/favicon-circle.svg", width=100, use_container_width=True)
    st.header("⚙️ Filter & Info")

    df_main = fetch_data()
    df = pd.DataFrame() 

    if not df_main.empty:
        st.metric("📰 Total Artikel Valid", len(df_main))
        if 'date' in df_main.columns and not df_main['date'].dropna().empty:
            min_date_db = df_main['date'].min()
            max_date_db = df_main['date'].max()
            st.metric("🗓️ Rentang Tanggal Data", f"{min_date_db.strftime('%d %b %Y')} - {max_date_db.strftime('%d %b %Y')}")
            df = df_main.copy()
        else:
            if not df_main.empty:
                 st.warning("Kolom 'date' tidak ada atau kosong di data utama.")
    else:
        st.warning("Tidak ada data valid di database untuk ditampilkan.")

    if not df.empty and 'source' in df.columns:
        available_sources = sorted(df['source'].unique().tolist())
        if available_sources:
            if 'selected_sources_ms' not in st.session_state:
                 st.session_state.selected_sources_ms = available_sources
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Pilih Semua", key="select_all_src_btn", use_container_width=True):
                    st.session_state.selected_sources_ms = available_sources
                    st.rerun()
            with col2:
                if st.button("Hapus Semua", key="deselect_all_src_btn", use_container_width=True):
                    st.session_state.selected_sources_ms = []
                    st.rerun()

            selected_sources = st.multiselect(
                "Pilih Sumber Berita:",
                options=available_sources,
                default=st.session_state.selected_sources_ms, 
                key="selected_sources_multiselect_key"
            )
            if selected_sources != st.session_state.selected_sources_ms:
                st.session_state.selected_sources_ms = selected_sources
                st.rerun() 

            if selected_sources:
                df = df[df['source'].isin(selected_sources)]
            else: 
                if not df.empty : 
                    st.info("Tidak ada sumber berita yang dipilih. Grafik akan kosong.")
                df = pd.DataFrame(columns=df.columns) 
        else: 
             if not df.empty:
                st.info("Tidak ada pilihan sumber berita tersedia dari data yang ada.")
    elif not df_main.empty and 'source' not in df.columns: 
        st.warning("Kolom 'source' tidak ditemukan dalam data untuk filter.")

    st.markdown("---")
    st.header("🛠️ Debugging Data")
    if st.button("Lihat Sampel Data Mentah (MongoDB)", key="sample_data_button"):
        with st.spinner("Mengambil sampel data..."):
            sample_data = check_sample_data()
        st.subheader("Sampel 5 Artikel dari MongoDB")
        if isinstance(sample_data, dict) and "error" in sample_data: st.error(sample_data["error"])
        elif isinstance(sample_data, dict) and "message" in sample_data: st.info(sample_data["message"])
        else: st.json(sample_data, expanded=False)

    st.markdown("---")
    st.caption(f"Data terakhir di-refresh: {datetime.now().strftime('%d %b %Y, %H:%M:%S')}")

# --- Main Content ---
if not df.empty:
    st.markdown("## 📈 Analisis Umum")
    with st.container(border=True): 
        st.subheader("📰 Distribusi Artikel per Sumber Berita")
        if 'source' in df.columns and not df['source'].dropna().empty:
            source_counts = df['source'].value_counts().reset_index()
            source_counts.columns = ['source', 'count']
            if not source_counts.empty:
                fig_source = px.pie(source_counts, names='source', values='count', template='seaborn', color_discrete_sequence=px.colors.qualitative.Pastel1, hole=0.4)
                fig_source.update_layout(legend_title_text='Sumber Berita', legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5), margin=dict(t=20, b=100, l=0, r=0))
                fig_source.update_traces(textposition='inside', textinfo='percent+label', insidetextorientation='radial', hovertemplate="<b>Sumber: %{label}</b><br>Jumlah: %{value}<br>%{percent}<extra></extra>")
                st.plotly_chart(fig_source, use_container_width=True)
            else: st.info("Tidak ada data sumber berita valid untuk ditampilkan (setelah filter).")
        elif 'source' not in df.columns and not df_main.empty : st.warning("Kolom 'source' tidak ada untuk grafik distribusi.")
        elif not df_main.empty : st.info("Tidak ada data sumber berita valid untuk ditampilkan.")

    st.markdown("<br>", unsafe_allow_html=True)
    with st.container(border=True): 
        st.subheader("🔑 Frekuensi Kata Kunci Pencarian Awal")
        if 'keywords_found' in df.columns and not df.empty:
            df_kw_proc = df[df['keywords_found'].apply(lambda x: isinstance(x, list) and len(x) > 0)].copy()
            if not df_kw_proc.empty:
                kw_exploded = df_kw_proc['keywords_found'].explode().dropna().astype(str)
                if not kw_exploded.empty:
                    kw_counts = kw_exploded.value_counts().reset_index()
                    kw_counts.columns = ['keyword', 'count']
                    kw_counts = kw_counts[kw_counts['keyword'].str.strip() != '']
                    if not kw_counts.empty:
                        fig_kw = px.bar(kw_counts.head(15), x='count', y='keyword', orientation='h', labels={'keyword': 'Kata Kunci', 'count': 'Jumlah'}, color='count', color_continuous_scale=px.colors.sequential.Mint, template='seaborn', text='count')
                        fig_kw.update_layout(yaxis={'categoryorder':'total ascending'}, coloraxis_showscale=False, height=500)
                        fig_kw.update_traces(textposition='outside', hovertemplate="<b>Kunci: %{y}</b><br>Jumlah: %{x}<extra></extra>")
                        st.plotly_chart(fig_kw, use_container_width=True)
                    else: st.info("Tidak ada kata kunci pencarian awal valid setelah diproses.")
                else: st.info("Tidak ada kata kunci pencarian awal setelah explode dan dropna.")
            else: st.info("Tidak ada artikel dengan kata kunci pencarian awal yang valid.")
        elif 'keywords_found' not in df.columns and not df_main.empty: st.warning("Kolom 'keywords_found' tidak ada.")
        
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("## 💬 Analisis Teks Berita")
    with st.container(border=True): 
        st.subheader("☁️ Kata Penting dari Judul dan Konten Berita")
        word_counts_data = None
        if not df.empty:
            try:
                with st.spinner("Menganalisis frekuensi kata..."):
                    word_counts_data = get_word_frequencies(df.copy())
            except Exception as e_freq:
                st.error(f"Error saat analisis frekuensi kata: {e_freq}") 
                logging.error("Error during get_word_frequencies call", exc_info=True)
        else: 
            if not df_main.empty: 
                 st.info("Tidak ada data artikel untuk dianalisis (setelah filter).")

        if word_counts_data and len(word_counts_data) > 0:
            col_wc, col_bar_freq = st.columns([2, 3])
            with col_wc:
                st.markdown("##### **Word Cloud**")
                wc_img = generate_wordcloud_image(word_counts_data)
                if wc_img:
                    fig_wc, ax = plt.subplots(figsize=(10,5))
                    ax.imshow(wc_img, interpolation='bilinear')
                    ax.axis('off')
                    fig_wc.patch.set_alpha(0.0)
                    ax.patch.set_alpha(0.0)
                    try:
                        st.pyplot(fig_wc, clear_figure=True, use_container_width=True)
                    except Exception as plt_err:
                        st.error(f"Gagal menampilkan Word Cloud: {plt_err}") 
                        logging.error(f"Error display matplotlib: {plt_err}")
                else: st.warning("Tidak dapat membuat gambar Word Cloud.")
            with col_bar_freq:
                st.markdown("##### **Frekuensi Kata Teratas**")
                top_n = st.slider("Jumlah kata teratas:", 5, 30, 15, 5, key="top_n_slider")
                top_words = word_counts_data.most_common(top_n)
                if top_words:
                    df_top = pd.DataFrame(top_words, columns=['Kata', 'Frekuensi'])
                    if not df_top.empty:
                        fig_bar = px.bar(df_top, x='Frekuensi', y='Kata', orientation='h', labels={'Kata': 'Kata', 'Frekuensi': 'Jumlah'}, template='seaborn', color='Frekuensi', color_continuous_scale=px.colors.sequential.Plasma_r, text='Frekuensi')
                        fig_bar.update_layout(yaxis={'categoryorder':'total ascending'}, coloraxis_showscale=False, height=max(400, top_n * 25))
                        fig_bar.update_traces(textposition='outside', hovertemplate="<b>Kata: %{y}</b><br>Jumlah: %{x}<extra></extra>")
                        st.plotly_chart(fig_bar, use_container_width=True)
                    else: st.info("Tidak ada kata valid yang cukup sering muncul.")
                else: st.info("Tidak ada kata yang cukup sering muncul.")
        elif not df.empty: 
            st.info("Tidak ada kata signifikan ditemukan untuk dianalisis (mungkin semua tersaring atau teks terlalu pendek).")
else: 
    st.warning("⚠️ Tidak ada data valid ditemukan di database atau setelah filter. Pastikan scraper berjalan atau sesuaikan filter.")

st.markdown("---")
st.caption("Dashboard Analisis Pemberitaan Kekerasan terhadap Perempuan | Dibuat dengan Streamlit")