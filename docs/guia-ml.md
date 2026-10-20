# 🧠 Guía Completa de Machine Learning para SmartPharma
### *Manual del Arquitecto — Del concepto al modelo en producción*

---

## ÍNDICE DE CONCEPTOS (de más básico a más avanzado)

| # | Concepto | Categoría |
|---|----------|-----------|
| 1 | ¿Qué es Machine Learning? | Fundamento |
| 2 | Tipos de ML (incluye Clustering) | Fundamento |
| 3 | Features y Label | Fundamento |
| 4 | Train / Test Split | Metodología |
| 5 | Sobreajuste (Overfitting) y Subajuste (Underfitting) | Metodología |
| 6 | Métricas de Evaluación | Metodología |
| 7 | Series Temporales (Time Series) | Fase 1: Previsión |
| 8 | Ingeniería de Features (incluye Geomarketing) | Fase 1 y 2 |
| 9 | Aprendizaje No Supervisado: Encontrar "Gemelos" | Fase 2: Auditoría |
| 10 | Selección de Modelos | Decisión |
| 11 | Hiperparámetros | Decisión |
| 12 | Validación Cruzada | Decisión |
| 13 | Importancia de Variables | Interpretación |
| 14 | El Problema del Dato Sucio | Calidad |
| 15 | Sesgo y Varianza | Diagnóstico |
| 16 | Entorno de Ejecución: ¿Local o Cloud? | Infraestructura |
| 17 | Pipelines de ML | Producción |
| 18 | Reentrenamiento y Deriva del Modelo | Producción |
| 19 | Interpretabilidad vs. Precisión | Filosofía del modelo |
| 20 | Ética y Riesgos en Predicción | Decisión crítica |

---

## BLOQUE 1 — FUNDAMENTOS

---

### 1. ¿Qué es Machine Learning?

**Definición simple:** Programación clásica = tú escribes las reglas. Machine Learning = le muestras ejemplos y él deduce las reglas solo.

```
Programación clásica:
  reglas + datos → respuestas

Machine Learning:
  datos + respuestas → reglas (el modelo)
```

**En SmartPharma:** No escribimos "si es diciembre y hay gripe → pide más antigripales". En su lugar, le damos 3 años de datos de ventas con sus fechas, y el modelo aprende él solo que en diciembre suben ciertas referencias.

**Lo que esto implica para ti como arquitecto:**
- El modelo es tan bueno como los datos que le das. Basura entra → basura sale.
- El modelo puede aprender relaciones que tú no habías visto, pero también puede aprender ruido aleatorio si no se controla bien.
- No es magia: todo lo que aprende viene de los datos históricos. Si algo no ocurrió en el histórico, el modelo no puede predecirlo.

**¿Cuándo NO usar ML?**
- Cuando tienes muy pocos datos (menos de 12-18 meses de histórico por producto).
- Cuando la respuesta se puede calcular con una fórmula simple y funciona bien.
- Cuando el negocio cambia tan rápido que el pasado no predice el futuro (pandemia, cambio de zona).

---

### 2. Tipos de Machine Learning

**Aprendizaje Supervisado** — El que usamos en SmartPharma

El modelo aprende de ejemplos donde conocemos la respuesta correcta.

- Ejemplo: Le damos ventas históricas (la pregunta) y el modelo aprende a predecir ventas futuras (la respuesta).
- Dos subtipos: **Regresión** (predecir un número → cuántas unidades) y **Clasificación** (predecir una categoría → ¿habrá rotura de stock? sí/no).
- En SmartPharma usaremos ambos: regresión para unidades, clasificación para alertas de rotura.

**Aprendizaje No Supervisado** — El motor de la Fase 2 (Auditoría)

El modelo encuentra patrones y agrupaciones naturales en los datos sin que tú le des "respuestas correctas" previas. No predecimos un valor, descubrimos una estructura oculta.

- Ejemplo: Le damos los datos de 50 farmacias (ventas, tamaño, ubicación) y el modelo las separa en 4 grupos ("clústeres") de comportamiento similar.
- Utilidad en SmartPharma (Fase 2): Encontrar la "Farmacia Gemela" para comparar rendimiento, o identificar qué "Tipo de Farmacia" (Barrio, Turística, Paso) es la que estamos auditando para valorar si su precio de compra es justo.
- Riesgo: Los grupos que encuentra la matemática pueden no tener un sentido de negocio evidente. Siempre requiere interpretación humana posterior para "bautizar" cada clúster.

**Aprendizaje por Refuerzo** — No aplicable aquí

El modelo aprende por ensayo y error, recibiendo premios y penalizaciones. Útil en robótica, juegos. No aplica en predicción de ventas farmacéuticas.

---

### 3. Features (Variables) y Label (Objetivo)

- **Features** = todas las variables de entrada que le damos al modelo para que aprenda. Son las *causas*.
- **Label** = lo que queremos predecir. Es el *efecto*.
- **Instancia / muestra** = una fila de datos. Ejemplo: las ventas de Ibuprofeno 400mg en marzo de 2024.

**Ejemplo completo en SmartPharma:**

| Feature | Tipo | Por qué podría ser útil |
|---------|------|------------------------|
| Mes del año | Categórica | Captura estacionalidad |
| Ventas mes anterior | Numérica | El pasado más reciente predice el futuro |
| Ventas mismo mes año anterior | Numérica | Captura ciclo anual |
| Media ventas últimos 3 meses | Numérica | Suaviza picos puntuales |
| ¿Es temporada de gripe? | Binaria (sí/no) | Conocimiento de negocio |
| Precio actual | Numérica | Cambios de precio afectan demanda |
| ¿Hubo rotura de stock? | Binaria | Ventas bajas pueden ser por falta de stock, no demanda real |
| Categoría del producto | Categórica | Medicamento vs parafarmacia tienen patrones distintos |

**Label (lo que predecimos):**
- `unidades_vendidas_mes_siguiente` → regresión
- `rotura_stock_proximo_mes` (sí/no) → clasificación

> [!IMPORTANT]
> **Regla clave:** Una feature solo es válida si en el momento real de hacer la predicción ya la tendrías disponible. Nunca puedes usar como feature "ventas de este mes" para predecir "ventas de este mes". Eso es **data leakage** y es el error más grave del ML.

**Tipos de variables que el modelo puede usar:**

- **Numéricas continuas:** unidades vendidas, precio, stock. El modelo las usa directamente.
- **Categóricas nominales:** tipo de producto (Medicamento, Parafarmacia), laboratorio. Hay que codificarlas (One-Hot Encoding o Label Encoding) para que el modelo las entienda.
- **Binarias:** sí/no, 0/1. Ya están listas para el modelo.
- **Ordinales:** categorías con orden (baja/media/alta rotación). Se pueden codificar como 1/2/3.

---

## BLOQUE 2 — METODOLOGÍA

---

### 4. Train / Test Split (Entrenamiento y Evaluación)

**El principio fundamental:** Un modelo debe evaluarse con datos que **nunca haya visto** durante el entrenamiento. Si no, la evaluación no dice nada.

**División estándar:**
- 70-80% de los datos → **Train** (el modelo aprende aquí)
- 20-30% de los datos → **Test** (medimos qué tan bien predice aquí)

**⚠️ La regla de oro para series temporales:**

En Series temporales NO se puede hacer un split aleatorio. El tiempo tiene dirección: no puedes "aprender del futuro".

```
❌ MAL — Split aleatorio (mezcla tiempos):
  [Abr23] [Nov24] [Feb22] ... → Train
  [Jun23] [Mar24] [Ene22] ... → Test

✅ BIEN — Split temporal (respeta el orden):
  Ene22 → Dic24 → Train
  Ene25 → Hoy  → Test
```

**Cuánto histórico necesitamos:**

| Situación | Histórico mínimo recomendado |
|-----------|------------------------------|
| Predicción mensual básica | 2 años |
| Predicción con estacionalidad anual | 3 años |
| Productos con mucha variabilidad | 4+ años |

**Horizonte de predicción:** ¿Cuántos meses adelante predecimos? Para SmartPharma lo ideal es:
- **1 mes vista:** para pedidos de reposición habitual (mayor precisión)
- **3 meses vista:** para planificación estacional (menor precisión, más estratégico)

Cuanto más lejos predecimos, mayor es el error. Es normal y esperado.

---

### 5. Sobreajuste y Subajuste — El balance fundamental

Este es el concepto más importante para tomar decisiones correctas.

**El Bias-Variance Tradeoff (Equilibrio Sesgo-Varianza):**

Todo modelo vive en un espectro entre dos extremos:

```
UNDERFITTING ←————————————————→ OVERFITTING
(Subajuste)                      (Sobreajuste)
Muy simple                        Muy complejo
No aprende nada                   Memoriza todo
Error alto en train               Error bajo en train
Error alto en test                Error MUY alto en test
```

**Subajuste (Underfitting):**
- El modelo es demasiado simple para captar los patrones reales.
- Ejemplo: usar solo el promedio histórico total como predicción.
- Síntoma: error alto tanto en train como en test.
- Solución: añadir más features, usar un modelo más complejo.

**Sobreajuste (Overfitting):**
- El modelo es demasiado complejo y aprende el ruido de los datos.
- Síntoma: error muy bajo en train, error alto en test.
- Ejemplo visual:

```
Datos reales (ventas):    ●  ●    ●    ●  ●
Línea de tendencia real:  ────────────────
Modelo sobreajustado:     /\/\/\/\/\/\/\/\
```

**Causas comunes de overfitting:**
1. Demasiados hiperparámetros optimizados sobre los mismos datos de test
2. Muy pocas muestras de entrenamiento
3. Modelo demasiado complejo para la cantidad de datos
4. Features irrelevantes que el modelo "memoriza"

**Cómo lo combatimos:**
- **Regularización:** penalizar al modelo por ser demasiado complejo (parámetros como `alpha`, `lambda`)
- **Pruning:** en árboles de decisión, limitar la profundidad máxima
- **Early stopping:** parar el entrenamiento antes de que empiece a memorizar
- **Cross-validation:** verificar que el rendimiento es consistente en varios períodos
- **Menos features:** a veces quitar features irrelevantes mejora mucho el modelo

> [!WARNING]
> **Regla práctica para SmartPharma:** Si propongo un ajuste de hiperparámetros y el error de train baja mucho pero el de test no mejora (o empeora), es overfitting. Rechazarlo es la decisión correcta aunque los números de train parezcan mejores.

---

### 6. Métricas de Evaluación

**Para regresión (predicción de unidades):**

**MAE — Error Absoluto Medio**
```
MAE = promedio de |predicción - valor_real|
```
- Interpretación directa: "Me equivoco de media ±15 unidades al mes"
- No penaliza más los errores grandes
- Bueno para productos donde todos los errores son igual de costosos

**RMSE — Raíz del Error Cuadrático Medio**
```
RMSE = √(promedio de (predicción - valor_real)²)
```
- Penaliza más los errores grandes (los cuadra)
- Útil cuando una predicción muy mala (comprar 0 cuando necesitas 200) es catastrófica
- Siempre será ≥ MAE. Si RMSE >> MAE, hay errores muy grandes puntuales

**MAPE — Error Porcentual Absoluto Medio**
```
MAPE = promedio de |(predicción - valor_real) / valor_real| × 100%
```
- Independiente del volumen: "Me equivoco un 8%"
- Permite comparar el modelo entre productos que venden 10 y productos que venden 1000 unidades
- ⚠️ Problema: cuando `valor_real = 0` (meses sin ventas), da infinito. Hay que manejarlo.

**Benchmarks para SmartPharma:**

| MAPE | Calidad |
|------|---------|
| < 10% | Excelente — nivel profesional |
| 10-15% | Bueno — válido para la mayoría de decisiones |
| 15-25% | Aceptable — útil como guía, con cautela |
| > 25% | Pobre — revisar datos y features |

**Para clasificación (predicción de rotura de stock sí/no):**

**Matriz de Confusión:**

```
                    Predijo: SÍ rotura   Predijo: NO rotura
Real: SÍ rotura        TP (acierto)        FN (fallo grave)
Real: NO rotura        FP (alarma falsa)   TN (acierto)
```

- **TP (True Positive):** predijo rotura → había rotura. ✅
- **TN (True Negative):** predijo no rotura → no hubo rotura. ✅
- **FP (False Positive):** alarma falsa. Pides de más. Costo: exceso de stock.
- **FN (False Negative):** no detectó la rotura. El más peligroso. Costo: venta perdida, cliente insatisfecho.

**Precision vs Recall:**
- **Precision:** de todas las veces que dije "habrá rotura", ¿cuántas acerté? (minimiza alarmas falsas)
- **Recall:** de todas las roturas reales, ¿cuántas detecté? (minimiza roturas no detectadas)

> [!TIP]
> En farmacia, el **Recall** es más importante que la **Precision**. Es mejor tener alguna alarma falsa (pedir un poco de más) que perderse una rotura real (quedarse sin stock de un medicamento esencial).

---

## BLOQUE 3 — EL PROBLEMA ESPECÍFICO

---

### 7. Series Temporales (Time Series) — El corazón de SmartPharma

Una **serie temporal** es una secuencia de observaciones ordenadas en el tiempo. Las ventas de un producto mes a mes son una serie temporal.

**Componentes que componen cualquier serie temporal:**

```
VENTAS_TOTALES = Tendencia + Estacionalidad + Ciclo + Ruido

Tendencia (T):      La dirección general a largo plazo
                    ↗ Crecimiento por expansión del barrio
                    ↘ Declive por competencia

Estacionalidad (S): Patrones que se repiten con periodo fijo
                    📅 Anual: pico antigripales en invierno
                    📅 Semanal: más ventas viernes-sábado

Ciclo (C):          Fluctuaciones irregulares de largo plazo
                    (crisis económica, pandemia)

Ruido (R):          Variación aleatoria impredecible
                    (una compra puntual grande, un error de registro)
```

**¿Por qué es distinto predecir una serie temporal?**

En ML clásico, cada fila es independiente. En series temporales, las filas están relacionadas: lo que vendiste ayer predice lo que venderás hoy.

A este concepto se le llama **autocorrelación**: la correlación de una variable consigo misma en el tiempo.

**El concepto de Lag (retardo):**

Un lag-1 es el valor de hace 1 período. Lag-12 es el valor de hace 12 meses (mismo mes del año anterior).

```python
# Ejemplo conceptual de lag features para enero 2025:
lag_1  = ventas_diciembre_2024   # ¿qué vendí el mes pasado?
lag_3  = ventas_octubre_2024     # ¿qué vendí hace 3 meses?
lag_12 = ventas_enero_2024       # ¿qué vendí hace un año exacto?
```

**Las lag features más poderosas para SmartPharma:**
- **Lag-1:** captura momentum reciente
- **Lag-3:** captura tendencia trimestral
- **Lag-12:** captura estacionalidad anual (el más importante en farmacia)
- **Rolling mean 3m:** media móvil 3 meses, suaviza ruido
- **Rolling mean 12m:** tendencia del último año

**Estacionariedad:**

Una serie temporal es **estacionaria** si su media y varianza no cambian con el tiempo. Muchos modelos clásicos (ARIMA) solo funcionan bien con series estacionarias.

```
No estacionaria (tiene tendencia):    ↗↗↗↗ (la media sube)
Estacionaria (oscila alrededor de la misma media): ≈≈≈≈
```

Cómo hacerla estacionaria: **diferenciación** (restar el valor anterior: ventas_hoy - ventas_ayer).

**Modelos especializados en series temporales:**

| Modelo | Tipo | Fortaleza |
|--------|------|-----------|
| ARIMA | Clásico | Capta autocorrelación y tendencia |
| SARIMA | Clásico | Como ARIMA + estacionalidad explícita |
| Prophet | Moderno-simple | Maneja festivos, outliers, gaps |
| XGBoost + lags | ML estándar | Muy potente si el feature engineering es bueno |
| LightGBM + lags | ML estándar | Más rápido que XGBoost, similar resultado |
| LSTM | Deep Learning | Aprende patrones muy complejos, costoso |

---

### 8. Ingeniería de Features (Feature Engineering)

**La feature engineering es donde el conocimiento del negocio se convierte en ventaja competitiva.**

Un modelo de ML puro aprende de números. Tú puedes transformar el contexto de la farmacia en números que el modelo pueda usar, y eso marca la diferencia entre un MAPE del 20% y uno del 8%.

**Categorías de features para SmartPharma:**

**A) Features temporales (calendáricas)**

```
mes_numero      → 1 a 12 (el modelo aprende que diciembre es especial)
trimestre       → 1 a 4
semana_del_año  → 1 a 52
es_fin_de_mes   → 1/0 (algunos pedidos se concentran a fin de mes)
dias_en_mes     → 28/29/30/31 (febrero tiene menos días)
```

**B) Features de estacionalidad farmacéutica**

```
temporada_gripe         → 1 si mes ∈ {11, 12, 1, 2}, si no 0
temporada_verano        → 1 si mes ∈ {6, 7, 8}, si no 0
temporada_alergias      → 1 si mes ∈ {3, 4, 5}, si no 0
semana_santa            → 1 si la semana cae en período de Semana Santa
festivos_mes            → número de festivos nacionales en ese mes
```

**C) Features de lag (historial de ventas)**

```
ventas_lag_1            → ventas del mes anterior
ventas_lag_2            → ventas de hace 2 meses
ventas_lag_3            → ventas de hace 3 meses
ventas_lag_6            → ventas de hace 6 meses
ventas_lag_12           → ventas del mismo mes del año anterior ⭐
ventas_rolling_mean_3   → media de los últimos 3 meses
ventas_rolling_mean_6   → media de los últimos 6 meses
ventas_rolling_std_3    → desviación estándar últimos 3 meses (volatilidad)
```

**D) Features de producto**

```
categoria               → Medicamento / Parafarmacia / OTC
laboratorio             → codificado numéricamente
precio_actual           → precio de venta
precio_cambio           → 1 si el precio cambió este mes, 0 si no
es_generico             → 1/0
es_referencia_marca     → 1/0
```

**E) Features de stock y operación**

```
stock_inicio_mes        → unidades al inicio del mes
rotura_mes_anterior     → 1 si el mes pasado hubo rotura, 0 si no
dias_rotura_anterior    → cuántos días duró la última rotura
tasa_servicio_proveedor → % de pedidos entregados a tiempo
```

**F) Features externas y de Geomarketing (Fase 2 - Auditoría de Compra)**

Para comparar farmacias inteligentemente (Location Intelligence), no basta con sus ventas internas. Necesitamos parametrizar su entorno usando APIs externas (como Google Places o catálogos públicos).

```
supermercados_radio_500m      → Cantidad de anclas comerciales cercanas (genera tráfico)
hospitales_clinicas_1km       → Cercanía a prescriptores médicos
competidores_radio_1km        → Número de otras farmacias cercanas
estacion_transporte_cerca     → 1 si hay metro/tren a <300m, 0 si no
renta_per_capita_barrio       → Dato sociodemográfico de la zona
```

> [!NOTE]
> Las features externas geográficas son la clave para la Fase 2. Permiten al modelo entender *por qué* una farmacia vende lo que vende, y si está por debajo o por encima del potencial real de su ubicación. Empezamos sin ellas para la Fase 1 (stock puramente histórico) y las añadimos cuando auditemos compras.

---

### 9. Aprendizaje No Supervisado: Encontrar "Gemelos" (Fase 2)

Cuando audites una farmacia para un posible comprador, comparar sus ventas con "la media nacional" es inútil. Una farmacia de costa en agosto no se comporta igual que una de interior en un barrio residencial. Necesitas compararla con sus **Gemelos Estadísticos**.

Para esto usamos algoritmos de **Clustering** (Agrupamiento):

**1. K-Means (El clásico de negocio)**
- **Cómo funciona:** Le dices "encuentra K grupos (ej. K=4)". El algoritmo busca centros de gravedad y asigna cada farmacia al centro más cercano basándose en sus features (ventas, tamaño, ubicación).
- **Ideal para:** Segmentar tu cartera de clientes o clasificar rápidamente una farmacia en "Categoría A, B, C o D".
- **Contras:** Te obliga a adivinar cuántos grupos hay de antemano (la "K").

**2. DBSCAN (Agrupamiento Espacial Basado en Densidad)**
- **Cómo funciona:** Agrupa las farmacias que están "apretujadas" en el espacio de datos (muy similares entre sí) y marca las que están solas como "ruido" o "anomalías". No necesitas decirle cuántos grupos hay.
- **Ideal para:** Detectar "Perlas Negras" o "Unicornios". Si estás auditando una farmacia y DBSCAN dice que es una anomalía positiva (vende excepcionalmente bien para su mal entorno), es una compra que requiere investigación cuidadosa.

**El proceso de la Fase 2:**
1. Metemos todas las *Features* de la farmacia auditada + la base de datos de mercado.
2. El modelo de clustering encuentra el grupo de las 10 farmacias más similares en toda España.
3. El dashboard de Auditoría muestra: *"Tus ventas en dermo crecen un 2%, pero tus 10 farmacias gemelas crecen al 8%. Tienes margen operativo de mejora"*.

**Codificación de variables categóricas:**

Los modelos necesitan números, no texto.

```
One-Hot Encoding (para pocas categorías):
  categoria = "Medicamento" → [1, 0, 0]
  categoria = "Parafarmacia" → [0, 1, 0]
  categoria = "OTC" → [0, 0, 1]

Label Encoding (para muchas categorías con orden lógico):
  baja_rotacion = 0, media_rotacion = 1, alta_rotacion = 2

Target Encoding (para laboratorios, muchos valores):
  cada laboratorio se reemplaza por su media histórica de ventas
```

**Normalización y Escalado:**

Algunos modelos (regresión lineal, LSTM) son sensibles a la escala. Si el precio va de 2€ a 200€ y el stock de 0 a 10.000, el modelo puede dar más peso al stock solo por su magnitud.

- **Min-Max Scaling:** escala entre 0 y 1. Bueno si no hay outliers.
- **Standard Scaling (Z-score):** media 0, desviación 1. Robusto a outliers.
- **Log Transform:** para variables muy asimétricas (ventas con picos muy extremos).

> [!TIP]
> XGBoost y LightGBM son **indiferentes al escalado** — son basados en árboles y no necesitan preescalado. ARIMA, regresión lineal y LSTM sí lo necesitan.

---

## BLOQUE 4 — DECISIONES DE MODELO

---

### 10. Selección de Modelos — Comparativa completa

**Filosofía:** Empieza simple. Añade complejidad solo si los datos la justifican.

**Nivel 1 — Baselines (punto de partida):**

Antes de cualquier modelo de ML, debemos calcular baselines simples. Si el modelo ML no supera estos, no sirve.

| Baseline | Cómo funciona | Cuándo usar |
|----------|--------------|-------------|
| Naive (último valor) | Predice que el próximo mes = este mes | Referencia mínima |
| Seasonal Naive | Predice que este mes = mismo mes año pasado | Muy bueno para estacionalidad fuerte |
| Media móvil | Predice la media de los últimos N meses | Suaviza variaciones |

**Nivel 2 — Modelos clásicos de series temporales:**

**ARIMA (AutoRegressive Integrated Moving Average)**
- Parámetros: `(p, d, q)` — orden autoregresivo, diferenciación, media móvil
- Pros: interpretable, rápido, funciona con pocos datos
- Contras: solo una serie a la vez, no escala bien a cientos de productos
- Para SmartPharma: útil para productos estrella donde queremos máxima interpretabilidad

**SARIMA (Seasonal ARIMA)**
- Añade parámetros `(P, D, Q, s)` para estacionalidad
- `s` = periodo estacional → en SmartPharma, s=12 (mensual anual)
- Pros: capta estacionalidad explícitamente
- Contras: 7 parámetros a ajustar, más complejo

**Prophet (de Meta/Facebook)**
- Diseñado para series con estacionalidad y festivos
- No requiere que la serie sea estacionaria
- Maneja automáticamente outliers y cambios de tendencia (changepoints)
- Permite añadir festivos por país
- Pros: robusto, fácil de interpretar, poco riesgo de overfitting en configuración básica
- Contras: no es el más preciso para productos sin estacionalidad clara

**Nivel 3 — ML con lag features (el más potente para SmartPharma a escala):**

**XGBoost / LightGBM con features de lag**

La idea: convertir el problema de serie temporal en un problema de regresión estándar añadiendo lag features.

```
Antes (serie temporal):
  Fecha | Ventas
  Ene24 |  120
  Feb24 |  135
  Mar24 |   ?  ← predecir

Después (problema de regresión con lags):
  fecha | lag_1 | lag_2 | lag_12 | rolling_3m | mes | Ventas
  Mar24 |  135  |  120  |   130  |    128     |  3  |   ?
```

- Pros: puede usar TODAS las features (producto, precio, stock, estacionalidad)
- Entrenas UN SOLO modelo para TODOS los productos (escala perfectamente)
- Muy preciso si el feature engineering es bueno
- Contras: necesita al menos 12-18 meses de histórico por product para lag-12

**Nivel 4 — Deep Learning (solo si realmente se justifica):**

**LSTM (Long Short-Term Memory)**
- Red neuronal especializada en secuencias temporales
- Aprende dependencias largas en el tiempo por sí sola
- Necesita: cientos de muestras por producto, GPU para entrenar, semanas de ajuste
- Para SmartPharma en su estado actual: **no recomendado** — alta complejidad, bajo retorno incremental

**Tabla de decisión para SmartPharma:**

| Criterio | Prophet | LightGBM+lags | SARIMA |
|----------|---------|---------------|--------|
| Facilidad de interpretación | Alta | Media | Alta |
| Escalabilidad (cientos de productos) | Media | ✅ Alta | Baja |
| Manejo de muchas features | ❌ No | ✅ Sí | ❌ No |
| Riesgo de overfitting | Bajo | Medio | Bajo |
| Festivos y eventos | ✅ Nativo | Manual | ❌ No |
| Datos mínimos necesarios | 1 año | 1.5 años | 2 años |
| **Recomendación SmartPharma** | Inicio | Producción | Análisis puntual |

---

### 11. Hiperparámetros — Los diales del modelo

**Definición:** Parámetros que tú configuras antes de entrenar el modelo. El modelo no los aprende solo, los defines tú (o el proceso de optimización).

**vs. Parámetros del modelo:** Los pesos internos que el modelo aprende durante el entrenamiento. Tú no los tocas.

```
                    LO QUE TÚ CONFIGURAS
                         (hiperparámetros)
                              ↓
Datos → [   ALGORITMO   ] → Modelo entrenado → Predicciones
              ↑
         Aprende esto solo
         (parámetros internos)
```

**Hiperparámetros de LightGBM (los más relevantes para decidir):**

| Hiperparámetro | Qué controla | Rango típico | Riesgo |
|----------------|-------------|--------------|--------|
| `n_estimators` | Cuántos árboles | 100-2000 | Más = más lento, rendimiento con retorno decreciente |
| `max_depth` | Profundidad máxima de cada árbol | 3-8 | Muy alto → overfitting |
| `learning_rate` | Velocidad de aprendizaje | 0.01-0.3 | Alto = inestable, bajo = muy lento |
| `num_leaves` | Complejidad del árbol | 20-150 | Muchas hojas → overfitting |
| `min_child_samples` | Mínimo de muestras por hoja | 5-100 | Bajo → overfitting |
| `subsample` | % de filas para cada árbol | 0.6-1.0 | Muy bajo → underfitting |
| `colsample_bytree` | % de features por árbol | 0.5-1.0 | Regularización, reduce overfitting |
| `reg_alpha` | Regularización L1 | 0-10 | Penaliza features innecesarias |
| `reg_lambda` | Regularización L2 | 0-10 | Penaliza modelos complejos |

**Hiperparámetros de Prophet:**

| Hiperparámetro | Qué controla | Opciones |
|----------------|-------------|---------|
| `changepoint_prior_scale` | Flexibilidad de la tendencia | 0.001-0.5 (mayor = más flexible, más riesgo overfitting) |
| `seasonality_prior_scale` | Fuerza de la estacionalidad | 1-20 (mayor = más peso a la estacionalidad) |
| `seasonality_mode` | ¿Estacionalidad suma o multiplica? | `additive` / `multiplicative` |
| `yearly_seasonality` | Estacionalidad anual | True/False/número de términos |
| `weekly_seasonality` | Estacionalidad semanal | True/False (con datos diarios) |

**Cómo se optimizan los hiperparámetros:**

**Grid Search:** Probar todas las combinaciones de una cuadrícula. Exhaustivo pero muy lento.

**Random Search:** Probar combinaciones aleatorias. Más eficiente que Grid Search.

**Bayesian Optimization (Optuna, Hyperopt):** Aprende qué zonas del espacio de hiperparámetros son prometedoras y busca ahí. El mejor método.

> [!WARNING]
> **El error más común:** Optimizar hiperparámetros evaluando sobre el conjunto de test. Eso convierte el test en train implícitamente, y el modelo aprende los hiperparámetros que funcionan para ESOS datos específicos, no para datos futuros reales. La solución: usar un conjunto de **validación** separado o cross-validation para optimizar, y el test solo se toca una vez al final para el reporte definitivo.

---

### 12. Validación Cruzada — Evaluar de forma fiable

**El problema del single split:** Si tienes mala suerte y el período de test fue atípico (pandemia, desabastecimiento puntual), la evaluación no refleja el rendimiento real del modelo.

**Walk-Forward Validation (la validación cruzada para series temporales):**

```
Intento 1: TRAIN [Jan22-Dec23] → VALID [Jan24-Mar24] → MAE: 12.3
Intento 2: TRAIN [Jan22-Mar24] → VALID [Apr24-Jun24] → MAE: 10.8
Intento 3: TRAIN [Jan22-Jun24] → VALID [Jul24-Sep24] → MAE: 14.1
Intento 4: TRAIN [Jan22-Sep24] → VALID [Oct24-Dec24] → MAE: 11.5

MAE promedio: 12.2  ← Esta es la métrica fiable
Desviación:   1.4   ← Esto mide la estabilidad del modelo
```

**Lo que nos dice cada número:**
- **MAE/MAPE promedio:** rendimiento esperado en producción real
- **Desviación estándar del error:** estabilidad. Alta varianza = el modelo es inestable

**Criterio de aceptación:**
- Si el MAPE varía mucho entre folds (ej: 8%, 18%, 9%, 19%) → hay inestabilidad. Investigar por qué.
- Si es consistente (ej: 11%, 12%, 10%, 13%) → el modelo es robusto. Proceder.

**Gap temporal en la validación:**

En predicción con horizonte de 1 mes, añadir un gap de 1 mes entre train y validation es buena práctica para simular el escenario real de predicción.

```
TRAIN [Jan22-Nov23] → GAP [Dic23] → VALID [Jan24-Mar24]
```

---

### 13. Importancia de Variables (Feature Importance)

Después de entrenar, podemos preguntarle al modelo: ¿qué has aprendido a usar más?

**Métodos de importancia:**

**Gain (importancia por ganancia):** cuánto mejora la predicción cuando se usa esa feature para dividir los datos. Es la métrica más confiable en árboles.

**Permutation Importance:** se baraja aleatoriamente una feature y se mide cuánto empeora el modelo. Más fiable pero más costoso computacionalmente.

**SHAP Values (SHapley Additive exPlanations):** el método más sofisticado. Explica cuánto contribuye cada feature a cada predicción individual.

```
Ejemplo output importancia para Ibuprofeno 400mg en Diciembre:

ventas_lag_12         ████████████████ +42 unidades
mes_numero (12)       ██████████       +28 unidades
ventas_lag_1          ████████         +18 unidades
temporada_gripe       ████             +10 unidades
precio               ██               - 5 unidades (precio alto reduce ventas)
stock_inicio_mes     █                + 2 unidades
```

**Por qué esto es valioso para ti como arquitecto:**

1. **Validación de sentido de negocio:** Si "id_cliente" aparece como la feature más importante, algo está mal (data leakage).
2. **Simplificación del modelo:** Features con importancia cercana a 0 → eliminar. Modelo más simple = menos overfitting.
3. **Comunicación con el equipo:** Puedes explicar por qué el modelo predice lo que predice.
4. **Detección de problemas de datos:** Una feature que debería importar mucho pero no importa → revisar su calidad.

---

## BLOQUE 5 — CALIDAD Y PRODUCCIÓN

---

### 14. El Problema del Dato Sucio

**"Garbage in, garbage out"** — es la frase más repetida en ML y la más importante.

El mejor modelo del mundo fracasa con datos malos. En farmacia, los datos sucios son más comunes de lo que parece.

**Tipos de problemas en datos farmacéuticos:**

**Valores faltantes (NaN / NULL):**
- Meses sin ventas porque el producto estaba de vacaciones o sin stock
- Ventas no registradas por error del sistema
- ¿Es 0 porque no se vendió nada, o porque no hay dato?

Estrategias para manejarlos:
```
Imputación con 0:        Si sabemos que estaban en stock y no se vendió nada
Imputación con media:    Para valores numéricos en períodos normales
Imputación con lag-12:   Usar el mismo mes del año anterior
Forward fill:            Copiar el último valor disponible
Eliminar la fila:        Si hay demasiados datos faltantes seguidos
```

**Outliers (valores atípicos):**
- Una compra institucional puntual (hospital, residencia) que infla un mes
- Un error de entrada: 1000 unidades en lugar de 100
- Una rotura de stock que hace que un mes tenga ventas artificialmente bajas

Estrategias:
```
Detección con IQR:          Valores fuera de [Q1 - 1.5×IQR, Q3 + 1.5×IQR]
Winsorizing:                Recortar al percentil 5 y 95
Logging + flag:             Marcar el outlier con una feature binaria
                            y ajustar el valor (el modelo aprende ambas cosas)
```

**Roturas de stock (crítico en SmartPharma):**

Si un mes vendiste 0 unidades porque no tenías stock (no porque no había demanda), ese 0 engaña al modelo. La demanda real era X pero parece 0.

```
Solución: añadir feature "rotura_stock_mes" = 1
         y considerar imputar las ventas con la demanda estimada
         en lugar del 0 observado.
```

**Discontinuación y nuevos productos:**

- Productos introducidos hace 3 meses no tienen lag-12 → el modelo no puede predecirlos bien con lags largos.
- Solución: predecirlos con un modelo más simple (Prophet) o excluirlos del modelo principal hasta tener histórico suficiente.

**Checklist de calidad de datos antes de entrenar:**

```
[ ] ¿Hay meses con ventas negativas? → Error de registro
[ ] ¿Hay productos con más del 20% de meses en 0? → Posible descontinuación
[ ] ¿Hay picos superiores a 3σ de la media? → Posible outlier
[ ] ¿El mismo SKU tiene distintos nombres? → Duplicados
[ ] ¿Los datos llegan hasta el mes actual sin gaps? → Integridad
[ ] ¿Las roturas de stock están marcadas? → Crítico
```

---

### 15. Sesgo y Varianza — El diagnóstico del modelo

**El diagnóstico más importante para saber qué hacer cuando el modelo falla.**

```
ALTO SESGO (Bias) → Underfitting
  Síntoma: Error similar y alto, tanto en train como en test
  El modelo es demasiado simple
  Solución: Añadir features, usar modelo más complejo

ALTA VARIANZA (Variance) → Overfitting
  Síntoma: Error bajo en train, error alto en test
  El modelo es demasiado complejo
  Solución: Más datos, regularización, menos features, modelo más simple

LO QUE BUSCAMOS:
  Error moderado-bajo en train
  Error similar (no mucho mayor) en test
```

**Curvas de aprendizaje:** Visualización para diagnosticar:

```
Curva de aprendizaje — modelo con OVERFITTING:

Error
  │
  │  error_train ──────── (muy bajo)
  │
  │
  │                      error_test ─ ─ ─ ─ (mucho más alto)
  └────────────────────────────────────────→ Tamaño del dataset de entrenamiento

Curva de aprendizaje — modelo BIEN AJUSTADO:

Error
  │
  │  error_train ──────── (moderado)
  │                 error_test ─ ─ ─ (similar al train, convergen)
  │
  └────────────────────────────────────────→ Tamaño del dataset de entrenamiento
```

> [!NOTE]
> Las curvas de aprendizaje también nos dicen si más datos ayudarían. Si las curvas aún no han convergido al añadir más datos de entrenamiento, conseguir más datos históricos mejoraría el modelo.

---

### 16. Entorno de Ejecución: ¿Local o Cloud? (Infraestructura)

Una duda arquitectónica crítica que los fundadores enfrentan pronto: *¿Podemos correr esto en mi portátil o necesitamos pagar servidores masivos de Amazon/Google?*

**La respuesta rápida para SmartPharma: Podemos hacerlo 100% en local.**

A diferencia de modelos masivos como ChatGPT (que requieren clústeres de GPUs de millones de dólares), el Machine Learning de datos tabulares (ventas, Excel, CSV) es extremadamente eficiente.

**El mito del Cloud para Tabular ML:**
Muchos creen que "Machine Learning = Cloud AWS = Dinero". Es falso. Algoritmos como LightGBM o Prophet, incluso entrenando cientos de miles de filas (varios años de ventas de miles de productos), tardan **segundos o pocos minutos en un ordenador portátil moderno estándar**.

| Entorno | Pros | Contras | Veredicto SmartPharma |
|---------|------|---------|----------------------|
| **Local (Tu ordenador)** | Gratis, 0 latencia, máxima privacidad de datos (crítico en salud), iteración ultrarrápida. | Atado a tu RAM (teóricos límites con >10 millones de filas simultáneas). | ✅ **Recomendado para Fase 1 y 2**. Ideal para prototipar, validar y operar para una consultora con volúmenes iniciales/medios. |
| **Cloud (AWS, Azure)** | Escalabilidad infinita, automatización (MLOps real), APIs externas. | Coste económico, configuración de seguridad pesada, complejidad técnica para desplegar. | ⏳ **Futuro (Fase 3)**. Solo necesario si SmartPharma pasa a ser SaaS y miles de farmacias se conectan simultáneamente a pedir predicciones por segundo. |

> [!TIP]
> **Estrategia sugerida:**
> Usa tu máquina local para todo el entrenamiento, experimentación y generación de informes de auditoría. Si en algún momento necesitas entrenar redes neuronales pesadas (LSTM) que tarden días, alquilamos una instancia GPU en la nube por horas (cuesta literalmente céntimos), entrenamos y descargamos el modelo. No asumas costes estructurales en la nube hasta que el negocio lo exija a gritos.

---

### 17. Pipelines de ML — Del dato crudo a la predicción

**Definición:** Un pipeline es la secuencia automatizada de transformaciones que llevan el dato bruto hasta la predicción final.

**Por qué los pipelines son críticos:**

Sin pipeline, cuando entrenas en datos de 2022-2024 y luego predices en 2025, podrías calcular la normalización con datos de 2025 (que no tenías disponibles en el entrenamiento). Eso corrompe todo.

**Pipeline tipo para SmartPharma:**

```
Datos brutos (CSV/DB)
       │
       ▼
1. Limpieza de datos
   → Eliminar duplicados
   → Manejar NaN
   → Detectar/tratar outliers
   → Marcar roturas de stock
       │
       ▼
2. Feature Engineering
   → Crear lag features
   → Crear rolling averages
   → Codificar variables temporales
   → One-Hot Encoding de categorías
       │
       ▼
3. Train/Test Split (temporal)
       │
   ┌───┴───┐
 TRAIN    TEST
   │
   ▼
4. Normalización/Escalado (fit solo en TRAIN)
   │
   ▼
5. Entrenamiento del modelo
   │
   ▼
6. Evaluación en TEST
   │
   ▼
7. Serialización del modelo (guardarlo)
   │
   ▼
8. Predicción en producción (nuevos datos → mismo pipeline)
```

> [!IMPORTANT]
> **Regla del pipeline:** Los parámetros de transformación (media para escalado, valores de imputación) deben calcularse SOLO con datos de TRAIN y luego aplicarse igual a TEST y producción. Si los calculas con todos los datos, filtras información del futuro hacia el pasado.

---

### 18. Reentrenamiento y Deriva del Modelo (Model Drift)

**El modelo no es eterno.** El mundo cambia, y el modelo aprende del pasado. Con el tiempo, empieza a predecir peor.

**Tipos de deriva:**

**Concept Drift (deriva conceptual):**
- La relación entre features y label cambia.
- Ejemplo: antes de la pandemia, enero era un mes normal. Post-pandemia, los patrones de compra cambiaron. El modelo entrenado antes de 2020 no entiende el mundo post-2020.

**Data Drift (deriva de datos):**
- La distribución de los datos de entrada cambia, aunque la relación siga siendo la misma.
- Ejemplo: abres una nueva línea de productos. El rango de precios cambia. El modelo nunca vio productos en ese rango.

**Cómo detectar deriva:**

```python
# Monitoreo continuo del MAPE real vs predicho:
Si MAPE_últimas_4_semanas > MAPE_baseline * 1.3:
    alertar: "El modelo puede estar degradado"
    iniciar_proceso_reentrenamiento()
```

**Estrategias de reentrenamiento:**

| Tipo | Cuándo | Pros | Contras |
|------|--------|------|---------|
| Periódico fijo | Cada 3-6 meses | Simple de implementar | Puede reentrenar innecesariamente o tarde |
| Basado en métricas | Cuando el MAPE supera un umbral | Reactivo a la realidad | Requiere monitoreo continuo |
| Ventana deslizante | Solo usar los últimos N meses de datos | El modelo olvida el pasado lejano | Puede perder estacionalidad anual si N < 12 |

> [!TIP]
> Para SmartPharma, recomiendo reentrenamiento **trimestral** más monitoreo mensual de métricas. Si el error sube > 30% respecto al baseline, reentrenar inmediatamente.

---

### 19. Interpretabilidad vs. Precisión

**Existe un trade-off real entre entender qué hace el modelo y que el modelo sea preciso.**

```
INTERPRETABILIDAD ALTA ←────────────────→ PRECISIÓN ALTA

Regresión lineal         ●
Árbol de decisión simple    ●
Random Forest                    ●
XGBoost / LightGBM                    ●
Redes Neuronales LSTM                       ●
```

**¿Por qué importa la interpretabilidad en SmartPharma?**

- **Regulación:** En el contexto sanitario, si el modelo recomienda algo, debe poder explicarse.
- **Confianza del usuario:** "El modelo dice que pidas 200 unidades" → el farmacéutico lo rechazará si no entiende por qué.
- **Detección de errores:** Si el modelo puede explicarse y la explicación no tiene sentido, hay un bug.

**Solución práctica — SHAP values:**

SHAP resuelve parcialmente el dilema. Permite usar un modelo complejo (LightGBM) y luego explicar cada predicción individual:

```
"SmartPharma predice 185 unidades de Augmentine 500mg para Febrero porque:
  +62 unidades: misma época el año pasado (lag-12 = 123u, + 50.4%)
  +28 unidades: tendencia creciente en los últimos 3 meses
  +18 unidades: temporada de infecciones respiratorias
  - 8 unidades: precio subió un 5% respecto al año anterior
  ─────────────────────────────────────────────────────
  Total: 185 unidades"
```

Esto convierte una "caja negra" en algo que el farmacéutico puede evaluar y validar.

---

### 20. Ética y Riesgos en Predicción — Decisiones críticas

**El modelo de ML de SmartPharma toma decisiones que afectan:**
- Disponibilidad de medicamentos para pacientes
- Inmovilización de capital en stock
- Relaciones con proveedores

**Riesgos a gestionar activamente:**

**Sesgo histórico:**
Si en los datos históricos siempre se realizaron pedidos conservadores (por política de empresa o liquidez), el modelo aprenderá a predecir conservadoramente. El modelo reproduce los sesgos de los datos, no la demanda real.

**Recomendación de intervención humana:**

El modelo debe ser una herramienta de apoyo, no un sistema autónomo en contextos críticos.

```
SEMÁFORO DE CONFIANZA:
🟢 MAPE < 10% + producto estable → Pedido automático sugerido
🟡 MAPE 10-15% + producto con variabilidad → Sugerir, revisión rápida humana
🔴 MAPE > 15% + producto crítico → Mostrar alerta, requiere decisión humana
```

**Medicamentos de alto riesgo:**

Algunos productos (oncológicos, antibióticos de último recurso, insulinas) tienen un costo de rotura de stock que va más allá del económico. Para estos, el modelo puede predecir con un margen de seguridad explícito:

```
pedido_sugerido = predicción_modelo × (1 + margen_seguridad)
margen_seguridad = 0.15 para productos críticos
margen_seguridad = 0.05 para productos habituales
```

**Transparencia hacia el usuario:**

El dashboard debe mostrar siempre:
- La predicción del modelo
- El intervalo de confianza (rango probable: min-max)
- La calidad histórica del modelo para ese producto (MAPE histórico)
- Los factores que más influyeron en la predicción (SHAP top-3)

---

## 🗺️ MAPA COMPLETO DEL PROCESO — SmartPharma ML

```
┌─────────────────────────────────────────────────────┐
│                 1. DATOS                            │
│  Exportar ventas históricas → Limpiar → Validar     │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│              2. FEATURE ENGINEERING                  │
│  Lags · Rolling means · Temporalidad · Categ.       │
│  ← Tu conocimiento del negocio entra aquí →         │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│           3. SPLIT TEMPORAL                          │
│  Train [2022-2024] → Validation → Test [2025]       │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│      4. SELECCIÓN Y ENTRENAMIENTO DE MODELO          │
│  Baseline → Prophet → LightGBM + lags               │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│       5. OPTIMIZACIÓN DE HIPERPARÁMETROS             │
│  Bayesian optimization sobre VALIDACIÓN              │
│  ← Nunca sobre TEST →                               │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│         6. WALK-FORWARD CROSS-VALIDATION             │
│  Verificar consistencia en múltiples períodos       │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│            7. EVALUACIÓN FINAL EN TEST               │
│  MAE · RMSE · MAPE · Comparar con baselines         │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│       8. INTERPRETABILIDAD (SHAP)                    │
│  ¿Qué features usa? ¿Tiene sentido de negocio?      │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│           9. PRODUCCIÓN Y MONITOREO                  │
│  Pipeline automatizado · Reentrenamiento trimestral  │
│  Semáforo de confianza · Intervalo de predicción    │
└─────────────────────────────────────────────────────┘
```

---

## 📌 REGLAS DE ORO PARA NUESTRO TRABAJO CONJUNTO

1. **Test solo se toca una vez.** La evaluación final se hace una sola vez. Si miras el test para ajustar el modelo, ya no es test — es train.

2. **Siempre hay baseline.** Antes de declarar que el modelo es bueno, comparamos contra seasonal naive. Si no supera el "mismo mes del año anterior", el modelo no sirve.

3. **Métricas en train Y test, siempre.** Si train >> test en rendimiento, reportamos overfitting y ajustamos antes de seguir.

4. **Ningún hiperparámetro sin justificación.** Cada cambio va acompañado de: qué hace, qué riesgo tiene, qué métrica esperamos mejorar.

5. **Simple primero.** Prophet antes que LightGBM. LightGBM antes que LSTM. Complejidad solo si los números la justifican.

6. **Tu conocimiento del negocio es parte del modelo.** Las features más poderosas vendrán de lo que tú sabes sobre cómo funciona una farmacia.

7. **El modelo informa, el farmacéutico decide.** Para medicamentos críticos, el modelo es apoyo, nunca el decisor final.

8. **MAPE objetivo: ≤ 12%.** Más que suficiente para tomar decisiones de pedido correctas en el 90%+ de los casos.

---

*Guía elaborada para SmartPharma — versión expandida*
*Próximo paso: diseño conjunto del modelo, feature a feature.*

---

## 🎯 DECISIONES DE PROYECTO APLICADAS (ACTUALIZADO)

Para la implementación real del modelo en SmartPharma, se han acordado las siguientes directrices estratégicas de datos:

1. **Histórico de Festivos y Horarios Comerciales (3 Años):** Se incluirá en el dataset de entrenamiento un mapeo de los días festivos locales/nacionales y el horario de apertura de los últimos 3 años. Esto permitirá al modelo distinguir entre una "caída de demanda real" y un "día con la farmacia cerrada".
2. **Validación de Eventos Especiales:** Se mantiene activa la lógica de la pestaña de configuración de la farmacia para variables como niveles de Gripe, COVID y Alergias. Se diseñará un método para monitorear y comprobar su impacto real sobre la calidad de las predicciones del modelo ("Feature Injection").
3. **Fotografía de Stock Mensual:** Ante la imposibilidad de recuperar el stock histórico detallado de los últimos 3 años, se instaura un proceso de subida iterativa. Cada mes se subirá una captura/foto del stock actual. Esto alimentará progresivamente al modelo hacia el futuro, enseñándole a identificar roturas recientes de stock y mejorando iterativamente su capacidad de sugerir reposiciones precisas.
