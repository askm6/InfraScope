"""Tests de la conversión de los CSV limpios a Parquet (capas Silver y Gold)."""
import json

import pandas as pd
import pytest

from src import convertir_parquet as cp
from src import lago


# ---------------- Tipos ----------------

def test_codigo_ine_recupera_el_cero_inicial():
    df = pd.DataFrame({"codigo_ine": ["1001", "28079", None]})
    resultado = cp.tipar(df)
    assert resultado["codigo_ine"].iloc[0] == "01001"
    assert resultado["codigo_ine"].iloc[1] == "28079"
    assert pd.isna(resultado["codigo_ine"].iloc[2])


def test_codigo_ine_escrito_como_decimal_se_arregla():
    resultado = cp.tipar(pd.DataFrame({"codigo_ine": ["8019.0"]}))
    assert resultado["codigo_ine"].iloc[0] == "08019"


def test_codigo_provincia_tiene_dos_cifras():
    resultado = cp.tipar(pd.DataFrame({"codigo_provincia": ["8", "28"]}))
    assert resultado["codigo_provincia"].tolist() == ["08", "28"]


def test_anio_con_huecos_pasa_a_entero():
    resultado = cp.tipar(pd.DataFrame({"anio_renta": [2024.0, None]}))
    assert str(resultado["anio_renta"].dtype) == "Int64"
    assert resultado["anio_renta"].iloc[0] == 2024
    assert pd.isna(resultado["anio_renta"].iloc[1])


def test_contador_con_decimales_no_se_convierte_a_entero():
    resultado = cp.tipar(pd.DataFrame({"meses": [1.5, 3.0]}))
    assert resultado["meses"].dtype == "float64"


def test_unidad_por_anio_no_se_confunde_con_un_anio():
    resultado = cp.tipar(pd.DataFrame({"perdidas_reales_m3_km_anio": [3.0, 4.0]}))
    assert resultado["perdidas_reales_m3_km_anio"].dtype == "float64"


def test_fechas_en_texto_pasan_a_fecha():
    resultado = cp.tipar(pd.DataFrame({"fecha": ["2016-01-04", "2016-01-11"]}))
    assert pd.api.types.is_datetime64_any_dtype(resultado["fecha"])


def test_fecha_invalida_se_queda_como_texto():
    resultado = cp.tipar(pd.DataFrame({"fecha_precio_max": ["no es una fecha"]}))
    assert resultado["fecha_precio_max"].iloc[0] == "no es una fecha"


def test_fecha_incompleta_no_se_convierte():
    resultado = cp.tipar(pd.DataFrame({"fecha": ["2016-03", "2016-04"]}))
    assert resultado["fecha"].iloc[0] == "2016-03"


def test_fecha_escrita_como_numero_no_se_convierte():
    resultado = cp.tipar(pd.DataFrame({"fecha_alta": [20160104, 20160111]}))
    assert pd.api.types.is_integer_dtype(resultado["fecha_alta"])


def test_numero_enorme_no_rompe_la_conversion_a_entero():
    resultado = cp.tipar(pd.DataFrame({"n_eventos": [1e30, 2.0]}))
    assert resultado["n_eventos"].dtype == "float64"


def test_tipar_no_modifica_la_tabla_original():
    original = pd.DataFrame({"codigo_ine": ["1001"], "anio": [2024.0]})
    cp.tipar(original)
    assert original["codigo_ine"].iloc[0] == "1001"
    assert original["anio"].dtype == "float64"


# ---------------- Validación ----------------

def test_clave_por_defecto_en_tablas_por_municipio():
    df = pd.DataFrame({"codigo_ine": ["01001"]})
    assert cp.clave("aeropuertos_municipios", df) == ["codigo_ine"]
    assert cp.clave("paro_municipios", df) == ["codigo_ine", "anio"]
    assert cp.clave("dataset_sin_clave", df) is None


def test_validar_detecta_duplicados_en_la_clave():
    df = pd.DataFrame({"codigo_ine": ["01001", "01001"]})
    errores, _ = cp.validar("energia_municipios", df, codigos_validos=None)
    assert any("duplicad" in e for e in errores)


def test_validar_detecta_codigo_ine_mal_formado():
    df = pd.DataFrame({"codigo_ine": ["ABCDE"]})
    errores, _ = cp.validar("energia_municipios", df, codigos_validos=None)
    assert any("codigo_ine" in e for e in errores)


def test_validar_detecta_claves_vacias():
    df = pd.DataFrame({"codigo_ine": [None, "01001"]})
    errores, _ = cp.validar("energia_municipios", cp.tipar(df), codigos_validos=None)
    assert any("vací" in e for e in errores)


def test_validar_avisa_si_un_contador_tiene_decimales():
    df = cp.tipar(pd.DataFrame({"meses_paro": [1.5, 2.0]}))
    _, avisos = cp.validar("socioeconomico_x", df, codigos_validos=None)
    assert any("meses_paro" in a for a in avisos)


def test_validar_avisa_de_otro_codigo_guardado_como_numero():
    df = pd.DataFrame({"codigo_comunidad": [1, 13]})
    _, avisos = cp.validar("dataset_sin_clave", df, codigos_validos=None)
    assert any("codigo_comunidad" in a for a in avisos)


def test_validar_avisa_de_codigos_que_no_estan_en_la_lista_maestra():
    df = pd.DataFrame({"codigo_ine": ["01001", "99999"]})
    errores, avisos = cp.validar("energia_municipios", df, codigos_validos={"01001"})
    assert errores == []
    assert any("99999" in a for a in avisos)


# ---------------- Conversión completa ----------------

@pytest.fixture
def datos(tmp_path, monkeypatch):
    """Carpeta data/ de prueba con dos CSV limpios en data/processed/."""
    monkeypatch.setattr(lago, "DIR_DATOS", tmp_path)
    trabajo = tmp_path / "processed"
    trabajo.mkdir()
    pd.DataFrame({"codigo_ine": ["01001", "28079"], "municipio": ["Alegría-Dulantzi", "Madrid"],
                  "latitud": [42.8, 40.4], "longitud": [-2.5, -3.7]}
                 ).to_csv(trabajo / "municipios.csv", index=False, encoding="utf-8")
    pd.DataFrame({"codigo_ine": ["01001", "28079"], "anio": [2024.0, None],
                  "renovable_pct": [55.5, 12.0]}
                 ).to_csv(trabajo / "energia_municipios.csv", index=False, encoding="utf-8-sig")
    return tmp_path


def test_convertir_crea_parquet_tipado_en_silver(datos):
    resultado = cp.convertir_todo()
    assert resultado["energia_municipios"] == cp.CONVERTIDO
    assert (datos / "silver" / "energia_municipios.parquet").exists()
    energia = lago.leer("energia_municipios")
    assert energia["codigo_ine"].tolist() == ["01001", "28079"]
    assert str(energia["anio"].dtype) == "Int64"


def test_convertir_guarda_catalogo_con_filas_y_tipos(datos):
    cp.convertir_todo()
    catalogo = json.loads((datos / "silver" / "catalogo.json").read_text(encoding="utf-8"))
    entrada = catalogo["energia_municipios"]
    assert entrada["filas"] == 2
    assert entrada["clave"] == ["codigo_ine"]
    assert entrada["tipos"]["anio"] == "Int64"
    assert len(entrada["sha256"]) == 64


def test_segunda_ejecucion_no_vuelve_a_convertir_si_el_csv_no_cambia(datos):
    cp.convertir_todo()
    assert cp.convertir_todo()["energia_municipios"] == cp.SIN_CAMBIOS
    assert cp.convertir_todo(forzar=True)["energia_municipios"] == cp.CONVERTIDO


def test_tabla_integrada_va_a_gold(datos):
    pd.DataFrame({"codigo_ine": ["01001"], "poblacion": [3000]}).to_csv(
        datos / "processed" / "tabla_integrada.csv", index=False)
    cp.convertir_todo()
    assert (datos / "gold" / "tabla_integrada.parquet").exists()
    assert not (datos / "silver" / "tabla_integrada.parquet").exists()


def test_dataset_con_duplicados_no_se_escribe(datos):
    pd.DataFrame({"codigo_ine": ["01001", "01001"], "x": [1, 2]}).to_csv(
        datos / "processed" / "duplicados_municipios.csv", index=False)
    resultado = cp.convertir_todo()
    assert resultado["duplicados_municipios"] == cp.ERROR
    assert not (datos / "silver" / "duplicados_municipios.parquet").exists()
    assert cp.main([]) == 1


def test_cambio_en_las_reglas_de_tipado_obliga_a_reconvertir(datos, monkeypatch):
    cp.convertir_todo()
    monkeypatch.setattr(cp, "VERSION_ESQUEMA", cp.VERSION_ESQUEMA + 1)
    assert cp.convertir_todo()["energia_municipios"] == cp.CONVERTIDO


def test_dataset_que_pasa_a_gold_no_deja_copia_vieja_en_silver(datos, monkeypatch):
    cp.convertir_todo()
    monkeypatch.setattr(cp, "DATASETS_GOLD", {"energia_municipios"})
    cp.convertir_todo()
    assert (datos / "gold" / "energia_municipios.parquet").exists()
    assert not (datos / "silver" / "energia_municipios.parquet").exists()


def test_catalogo_corrupto_no_bloquea_la_conversion(datos):
    (datos / "silver").mkdir()
    (datos / "silver" / "catalogo.json").write_text("{ esto no es json", encoding="utf-8")
    assert cp.convertir_todo()["energia_municipios"] == cp.CONVERTIDO


def test_error_al_escribir_un_dataset_no_para_los_demas(datos, monkeypatch):
    original = cp.guardar_parquet

    def falla_con_energia(df, destino):
        if destino.stem == "energia_municipios":
            raise PermissionError("archivo abierto en otro programa")
        original(df, destino)

    monkeypatch.setattr(cp, "guardar_parquet", falla_con_energia)
    resultado = cp.convertir_todo()
    assert resultado["energia_municipios"] == cp.ERROR
    assert resultado["municipios"] == cp.CONVERTIDO
    catalogo = json.loads((datos / "silver" / "catalogo.json").read_text(encoding="utf-8"))
    assert "municipios" in catalogo


def test_leer_avisa_si_el_dataset_se_quedo_sin_actualizar(datos):
    cp.convertir_todo()
    pd.DataFrame({"codigo_ine": ["01001", "01001"], "anio": [2024, 2024]}).to_csv(
        datos / "processed" / "energia_municipios.csv", index=False)
    assert cp.convertir_todo()["energia_municipios"] == cp.ERROR
    with pytest.warns(UserWarning, match="desactualizado"):
        lago.leer("energia_municipios")


def test_leer_un_dataset_que_no_existe_da_un_error_claro(datos):
    with pytest.raises(FileNotFoundError, match="convertir_parquet"):
        lago.leer("no_existe")
