import streamlit as st
import folium
import requests
import pandas as pd
import plotly.express as px
import unicodedata
import re
from streamlit_folium import st_folium
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut
from folium.plugins import MarkerCluster, HeatMap

st.set_page_config(layout="wide", page_title="🗺️ CEPs SP - Dashboard")

st.markdown("""
<style>
  .reportview-container, .sidebar-content {
    background-color: #1e1e2e !important;
    color: #e0e0e0 !important;
  }
  .main-header {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    padding: 2rem; border-radius: 15px; margin-bottom: 1rem;
    box-shadow: 0 10px 30px rgba(0,0,0,0.3); text-align: center;
  }
  .main-header h1, .main-header p {
    color: white !important;
    text-shadow: 2px 2px 4px rgba(0,0,0,0.5);
  }
  .stButton > button {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white; border: none; border-radius: 25px;
    padding: 0.75rem 2rem; font-weight: bold;
    box-shadow: 0 4px 15px rgba(102,126,234,0.4);
    transition: transform .2s;
  }
  .stButton > button:hover {
    transform: scale(1.05);
  }
  .stMetric {
    background-color: rgba(255,255,255,0.1) !important;
    border-radius: 8px;
    padding: 0.75rem;
  }
  .stMetric > div[data-testid="stMetricValue"] {
    color: white !important;
    font-size: 2rem;
  }
  .stMetric > div[data-testid="stMetricLabel"] {
    color: #c0c0c0 !important;
  }
</style>
""", unsafe_allow_html=True)

st.markdown(
    "<div class='main-header'><h1>🗺️ Dashboard de CEPs de São Paulo</h1>"
    "<p>Analytics completo com mapas, heatmap e métricas em tempo real</p></div>",
    unsafe_allow_html=True
)

if 'locations' not in st.session_state:
    st.session_state.locations = []
if 'heatmap' not in st.session_state:
    st.session_state.heatmap = False

ZONAS_BAIRROS = {
    "Norte": ["Anhanguera","Brasilândia","Cachoeirinha","Casa Verde","Freguesia do Ó","Jaçanã","Jaraguá","Limão","Mandaqui","Perus","Pirituba","Santana","Tremembé","Tucuruvi","Vila Guilherme","Vila Maria","Vila Medeiros"],
    "Sul": ["Campo Belo","Campo Grande","Campo Limpo","Capão Redondo","Cidade Ademar","Cidade Dutra","Grajaú","Interlagos","Jabaquara","Jardim Ângela","Jardim São Luís","Marsilac","Parelheiros","Pedreira","Santo Amaro","Socorro","Vila Andrade","Vila Mariana","Moema","Saúde"],
    "Leste": ["Água Rasa","Aricanduva","Artur Alvim","Belém","Brás","Cangaíba","Carrão","Cidade Líder","Cidade Tiradentes","Ermelino Matarazzo","Guaianases","Iguatemi","Itaim Paulista","Itaquera","Jardim Helena","José Bonifácio","Mooca","Parque do Carmo","Penha","Ponte Rasa","Sapopemba","Tatuapé"],
    "Oeste": ["Alto de Pinheiros","Barra Funda","Butantã","Jaguaré","Jardim Paulista","Lapa","Morumbi","Perdizes","Pinheiros","Rio Pequeno","Vila Leopoldina","Vila Madalena","Vila Sônia","Itaim Bibi"],
    "Centro": ["Aclimação","Bela Vista","Bom Retiro","Cambuci","Consolação","Higienópolis","Liberdade","República","Santa Cecília","Sé"]
}
ZONE_COLORS = {
    "Norte": "#FF6B6B","Sul": "#4ECDC4",
    "Leste": "#45B7D1","Oeste": "#96CEB4",
    "Centro": "#FFEAA7","Indefinida": "#CCCCCC"
}

def normalize_string(s):
    if not isinstance(s, str): return ""
    s = s.strip().lower()
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')

def get_zone(cep, neighborhood, city, lat, lon):
    if normalize_string(city) != "sao paulo":
        return "Indefinida"
    nb = normalize_string(neighborhood)
    for zone, bairros in ZONAS_BAIRROS.items():
        if any(normalize_string(b) in nb for b in bairros):
            return zone
    cep_i = int(cep.replace("-", ""))
    ranges = {
      "Centro": (1000000,1099999),
      "Norte": (2000000,2999999),
      "Leste": (3000000,3999999),
      "Sul":   (4000000,4999999),
      "Oeste": (5000000,5999999)
    }
    for z,(a,b) in ranges.items():
        if a <= cep_i <= b:
            return z
    return "Indefinida"

@st.cache_data(show_spinner=False, ttl=3600)
def get_coords_from_cep(cep: str):
    cep_clean = cep.replace("-", "")
    if any(loc['cep']==cep_clean for loc in st.session_state.locations):
        return None, "CEP já adicionado"
    try:
        resp = requests.get(f"https://brasilapi.com.br/api/cep/v2/{cep_clean}", timeout=5)
        if resp.status_code==200:
            d = resp.json()
            loc = d.get("location")
            if loc and loc.get("type")=="Point":
                coord = loc["coordinates"]
                return {
                  "cep":d["cep"], "street":d.get("street","N/I"),
                  "neighborhood":d.get("neighborhood","N/I"), "city":d.get("city",""),
                  "lat": coord["latitude"], "lon": coord["longitude"],
                  "source":"BrasilAPI"
                }, None
    except: pass
    try:
        resp = requests.get(f"https://viacep.com.br/ws/{cep_clean}/json/", timeout=5)
        d = resp.json()
        if resp.status_code==200 and 'erro' not in d:
            addr = f"{d['logradouro']}, {d['localidade']}"
            geoloc = Nominatim(user_agent="app").geocode(addr, timeout=10)
            if not geoloc:
                addr = f"{d['logradouro']}, {d['bairro']}, {d['localidade']}, {d['uf']}, Brasil"
                geoloc = Nominatim(user_agent="app").geocode(addr, timeout=10)
            if geoloc:
                return {
                  "cep":d["cep"], "street":d.get("logradouro","N/I"),
                  "neighborhood":d.get("bairro","N/I"), "city":d.get("localidade",""),
                  "lat": geoloc.latitude, "lon": geoloc.longitude,
                  "source":"ViaCEP + Nominatim"
                }, None
    except: pass
    return None, "CEP não encontrado"

total = len(st.session_state.locations)
zones = len({loc['zone'] for loc in st.session_state.locations})
last = st.session_state.locations[-1]['cep'] if total>0 else "—"
c1, c2, c3, c4 = st.columns(4)
c1.metric("CEPs Totais", total)
c2.metric("Zonas Diferentes", zones)
c3.metric("Fontes Usadas", len({loc['source'] for loc in st.session_state.locations}))
c4.metric("Último CEP", last)
st.markdown("---")

left, right = st.columns([1,2])
with left:
    ceps_input = st.text_area("Insira CEPs separados por vírgula:", placeholder="Ex: 00000-000 ou 00000000", height=80)
    if st.button("📍 Adicionar Marcadores", use_container_width=True):
        if ceps_input:
            for cep_item in ceps_input.split(","):
                cep_clean = cep_item.strip()
                if cep_clean.replace("-", "").isdigit() and len(cep_clean.replace("-", ""))==8:
                    loc, err = get_coords_from_cep(cep_clean)
                    if loc:
                        loc['zone'] = get_zone(loc['cep'], loc['neighborhood'], loc['city'], loc['lat'], loc['lon'])
                        st.session_state.locations.append(loc)
                        st.success(f"✔️ CEP {loc['cep']} adicionado ({loc['city'] or 'Sem Cidade'})")
                    else:
                        st.error(f"❌ {cep_clean}: {err}")
                else:
                    st.warning(f"⚠️ {cep_clean} não é um CEP válido.")
        else:
            st.warning("Digite pelo menos um CEP.")
    st.checkbox("🔆 Exibir Heatmap", key="heatmap")

    if st.session_state.locations:
        st.markdown("---")
        st.subheader("CEPs Adicionados")
        for idx, loc in enumerate(st.session_state.locations):
            colA, colB = st.columns([3,1])
            with colA:
                st.write(f"**{loc['cep']}** — {loc['neighborhood']} ({loc['zone']}) - {loc['city']}")
            with colB:
                if st.button("X", key=f"remove_{idx}", help="Remover este CEP"):
                    st.session_state.locations.pop(idx)
                    st.experimental_rerun()

with right:
    center = [-23.5505, -46.6333]
    zoom = 11
    if total>0:
        center = [st.session_state.locations[-1]['lat'], st.session_state.locations[-1]['lon']]
        zoom = 14
    m = folium.Map(location=center, zoom_start=zoom, tiles="OpenStreetMap")
    if st.session_state.heatmap:
        pts = [[loc['lat'], loc['lon']] for loc in st.session_state.locations]
        HeatMap(pts, radius=25).add_to(m)
    cluster = MarkerCluster().add_to(m)
    for loc in st.session_state.locations:
        color = ZONE_COLORS.get(loc['zone'], "#CCCCCC")
        folium.CircleMarker(
            [loc['lat'], loc['lon']],
            radius=7, color=color, fill=True, fill_opacity=0.8,
            popup=f"CEP: {loc['cep']}<br>{loc['street']}, {loc['neighborhood']}",
            tooltip=loc['zone']
        ).add_to(cluster)
    st_folium(m, width="100%", height=500)

if total>0:
    st.markdown("---")
    st.header("📊 Análise de CEPs")
    df = pd.DataFrame(st.session_state.locations)
    df['in_sp'] = df['city'].apply(lambda x: normalize_string(x) == "sao paulo")
    sp_vs = df['in_sp'].map({True:"São Paulo",False:"Fora SP"}).value_counts().reset_index()
    sp_vs.columns = ["Localização","Quantidade"]
    zn = df[df['in_sp']].copy()
    zn = zn['zone'].value_counts().reset_index()
    zn.columns = ["Zona","Quantidade"]
    nb = df[df['in_sp']]['neighborhood'].value_counts().reset_index().head(10)
    nb.columns = ["Bairro","Quantidade"]

    r1, r2 = st.columns(2)
    with r1:
        st.plotly_chart(px.pie(sp_vs, names="Localização", values="Quantidade", hole=0.4, title="SP vs Outras"), use_container_width=True)
        st.plotly_chart(px.bar(zn, x="Zona", y="Quantidade", text="Quantidade",
                              color="Zona", color_discrete_map=ZONE_COLORS, title="CEPs por Zona"), use_container_width=True)
    with r2:
        st.plotly_chart(px.pie(zn, names="Zona", values="Quantidade", hole=0.4,
                   title="Distribuição de CEPs por Zona", color_discrete_map=ZONE_COLORS), use_container_width=True)
        st.plotly_chart(px.pie(nb, names="Bairro", values="Quantidade", title="Top 10 Bairros"), use_container_width=True)

    st.markdown("---")
    st.subheader("Detalhes dos CEPs")
    st.dataframe(df[['cep','street','neighborhood','zone','city','source','lat','lon']], use_container_width=True, hide_index=True)
    csv = df.to_csv(index=False).encode('utf-8')
    st.download_button("📥 Baixar CSV", csv, f"ceps_sp_{pd.Timestamp('today').strftime('%Y%m%d')}.csv", "text/csv")
