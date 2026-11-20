"""Códigos INE de provincias y su comunidad autónoma.

Lo usan los scripts de limpieza que trabajan con datos por provincia o por
comunidad, para poder cruzarlos con los municipios (los 2 primeros dígitos
del código INE de un municipio son el código de su provincia).
Los nombres de comunidad siguen el formato del INE, igual que energia.py.
"""

# codigo_provincia: (nombre INE de la provincia, comunidad autónoma)
PROVINCIAS = {
    "01": ("Araba/Álava", "País Vasco"),
    "02": ("Albacete", "Castilla - La Mancha"),
    "03": ("Alicante/Alacant", "Comunitat Valenciana"),
    "04": ("Almería", "Andalucía"),
    "05": ("Ávila", "Castilla y León"),
    "06": ("Badajoz", "Extremadura"),
    "07": ("Balears, Illes", "Balears, Illes"),
    "08": ("Barcelona", "Cataluña"),
    "09": ("Burgos", "Castilla y León"),
    "10": ("Cáceres", "Extremadura"),
    "11": ("Cádiz", "Andalucía"),
    "12": ("Castellón/Castelló", "Comunitat Valenciana"),
    "13": ("Ciudad Real", "Castilla - La Mancha"),
    "14": ("Córdoba", "Andalucía"),
    "15": ("Coruña, A", "Galicia"),
    "16": ("Cuenca", "Castilla - La Mancha"),
    "17": ("Girona", "Cataluña"),
    "18": ("Granada", "Andalucía"),
    "19": ("Guadalajara", "Castilla - La Mancha"),
    "20": ("Gipuzkoa", "País Vasco"),
    "21": ("Huelva", "Andalucía"),
    "22": ("Huesca", "Aragón"),
    "23": ("Jaén", "Andalucía"),
    "24": ("León", "Castilla y León"),
    "25": ("Lleida", "Cataluña"),
    "26": ("Rioja, La", "Rioja, La"),
    "27": ("Lugo", "Galicia"),
    "28": ("Madrid", "Madrid, Comunidad de"),
    "29": ("Málaga", "Andalucía"),
    "30": ("Murcia", "Murcia, Región de"),
    "31": ("Navarra", "Navarra, Comunidad Foral de"),
    "32": ("Ourense", "Galicia"),
    "33": ("Asturias", "Asturias, Principado de"),
    "34": ("Palencia", "Castilla y León"),
    "35": ("Palmas, Las", "Canarias"),
    "36": ("Pontevedra", "Galicia"),
    "37": ("Salamanca", "Castilla y León"),
    "38": ("Santa Cruz de Tenerife", "Canarias"),
    "39": ("Cantabria", "Cantabria"),
    "40": ("Segovia", "Castilla y León"),
    "41": ("Sevilla", "Andalucía"),
    "42": ("Soria", "Castilla y León"),
    "43": ("Tarragona", "Cataluña"),
    "44": ("Teruel", "Aragón"),
    "45": ("Toledo", "Castilla - La Mancha"),
    "46": ("Valencia/València", "Comunitat Valenciana"),
    "47": ("Valladolid", "Castilla y León"),
    "48": ("Bizkaia", "País Vasco"),
    "49": ("Zamora", "Castilla y León"),
    "50": ("Zaragoza", "Aragón"),
    "51": ("Ceuta", "Ceuta"),
    "52": ("Melilla", "Melilla"),
}

# nombre de provincia -> código (para tablas que solo traen el nombre)
CODIGO_POR_PROVINCIA = {nombre: cod for cod, (nombre, _) in PROVINCIAS.items()}


def ccaa_de_municipio(codigo_ine):
    """'28079' -> 'Madrid, Comunidad de'."""
    return PROVINCIAS.get(str(codigo_ine).zfill(5)[:2], (None, None))[1]
