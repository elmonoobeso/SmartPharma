import streamlit as st
import pandas as pd
from config.settings import COL_CN, COL_FECHA, COL_LAB, COL_MOLECULA, COL_NOMBRE, COL_PVL, COL_STOCK, COL_VENTAS
from core.business import cargar_calendario_farmacia, cargar_perfil_farmacia, cargar_productos_protegidos, cargar_reglas_surtido, guardar_calendario_farmacia, guardar_perfil_farmacia, guardar_productos_protegidos, guardar_reglas_surtido, imputar_stockouts, normalizar_ofertas_dinamico, obtener_ventas_media, registrar_snapshot_auditoria
from data.io import guardar_dataframe_farmacia, ruta_farmacia_activa
from ml.engine import ML_AVAILABLE, build_features, entrenar_modelo_ml, guardar_modelo_farmacia, invalidar_cache_modelo, necesita_reentrenamiento, obtener_modelo_cacheado
from ui.charts import grafico_importancia_features
from ui.components import render_kpi
from core.analisis import normalizar_opcionales
from ui.tabs.analisis_ui import render_columnas_opcionales, render_compras, render_fecha_inventario, render_parametros_analisis
from utils.helpers import validar_y_renombrar_columnas
from utils.network import ejecutar_benchmark_red


def _archivo_ya_procesado(archivo, clave):
    """st.file_uploader devuelve el mismo archivo en CADA rerun. Sin esto, cualquier clic
    en la app volvia a guardar el parquet, anadir un snapshot de auditoria (borrando el
    historial real al superar el tope) o pisar las ediciones manuales de protegidos."""
    return st.session_state.get(clave) == _id_archivo(archivo)

def _marcar_procesado(archivo, clave):
    st.session_state[clave] = _id_archivo(archivo)

def _id_archivo(archivo):
    return getattr(archivo, "file_id", None) or f"{archivo.name}-{archivo.size}"


def modulo_configuracion():
    st.markdown("### \u2699\ufe0f Centro de Control")

    # --- A. Archivos ---
    st.markdown("#### A. Archivos Base")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown('<div class="upload-zone">', unsafe_allow_html=True)
        file_inv = st.file_uploader("\U0001f4e6 INVENTARIO", type=["xlsx","xls","csv"], key="up_inv")
        st.markdown('</div>', unsafe_allow_html=True)
        if file_inv and _archivo_ya_procesado(file_inv, "_proc_up_inv"):
            st.caption(f"\u2705 {file_inv.name} ya cargado ({len(st.session_state.get('inventario', []))} productos)")
        elif file_inv:
            try:
                df_inv = pd.read_csv(file_inv) if file_inv.name.endswith(".csv") else pd.read_excel(file_inv)
                df_inv, inf = validar_y_renombrar_columnas(df_inv, [COL_CN, COL_STOCK, COL_PVL, COL_LAB, COL_NOMBRE, COL_MOLECULA])
                df_inv, opc_inv = normalizar_opcionales(df_inv, "inventario")
                st.session_state["inventario"] = df_inv
                guardar_dataframe_farmacia("inventario.parquet", df_inv)
                for col, found in inf.items(): st.markdown(f"\u2705 `{col}`" if found else f"\u274c `{col}` no encontrada")
                render_columnas_opcionales(opc_inv)
                st.info(f"{len(df_inv)} productos cargados")
                # Snapshot de auditoria automatico
                df_vm_snap = obtener_ventas_media(meses_cobertura=2) if "historico" in st.session_state else pd.DataFrame()
                if not df_vm_snap.empty:
                    snap = registrar_snapshot_auditoria(df_inv, df_vm_snap)
                    st.caption(f"\U0001f4f8 Snapshot guardado: {snap['n_zombies']} zombies, {snap['n_roturas']} roturas")
                _marcar_procesado(file_inv, "_proc_up_inv")
            except Exception as e: st.error(f"Error: {e}")
        render_fecha_inventario()
    with c2:
        st.markdown('<div class="upload-zone">', unsafe_allow_html=True)
        file_v =st.file_uploader("\U0001f4c8 HISTORICO VENTAS (36 meses)", type=["xlsx","xls","csv"], key="up_ven")
        st.markdown('</div>', unsafe_allow_html=True)
        if file_v and _archivo_ya_procesado(file_v, "_proc_up_ven"):
            st.caption(f"\u2705 {file_v.name} ya cargado ({len(st.session_state.get('historico', []))} registros)")
        elif file_v:
            try:
                df_v = pd.read_csv(file_v) if file_v.name.endswith(".csv") else pd.read_excel(file_v)
                df_v, inf = validar_y_renombrar_columnas(df_v, [COL_CN, COL_VENTAS, COL_FECHA])
                df_v, opc_v = normalizar_opcionales(df_v, "historico")
                st.session_state["historico"] = df_v
                guardar_dataframe_farmacia("historico.parquet", df_v)
                st.session_state.pop("ventas_media_cache", None); st.session_state.pop("historico_hash", None)
                for col, found in inf.items(): st.markdown(f"\u2705 `{col}`" if found else f"\u274c `{col}` no encontrada")
                render_columnas_opcionales(opc_v)
                if COL_FECHA in df_v.columns:
                    df_v[COL_FECHA] = pd.to_datetime(df_v[COL_FECHA], errors="coerce", dayfirst=True)
                    anios = df_v[COL_FECHA].dropna().dt.year.nunique()
                    st.info(f"{len(df_v)} registros | {anios} anio(s)")
                else: st.info(f"{len(df_v)} registros")
                _marcar_procesado(file_v, "_proc_up_ven")
            except Exception as e: st.error(f"Error: {e}")

    # --- B. Ofertas Tiers Dinamicos ---
    st.divider()
    st.markdown("#### B. Ofertas del Laboratorio")
    file_of = st.file_uploader("\U0001f3f7\ufe0f OFERTAS", type=["xlsx","xls","csv"], key="up_of")
    if file_of and not _archivo_ya_procesado(file_of, "_proc_up_of"):
        try:
            df_of = pd.read_csv(file_of) if file_of.name.endswith(".csv") else pd.read_excel(file_of)
            st.session_state["ofertas_raw"] = df_of
            _marcar_procesado(file_of, "_proc_up_of")
        except Exception as e: st.error(f"Error: {e}")
    df_of_raw = st.session_state.get("ofertas_raw")
    if df_of_raw is not None and not df_of_raw.empty:
        st.dataframe(df_of_raw.head(5), width='stretch', hide_index=True)
        cols_d = list(df_of_raw.columns); na = "-- No aplica --"; opts = [na] + cols_d
        mn = st.selectbox("Columna Nombre/Molecula:", opts, key="of_mn")
        st.markdown("**Tramos:**")
        n_t = int(st.number_input("Numero de tiers:", 1, 10, 2, key="n_tiers"))
        mt_list = []; cols_t = st.columns(min(int(n_t), 5))
        for i in range(int(n_t)):
            with cols_t[i % len(cols_t)]:
                st.markdown(f"**T{i+1}:**")
                cc = st.selectbox(f"Cant T{i+1}:", opts, key=f"oc_{i}")
                cd = st.selectbox(f"Dto T{i+1}:", opts, key=f"od_{i}")
                if cc != na and cd != na: mt_list.append({"col_cantidad": cc, "col_descuento": cd})
        if st.button("\u2728 Procesar Ofertas", type="primary"):
            if mn == na: st.error("Mapea Nombre/Molecula.")
            elif not mt_list: st.error("Mapea al menos un tramo.")
            else:
                df_n = normalizar_ofertas_dinamico(df_of_raw, mn, mt_list)
                st.session_state["ofertas_normalizadas"] = df_n
                guardar_dataframe_farmacia("ofertas_normalizadas.parquet", df_n)
                st.success(f"\u2705 {len(df_n)} ofertas procesadas.")

    # --- C. Reglas de Surtido ---
    st.divider()
    st.markdown("#### C. Reglas de Surtido")
    st.caption("Formato: Molecula,Dosis,Cantidad. Sin reglas = optimizacion libre.")
    reglas = cargar_reglas_surtido()
    df_reg = pd.DataFrame(reglas) if reglas else pd.DataFrame(columns=["presentacion","min_labs","labs_obligatorios"])
    df_reg_e = st.data_editor(df_reg, num_rows="dynamic", width='stretch', key="ed_reg")
    if st.button("\U0001f4be Guardar Reglas Surtido"):
        guardar_reglas_surtido(df_reg_e.dropna(subset=["presentacion"]).to_dict("records"))
        st.success("\u2705 Guardadas.")

    # --- D. Productos Protegidos (Excel + editor) ---
    st.divider()
    st.markdown("#### D. Productos Protegidos")
    st.caption("Carga por Excel o edita manualmente. Formato: codigo_nacional, nombre, stock_minimo, motivo")

    file_prot = st.file_uploader("\U0001f4c4 Cargar desde Excel:", type=["xlsx","xls","csv"], key="up_prot")
    if file_prot and _archivo_ya_procesado(file_prot, "_proc_up_prot"):
        st.caption(f"\u2705 {file_prot.name} ya cargado. Las ediciones de la tabla se conservan.")
    elif file_prot:
        try:
            df_prot_up = pd.read_csv(file_prot) if file_prot.name.endswith(".csv") else pd.read_excel(file_prot)
            df_prot_up, _ = validar_y_renombrar_columnas(df_prot_up, ["codigo_nacional", "nombre", "stock_minimo", "motivo"])
            if "codigo_nacional" in df_prot_up.columns:
                nuevos = df_prot_up.dropna(subset=["codigo_nacional"]).to_dict("records")
                guardar_productos_protegidos(nuevos)
                st.success(f"\u2705 {len(nuevos)} productos protegidos cargados desde Excel.")
                _marcar_procesado(file_prot, "_proc_up_prot")
            else:
                st.error("El Excel debe tener columna 'codigo_nacional'.")
        except Exception as e: st.error(f"Error: {e}")

    prot = cargar_productos_protegidos()
    df_pr = pd.DataFrame(prot) if prot else pd.DataFrame(columns=["codigo_nacional","nombre","stock_minimo","motivo"])
    df_pr_e = st.data_editor(df_pr, num_rows="dynamic", width='stretch', key="ed_prot")
    if st.button("\U0001f4be Guardar Protegidos"):
        guardar_productos_protegidos(df_pr_e.dropna(subset=["codigo_nacional"]).to_dict("records"))
        st.success("\u2705 Guardados.")

    # --- E. Perfil de la Farmacia (3 epis) ---
    st.divider()
    st.markdown("#### E. Perfil de la Farmacia")
    st.caption("Configura una vez. Informativo: el modelo de cada farmacia no lo usa porque es un valor fijo en todo su historico.")
    perfil = cargar_perfil_farmacia()
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Proximidad:**")
        perfil["centro_salud"] = st.checkbox("Centro de Salud", perfil.get("centro_salud", False), key="pf_cs")
        perfil["residencia"] = st.checkbox("Residencia Mayores", perfil.get("residencia", False), key="pf_res")
        perfil["colegio"] = st.checkbox("Colegio", perfil.get("colegio", False), key="pf_col")
        perfil["zona_turistica"] = st.checkbox("Zona Turistica", perfil.get("zona_turistica", False), key="pf_tur")
        perfil["zona_rural"] = st.checkbox("Zona Rural", perfil.get("zona_rural", False), key="pf_rur")
    with c2:
        st.markdown("**Nivel Epidemiologico:**")
        epi_labels = {0: "0 \u2014 Normal", 1: "1 \u2014 Alerta leve", 2: "2 \u2014 Epidemia activa"}
        perfil["epi_gripe"] = st.selectbox("\U0001f912 Gripe / Respiratorio:", [0,1,2],
            index=perfil.get("epi_gripe", 0), key="epi_g", format_func=lambda x: epi_labels[x])
        perfil["epi_alergias"] = st.selectbox("\U0001f33c Alergias / Polen:", [0,1,2],
            index=perfil.get("epi_alergias", 0), key="epi_a", format_func=lambda x: epi_labels[x])
        perfil["epi_covid"] = st.selectbox("\U0001f9eb COVID / Otros:", [0,1,2],
            index=perfil.get("epi_covid", 0), key="epi_c", format_func=lambda x: epi_labels[x])
        st.caption("Ref: svge.isciii.es (gripe), polenes.com (alergias)")
        st.markdown("**Zona Climatica:**")
        zonas_clima = ["Mediterraneo", "Continental", "Atlantico"]
        zona_actual = perfil.get("zona_climatica", "mediterraneo").capitalize()
        if zona_actual not in zonas_clima:
            zona_actual = "Mediterraneo"
        perfil["zona_climatica"] = st.selectbox("\U0001f321\ufe0f Clima:", zonas_clima,
            index=zonas_clima.index(zona_actual), key="zona_cli").lower()
    if st.button("\U0001f4be Guardar Perfil"):
        guardar_perfil_farmacia(perfil)
        st.success("\u2705 Perfil guardado.")

    # --- F. Calendario (3 capas) ---
    st.divider()
    st.markdown("#### F. Calendario de la Farmacia")
    cal = cargar_calendario_farmacia()
    horario = cal.get("horario", {})

    st.markdown("**Horario semanal:**")
    dias_es = ["lunes","martes","miercoles","jueves","viernes","sabado","domingo"]
    dias_labels = ["Lunes","Martes","Miercoles","Jueves","Viernes","Sabado","Domingo"]

    cols_h = st.columns(7)
    for i, (dia, label) in enumerate(zip(dias_es, dias_labels)):
        cfg = horario.get(dia, {"abre": i < 6, "apertura": "09:30", "cierre": "21:00"})
        with cols_h[i]:
            st.markdown(f"**{label}**")
            cfg["abre"] = st.checkbox("Abre", cfg.get("abre", i < 6), key=f"h_abre_{dia}")
            if cfg["abre"]:
                cfg["apertura"] = st.text_input("Desde:", cfg.get("apertura", "09:30"), key=f"h_ap_{dia}")
                cfg["cierre"] = st.text_input("Hasta:", cfg.get("cierre", "21:00"), key=f"h_ci_{dia}")
            horario[dia] = cfg

    st.markdown("**Festivos** (uno por linea, formato DD/MM/AAAA):")
    festivos_str = "\n".join(cal.get("festivos", []))
    nuevos_festivos = st.text_area("Festivos:", festivos_str, height=80, key="cal_fest")

    st.markdown("**Excepciones: dias que ABRE aunque sea festivo** (guardias, etc.):")
    excepciones_str = "\n".join(cal.get("excepciones_abiertas", []))
    nuevas_excepciones = st.text_area("Excepciones:", excepciones_str, height=60, key="cal_exc")

    if st.button("\U0001f4be Guardar Calendario"):
        cal_nuevo = {
            "horario": horario,
            "festivos": [d.strip() for d in nuevos_festivos.split("\n") if d.strip()],
            "excepciones_abiertas": [d.strip() for d in nuevas_excepciones.split("\n") if d.strip()],
        }
        guardar_calendario_farmacia(cal_nuevo)
        st.success("\u2705 Calendario guardado.")

    # --- G. Datos Complementarios (ML) ---
    st.divider()
    st.markdown("#### G. Datos Complementarios (ML)")
    st.caption("Opcionales. Mejoran la precision del modelo si se proporcionan.")
    cg1, cg2 = st.columns(2)
    with cg1:
        st.markdown("**Tabla Maestra ATC** (Excel: Codigo_Nacional + Grupo_ATC)")
        file_atc = st.file_uploader("\U0001f9ec Tabla ATC", type=["xlsx","xls","csv"], key="up_atc")
        if file_atc and not _archivo_ya_procesado(file_atc, "_proc_up_atc"):
            try:
                if file_atc.name.endswith(".csv"):
                    df_atc = pd.read_csv(file_atc, dtype=str)
                else:
                    df_atc = pd.read_excel(file_atc, dtype=str)
                st.session_state["tabla_maestra_atc"] = df_atc
                # Persistir en carpeta de farmacia
                ruta_f = ruta_farmacia_activa()
                if ruta_f:
                    df_atc.to_csv(ruta_f / "tabla_atc.csv", index=False)
                st.success(f"\u2705 Tabla ATC: {len(df_atc)} registros | Columnas: {', '.join(df_atc.columns[:4])}")
                _marcar_procesado(file_atc, "_proc_up_atc")
            except Exception as e:
                st.error(f"Error leyendo tabla ATC: {e}")
        if "tabla_maestra_atc" not in st.session_state:
            # Intentar cargar de disco
            ruta_f = ruta_farmacia_activa()
            if ruta_f and (ruta_f / "tabla_atc.csv").exists():
                st.session_state["tabla_maestra_atc"] = pd.read_csv(ruta_f / "tabla_atc.csv", dtype=str)
        if "tabla_maestra_atc" in st.session_state:
            st.info(f"\u2705 Tabla ATC cargada ({len(st.session_state['tabla_maestra_atc'])} registros)")
        else:
            st.caption("Sin tabla ATC se usa proxy por molecula (funciona pero es menos preciso).")
    with cg2:
        st.markdown("**Temperatura Historica** (CSV: Anio, Mes, Temp_Media)")
        file_temp = st.file_uploader("\U0001f321\ufe0f Temperatura", type=["csv","xlsx"], key="up_temp")
        if file_temp and not _archivo_ya_procesado(file_temp, "_proc_up_temp"):
            try:
                if file_temp.name.endswith(".csv"):
                    df_temp = pd.read_csv(file_temp)
                else:
                    df_temp = pd.read_excel(file_temp)
                for c in ["Anio", "Mes", "Temp_Media"]:
                    df_temp[c] = pd.to_numeric(df_temp[c], errors="coerce")
                df_temp = df_temp.dropna(subset=["Anio", "Mes", "Temp_Media"])
                st.session_state["temperatura_historica"] = df_temp
                # Persistir en carpeta de farmacia
                ruta_f = ruta_farmacia_activa()
                if ruta_f:
                    df_temp.to_csv(ruta_f / "temperatura.csv", index=False)
                st.success(f"\u2705 Temperatura: {len(df_temp)} meses cargados")
                _marcar_procesado(file_temp, "_proc_up_temp")
            except Exception as e:
                st.error(f"Error leyendo temperatura: {e}")
        if "temperatura_historica" not in st.session_state:
            # Intentar cargar de disco
            ruta_f = ruta_farmacia_activa()
            if ruta_f and (ruta_f / "temperatura.csv").exists():
                df_t = pd.read_csv(ruta_f / "temperatura.csv")
                for c in ["Anio", "Mes", "Temp_Media"]:
                    df_t[c] = pd.to_numeric(df_t[c], errors="coerce")
                st.session_state["temperatura_historica"] = df_t.dropna(subset=["Anio","Mes","Temp_Media"])
        if "temperatura_historica" in st.session_state:
            st.info(f"\u2705 Temperatura cargada ({len(st.session_state['temperatura_historica'])} meses)")
        else:
            st.caption(f"Sin CSV se usa climatologia de la zona ({perfil.get('zona_climatica', 'mediterraneo').capitalize()}).")

    # --- H. Motor de Prediccion ML ---
    st.divider()
    st.markdown("#### H. Motor de Prediccion ML")
    if not ML_AVAILABLE:
        st.warning("Instala xgboost y scikit-learn: `pip install xgboost scikit-learn joblib`")
    else:
        model_ok, met, _ = obtener_modelo_cacheado()
        if model_ok and met:
            fecha_ent = met.get("fecha_entrenamiento", "?")
            st.success(f"\u2705 Modelo entrenado | RMSE: {met.get('rmse','?')} | R\u00b2: {met.get('r2','?')} | Fecha: {fecha_ent}")
            if necesita_reentrenamiento():
                st.warning("\u26a0\ufe0f El historico ha cambiado desde el ultimo entrenamiento. Reentrena para mejores resultados.")
        elif met and met.get("obsoleto"):
            st.warning("⚠️ El modelo guardado se entreno con una version anterior del "
                       "motor y ya no es compatible. Reentrenalo para volver a usar la IA.")
        else:
            st.info("No hay modelo entrenado para esta farmacia.")

        if "inventario" in st.session_state and "historico" in st.session_state:
            if st.button("\U0001f9e0 Entrenar Modelo ML", type="primary", width='stretch'):
                with st.spinner("Entrenando modelo..."):
                    df_hist_imp = imputar_stockouts(st.session_state["historico"], st.session_state["inventario"])
                    perfil_f = cargar_perfil_farmacia()
                    cal_f = cargar_calendario_farmacia()
                    ofertas_n = st.session_state.get("ofertas_normalizadas")
                    df_feat = build_features(df_hist_imp, st.session_state["inventario"], perfil_f, cal_f, ofertas_n)
                    model, metricas, rmse_cn = entrenar_modelo_ml(df_feat, contexto={
                        "df_ventas": df_hist_imp, "df_inventario": st.session_state["inventario"],
                        "perfil": perfil_f, "calendario": cal_f, "df_ofertas": ofertas_n})
                    if model is not None:
                        guardar_modelo_farmacia(model, metricas, rmse_cn, df_feat)
                        invalidar_cache_modelo()
                        bt = metricas.get("backtest", {})
                        mejora = bt.get("mejora_pct")
                        st.success(f"\u2705 Modelo entrenado | RMSE backtest: {metricas['rmse']} | R\u00b2 holdout: {metricas['r2']}")
                        if mejora is not None:
                            if mejora > 0:
                                st.info(f"El ML mejora al baseline heuristico en un {mejora}% de RMSE.")
                            else:
                                st.warning(f"El ML NO mejora al baseline heuristico ({mejora}%). "
                                           "Conviene usar el motor Heuristico para esta farmacia.")
                        fig_imp = grafico_importancia_features(metricas)
                        if fig_imp: st.plotly_chart(fig_imp, width='stretch', key='cfg_importancia')
                    else:
                        st.error(f"Error: {metricas.get('error','Desconocido')}")

    # --- I. Benchmark de Red ---
    st.divider()
    st.markdown("#### I. Benchmark de Red")
    st.caption("Verifica la latencia de tu conexión frente a endpoints globales.")
    if st.button("🌐 Iniciar Prueba de Red"):
        with st.spinner("Midiendo latencia..."):
            res = ejecutar_benchmark_red()
        
        if res["sana"]:
            st.success("✅ Conexión de red saludable.")
        else:
            st.warning("⚠️ Posibles problemas de red o firewall bloqueando el tráfico.")
            
        c_bench = st.columns(len(res["resultados"]))
        for i, r in enumerate(res["resultados"]):
            with c_bench[i]:
                lat = f"{r['latencia_ms']} ms" if r['latencia_ms'] is not None else "Timeout/Error"
                render_kpi(r['url'].replace("https://", ""), lat, "OK" if r['estado'] == "OK" else r['estado'], r['estado'] == "OK")

    # --- J y K. Parametros de analisis y compras (BI y Auditoria) ---
    render_parametros_analisis()
    render_compras()

    # --- Estado ---
    st.divider()
    st.markdown("#### Estado")
    c1, c2, c3, c4 = st.columns(4)
    inv_ok = "inventario" in st.session_state
    hist_ok = "historico" in st.session_state
    of_ok = "ofertas_normalizadas" in st.session_state
    ml_ok, _, _ = obtener_modelo_cacheado()
    with c1: st.markdown(f"{'\u2705' if inv_ok else '\u23f3'} **Inventario**")
    with c2: st.markdown(f"{'\u2705' if hist_ok else '\u23f3'} **Historico**")
    with c3: st.markdown(f"{'\u2705' if of_ok else '\u23f3'} **Ofertas**")
    with c4: st.markdown(f"{'\u2705' if ml_ok else '\u23f3'} **Modelo ML**")
