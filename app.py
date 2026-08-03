import os
import re
import calendar
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ==========================================
# CONFIGURACIÓN DE PÁGINA
# ==========================================
st.set_page_config(page_title="Planificador GRYMFIT", layout="wide")

# ==========================================
# CONEXIÓN DIRECTA A GOOGLE DRIVE
# ==========================================
def conectar_drive():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["google_credentials"])
    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    service = build('sheets', 'v4', credentials=creds)
    drive_service = build('drive', 'v3', credentials=creds)

    query = "name contains 'Planificador General 2026' and mimeType='application/vnd.google-apps.spreadsheet' and trashed=false"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get('files', [])

    if not files:
        st.error("❌ CRÍTICO: No se encontró 'Planificador General 2026' en Google Drive.")
        st.stop()

    spreadsheet_id = files[0]['id']
    return service, spreadsheet_id

service, spreadsheet_id = conectar_drive()

# Cargar listas base
def cargar_listas_base():
    try:
        res_ej = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="Ejercicios!A:B").execute()
        rows_ej = res_ej.get('values', [])
        df_ejercicios = pd.DataFrame(rows_ej[1:], columns=[rows_ej[0][0], rows_ej[0][1]]) if len(rows_ej) > 1 else pd.DataFrame()

        res_al = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range="Alumnos!A:Z").execute()
        rows_al = res_al.get('values', [])
        if rows_al:
            max_cols = max(len(row) for row in rows_al)
            rows_al_padded = [row + [''] * (max_cols - len(row)) for row in rows_al]
            df_alumnos = pd.DataFrame(rows_al_padded[1:], columns=rows_al_padded[0])
        else:
            df_alumnos = pd.DataFrame()

        return df_alumnos, df_ejercicios
    except Exception as e:
        st.error(f"Error cargando listas: {e}")
        return pd.DataFrame(), pd.DataFrame()

df_alumnos, df_ejercicios = cargar_listas_base()

if not df_alumnos.empty:
    df_alumnos.columns = [str(c).strip() for c in df_alumnos.columns]

col_grupo_raw = df_ejercicios.columns[0] if not df_ejercicios.empty else "Grupo"
col_ejercicio_raw = df_ejercicios.columns[1] if not df_ejercicios.empty else "Ejercicio"

def normalizar_grupo(texto):
    txt = str(texto).strip().capitalize()
    if txt.endswith('s') and not txt.lower().endswith(('biops', 'triceps', 'biceps', 'hombros')):
        txt = txt[:-1]
    return txt

if not df_ejercicios.empty:
    df_ejercicios['Grupo_Norm'] = df_ejercicios[col_grupo_raw].apply(normalizar_grupo)

dic_meses = {
    "Enero": 1, "Febrero": 2, "Marzo": 3, "Abril": 4, "Mayo": 5, "Junio": 6,
    "Julio": 7, "Agosto": 8, "Septiembre": 9, "Octubre": 10, "Noviembre": 11, "Diciembre": 12
}

def obtener_semanas_del_mes(mes_nombre):
    num_mes = dic_meses.get(mes_nombre, 8)
    return len(calendar.monthcalendar(2026, num_mes))

def col2letter(col_idx):
    result = ""
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        result = chr(65 + remainder) + result
    return result

# ==========================================
# LECTURA DE BÚSQUEDA ROBUSTA E INTELIGENTE
# ==========================================
def leer_plan_desde_drive(nombre_alumno, mes_nombre):
    if not nombre_alumno or nombre_alumno == "-- Seleccionar --":
        return []

    try:
        sheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = sheet_metadata.get('sheets', [])
        
        # Primero buscar pestañas que coincidan con el mes
        hojas_candidatas = [h['properties']['title'] for h in sheets if mes_nombre.lower() in h['properties']['title'].lower()]
        
        # Si no hay coincidencias exactas por nombre de mes, buscar en TODAS las pestañas que contengan la palabra "plan" o "app"
        if not hojas_candidatas:
            hojas_candidatas = [h['properties']['title'] for h in sheets if "plan" in h['properties']['title'].lower() or "app" in h['properties']['title'].lower()]

        if not hojas_candidatas:
            hojas_candidatas = [h['properties']['title'] for h in sheets]

        semanas_mes = obtener_semanas_del_mes(mes_nombre)
        frec_semanal = 3
        total_dias = frec_semanal * semanas_mes
        registros = []

        nombre_buscar = re.sub(r'\s+', ' ', str(nombre_alumno).strip().upper())

        for nombre_hoja_real in hojas_candidatas:
            res_completo = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=f"'{nombre_hoja_real}'!A1:ZZ1000"
            ).execute()
            rows_matriz = res_completo.get('values', [])
            if not rows_matriz:
                continue

            # Normalizar matriz a un ancho uniforme (para evitar saltos por celdas vacías)
            max_c = max(len(r) for r in rows_matriz)
            matriz = [r + [''] * (max_c - len(r)) for r in rows_matriz]

            for idx_f, fila in enumerate(matriz):
                for idx_c_nombre, val in enumerate(fila):
                    val_clean = re.sub(r'\s+', ' ', str(val).strip().upper())
                    
                    # Coincidencia flexible de nombre de alumno
                    if nombre_buscar in val_clean and len(val_clean) > 2:
                        fila_alumno = idx_f
                        fila_ej_base = -1
                        col_ejercicio_detectada = -1

                        # Buscar la palabra 'Ejercicio' cerca del alumno (hacia abajo)
                        for idx_sub in range(fila_alumno, min(fila_alumno + 25, len(matriz))):
                            fila_sub = matriz[idx_sub]
                            for idx_c, val_c in enumerate(fila_sub):
                                if str(val_c).strip().lower() in ["ejercicio", "ejercicios"]:
                                    fila_ej_base = idx_sub
                                    col_ejercicio_detectada = idx_c
                                    break
                            if fila_ej_base != -1:
                                break

                        if fila_ej_base == -1:
                            fila_ej_base = fila_alumno + 7
                            col_ejercicio_detectada = 5

                        fila_ejercicios_inicio = fila_ej_base + 1
                        col_inicio = col_ejercicio_detectada

                        for d in range(1, total_dias + 1):
                            s_num = ((d - 1) // frec_semanal) + 1
                            d_num = ((d - 1) % frec_semanal) + 1

                            for fila_idx in range(12):
                                idx_f_matriz = fila_ejercicios_inicio + fila_idx
                                if idx_f_matriz < len(matriz):
                                    f_row = matriz[idx_f_matriz]
                                    ej = f_row[col_inicio] if len(f_row) > col_inicio else ""
                                    p = f_row[col_inicio + 1] if len(f_row) > col_inicio + 1 else ""
                                    r = f_row[col_inicio + 2] if len(f_row) > col_inicio + 2 else ""

                                    ej_str = str(ej).strip()
                                    if ej_str and ej_str.lower() not in ["", "-- seleccionar ejercicio --", "ejercicio", "none"]:
                                        registros.append({
                                            "Semana": s_num,
                                            "Día": d_num,
                                            "Fila": fila_idx + 1,
                                            "Ejercicio": ej_str,
                                            "Peso": str(p).strip(),
                                            "Series_Reps": str(r).strip()
                                        })
                            col_inicio += 3

                        if registros:
                            return registros
        return registros
    except Exception:
        return []

# ==========================================
# INTERFAZ Y NAVEGACIÓN
# ==========================================
st.sidebar.title("GRYMFIT App")
modo_app = st.sidebar.radio("Navegación:", ["Armar Planificación Mensual", "Ver Rutinas en Vivo (4 Bloques)"])

col_alumno = "Alumnos" if "Alumnos" in df_alumnos.columns else (df_alumnos.columns[0] if not df_alumnos.empty else "Alumno")
col_frec = "Frecuencia de Entrenamiento" if "Frecuencia de Entrenamiento" in df_alumnos.columns else (df_alumnos.columns[1] if len(df_alumnos.columns) > 1 else "Frecuencia")
lista_alumnos = sorted(df_alumnos[col_alumno].dropna().unique().tolist()) if not df_alumnos.empty else []
if "" in lista_alumnos:
    lista_alumnos.remove("")

if modo_app == "Armar Planificación Mensual":
    st.title("Armar Planificación Mensual")
    c_al, c_mes, c_frec = st.columns([2, 1, 1])

    with c_al:
        alumno_sel = st.selectbox("Alumno a Planificar:", lista_alumnos if lista_alumnos else ["Sin Alumnos"])
    with c_mes:
        mes_sel = st.selectbox("Mes de Planificación:", list(dic_meses.keys()), index=7)

    semanas_mes = obtener_semanas_del_mes(mes_sel)
    datos_al = df_alumnos[df_alumnos[col_alumno] == alumno_sel] if not df_alumnos.empty else pd.DataFrame()
    frec_semanal = 3
    if not datos_al.empty and col_frec in datos_al.columns:
        nums = re.findall(r'\d+', str(datos_al[col_frec].values[0]))
        if nums:
            frec_semanal = int(nums[0])

    total_dias_mes = frec_semanal * semanas_mes
    with c_frec:
        st.metric("Total Días al Mes", f"{total_dias_mes} Días", delta=f"{semanas_mes} sem x {frec_semanal} días/sem")

    st.markdown("---")

    if "plan_datos" not in st.session_state:
        st.session_state["plan_datos"] = {}

    key_carga = f"cargado_{alumno_sel}_{mes_sel}"
    if key_carga not in st.session_state:
        datos_existentes_drive = leer_plan_desde_drive(alumno_sel, mes_sel)
        for reg in datos_existentes_drive:
            k_dia = f"{alumno_sel}_{mes_sel}_S{reg['Semana']}_D{reg['Día']}"
            if k_dia not in st.session_state["plan_datos"]:
                st.session_state["plan_datos"][k_dia] = {}
            
            st.session_state["plan_datos"][k_dia][f"fila_{reg['Fila']}"] = {
                "Alumno": alumno_sel, "Mes": mes_sel, "Semana": reg['Semana'], "Día": reg['Día'],
                "Ejercicio": reg['Ejercicio'], "Peso": reg['Peso'], "Series_Reps": reg['Series_Reps']
            }
            st.session_state[f"ej_{k_dia}_{reg['Fila']}"] = reg['Ejercicio']
            st.session_state[f"p_{k_dia}_{reg['Fila']}"] = reg['Peso']
            st.session_state[f"r_{k_dia}_{reg['Fila']}"] = reg['Series_Reps']

        st.session_state[key_carga] = True

    grupos_unicos = sorted(df_ejercicios['Grupo_Norm'].dropna().unique().tolist()) if not df_ejercicios.empty else []
    grupos_opciones = ["Ninguno"] + grupos_unicos

    tabs_semanas = st.tabs([f"Semana {s}" for s in range(1, semanas_mes + 1)])

    for s_num, tab_sem in enumerate(tabs_semanas, start=1):
        with tab_sem:
            st.subheader(f"Planificación de la Semana {s_num}")
            tabs_dias = st.tabs([f"Día {d}" for d in range(1, frec_semanal + 1)])
            
            for d_num, tab_dia in enumerate(tabs_dias, start=1):
                key_dia = f"{alumno_sel}_{mes_sel}_S{s_num}_D{d_num}"
                if key_dia not in st.session_state["plan_datos"]:
                    st.session_state["plan_datos"][key_dia] = {}

                with tab_dia:
                    st.markdown(f"#### Rutina: Semana {s_num} - Día {d_num}")
                    cg1, cg2, cg3, cg4 = st.columns(4)
                    with cg1: g1 = st.selectbox("Músculo 1", grupos_opciones, key=f"g1_{key_dia}")
                    with cg2: g2 = st.selectbox("Músculo 2", grupos_opciones, key=f"g2_{key_dia}")
                    with cg3: g3 = st.selectbox("Músculo 3", grupos_opciones, key=f"g3_{key_dia}")
                    with cg4: g4 = st.selectbox("Músculo 4", grupos_opciones, key=f"g4_{key_dia}")

                    grupos_elegidos = [g for g in [g1, g2, g3, g4] if g != "Ninguno"]
                    if grupos_elegidos and not df_ejercicios.empty:
                        ejercicios_disponibles = df_ejercicios[df_ejercicios['Grupo_Norm'].isin(grupos_elegidos)][col_ejercicio_raw].dropna().unique().tolist()
                    elif not df_ejercicios.empty:
                        ejercicios_disponibles = df_ejercicios[col_ejercicio_raw].dropna().unique().tolist()
                    else:
                        ejercicios_disponibles = []

                    lista_ej_opciones = ["-- Seleccionar Ejercicio --"] + sorted(ejercicios_disponibles)
                    st.markdown("---")

                    for fila in range(1, 11):
                        c_ej, c_p, c_r = st.columns([2, 1, 1])
                        val_ej_prev = st.session_state.get(f"ej_{key_dia}_{fila}", "-- Seleccionar Ejercicio --")
                        idx_ej = lista_ej_opciones.index(val_ej_prev) if val_ej_prev in lista_ej_opciones else 0

                        with c_ej: ej_val = st.selectbox(f"Ejercicio {fila}", lista_ej_opciones, index=idx_ej, key=f"ej_{key_dia}_{fila}")
                        with c_p: peso_val = st.text_input("Peso / Tiempo", key=f"p_{key_dia}_{fila}", placeholder="ej: 20 kg")
                        with c_r: reps_val = st.text_input("Series x Reps", key=f"r_{key_dia}_{fila}", placeholder="ej: 4x12")

                        st.session_state["plan_datos"][key_dia][f"fila_{fila}"] = {
                            "Alumno": alumno_sel, "Mes": mes_sel, "Semana": s_num, "Día": d_num,
                            "Grupos": grupos_elegidos, "Ejercicio": ej_val, "Peso": peso_val, "Series_Reps": reps_val
                        }

    st.markdown("---")
    st.header(f"Resumen de {alumno_sel} ({mes_sel})")

    registros_finales = []
    for k_item, filas_dict in st.session_state["plan_datos"].items():
        for f_key, datos in filas_dict.items():
            if datos.get("Alumno") == alumno_sel and datos.get("Mes") == mes_sel:
                if datos.get("Ejercicio") not in ["-- Seleccionar Ejercicio --", "", None]:
                    registros_finales.append({
                        "Alumno": datos["Alumno"], "Mes": datos["Mes"],
                        "Semana": f"Semana {datos['Semana']}", "Día": f"Día {datos['Día']}",
                        "Ejercicio": datos["Ejercicio"], "Peso": datos["Peso"], "Series/Reps": datos["Series_Reps"]
                    })

    if registros_finales:
        df_resumen = pd.DataFrame(registros_finales).drop_duplicates(subset=["Semana", "Día", "Ejercicio"], keep="last")
        st.dataframe(df_resumen, use_container_width=True)

        if st.button("💾 GUARDAR Y SINCRONIZAR EN GOOGLE DRIVE", type="primary", use_container_width=True):
            with st.spinner("⏳ Guardando planificación directamente en Google Drive..."):
                try:
                    hoja_app_destino = f"Plan_{mes_sel}_App"

                    sheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
                    sheets = sheet_metadata.get('sheets', [])
                    dict_hojas = {h['properties']['title']: h['properties']['sheetId'] for h in sheets}

                    if hoja_app_destino not in dict_hojas:
                        id_plantilla = list(dict_hojas.values())[0]
                        body_copy = {'requests': [{'duplicateSheet': {'sourceSheetId': id_plantilla, 'newSheetName': hoja_app_destino}}]}
                        res_copy = service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body_copy).execute()
                        id_hoja_destino = res_copy['replies'][0]['duplicateSheet']['properties']['sheetId']
                    else:
                        id_hoja_destino = dict_hojas[hoja_app_destino]

                    cols_necesarias = 6 + (total_dias_mes * 3) + 10
                    body_expand_cols = {'requests': [{'updateSheetProperties': {'properties': {'sheetId': id_hoja_destino, 'gridProperties': {'columnCount': max(100, cols_necesarias)}}, 'fields': 'gridProperties.columnCount'}}]}
                    service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body_expand_cols).execute()

                    res_completo = service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=f"'{hoja_app_destino}'!A1:AZ2000").execute()
                    matriz = res_completo.get('values', [])

                    filas_control = [2 + (41 * i) for i in range(50)]

                    res_b = service.spreadsheets().values().batchGet(
                        spreadsheetId=spreadsheet_id, 
                        ranges=[f"'{hoja_app_destino}'!B{f}" for f in filas_control]
                    ).execute()
                    value_ranges = res_b.get('valueRanges', [])
                    
                    fila_control_alumno = -1
                    primer_slot_libre = -1
                    for idx, vr in enumerate(value_ranges):
                        val = vr.get('values', [['']])[0][0].strip() if vr.get('values') else ""
                        if val.upper() == alumno_sel.upper():
                            fila_control_alumno = filas_control[idx]
                            break
                        if val == "" and primer_slot_libre == -1:
                            primer_slot_libre = filas_control[idx]

                    if fila_control_alumno == -1:
                        fila_control_alumno = primer_slot_libre if primer_slot_libre != -1 else filas_control[0]

                    service.spreadsheets().values().update(
                        spreadsheetId=spreadsheet_id, range=f"'{hoja_app_destino}'!B{fila_control_alumno}:C{fila_control_alumno}",
                        valueInputOption="USER_ENTERED", body={'values': [[alumno_sel, frec_semanal]]}
                    ).execute()

                    filas_encabezado_ejercicio = [idx_f + 1 for idx_f, fila in enumerate(matriz) if any(str(val_c).strip().lower() == "ejercicio" for val_c in fila)]
                    
                    fila_ej_base = fila_control_alumno + 7
                    for f_ej in filas_encabezado_ejercicio:
                        if f_ej > fila_control_alumno:
                            fila_ej_base = f_ej
                            break

                    fila_musculos_inicio = fila_ej_base - 4
                    fila_ejercicios_inicio = fila_ej_base + 1
                    col_inicio = 6

                    batch_global_data = []

                    for d in range(1, total_dias_mes + 1):
                        s_num = ((d - 1) // frec_semanal) + 1
                        d_num = ((d - 1) % frec_semanal) + 1
                        key_dia = f"{alumno_sel}_{mes_sel}_S{s_num}_D{d_num}"
                        
                        letra_col_ej = col2letter(col_inicio)
                        letra_col_rep = col2letter(col_inicio + 2)

                        ejercicios_dia = []
                        grupos_dia = []

                        if key_dia in st.session_state["plan_datos"]:
                            filas_dict = st.session_state["plan_datos"][key_dia]
                            for f_idx in range(1, 11):
                                datos_f = filas_dict.get(f"fila_{f_idx}", {})
                                ej = datos_f.get("Ejercicio", "")
                                p = datos_f.get("Peso", "")
                                r = datos_f.get("Series_Reps", "")
                                if datos_f.get("Grupos"):
                                    grupos_dia = datos_f.get("Grupos")
                                
                                if ej not in ["-- Seleccionar Ejercicio --", "", None]:
                                    ejercicios_dia.append([ej, p, r])
                                else:
                                    ejercicios_dia.append(["", "", ""])
                        else:
                            ejercicios_dia = [["", "", ""]] * 10

                        g_matriz = [[g] for g in grupos_dia] + [[""]] * (4 - len(grupos_dia))
                        
                        batch_global_data.append({'range': f"'{hoja_app_destino}'!{letra_col_ej}{fila_musculos_inicio}:{letra_col_ej}{fila_musculos_inicio+3}", 'values': g_matriz[:4]})
                        batch_global_data.append({'range': f"'{hoja_app_destino}'!{letra_col_ej}{fila_ejercicios_inicio}:{letra_col_rep}{fila_ejercicios_inicio+9}", 'values': ejercicios_dia})
                        
                        col_inicio += 3

                    service.spreadsheets().values().batchUpdate(
                        spreadsheetId=spreadsheet_id, body={'valueInputOption': 'USER_ENTERED', 'data': batch_global_data}
                    ).execute()

                    if key_carga in st.session_state:
                        del st.session_state[key_carga]

                    st.balloons()
                    st.success(f"✅ ¡Guardado completado! La rutina de {alumno_sel} ({mes_sel}) fue actualizada correctamente en Google Drive.")
                    st.rerun()
                except Exception as error:
                    st.error(f"❌ ERROR AL GUARDAR: {error}")

else:
    st.title("Consulta de Rutinas en Vivo (Gimnasio)")
    
    c_mes_v, c_ref = st.columns([3, 1])
    with c_mes_v:
        mes_ver = st.selectbox("Seleccionar Mes a Consultar:", list(dic_meses.keys()), index=7, key="mes_ver_vivo")
    with c_ref:
        if st.button("🔄 Refrescar Datos en Vivo", use_container_width=True, type="primary"):
            st.rerun()

    st.markdown("### Selecciona qué Alumno cargar en cada Bloque:")
    
    ca1, ca2, ca3, ca4 = st.columns(4)
    with ca1: al_v1 = st.selectbox("Bloque 1:", ["-- Seleccionar --"] + lista_alumnos, key="b1_sel")
    with ca2: al_v2 = st.selectbox("Bloque 2:", ["-- Seleccionar --"] + lista_alumnos, key="b2_sel")
    with ca3: al_v3 = st.selectbox("Bloque 3:", ["-- Seleccionar --"] + lista_alumnos, key="b3_sel")
    with ca4: al_v4 = st.selectbox("Bloque 4:", ["-- Seleccionar --"] + lista_alumnos, key="b4_sel")

    alumnos_a_ver = [a for a in [al_v1, al_v2, al_v3, al_v4] if a and a != "-- Seleccionar --"]
    st.markdown("---")

    if alumnos_a_ver:
        tabs_al_ver = st.tabs([f"{al}" for al in alumnos_a_ver])
        for idx, tab_al_v in enumerate(tabs_al_ver):
            al_nombre = alumnos_a_ver[idx]
            with tab_al_v:
                st.subheader(f"Planificación: {al_nombre} ({mes_ver})")
                
                ejercicios_alumno = leer_plan_desde_drive(al_nombre, mes_ver)

                if ejercicios_alumno:
                    df_al_v = pd.DataFrame(ejercicios_alumno)
                    semanas_unicas = sorted(df_al_v["Semana"].unique().tolist())
                    t_sems_v = st.tabs([f"Semana {s}" for s in semanas_unicas])
                    for sem_idx, sem_v in enumerate(semanas_unicas):
                        with t_sems_v[sem_idx]:
                            df_sem = df_al_v[df_al_v["Semana"] == sem_v][["Día", "Ejercicio", "Peso", "Series_Reps"]]
                            df_sem.columns = ["Día", "Ejercicio", "Peso", "Series x Reps"]
                            st.dataframe(df_sem, use_container_width=True, hide_index=True)
                else:
                    st.warning(f"No hay ninguna rutina registrada en Google Drive para {al_nombre} en {mes_ver}.")
    else:
        st.info("Selecciona al menos un alumno en los bloques superiores para ver su rutina.")
