"""The subset of supplier suggestions supported by live store updates."""
STORE_FIELDS = {
    'description': 'Sinopsis', 'yumekai_status': 'Estado Yumekai', 'retail_price': 'PVP', 'sale_price': 'Rebajado',
    'author': 'Autoría', 'publisher': 'Editorial', 'series': 'Colección', 'volume': 'Tomo',
    'language': 'Idioma', 'book_format': 'Formato', 'pages': 'Páginas', 'work_type': 'Tipo de obra',
}


def store_changes(changes):
    return {field: value for field, value in changes.items() if field in STORE_FIELDS}
