import os
import re
import calendar
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

# ==========================================
# CONFIGURACIÓN DE LA PÁGINA
# ==========================================
st.set_page_config(page_title="Planificador GRYMFIT", layout="wide")

# ==========================================
# CONEXIÓN DIRECTA A GOOGLE DRIVE Y SHEETS
# ==========================================
@st.cache_data(ttl=30)
def cargar_datos_drive():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    
    # Obtener credenciales de Streamlit Secrets
    creds_dict = dict(st.secrets["google_credentials"])
    
    # Reparar saltos de línea en la clave privada si vienen escapados
    if "private_key" in creds_dict:
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")
    
    try:
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        service = build('sheets', 'v4', credentials=creds)
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Buscar el archivo "Planificador General 2026" en Drive
        results = drive_service.files().list(
            q="name = 'Planificador General 2026' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false",
            fields="files(id, name)"
        ).execute()
        files = results.get('files', [])
        
        if not files:
            st.error("No se encontró el archivo 'Planificador General 2026' en Google Drive. Verifica haberlo compartido con el correo de la cuenta de servicio.")
            st.stop()
            
        spreadsheet_id = files[0]['id']
        
        sheet_metadata = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
        sheets = sheet_metadata.get('sheets', '')
        nombres_pestanas = [sheet['properties']['title'] for sheet in sheets]
        
        datos_pestanas = {}
        for nombre in nombres_pestanas:
            result = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id, range=nombre
            ).execute()
            values = result.get('values', [])
            if values:
                df = pd.DataFrame(values[1:], columns=values[0])
                datos_pestanas[nombre] = df
            else:
                datos_pestanas[nombre] = pd.DataFrame()
                
        return datos_pestanas, spreadsheet_id, service
    except Exception as e:
        st.error(f"Error al conectar con Google Drive: {e}")
        st.stop()

# Cargar datos
datos, spreadsheet_id, service = cargar_datos_drive()

st.title("🏋️‍♂️ Planificador GRYMFIT")

# Mostrar las pestañas de tu Google Sheet en la App
if datos:
    opcion = st.sidebar.selectbox("Selecciona una sección:", list(datos.keys()))
    st.header(f"Sección: {opcion}")
    st.dataframe(datos[opcion], use_container_width=True)
else:
    st.warning("No se encontraron datos en el documento.")
