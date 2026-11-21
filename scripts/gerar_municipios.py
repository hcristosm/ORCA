"""Gera docs/dashboard/municipios.json: todos os municípios do IBGE com um ponto.

Uso (só quando o IBGE criar ou renomear município; o arquivo vai no git):

    .venv/bin/python scripts/gerar_municipios.py

A busca do dashboard usa este arquivo para achar município SEM setor da CPRM
(São Paulo, Rio, Petrópolis...): sem ele, digitar o nome não achava nada.
O ponto é o centroide do polígono, ou um ponto interno quando o centroide cai
fora (município em forma de meia-lua), e serve de centro no mapa e na tela Perto.

Arquivo estático de propósito: o dashboard não passa a depender do IBGE no ar.
A cobertura da CPRM NÃO vai aqui; o front-end a calcula com os dados do dia.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import geopandas as gpd
import requests

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "docs" / "dashboard" / "municipios.json"

URL_NOMES = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
URL_MALHA = (
    "https://servicodados.ibge.gov.br/api/v3/malhas/paises/BR"
    "?formato=application/vnd.geo+json&qualidade=minima&intrarregiao=municipio"
)
TIMEOUT = 180


def _uf(municipio: dict) -> str:
    # Município criado depois de 2017 pode vir sem microrregião.
    micro = municipio.get("microrregiao")
    if micro:
        return micro["mesorregiao"]["UF"]["sigla"].lower()
    return municipio["regiao-imediata"]["regiao-intermediaria"]["UF"]["sigla"].lower()


def main() -> None:
    nomes = requests.get(URL_NOMES, timeout=TIMEOUT)
    nomes.raise_for_status()
    malha = requests.get(URL_MALHA, timeout=TIMEOUT)
    malha.raise_for_status()

    poligonos = gpd.GeoDataFrame.from_features(malha.json()["features"], crs="EPSG:4326")
    # Centroide em graus é aproximado, mas a escala de município basta.
    centroides = poligonos.geometry.centroid
    internos = poligonos.geometry.representative_point()
    dentro = centroides.within(poligonos.geometry)
    pontos = dict(zip(
        poligonos["codarea"].astype(str),
        centroides.where(dentro, internos),
        strict=True,
    ))

    linhas = []
    sem_malha = []
    for m in nomes.json():
        ponto = pontos.get(str(m["id"]))
        if ponto is None:
            sem_malha.append(f"{m['nome']} ({_uf(m).upper()})")
            continue
        linhas.append([_uf(m), m["nome"], round(ponto.y, 4), round(ponto.x, 4)])

    # Sem município nenhum é o IBGE falhando, não o Brasil sem municípios.
    if len(linhas) < 5000:
        raise SystemExit(f"Só {len(linhas)} municípios com malha; nada gravado.")
    linhas.sort(key=lambda linha: (linha[0], linha[1]))
    SAIDA.write_text(json.dumps({
        "gerado_em": datetime.now(UTC).date().isoformat(),
        "fonte": "IBGE (localidades v1 e malhas v3)",
        "campos": ["uf", "nome", "lat", "lon"],
        "municipios": linhas,
    }, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    print(f"{len(linhas)} municípios gravados em {SAIDA.relative_to(RAIZ)}.")
    if sem_malha:
        print(f"Sem polígono na malha (fora do arquivo): {', '.join(sem_malha)}")


if __name__ == "__main__":
    main()
