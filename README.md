# SmartPharma

**Análisis de negocio, optimización de stock y predicción de demanda para farmacias.**

Herramienta central de una consultoría de datos para farmacias, **en piloto con una farmacia
real**. Se ejecuta en local, en el equipo del consultor: la farmacia solo entrega
exportaciones de su ERP y recibe informes, pedidos sugeridos y recomendaciones. Sus datos no
salen de ese equipo ni pasan por ningún servicio en la nube.

*EN — Business analytics, inventory optimization and demand forecasting for pharmacies. The
core tool of a pharmacy data consultancy, piloted in a real pharmacy. Runs locally on the
consultant's machine; pharmacy data never leaves it.*

Autor: **Miguel Ángel Leo Acedo** — Data & IA aplicada a farmacia, +5 años trabajando en
farmacia.

---

## El problema

Una farmacia tiene buena parte de su capital en stock, y las decisiones de compra se toman con
prisa, de memoria o siguiendo la propuesta del delegado. El resultado se repite:

- **Stock parado** que nadie ha vendido en un año.
- **Roturas** de productos con demanda, es decir, ventas perdidas.
- **Descuentos transfer mal aprovechados**: se pide de más por llegar a un tramo, o de menos
  y se pierde el tramo.

Los datos para evitarlo ya están en el ERP de la farmacia. SmartPharma los convierte en
decisiones.

## Qué hace

| Módulo | Qué responde |
|---|---|
| **Business Intelligence** | ¿Cómo está mi stock? Health Score, stock zombie (sin ventas en 12 meses), sobrestock, roturas y su coste de oportunidad, ROI y rotación por laboratorio, informe PDF para el titular |
| **Pedidos transfer** | ¿Qué pido y cuánto? Pedido por cobertura (meses) o por presupuesto, con tramos de descuento por oferta, productos protegidos, reglas de surtido y Excel por laboratorio |
| **Predicción de demanda** | ¿Cuánto voy a vender? Modelo XGBoost por farmacia con calendario, clima, grupo terapéutico (ATC) y promociones, y stock de seguridad según el nivel de servicio |
| **Auditoría** | ¿Cuadra lo que tengo? Conciliación físico frente a lógico, riesgo de caducidad, análisis ABC, flujo de caja del inventario y estacionalidad |
| **Torre de control** | ¿Podemos comprar juntos? Detecta farmacias de una red que van a pedir al mismo laboratorio en la misma ventana y simula la compra conjunta para alcanzar un tramo mejor |
| **Laboratorio ML** | ¿Me puedo fiar de la predicción? Explica paso a paso cómo se entrenó y validó el modelo de cada farmacia, y dónde falla |

## Motor de predicción: validado, no caja negra

- **Objetivo relativo**: el modelo predice ventas / media de 12 meses, así el mismo patrón sirve
  a productos grandes y pequeños.
- **Sin fugas de información**: split temporal, ajuste de hiperparámetros y selección
  automática de grupos de variables solo con datos de entrenamiento, y backtest walk-forward
  encadenado al horizonte real del pedido.
- **Siempre contra un baseline honesto** (mismo mes del año anterior), para comprobar en cada
  farmacia si el ML aporta de verdad.
- **Productos nuevos** (cold start) mezclados con la media de su molécula, y **stock de
  seguridad** estadístico (z × RMSE × √meses).

**Resultados.** Con datos sintéticos de patrón conocido, el modelo reduce entre un 39 % y un
46 % el error a 3 meses frente al baseline (varía entre ejecuciones). En la farmacia demo gana a 1 mes (+11,6 %) y pierde a 3 meses
(−8,3 %). Con historiales cortos el ML no siempre gana; por eso existe el modo **Ensemble**
(ML + heurístico) y el **Laboratorio ML** enseña, farmacia por farmacia, si conviene usarlo.
Detalle en [`docs/revision-codigo.md`](docs/revision-codigo.md) y conceptos en
[`docs/guia-ml.md`](docs/guia-ml.md).

## Privacidad

- Todo se ejecuta en local. No hay servidor, base de datos externa ni llamadas a APIs con
  datos de la farmacia.
- Cada farmacia tiene su propia carpeta en `farmacias/`, excluida de git: **en este
  repositorio solo hay datos sintéticos** de dos farmacias demo.
- La herramienta la usa solo el consultor. Cuando trabaja con una red, los datos de cada
  farmacia se guardan por separado y solo se cruzan para simular la compra conjunta.

## Probar la demo

Requiere Python 3.14.

```bash
py -3.14 -m pip install -r requirements.txt
py -3.14 -m streamlit run app.py
```

1. Elige `Farmacia_Demo_Centro` en el selector.
2. Configuración → **H. Motor de Predicción ML** → entrena el modelo (no se versionan modelos
   entrenados).
3. Recorre las pestañas. La Torre de control usa las dos farmacias demo como red.

Sin `xgboost`/`scikit-learn` la app funciona igual con el motor heurístico.

## Tests

```bash
py -3.14 tests/test_ml_engine.py
```

7 pruebas con datos sintéticos que comprueban que el motor no ve el futuro: sin fugas en
ninguna variable, no aprende de ruido ni de ventas barajadas, gana al baseline con un patrón
conocido, capta la estacionalidad y predice todos los meses del pedido.

## Stack

Python · pandas · NumPy · XGBoost · scikit-learn · Streamlit · Plotly · Parquet (pyarrow) ·
fpdf2 · Ruff

## Estructura

```
app.py                Punto de entrada (Streamlit)
config/settings.py    Constantes y configuración
core/business.py      Lógica de negocio: KPIs, pedidos, auditoría, surtido
core/network.py       Red de farmacias y compra conjunta
data/io.py            Carga y persistencia por farmacia
ml/engine.py          Motor de predicción (features, entrenamiento, validación, pedido ML)
ui/tabs/              Una pestaña por módulo
utils/                Helpers, informe PDF
farmacias/            Datos por farmacia (solo las demo están versionadas)
tests/                Banco de pruebas del motor ML
docs/                 Guía de ML y auditoría de código
```

## Hoja de ruta

- Stock pendiente de recibir y encargos en el cálculo del pedido.
- Múltiplos de caja e importe mínimo por laboratorio.
- Integración con CIMA (AEMPS): clasificación oficial, ATC y alertas de problemas de
  suministro.
- Coste de oportunidad y ROI sobre margen (PVP − PVL).
- Plan de liquidación del stock zombie: devolver, traspasar en la red, promocionar o provisionar.
- Plantillas de importación por ERP (Farmatic, Nixfarma, Unycop) y control de calidad de datos.
- Medición del impacto: foto inicial del cliente y panel antes/después.

## Desarrollo asistido por IA

SmartPharma se ha desarrollado con asistencia de IA (Claude, Google Antigravity). El reparto:

- **Mío**: el problema y el conocimiento de farmacia, las reglas de negocio (tramos, surtido,
  protegidos, zombie, coste de oportunidad), el diseño de los módulos, las decisiones de cada
  lote de cambios y la validación de resultados.
- **De la IA**: buena parte de la implementación, la auditoría de código y el banco de pruebas,
  siempre revisados y aprobados por mí. El proceso completo, con cada hallazgo y decisión, está
  en [`docs/revision-codigo.md`](docs/revision-codigo.md).

## Licencia

© 2026 Miguel Ángel Leo Acedo. **Todos los derechos reservados.** El código se publica solo
para su consulta; no se concede licencia de uso, copia ni distribución. Ver [LICENSE](LICENSE).
