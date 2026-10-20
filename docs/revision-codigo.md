# REVISION SmartPharma

Harness de pruebas: copia del repo en scratchpad (no toca farmacias/), AppTest con `farmacia_activa=Farmacia_Demo_Centro`,
necesita `sys.path.insert(0, raiz)` y `PYTHONIOENCODING=utf-8`.

## Fase 1: auditoria

### 1. Ruff + imports — HECHO
- Ruff (F, E9) limpio; todos los modulos importan; AppTest de app.py con Farmacia_Demo_Centro: sin excepciones (2,5 s), 6 pestanas.
- Carga inicial muestra aviso "modelo guardado incompatible con version anterior del motor" (revisar en paso ML).
- Bajo: ruff B905/B007 (zip sin strict en ml/engine.py:377, ui/charts.py, ui/tabs/configuracion.py:169). No bloqueante.

### 2. Funciones legacy vs modular — HECHO
- No falta ninguna funcion ni constante de nivel modulo del legacy (115 defs legacy; 89 identicas por AST).
- Cambios cosmeticos/benignos: width='stretch', nombre app, escritura atomica en guardar_json/dataframe, pestana ML en main, import local en calcular_benchmark_hs.
- Pendientes de revisar en su paso: modulo_configuracion/BI/auditoria (diffs 25-38 lineas) y ML (build_features, entrenar_modelo_ml, cargar/guardar modelo, FEATURE_COLS).

### 3a. Selector + carga — HECHO
- Datos Farmacia_Demo_Centro: Fecha en historico es texto dd/mm/aaaa; ofertas con Tiers como array de dicts.
- MEDIO (comprobado) core/business.py:531 Fecha_Caducidad sin dayfirst: '05/03/2025' -> 3 mayo y '25/03/2025' -> NaT (se ignora). Arreglo: dayfirst=True. (Mismo patron sin dayfirst en :58, pero ahi es ISO propio: ok.)
- MEDIO (lectura) data/io.py:65 guardar_dataframe_farmacia traga cualquier excepcion (`except: pass`): el usuario cree que guardo. Arreglo: st.error/log.
- BAJO data/io.py:54 df vacio no se guarda -> un parquet antiguo reaparece al reabrir. data/io.py:13 crear_farmacia no sanea '..', '\\', ':' (ruta invalida/traversal en Windows). core/business.py:533 `df.get(COL_PVL, pd.Series(0))` desalineado si falta PVL.

### 3b. Configuracion — HECHO (diff vs legacy: solo aviso modelo obsoleto, backtest/baseline y benchmark de red)
- ALTO (lectura; file_uploader devuelve el archivo en cada rerun) ui/tabs/configuracion.py:23-35: mientras el inventario sigue en el uploader, CADA rerun (cualquier clic en cualquier pestana) reescribe inventario.parquet y anade un snapshot a historico_auditorias.json (tope 24) -> en 24 clics se borra el historial real de auditorias. Idem :41-47 (reescribe historico y vacia caches cada rerun), :105-111 (Excel de protegidos sobrescribe las ediciones manuales del editor), :204-214 y :230-243. Arreglo: procesar solo si cambia file_id (guardar `st.session_state['_up_inv_id']`).
- ALTO (comprobado con pandas) sin normalizar tipo de Codigo_Nacional en ninguna carga: inventario int + historico texto (CSV/Excel con ceros o texto) -> merge lanza ValueError; float vs int funciona. Arreglo: normalizar COL_CN a str sin '.0' en la carga (configuracion.py:26,44 y data/io.py autocarga).
- MEDIO utils/helpers.py:71-74 emparejado de columnas por subcadena: 'Nombre Laboratorio' puede mapearse a Nombre y a Laboratorio; varias esperadas a la misma columna. Tampoco convierte Stock/PVL/Ventas a numerico. Y se guarda aunque falten columnas obligatorias (:26-28, :44-46) -> errores en otras pestanas.
- BAJO :141-145 selectbox index=perfil.get(...) falla si el JSON trae texto/>2.

### 3c. BI — HECHO (diff vs legacy: solo nombre del PDF). Revisadas core/business.py:247-455
- CRITICO (comprobado con Farmacia_Demo_Centro) core/business.py:294-303 Factor_Tendencia compara sumas anuales incluyendo el ano parcial (2025 = 2 meses) -> tendencia media -31% (tope -50%) y :320 la aplica a la venta media: VMM media 33,5 vs real ultimos 12m 48,6. Afecta HS, roturas, rotacion, ROI, pedidos (pide de menos) y KPI "Tend. Ventas". Arreglo: tendencia sobre ventanas de 12 meses moviles (ult. 12m vs 12m previos) o solo anos completos.
- MEDIO core/business.py:310 "mirror" estacional usa solo anio_max: si el ultimo ano es parcial nunca encuentra los meses futuros y cae a media global. Arreglo: ultimo ano que tenga ese mes. :312 media mensual solo sobre meses con fila (meses sin venta ausentes inflan la media) — sospecha segun formato del ERP.
- ALTO (lectura) ui/tabs/business_intelligence.py:216 "Ahorro generado con pedidos" del PDF = suma de ahorro_pedido de TODOS los snapshots KPI, que guardan el ahorro de la previsualizacion (:55) -> se duplica en cada snapshot y no son pedidos reales. La seccion 4 (:110) usa historico_pedidos.json. Arreglo: usar historico_pedidos. KeyError si snapshots antiguos sin 'ahorro_pedido'.
- MEDIO :217-232 genera el PDF y lo escribe en el directorio de trabajo en CADA rerun de la app (todas las pestanas se ejecutan), compartido entre farmacias. Arreglo: generar solo en download_button sin escribir a disco (o en carpeta de la farmacia bajo boton).
- MEDIO incoherencia "zombie": BI = stock>0 sin ventas 12m (business.py:348); snapshot de auditoria (business.py:73) = stock>0 y VMM==0 (sin ventas en toda la historia). Mismo nombre, cifras distintas entre pestanas.
- BAJO :84 donut recibe sobrestock=0 fijo (no se calcula). business.py:363,410 stock negativo no cuenta ni como rotura ni en rotacion. :360 `get(COL_PVL, pd.Series(0))` desalineado.
- PREGUNTA negocio: coste de oportunidad (business.py:449) valora la venta perdida a PVL (coste), no a PVP/margen. Health Score (:342) ignora productos sin ventas (una farmacia llena de zombies puntua alto). ¿Intencionado?

### 3d. Pedidos — HECHO (diff vs legacy: cosmetico). Revisadas business.py:221-246, :735-861, network.py:79-130
- ALTO (comprobado) core/business.py:853 modo presupuesto recorta unidades pero conserva el descuento del tramo calculado con la cantidad completa (Farmacia_Demo_Centro, 500 EUR: 11 uds con 16% "Tier 2", minimo 36). Coste y ahorro falsos. Arreglo: reaplicar aplicar_tiers_dinamicos tras recortar (sin upselling).
- ALTO (comprobado) core/business.py:818 protegido con CN texto ('654321') vs inventario int: no casa y anade fila duplicada Stock=0, 500 uds, precio 0 -> pide stock que ya existe y coste 0. Sin Laboratorio -> ui/tabs/pedidos.py:139 dropna la oculta de la tabla pero cuenta en unidades. Tambien ignora el filtro de laboratorio. Arreglo: normalizar CN (ver 3b) y no anadir protegidos fuera de inventario sin avisar.
- ALTO (lectura) ui/tabs/pedidos.py:179 "Confirmar Pedido" no se bloquea tras confirmar: cada clic vuelve a registrar pedido, promociones y snapshot KPI -> duplica ahorro/inversion en BI y torre. Arreglo: pop pedido_generado o flag confirmado.
- MEDIO pedidos.py:106-208 el pedido persiste al cambiar laboratorio/meses/modo: se confirma con la etiqueta/meses actuales pero lineas del pedido anterior. Arreglo: guardar parametros con el pedido y usarlos al confirmar (o invalidar si cambian).
- MEDIO pedidos.py:68 con motor ML/Ensemble se ignora el modo Presupuesto sin avisar.
- MEDIO network.py:96 y pedidos.py:199 dias de cobertura = uds pedidas / venta diaria, sin sumar el stock actual -> "Proximo pedido sugerido" demasiado pronto; y el minimo lo marca un producto con mucho stock y poco pedido.
- PREGUNTA negocio business.py:749-765 las ofertas se casan solo por nombre/molecula, sin laboratorio: la oferta de un laboratorio se aplicaria a la misma molecula de otro (en Farmacia_Demo_Centro hay 1 lab por molecula, no se ve). ¿Las ofertas son siempre de un laboratorio concreto?
- BAJO pedidos.py:254 `ts.split` falla si Tipo es NaN; :267 filtro de labs por subcadena.

### 3e. Auditoria — HECHO (diff vs legacy: quitado df_rot sin uso). Revisadas business.py:489-647
- MEDIO (comprobado) ui/tabs/auditoria.py:45-51 donut "dinero en riesgo": el sobrestock incluye el stock de los zombies -> se cuentan dos veces (Farmacia_Demo_Centro: 1.925,70 EUR de 5.090,15 son zombies). Arreglo: excluir CN zombie/UVI del exceso.
- MEDIO (comprobado) core/business.py:537-542 sin columna Fecha_Caducidad inventa un 3% del valor de stock (279,71 EUR) y lo muestra como KPI "Caducidades". Arreglo: mostrar "sin datos".
- MEDIO auditoria.py:132 read_csv de facturas sin try y solo utf-8/',' (CSV espanol ';'/latin-1) -> excepcion que corta el resto de la app (pestanas 5-6 no se pintan). Idem :92,:101,:106,:194 KeyError si falta Nombre/Laboratorio.
- BAJO business.py:503 fill rate cuenta como rotura CN con ventas que ya no estan en inventario. :609 conciliacion con CN de distinto tipo -> error (capturado); sobrantes sin PVL dan NaN y no suman. auditoria.py:59-61 "Comparativa Zombies" usa la definicion de snapshot (ver 3c).

### 3f. Torre de control — HECHO (diff vs legacy: cosmetico). Revisada core/network.py:134-405
- ALTO (lectura) ui/tabs/torre_control.py:231-243 "Marcar Ejecutada"/"No Ejecutada" repetibles y no marcan la oportunidad como resuelta: cada clic duplica "Ahorro Red Total" o "ahorro perdido"; se pueden pulsar ambos. Arreglo: guardar id de oportunidad (farmacias+lab+fecha pedidos) y ocultar/ignorar si ya registrada.
- MEDIO (lectura, logica) core/network.py:218-245 rama "optimizado" es codigo muerto: sus condiciones implican solape natural (optima_j <= limite_i y optima_j <= limite_j), asi que nunca sugiere ajustes. Arreglo: redefinir (p.ej. adelantar el pedido de uno dentro de su margen) — requiere decidir regla de negocio.
- MEDIO network.py:153-156 ventanas vencidas se recortan a hoy (optima=limite=hoy, 0 dias) y quedan excluidas de oportunidades en vez de avisar de urgencia. Hereda el error de dias de cobertura sin stock (3d).
- MEDIO torre_control.py:188 la simulacion conjunta usa las ofertas de la farmacia activa para todas; sin ofertas cargadas el ahorro sale 0.
- BAJO network.py:312-330 tier_info se sobrescribe y muestra el ultimo producto, no el mas cercano al siguiente tramo. torre_control.py:40,69,76 `return` oculta secciones 5-6 (coste de no actuar, historial).

### 3g. Laboratorio ML — HECHO (solo lee modelo_pipeline.json; Farmacia_Demo_Centro no lo tiene -> pestana no ejercitada hasta reentrenar)
- BAJO ui/tabs/laboratorio_ml.py:104-111 acceso directo f["ml"]["rmse"] etc.: KeyError con JSON de otra version. Texto :159-165 "colchon = z x RMSE" a contrastar con el motor en paso 4.

### 3h. Exportacion PDF/Excel — HECHO
- MEDIO (comprobado) ui/charts.py:17-18 Excel multi-laboratorio omite lineas sin Laboratorio (dropna): 2 de 3 filas exportadas -> los protegidos anadidos (3d) no llegan al pedido descargado. Arreglo: hoja "Sin laboratorio".
- MEDIO (comprobado) ui/charts.py:20,23 nombre de hoja solo sanea '/': 'Lab: A' -> InvalidWorksheetName; nombres >31 que coinciden al truncar -> duplicado. Se llama en cada render de pedidos (pedidos.py:174) -> la excepcion corta las pestanas siguientes.
- MEDIO (comprobado) utils/pdf_generator.py:25 fuente Helvetica sin unicode: nombre de farmacia con caracteres fuera de latin-1 -> FPDFUnicodeEncodingException en cada render de BI (corta pestanas 3-6). Arreglo: sanear texto (encode latin-1 'replace') o try/except.
- PDF hereda "Ahorro acumulado" erroneo (3c) y la VMM con tendencia erronea (3c).

### 4. ML (ml/engine.py) — HECHO. Experimento en copia scratchpad con Farmacia_Demo_Centro (sin escribir datos)
- OK: split temporal (holdout 3 meses), tuning solo con train, backtest walk-forward, baseline mismo mes ano anterior/lag, ATC sin fuga temporal, guardado por farmacia (ruta activa) y cache invalidada al cambiar farmacia, deteccion de modelo obsoleto.
- CRITICO (comprobado) ml/engine.py:149-157 Growth_Factor: ultimo ano vs penultimo sobre TODO el historico (incluye holdout = fuga) y con ano parcial (media -44%), constante por producto. Es la 2a feature mas importante y empeora: backtest ML 8,54 vs baseline 8,47 (mejora -0,8%); sin ella ML 7,67 (mejora +9,4%), holdout 10,23 -> 9,04. Arreglo: crecimiento con ventanas moviles desplazadas (solo pasado) o eliminarla.
- CRITICO (lectura) ui/tabs/pedidos.py:74-78 + engine.py:414 la "prediccion" usa las features del ultimo mes observado (con su Lag y Mirroring), con un modelo final entrenado sobre esas mismas filas: devuelve el ajuste del ultimo mes, no el mes siguiente ni los meses de cobertura (sin estacionalidad futura). Arreglo: construir fila futura (Mes+1..meses, Lag_30=ultimo mes, Base_Mirroring=mes objetivo del ano anterior).
- ALTO (comprobado) engine.py:62,71 vs :193 mapa ATC con claves str y CN int64 -> todo "OTRO": ATC_Encoded identico para todos los productos (1 valor por periodo). Arreglo: normalizar CN (ver 3b) o mapear con astype(str).
- ALTO (lectura) engine.py:113-129 cold_start_proxy sustituye la VARIABLE OBJETIVO (Ventas) de productos con <6 meses por la media de su molecula en todo el historico (fuga + etiquetas falsas) y ademas contamina las metricas del backtest (y_real inventado). Arreglo: no tocar Ventas en entrenamiento; aplicar proxy solo a la prediccion.
- MEDIO engine.py:553,568 Venta_Media_Mensual = prediccion + z*RMSE y generar_pedido_cobertura la multiplica por meses -> colchon x meses (lineal), y la tabla muestra Safety_Stock=0. Ensemble :540-543 mezcla prediccion con colchon y heuristico sin colchon. Texto de Laboratorio ML (:159-165) no refleja esto.
- MEDIO engine.py:169-174,178-187 Epi_*, Perfil_*, Is_Future_Promo, Was_Promo son constantes por farmacia/producto aplicadas a todo el historico con valores actuales: no aportan senal (la UI dice que "afectan a las predicciones"). :203 Temp_Desviacion usa media de todos los meses (fuga leve). :159 Lag_30 = fila anterior, no mes anterior, si faltan meses.
- BAJO engine.py:518 necesita_reentrenamiento compara filas del historico con filas mensuales agregadas (falso aviso si el historico no es mensual) — sospecha. :471 joblib.dump no atomico.

## Plan de lotes (Fase 2) — (C)=comprobado ejecutando, (L)=lectura/sospecha
Critico
1. Tendencia heuristica con ano parcial: business.py:294-320 (C). Resuelve cifras de BI/pedidos/PDF.
2. Normalizar Codigo_Nacional a texto en todas las cargas (inventario, historico, protegidos, ATC, fisico) (C: merge ValueError, protegidos duplicados, ATC colapsado).
3. ML: quitar fuga de Growth_Factor y no reescribir Ventas en cold start (C/L).
4. ML: construir filas futuras reales para predecir (L) — cambio mayor, pedir OK de diseno.
Alto
5. Uploaders que reprocesan en cada rerun (snapshots de auditoria borrados, protegidos sobrescritos) (L).
6. Botones repetibles: Confirmar Pedido, Marcar Ejecutada/No Ejecutada (L).
7. Presupuesto: reaplicar tramos tras recortar (C).
8. PDF "Ahorro acumulado" desde historico_pedidos y no escribir PDF a disco en cada rerun (L).
Medio
9. Robustez que corta pestanas: nombre de hoja Excel, lineas sin laboratorio en Excel, PDF unicode, CSV facturas sin try (C).
10. Donut: sobrestock sin zombies; caducidad "mock" -> sin datos; Fecha_Caducidad dayfirst (C).
11. Pedido persistente al cambiar parametros; dias de cobertura con stock; ML ignora presupuesto; colchon ML x meses (L).
12. Torre: rama "optimizado" muerta y ventanas vencidas (L) — requiere regla de negocio.
13. guardar_dataframe_farmacia traga errores; validar columnas obligatorias/tipos numericos al cargar (L).
Bajo
14. Resto de BAJO (crear_farmacia, stock negativo, tier_info, KeyErrors defensivos, B905).
Preguntas pendientes: coste de oportunidad a PVL o PVP; Health Score sin productos sin venta; ofertas por laboratorio; definicion unica de "zombie" (12m vs nunca); regla de ajuste de ventanas en torre.

ESTADO: Fase 1 terminada. Esperando aprobacion para empezar lote 1 en rama revision-fable.

## Decisiones del usuario (2026-09-13)
- Arreglar criticos en el codigo (los datos de prueba pueden ser raros). Aprobados en principio: tendencia, normalizar CN, Growth_Factor, prediccion a futuro, uploaders sin sobrescribir, confirmar pedido, presupuesto.
- Coste de oportunidad a PVL (se mantiene). Health Score debe incluir productos con stock sin ventas. Zombie: pendiente confirmar definicion (12m). Torre de control: NO tocar.
- Pendiente: explicacion lote 4 dada; esperar visto bueno antes de editar.

## Fase 2: correccion (rama revision-fable)
- [x] Lote 1 CN normalizado (utils/helpers.normalizar_cn): cargas y autocarga, protegidos, promociones, conciliacion, mapa ATC. Verificado: float/str casan, protegido sin duplicar, ATC 29 grupos (antes 1), AppTest sin excepciones.
- [x] Lote 2 business.crecimiento_12m (12m vs 12m previos, solo pasado) usado en tendencia heuristica y Growth_Factor ML; mirroring sobre ultimos 12m; HS con stock sin ventas = desv 2.0; zombie del snapshot = 12m. Verificado: tendencia media -31%->+3,1% (igual a calculo manual), VMM 33,5->53,1, sin fuga (alterar meses futuros no cambia pasado), backtest ML 7,99 vs base 8,47 (+5,7%), HS Farmacia_Demo_Centro 49,9->7,0 (12 de 42 con stock sin ventas), AppTest OK. Nota lote 3: Was_Promo sale 3a en importancia (constante por CN con promos actuales, posible fuga).
- [x] Lote 3 ml/engine.py: construir_features_futuras predice los meses de cobertura (mes siguiente a hoy), recursivo sobre meses sin historico, aviso si desfase >2 meses; build_features dividido (_agregar_mensual/_features_desde_mensual), Lag/Mirroring por calendario, calendario/clima por mes; Was_Promo por mes (antes constante = fuga); cold start ya no toca Ventas (mezcla 50/50 con media de molecula solo en prediccion, <6 meses); colchon ML = z*RMSE*raiz(meses) (antes (pred+z*RMSE)*meses). Verificado: backtest honesto en Farmacia_Demo_Centro ML 8,70 vs base 8,47 (-2,7%; el +5,7% del lote 2 venia de las fugas Was_Promo/cold start); prueba fuera de muestra entrenando hasta nov/dic-2024: ene-2025 RMSE 8,14 (metodo anterior 28,22, mirroring 10,28), feb-2025 10,52 (anterior 8,67, mirroring 8,17); AppTest entrenar + pedido ML y Ensemble sin excepciones, aviso de 19 meses de desfase. Pendiente menor: tras entrenar, el aviso 'modelo obsoleto' sigue visible hasta el siguiente rerun (preexistente).
- [x] Lote 3c ml/engine.py GRUPOS_FEATURES (Historia de ventas obligatoria, Calendario, Clima, Grupo terapeutico, Promociones; fuera Epi/Perfil por ser constantes) + _seleccionar_grupos (eliminacion hacia atras con validacion temporal solo en train; si quitar varios a la vez empeora, se mantienen todas); prediccion usa feature_names_in_ del modelo. Laboratorio ML: grafico de seleccion + tabla, linea temporal con fechas (ventas reales, zonas train/holdout, ML y baseline en backtest), grafico walk-forward por paso. Verificado AppTest entrenar + Lab sin excepciones; Farmacia_Demo_Centro descarta Clima (-0,57%), RMSE validacion 4,651->4,624. Observacion para 3b: mejora vs baseline oscila entre ejecuciones (-2,7% / -13,2%) con solo 3 meses de backtest -> metricas con mucha varianza.
- [x] Lote 3b tests/test_ml_engine.py (py -3.14 tests/test_ml_engine.py, datos sinteticos, no toca farmacias/): 6/6 pasan -> sin fugas en las 13 variables, patron conocido gana al baseline (+36%), ruido puro y ventas barajadas no bajan del minimo posible, prediccion futura cubre los meses sin NaN, backtest a varios meses no depende de ventas posteriores al corte. Anadido _backtest_horizonte (holdout encadenado como el pedido) en entrenamiento, pipeline y Laboratorio ML (grafico por mes + KPIs). AppTest OK. Farmacia_Demo_Centro a 3 meses: ML -22,6% vs baseline.
- HALLAZGO DISENO (de las pruebas, pendiente de aprobacion): el ML queda lejos del optimo con patron claro (22,4 vs minimo 9,7) y sobreajusta con ruido (11,8 vs 8,0; peor que la media con barajadas). Causa: XGBoost predice unidades absolutas y no extrapola tendencias fuera del rango visto; faltan variables de nivel. Experimento (scratch): Media_12m + Mirroring_Ajustado -> ruido 9,4, patron 21,3, horizonte 3m +16%->+25,5%, sin fugas. Propuesta: (a) anadir esas variables, (b) objetivo relativo (ventas / Media_12m) y reescalar, (c) mas regularizacion en la rejilla.
- [x] Lote 3d ml/engine.py VERSION_MOTOR=2: variables de nivel (Media_12m, Mirroring_Ajustado, Mirroring_Rel, Lag_Rel); objetivo relativo ventas/max(Media_12m,1) con peso por nivel (_entrenar/_predecir en todos los fit/predict); rejilla con 3 combinaciones regularizadas; modelos de otra version = obsoletos. Test nuevo de estacionalidad. Banco 7/7: ruido 11,83->9,09 (min 7,97); barajadas 64,9->52,9 (= media, sin sobreajuste); horizonte 3m mejora 16%->39,4%, error por mes +1 20,5->13,2 / +2 39,2->32,1 / +3 30,0->22,1; estacionalidad may-jul vs feb-abr x1,70 (real x1,73), total verano 8% error. Empeora 1 mes con patron claro 22,4->26,4 (sigue ganando al baseline 35,2). Farmacia_Demo_Centro: 1 mes -13,2%->+11,6%, 3 meses -22,6%->-8,3%. AppTest entrenar + pedidos ML/Ensemble OK.
- [x] Lote 4 ui/tabs/configuracion.py: cada archivo del uploader se procesa una vez por file_id (_archivo_ya_procesado/_marcar_procesado) en inventario, historico, ofertas, protegidos, ATC y temperatura. Verificado con AppTest y uploader simulado, antes/despues: 1 carga + 5 clics -> antes se perdian 6 de 24 snapshots de auditoria, reescribia inventario.parquet y el Excel pisaba la edicion manual de protegidos (99->5); ahora se pierde solo 1 (el snapshot legitimo de la carga), no reescribe y conserva 99. Cargas de Auditoria (facturas, fisico) no escriben: sin cambio.
- [x] Lote 5 ui/tabs/pedidos.py: el pedido guarda sus parametros (pedido_params: lab, modo, meses, presupuesto, motor, nivel) y resultados/confirmacion usan esos; si cambian los widgets, aviso y confirmar deshabilitado; una confirmacion por pedido (pedido_confirmado, boton deshabilitado + guarda en servidor). Verificado AppTest antes/despues: 3 clics en Confirmar (pedido 'Todos', 7 labs) -> antes +21 registros y +3 snapshots KPI; ahora +7 y +1. Cambiar laboratorio tras generar -> aviso y boton deshabilitado; volver al lab generado y confirmar -> registra 1 con el lab correcto. Nota: AppTest no respeta disabled, por eso la guarda en servidor.
- [x] Lote 6 core/business.py: generar_pedido_presupuesto recalcula el tramo al recortar (max_unidades_en_presupuesto evalua cada tramo: mayor cantidad cuyo coste con el descuento de esa cantidad cabe; coste no monotono). Verificado Farmacia_Demo_Centro presupuestos 150-3000: antes 3 de 7 con descuento indebido, ahora 0; coste siempre <= presupuesto. Casos borde OK. AppTest modo presupuesto 500 EUR: 498,91, sin excepciones.

- [x] Lote 7 (a) core/business.calcular_sobrestock(excluir_cns): donut Auditoria/BI y snapshot sin stock zombie; grafico de concentracion sin zombie ni UVI. Farmacia_Demo_Centro: sobrestock 3.676,89 -> 1.751,19 (0 solapes con zombie 1.925,70); BI ya no pasa 0. (b) calcular_riesgo_caducidad sin Fecha_Caducidad valida -> None ("Sin datos"), sin mock; dayfirst=True. (c) network.registrar_pedido_confirmado: dias = (stock actual + pedido) / venta diaria de la propia linea (demanda ML si el pedido es ML); pedidos 'Todos' toma el minimo de los registros y registra lineas sin laboratorio como 'General'. Antes 14-41 dias, ahora ~66 para 2 meses de cobertura. (d) ML y Ensemble respetan el modo presupuesto (_pedido_desde_demanda -> generar_pedido_presupuesto con z del nivel de servicio): 500 EUR -> 499,01 / 499,82. AppTest sin excepciones; banco ML 7/7.

## Estado tras Fase 2 (lotes aprobados completos) — pendientes del plan original, sin aprobar
- Medio: robustez que corta pestanas (hoja Excel invalida, lineas sin laboratorio fuera del Excel, PDF unicode, CSV facturas sin try); donut con zombies duplicados; caducidad 'mock'; Fecha_Caducidad sin dayfirst; PDF 'ahorro acumulado' desde snapshots y escrito a disco en cada rerun; dias de cobertura sin stock; ML ignora modo presupuesto; guardar_dataframe_farmacia traga errores; validacion de columnas/tipos al cargar.
- Bajo: crear_farmacia sin sanear, stock negativo, KeyErrors defensivos, B905.
- Torre de control: no tocar (decision usuario). Ofertas por laboratorio: sin respuesta.
Torre de control: no tocar. Ofertas por laboratorio: sin respuesta, no se cambia.
