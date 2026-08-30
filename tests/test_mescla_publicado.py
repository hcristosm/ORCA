"""Testes da mescla não-destrutiva (spec §4.5).

O passo de mescla vira a rede de segurança da publicação e, por isso, o
ponto único mais perigoso do sistema (§6). Estes testes cobrem a parte
que dá pra exercitar sem git nem rede: a cópia por UF e a reconciliação
do `ufs_disponiveis.json`, que é o que o front-end lê pra montar o
seletor de UF.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import mesclar_publicado as mp


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
    preservadas, _ = mp.mesclar(pub, atual, {"sp", "rj"})
    assert preservadas == ["rj"]
    assert json.loads((atual / "meta_rj.json").read_text()) == {"marca": "velho"}


def test_uf_presente_no_run_nao_e_sobrescrita_pela_publicada(tmp_path):
    pub, atual = _montar(tmp_path, ["sp"], ["sp"])
    assert mp.mesclar(pub, atual, {"sp"})[0] == []
    assert json.loads((atual / "meta_sp.json").read_text()) == {"marca": "novo"}


def test_indice_reconcilia_run_mais_preservadas(tmp_path):
    pub, atual = _montar(tmp_path, ["sp", "rj", "mg"], ["sp"])
    mp.mesclar(pub, atual, {"sp", "rj", "mg"})
    assert json.loads((atual / mp.INDICE).read_text()) == ["mg", "rj", "sp"]


def test_indice_nao_regride_quando_run_cresce(tmp_path):
    pub, atual = _montar(tmp_path, ["sp"], ["sp", "rj"])
    assert mp.mesclar(pub, atual, {"sp", "rj"})[0] == []
    assert json.loads((atual / mp.INDICE).read_text()) == ["rj", "sp"]


def test_uf_fora_do_escopo_sai_do_dashboard(tmp_path):
    # Uma UF legitimamente retirada do dados-base precisa poder sumir:
    # preservar tudo pra sempre congelaria dado morto no ar.
    pub, atual = _montar(tmp_path, ["sp", "rj"], ["sp"])
    assert mp.mesclar(pub, atual, {"sp"})[0] == []
    assert json.loads((atual / mp.INDICE).read_text()) == ["sp"]
    assert not (atual / "meta_rj.json").exists()


def test_uf_no_indice_publicado_sem_arquivos_nao_entra(tmp_path):
    pub, atual = _montar(tmp_path, ["sp", "rj"], ["sp"])
    for arquivo in pub.glob("*_rj.*"):
        arquivo.unlink()
    assert mp.mesclar(pub, atual, {"sp", "rj"})[0] == []
    assert json.loads((atual / mp.INDICE).read_text()) == ["sp"]


def test_uf_sem_previsao_ainda_e_preservada(tmp_path):
    pub, atual = _montar(tmp_path, ["sp"], ["rj"])
    (pub / "previsao_sp.json").unlink()
    assert mp.mesclar(pub, atual, {"sp", "rj"})[0] == ["sp"]
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
    assert mp.mesclar(pub, atual, {"sp", "rj"})[0] == []
    assert json.loads((atual / mp.INDICE).read_text()) == ["rj"]


def test_indice_publicado_com_caixa_alta_e_normalizado(tmp_path):
    pub, atual = _montar(tmp_path, ["sp"], ["rj"])
    mp.escrever_indice(pub / mp.INDICE, ["SP"])
    assert mp.mesclar(pub, atual, {"sp", "rj"})[0] == ["sp"]


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
    # 2 de 3 UFs do escopo (67%) passa o piso de cobertura; mg é preservada.
    pub, atual = _montar(tmp_path, ["mg", "rj", "sp"], ["rj", "sp"])
    escopo = tmp_path / "data"
    escopo.mkdir()
    for uf in ("mg", "rj", "sp"):
        (escopo / f"risco_{uf}.gpkg").write_bytes(b"")
    assert mp.main(["--publicado", str(pub), "--atual", str(atual), "--escopo", str(escopo)]) == 0
    assert json.loads((atual / mp.INDICE).read_text()) == ["mg", "rj", "sp"]


def test_ufs_no_escopo_le_os_gpkg(tmp_path):
    (tmp_path / "risco_sp.gpkg").write_bytes(b"")
    (tmp_path / "risco_rj.gpkg").write_bytes(b"")
    (tmp_path / "chuva_sp_2026.csv").write_text("")
    assert mp.ufs_no_escopo(tmp_path) == {"sp", "rj"}


# --- Piso de cobertura nova (ruling R-12) -----------------------------------


def _escopo(base: Path, ufs: list[str]) -> Path:
    escopo = base / "escopo"
    escopo.mkdir(parents=True, exist_ok=True)
    for uf in ufs:
        (escopo / f"risco_{uf}.gpkg").write_bytes(b"")
    return escopo


def test_main_recusa_run_degenerado(tmp_path):
    # 1 de 5 UFs exportadas: sem o piso, a mescla completaria as outras 4 do
    # gh-pages, o índice viraria união, a guarda anti-regressão veria
    # atual >= publicado e o run fecharia verde com 1 UF nova.
    todas = ["ac", "al", "am", "ap", "ba"]
    pub, atual = _montar(tmp_path, todas, ["ac"])
    escopo = _escopo(tmp_path, todas)
    argv = ["--publicado", str(pub), "--atual", str(atual), "--escopo", str(escopo)]
    assert mp.main(argv) == 1
    assert json.loads((atual / mp.INDICE).read_text()) == ["ac"]
    assert not (atual / "meta_al.json").exists()


def test_main_aceita_cobertura_no_pior_caso_normal(tmp_path):
    # 74% foi a pior cobertura de um run limpo (spec §2.4): tem que passar,
    # senão o piso recria a catraca que a mescla veio remover.
    todas = [f"u{i}" for i in range(100)]
    exportadas = todas[:74]
    pub, atual = _montar(tmp_path, todas, exportadas)
    escopo = _escopo(tmp_path, todas)
    argv = ["--publicado", str(pub), "--atual", str(atual), "--escopo", str(escopo)]
    assert mp.main(argv) == 0
    assert len(json.loads((atual / mp.INDICE).read_text())) == 100


def test_piso_e_configuravel(tmp_path):
    todas = ["ac", "al", "am", "ap", "ba"]
    pub, atual = _montar(tmp_path, todas, ["ac", "al"])
    escopo = _escopo(tmp_path, todas)
    argv = ["--publicado", str(pub), "--atual", str(atual), "--escopo", str(escopo)]
    assert mp.main(argv + ["--piso", "0.4"]) == 0
    pub, atual = _montar(tmp_path / "b", todas, ["ac", "al"])
    argv = ["--publicado", str(pub), "--atual", str(atual), "--escopo", str(escopo)]
    assert mp.main(argv + ["--piso", "0.8"]) == 1


def test_piso_vem_do_ambiente(tmp_path, monkeypatch):
    todas = ["ac", "al", "am", "ap", "ba"]
    pub, atual = _montar(tmp_path, todas, ["ac", "al"])
    escopo = _escopo(tmp_path, todas)
    argv = ["--publicado", str(pub), "--atual", str(atual), "--escopo", str(escopo)]
    monkeypatch.setenv("ORCA_PISO_COBERTURA", "0.4")
    assert mp.main(argv) == 0


def test_piso_nao_bloqueia_quando_escopo_e_desconhecido(tmp_path):
    # Sem GeoPackages não dá para medir cobertura; quem barra esse caso é o
    # passo "Baixar setores da branch dados-base", que é fatal.
    todas = ["ac", "al"]
    pub, atual = _montar(tmp_path, todas, ["ac"])
    escopo = tmp_path / "vazio"
    escopo.mkdir()
    argv = ["--publicado", str(pub), "--atual", str(atual), "--escopo", str(escopo)]
    assert mp.main(argv) == 0


def test_mesclar_relata_ufs_que_sairam_do_escopo(tmp_path):
    pub, atual = _montar(tmp_path, ["sp", "rj"], ["sp"])
    preservadas, fora = mp.mesclar(pub, atual, {"sp"})
    assert preservadas == []
    assert fora == ["rj"]


# --- Validação da faixa do piso ---------------------------------------------
#
# Uma proteção contra degradação silenciosa que pode ser DESLIGADA em
# silêncio não é proteção: neste projeto o dashboard já foi destruído duas
# vezes fechando como `success`.


def _argv_degenerado(tmp_path: Path) -> list[str]:
    todas = ["ac", "al", "am", "ap", "ba"]
    pub, atual = _montar(tmp_path, todas, ["ac"])
    escopo = _escopo(tmp_path, todas)
    return ["--publicado", str(pub), "--atual", str(atual), "--escopo", str(escopo)]


def test_piso_zero_ou_negativo_e_rejeitado(tmp_path, capsys):
    for valor in ("0", "-1", "-0.5"):
        argv = _argv_degenerado(tmp_path / valor)
        assert mp.main(argv + ["--piso", valor]) == 1
        assert "piso" in capsys.readouterr().err.lower()


def test_piso_negativo_no_ambiente_nao_desarma_a_protecao(tmp_path, monkeypatch):
    monkeypatch.setenv("ORCA_PISO_COBERTURA", "-1")
    argv = _argv_degenerado(tmp_path)
    assert mp.main(argv) == 1
    # a mescla não pode ter acontecido
    assert json.loads((Path(argv[3]) / mp.INDICE).read_text()) == ["ac"]


def test_piso_maior_que_um_e_rejeitado(tmp_path):
    argv = _argv_degenerado(tmp_path)
    assert mp.main(argv + ["--piso", "1.5"]) == 1


def test_piso_igual_a_um_e_aceito(tmp_path):
    todas = ["ac", "al"]
    pub, atual = _montar(tmp_path, todas, todas)
    escopo = _escopo(tmp_path, todas)
    argv = ["--publicado", str(pub), "--atual", str(atual), "--escopo", str(escopo)]
    assert mp.main(argv + ["--piso", "1"]) == 0


def test_piso_nao_numerico_no_ambiente_da_mensagem_legivel(tmp_path, capsys):
    for valor in ("", "abc"):
        argv = _argv_degenerado(tmp_path / f"x{valor}")
        os.environ["ORCA_PISO_COBERTURA"] = valor
        try:
            assert mp.main(argv) == 1
        finally:
            del os.environ["ORCA_PISO_COBERTURA"]
        erro = capsys.readouterr().err
        assert "ORCA_PISO_COBERTURA" in erro
        assert "Traceback" not in erro


def test_ambiente_invalido_nao_impede_piso_explicito(tmp_path, monkeypatch):
    # `default=` avaliado ansiosamente derrubava o script mesmo com --piso
    # passado, e derrubava até o --help.
    monkeypatch.setenv("ORCA_PISO_COBERTURA", "abc")
    todas = ["ac", "al"]
    pub, atual = _montar(tmp_path, todas, todas)
    escopo = _escopo(tmp_path, todas)
    argv = ["--publicado", str(pub), "--atual", str(atual), "--escopo", str(escopo)]
    assert mp.main(argv + ["--piso", "0.6"]) == 0


def test_numerador_do_piso_ignora_uf_fora_do_escopo(tmp_path):
    # Denominador vem dos gpkg; o numerador tem que vir da interseção, senão
    # UFs de fora do escopo no índice inflariam a cobertura medida.
    todas = ["ac", "al", "am", "ap", "ba"]
    pub, atual = _montar(tmp_path, todas, ["ac", "zz", "yy", "xx"])
    escopo = _escopo(tmp_path, todas)
    argv = ["--publicado", str(pub), "--atual", str(atual), "--escopo", str(escopo)]
    assert mp.main(argv) == 1


def test_aviso_de_escopo_reduzido_orienta_o_operador(tmp_path, capsys):
    pub, atual = _montar(tmp_path, ["sp", "rj"], ["sp"])
    mp.mesclar(pub, atual, {"sp"})
    saida = capsys.readouterr().out
    assert "::warning::" in saida
    assert "rj" in saida
    assert "ingerir-setores.yml" in saida
    assert "regressão" in saida
