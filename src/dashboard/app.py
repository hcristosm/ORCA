"""Dashboard local do ORCA: setores de risco geológico (CPRM/SGB) x chuva (INMET)."""

from __future__ import annotations

import sys
from pathlib import Path

_RAIZ_PROJETO = Path(__file__).resolve().parents[2]
if str(_RAIZ_PROJETO) not in sys.path:
    sys.path.insert(0, str(_RAIZ_PROJETO))

import folium
import geopandas as gpd
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

from src.config import (
    DATA_DIR,
    LIMIAR_ATENCAO_MM_PADRAO,
    UFS_DISPONIVEIS,
    caminho_chuva,
    caminho_setores,
)
from src.ingest.cprm import ingerir_uf as ingerir_cprm
from src.ingest.inmet import ingerir_uf as ingerir_inmet
from src.processing.cruzamento import calcular_cruzamento, sinalizar_atencao
from src.storage import chuva_existe, ler_chuva, ler_setores, setores_existem

CORES_GRAU_RISCO = {
    "alto": "#ec835a",       # status "serious"
    "muito alto": "#d03b3b",  # status "critical"
}
COR_PADRAO = "#9a9a94"
COR_CHUVA = "#256abf"  # sequencial azul, passo 500

st.set_page_config(page_title="ORCA — Risco geológico x chuva", layout="wide")


@st.cache_data(show_spinner=False)
def _carregar_setores(uf: str) -> gpd.GeoDataFrame:
    caminho = caminho_setores(uf, DATA_DIR)
    if not setores_existem(caminho):
        return ingerir_cprm(uf, caminho)
    return ler_setores(caminho)


@st.cache_data(show_spinner=False)
def _carregar_chuva(uf: str, ano: int) -> pd.DataFrame:
    caminho = caminho_chuva(uf, ano, DATA_DIR)
    if not chuva_existe(caminho):
        return ingerir_inmet(uf, ano, DATA_DIR)
    return ler_chuva(caminho)


def _mtimes_dados(uf: str, ano: int) -> tuple[float, float]:
    """Timestamps de modificação dos arquivos locais de setores e chuva (0.0 se ausentes).

    Usado para detectar que outro processo (cron diário, `orca atualizar` manual)
    atualizou os dados em disco enquanto o dashboard está aberto.
    """
    caminho_s = caminho_setores(uf, DATA_DIR)
    caminho_c = caminho_chuva(uf, ano, DATA_DIR)
    mtime_s = caminho_s.stat().st_mtime if caminho_s.exists() else 0.0
    mtime_c = caminho_c.stat().st_mtime if caminho_c.exists() else 0.0
    return mtime_s, mtime_c


def _info_ultima_atualizacao() -> str | None:
    marcador = DATA_DIR / "ultima_atualizacao.txt"
    if not marcador.exists():
        return None
    return marcador.read_text().strip()


def _verificar_dados_atualizados(uf: str, ano: int) -> None:
    """Corpo do fragmento de verificação automática: recarrega a página se os
    arquivos locais mudaram desde a última checagem nesta sessão."""
    atual = _mtimes_dados(uf, ano)
    anterior = st.session_state.get("_mtimes_dados")
    st.session_state["_mtimes_dados"] = atual
    if anterior is not None and anterior != atual:
        st.cache_data.clear()
        st.rerun()


def _cor_por_grau(grau: str | None) -> str:
    if grau is None:
        return COR_PADRAO
    return CORES_GRAU_RISCO.get(str(grau).strip().lower(), COR_PADRAO)


def _construir_mapa(cruzado: gpd.GeoDataFrame) -> folium.Map:
    bounds = cruzado.total_bounds  # minx, miny, maxx, maxy
    centro = [(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2]
    mapa = folium.Map(location=centro, zoom_start=8, tiles="CartoDB positron")

    exibicao = cruzado.copy()
    for col in ("chuva_24h", "chuva_72h", "distancia_km"):
        if col in exibicao.columns:
            exibicao[col] = exibicao[col].round(1)

    def estilo(feature):
        props = feature["properties"]
        cor = _cor_por_grau(props.get("grau_risco"))
        em_atencao = props.get("em_atencao")
        return {
            "fillColor": cor,
            "color": "#1a1a19" if em_atencao else cor,
            "weight": 3 if em_atencao else 1,
            "fillOpacity": 0.75,
        }

    campos = ["munic", "num_setor", "grau_risco", "distancia_km", "chuva_24h", "chuva_72h"]
    aliases = [
        "Município:", "Setor:", "Grau de risco:", "Estação a (km):",
        "Chuva 24h (mm):", "Chuva 72h (mm):",
    ]
    campos = [c for c in campos if c in exibicao.columns]
    aliases = aliases[: len(campos)]

    folium.GeoJson(
        data=exibicao.to_json(),
        style_function=estilo,
        tooltip=folium.GeoJsonTooltip(fields=campos, aliases=aliases, sticky=True),
    ).add_to(mapa)

    legenda_html = """
    <div style="position: fixed; bottom: 30px; left: 30px; z-index: 1000;
                background: white; padding: 10px 14px; border-radius: 6px;
                box-shadow: 0 1px 4px rgba(0,0,0,0.3); font-size: 13px;">
      <b>Grau de risco</b><br>
      <span style="color:#ec835a;">&#9632;</span> Alto<br>
      <span style="color:#d03b3b;">&#9632;</span> Muito alto<br>
      <span style="border:2px solid #1a1a19; padding:0 4px;">&#9632;</span> Em atenção (chuva acima do limiar)
    </div>
    """
    mapa.get_root().html.add_child(folium.Element(legenda_html))
    return mapa


def main() -> None:
    st.title("ORCA — Setores de risco geológico x chuva recente")
    st.caption(
        "Fontes: setores de risco da CPRM/SGB (ArcGIS REST) e chuva horária do INMET "
        "(pacote histórico anual, sem captcha). Dados públicos podem estar defasados — "
        "ver limitações no README."
    )

    st.sidebar.header("Filtros")
    uf = st.sidebar.selectbox("UF", UFS_DISPONIVEIS)
    ano = st.sidebar.number_input("Ano dos dados de chuva (INMET)", min_value=2020, max_value=2026, value=2026)

    if st.sidebar.button("Baixar/atualizar dados agora"):
        with st.spinner("Baixando dados da CPRM/SGB e do INMET..."):
            ingerir_cprm(uf, caminho_setores(uf, DATA_DIR))
            ingerir_inmet(uf, ano, DATA_DIR)
        st.cache_data.clear()
        st.rerun()

    info_atualizacao = _info_ultima_atualizacao()
    if info_atualizacao:
        st.sidebar.caption(f"Última atualização automática (cron):\n\n```\n{info_atualizacao}\n```")

    auto_atualizar = st.sidebar.checkbox(
        "Verificar novos dados automaticamente",
        value=False,
        help=(
            "Não baixa dados novos das fontes — apenas detecta, em segundo plano, "
            "se outro processo (o cron diário ou um `orca atualizar` manual) "
            "já atualizou os arquivos em data/ e recarrega a página."
        ),
    )
    if auto_atualizar:
        intervalo_min = st.sidebar.slider("Verificar a cada (min)", 1, 30, 5)
        st.fragment(run_every=intervalo_min * 60)(_verificar_dados_atualizados)(uf, ano)

    if not setores_existem(caminho_setores(uf, DATA_DIR)) or not chuva_existe(
        caminho_chuva(uf, ano, DATA_DIR)
    ):
        st.warning(
            "Ainda não há dados locais para essa UF/ano. Clique em "
            "'Baixar/atualizar dados agora' na barra lateral."
        )
        st.stop()

    with st.spinner("Carregando dados locais..."):
        setores = _carregar_setores(uf)
        chuva = _carregar_chuva(uf, ano)

    municipios = sorted(setores["munic"].dropna().unique())
    municipios_selecionados = st.sidebar.multiselect("Município", municipios, default=[])

    janela = st.sidebar.radio("Janela de chuva acumulada", [24, 72], index=1, format_func=lambda h: f"{h}h")
    limiar_mm = st.sidebar.slider(
        f"Limiar de atenção — chuva acumulada em {janela}h (mm)",
        min_value=0, max_value=300, value=int(LIMIAR_ATENCAO_MM_PADRAO), step=5,
    )
    st.sidebar.caption(
        "100mm/72h é uma referência ilustrativa comum na literatura de risco de "
        "deslizamento — não é um limiar oficial calibrado para estes setores. Ajuste "
        "livremente."
    )

    setores_filtrados = setores
    if municipios_selecionados:
        setores_filtrados = setores[setores["munic"].isin(municipios_selecionados)]

    if setores_filtrados.empty:
        st.warning("Nenhum setor encontrado para o filtro atual.")
        st.stop()

    cruzado = calcular_cruzamento(setores_filtrados, chuva, janelas=(24, 72))
    cruzado = sinalizar_atencao(cruzado, limiar_mm=limiar_mm, coluna_chuva=f"chuva_{janela}h")

    st.caption(
        f"Chuva acumulada calculada em relação à leitura mais recente disponível no "
        f"INMET: **{cruzado.attrs['referencia']}** (pode estar alguns dias atrás da "
        f"data de hoje — ver README)."
    )

    col_mapa, col_atencao = st.columns([2, 1])

    with col_mapa:
        st.subheader(f"Mapa de setores de risco — {len(cruzado)} setores")
        st_folium(_construir_mapa(cruzado), width=None, height=560, returned_objects=[])

    with col_atencao:
        st.subheader("Setores em atenção")
        em_atencao = cruzado[cruzado["em_atencao"]].sort_values(f"chuva_{janela}h", ascending=False)
        if em_atencao.empty:
            st.info("Nenhum setor ultrapassa o limiar configurado no momento.")
        else:
            st.dataframe(
                em_atencao[["munic", "num_setor", "grau_risco", f"chuva_{janela}h", "distancia_km"]]
                .rename(columns={
                    "munic": "Município", "num_setor": "Setor", "grau_risco": "Grau de risco",
                    f"chuva_{janela}h": f"Chuva {janela}h (mm)", "distancia_km": "Estação a (km)",
                })
                .reset_index(drop=True),
                use_container_width=True,
            )

    st.subheader("Série temporal de chuva por estação")
    estacoes = (
        chuva[["codigo_estacao", "nome_estacao"]]
        .drop_duplicates()
        .sort_values("nome_estacao")
    )
    rotulos = {
        row.codigo_estacao: f"{row.nome_estacao} ({row.codigo_estacao})"
        for row in estacoes.itertuples()
    }
    codigo_selecionado = st.selectbox(
        "Estação", options=list(rotulos.keys()), format_func=lambda c: rotulos[c]
    )
    serie = chuva[chuva["codigo_estacao"] == codigo_selecionado].sort_values("data_hora")

    fig = go.Figure()
    fig.add_bar(x=serie["data_hora"], y=serie["chuva_mm"], marker_color=COR_CHUVA, name="Chuva horária (mm)")
    fig.update_layout(
        xaxis_title="Data/hora (UTC)",
        yaxis_title="Chuva horária (mm)",
        showlegend=False,
        margin=dict(l=10, r=10, t=10, b=10),
        height=350,
    )
    st.plotly_chart(fig, use_container_width=True)


if __name__ == "__main__":
    main()
