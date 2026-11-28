"""Tests de la superficie y el tipo de cada recinto municipal (límites del IGN)."""
import zipfile

import numpy as np
import pytest

from src import municipios_limites as ml


def rectangulo(lat0, lat1, lon0, lon1):
    """Anillo cerrado (lat, lon) de un rectángulo, en sentido antihorario."""
    return np.array([[lat0, lon0], [lat0, lon1], [lat1, lon1], [lat1, lon0], [lat0, lon0]])


# ---------------- Superficie ----------------

def test_un_grado_por_un_grado_en_el_ecuador():
    # 1° de latitud (110,57 km) x 1° de longitud (111,32 km) en el elipsoide GRS80
    assert ml.area_anillo_km2(rectangulo(0, 1, 0, 1)) == pytest.approx(12_308, rel=0.002)


def test_un_grado_por_un_grado_en_espana():
    # A 40-41° N el grado de longitud mide unos 84,8 km y el de latitud unos 111,0 km
    assert ml.area_anillo_km2(rectangulo(40, 41, 0, 1)) == pytest.approx(9_413, rel=0.003)


def test_el_sentido_del_anillo_no_cambia_el_area():
    anillo = rectangulo(40, 40.1, -3.7, -3.6)
    assert ml.area_anillo_km2(anillo) == pytest.approx(ml.area_anillo_km2(anillo[::-1]))


def test_los_huecos_se_restan():
    exterior = rectangulo(40, 40.2, -3.8, -3.6)
    hueco = rectangulo(40.05, 40.1, -3.75, -3.7)
    esperado = ml.area_anillo_km2(exterior) - ml.area_anillo_km2(hueco)
    assert ml.area_poligono_km2(exterior, [hueco]) == pytest.approx(esperado)


def test_coordenadas_con_altura_se_quedan_en_latitud_y_longitud():
    import xml.etree.ElementTree as ET
    pos_list = ET.fromstring('<p srsDimension="3">40.0 -3.0 650 40.1 -3.1 700</p>')
    assert ml.puntos(pos_list, "prueba").tolist() == [[40.0, -3.0], [40.1, -3.1]]


def test_poligono_sin_coordenadas_da_un_error_claro():
    with pytest.raises(ValueError, match="sin coordenadas"):
        ml.puntos(None, "recinto 34130228079")


# ---------------- Tipo de recinto ----------------

def test_tipo_de_recinto():
    assert ml.tipo_recinto("34100303075", "Municipio") == ml.MUNICIPIO
    assert ml.tipo_recinto("34070953005", "Municipio") == ml.CONDOMINIO
    assert ml.tipo_recinto("34015154001", "Territorio") == ml.TERRITORIO


# ---------------- Lectura del GML ----------------

GML = """<?xml version='1.0' encoding='UTF-8'?>
<wfs:FeatureCollection xmlns:wfs="http://www.opengis.net/wfs/2.0" xmlns:gml="http://www.opengis.net/gml/3.2">
 <wfs:member>
  <au:AdministrativeUnit xmlns:au="http://inspire.ec.europa.eu/schemas/au/4.0" gml:id="A1">
   <au:geometry><gml:MultiSurface gml:id="G1">
    <gml:surfaceMember><gml:Polygon gml:id="P1">
     <gml:exterior><gml:LinearRing><gml:posList>40.0 -3.8 40.0 -3.6 40.2 -3.6 40.2 -3.8 40.0 -3.8</gml:posList></gml:LinearRing></gml:exterior>
     <gml:interior><gml:LinearRing><gml:posList>40.05 -3.75 40.1 -3.75 40.1 -3.7 40.05 -3.7 40.05 -3.75</gml:posList></gml:LinearRing></gml:interior>
    </gml:Polygon></gml:surfaceMember>
    <gml:surfaceMember><gml:Polygon gml:id="P2">
     <gml:exterior><gml:LinearRing><gml:posList>41.0 -3.0 41.0 -2.9 41.1 -2.9 41.1 -3.0 41.0 -3.0</gml:posList></gml:LinearRing></gml:exterior>
    </gml:Polygon></gml:surfaceMember>
   </gml:MultiSurface></au:geometry>
   <au:nationalCode>34130228079</au:nationalCode>
   <au:nationalLevelName><gmd:LocalisedCharacterString xmlns:gmd="http://www.isotc211.org/2005/gmd">Municipio</gmd:LocalisedCharacterString></au:nationalLevelName>
   <au:name><gn:GeographicalName xmlns:gn="http://inspire.ec.europa.eu/schemas/gn/4.0"><gn:spelling><gn:SpellingOfName><gn:text>Madrid</gn:text></gn:SpellingOfName></gn:spelling></gn:GeographicalName></au:name>
  </au:AdministrativeUnit>
 </wfs:member>
 <wfs:member>
  <au:AdministrativeUnit xmlns:au="http://inspire.ec.europa.eu/schemas/au/4.0" gml:id="A2">
   <au:geometry><gml:MultiSurface gml:id="G2">
    <gml:surfaceMember><gml:Polygon gml:id="P3">
     <gml:exterior><gml:LinearRing><gml:posList>42.0 -3.0 42.0 -2.9 42.1 -2.9 42.1 -3.0 42.0 -3.0</gml:posList></gml:LinearRing></gml:exterior>
    </gml:Polygon></gml:surfaceMember>
   </gml:MultiSurface></au:geometry>
   <au:nationalCode>34070953005</au:nationalCode>
   <au:nationalLevelName><gmd:LocalisedCharacterString xmlns:gmd="http://www.isotc211.org/2005/gmd">Municipio</gmd:LocalisedCharacterString></au:nationalLevelName>
   <au:name><gn:GeographicalName xmlns:gn="http://inspire.ec.europa.eu/schemas/gn/4.0"><gn:spelling><gn:SpellingOfName><gn:text>Comunidad de Los Ausines</gn:text></gn:SpellingOfName></gn:spelling></gn:GeographicalName></au:name>
  </au:AdministrativeUnit>
 </wfs:member>
</wfs:FeatureCollection>
"""


@pytest.fixture
def zip_ign(tmp_path):
    ruta = tmp_path / "lineas_limite_gml.zip"
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr(ml.ARCHIVO_MUNICIPIOS, GML)
    return ruta


def test_leer_recintos_del_gml(zip_ign):
    recintos = ml.leer_recintos(zip_ign).set_index("codigo_ign")
    madrid = recintos.loc["34130228079"]
    assert madrid["codigo_ine"] == "28079"
    assert madrid["nombre"] == "Madrid"
    assert madrid["tipo_recinto"] == ml.MUNICIPIO
    assert madrid["n_poligonos"] == 2
    exterior = ml.area_anillo_km2(rectangulo(40, 40.2, -3.8, -3.6))
    hueco = ml.area_anillo_km2(rectangulo(40.05, 40.1, -3.75, -3.7))
    trozo = ml.area_anillo_km2(rectangulo(41, 41.1, -3.0, -2.9))
    assert madrid["superficie_km2"] == pytest.approx(exterior - hueco + trozo, abs=0.01)


def test_un_condominio_no_tiene_codigo_ine(zip_ign):
    recintos = ml.leer_recintos(zip_ign).set_index("codigo_ign")
    condominio = recintos.loc["34070953005"]
    assert condominio["tipo_recinto"] == ml.CONDOMINIO
    assert condominio["codigo_ine"] is None or condominio["codigo_ine"] != condominio["codigo_ine"]
