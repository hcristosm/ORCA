"""Testes da mescla não-destrutiva (spec §4.5).

O passo de mescla vira a rede de segurança da publicação e, por isso, o
ponto único mais perigoso do sistema (§6). Estes testes cobrem a parte
que dá pra exercitar sem git nem rede: a cópia por UF e a reconciliação
do `ufs_disponiveis.json`, que é o que o front-end lê pra montar o
seletor de UF.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import mesclar_publicado as mp  # noqa: E402


def _escrever_uf(diretorio: Path, uf: str, marca: str, com_previsao: bool = True) -> None:
    diretorio.mkdir(parents=True, exist_ok=True)
    (diretorio / f"meta_{uf}.json").write_text(json.dumps({"marca": marca}))
    (diretorio / f"series_{uf}.json").write_text(json.dumps([marca]))
    (diretorio / f"setores_{uf}.geojson").write_text(json.dumps({"marca": marca}))
    if com_previsao:
        (diretorio / f"previsao_{uf}.json").write_text(json.dumps({"marca": marca}))


def _montar(base: Path, publicadas: list[str], atuais: list[str]) -> tuple[Path, Path]:
    pub, atual = base / "pub", base / "atual"
    for uf in publicadas:
        _escrever_uf(pub, uf, "velho")
    mp.escrever_indice(pub / mp.INDICE, publicadas)
    for uf in atuais:
        _escrever_uf(atual, uf, "novo")
    atual.mkdir(parents=True, exist_ok=True)
    mp.escrever_indice(atual / mp.INDICE, atuais)
    return pub, atual


def test_uf_ausente_no_run_e_preservada(tmp_path):
    pub, atual = _montar(tmp_path, ["sp", "rj"], ["sp"])
    preservadas = mp.mesclar(pub, atual, {"sp", "rj"})
    assert preservadas == ["rj"]
    assert json.loads((atual / "meta_rj.json").read_text()) == {"marca": "velho"}


def test_uf_presente_no_run_nao_e_sobrescrita_pela_publicada(tmp_path):
    pub, atual = _montar(tmp_path, ["sp"], ["sp"])
    assert mp.mesclar(pub, atual, {"sp"}) == []
    assert json.loads((atual / "meta_sp.json").read_text()) == {"marca": "novo"}


def test_indice_reconcilia_run_mais_preservadas(tmp_path):
    pub, atual = _montar(tmp_path, ["sp", "rj", "mg"], ["sp"])
    mp.mesclar(pub, atual, {"sp", "rj", "mg"})
    assert json.loads((atual / mp.INDICE).read_text()) == ["mg", "rj", "sp"]


def test_indice_nao_regride_quando_run_cresce(tmp_path):
    pub, atual = _montar(tmp_path, ["sp"], ["sp", "rj"])
    assert mp.mesclar(pub, atual, {"sp", "rj"}) == []
    assert json.loads((atual / mp.INDICE).read_text()) == ["rj", "sp"]


def test_uf_fora_do_escopo_sai_do_dashboard(tmp_path):
    # Uma UF legitimamente retirada do dados-base precisa poder sumir:
    # preservar tudo pra sempre congelaria dado morto no ar.
    pub, atual = _montar(tmp_path, ["sp", "rj"], ["sp"])
    assert mp.mesclar(pub, atual, {"sp"}) == []
    assert json.loads((atual / mp.INDICE).read_text()) == ["sp"]
    assert not (atual / "meta_rj.json").exists()


def test_uf_no_indice_publicado_sem_arquivos_nao_entra(tmp_path):
    pub, atual = _montar(tmp_path, ["sp", "rj"], ["sp"])
    for arquivo in pub.glob("*_rj.*"):
        arquivo.unlink()
    assert mp.mesclar(pub, atual, {"sp", "rj"}) == []
    assert json.loads((atual / mp.INDICE).read_text()) == ["sp"]


def test_uf_sem_previsao_ainda_e_preservada(tmp_path):
    pub, atual = _montar(tmp_path, ["sp"], ["rj"])
    (pub / "previsao_sp.json").unlink()
    assert mp.mesclar(pub, atual, {"sp", "rj"}) == ["sp"]
    assert (atual / "meta_sp.json").exists()
    assert not (atual / "previsao_sp.json").exists()


def test_residuo_de_geracao_antiga_nao_e_ressuscitado(tmp_path):
    # vento_* saiu do escopo em §4.1 mas continua no gh-pages.
    pub, atual = _montar(tmp_path, ["sp"], ["rj"])
    (pub / "vento_sp.geojson").write_text("{}")
    mp.mesclar(pub, atual, {"sp", "rj"})
    assert not (atual / "vento_sp.geojson").exists()


def test_indice_publicado_ilegivel_nao_derruba_a_mescla(tmp_path):
    pub, atual = _montar(tmp_path, ["sp"], ["rj"])
    (pub / mp.INDICE).write_text("isto não é json")
    assert mp.mesclar(pub, atual, {"sp", "rj"}) == []
    assert json.loads((atual / mp.INDICE).read_text()) == ["rj"]


def test_indice_publicado_com_caixa_alta_e_normalizado(tmp_path):
    pub, atual = _montar(tmp_path, ["sp"], ["rj"])
    mp.escrever_indice(pub / mp.INDICE, ["SP"])
    assert mp.mesclar(pub, atual, {"sp", "rj"}) == ["sp"]


def test_main_recusa_run_sem_indice(tmp_path, capsys):
    pub, atual = _montar(tmp_path, ["sp"], [])
    (atual / mp.INDICE).unlink()
    assert mp.main(["--publicado", str(pub), "--atual", str(atual), "--escopo", str(tmp_path)]) == 1
    assert not (atual / "meta_sp.json").exists()


def test_main_recusa_run_com_indice_vazio(tmp_path):
    # `exportar_nacional` grava o índice mesmo com zero sucessos: mesclar
    # aqui publicaria 27 UFs de dado velho como se fossem novas.
    pub, atual = _montar(tmp_path, ["sp", "rj"], [])
    assert mp.main(["--publicado", str(pub), "--atual", str(atual), "--escopo", str(tmp_path)]) == 1
    assert json.loads((atual / mp.INDICE).read_text()) == []
    assert not (atual / "meta_sp.json").exists()


def test_main_mescla_e_usa_os_gpkg_como_escopo(tmp_path):
    pub, atual = _montar(tmp_path, ["sp", "rj"], ["sp"])
    escopo = tmp_path / "data"
    escopo.mkdir()
    for uf in ("sp", "rj"):
        (escopo / f"risco_{uf}.gpkg").write_bytes(b"")
    assert mp.main(["--publicado", str(pub), "--atual", str(atual), "--escopo", str(escopo)]) == 0
    assert json.loads((atual / mp.INDICE).read_text()) == ["rj", "sp"]


def test_ufs_no_escopo_le_os_gpkg(tmp_path):
    (tmp_path / "risco_sp.gpkg").write_bytes(b"")
    (tmp_path / "risco_rj.gpkg").write_bytes(b"")
    (tmp_path / "chuva_sp_2026.csv").write_text("")
    assert mp.ufs_no_escopo(tmp_path) == {"sp", "rj"}
