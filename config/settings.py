from pathlib import Path

APP_NAME = "SmartPharma"
APP_ICON = "💊"
VERSION = "4.3"

COL_CN = "Codigo_Nacional"
COL_NOMBRE = "Nombre"
COL_STOCK = "Stock"
COL_PVL = "PVL"
COL_LAB = "Laboratorio"
COL_VENTAS = "Ventas"
COL_FECHA = "Fecha"
COL_MOLECULA = "Molecula"

# The original file was in the root, so __file__.parent was root.
# Now this file is in config/, so parent.parent is root.
BASE_DIR = Path(__file__).parent.parent / "farmacias"

COLORS = {
    "primary": "#0066FF", "secondary": "#00C49A", "danger": "#FF4B4B",
    "warning": "#FFA726", "bg_card": "#F8F9FC", "text": "#1E293B",
    "muted": "#64748B", "success": "#10B981",
}

Z_SCORES = {95: 1.645, 99: 2.326}

HEALTH_SCORE_MESES_DEFAULT = 2.0
