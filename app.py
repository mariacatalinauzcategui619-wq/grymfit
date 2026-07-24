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
    
    # Cargar credenciales directamente desde los Secrets de Streamlit
    creds_dict = dict(st.secrets["google_credentials"])
    try:
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        service = build('sheets', 'v4', credentials=creds)
        drive_service = build('drive', 'v3', credentials=creds)
        
        # Buscar el archivo "Planificador Grymfit" en Drive
        results = drive_service.files().list(
            q="name = 'Planificador Grymfit' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false",
            fields="files(id, name)"
        ).execute()
        files = results.get('files', [])
        
        if not files:
            st.error("No se encontró el archivo 'Planificador Grymfit' en Google Drive.")
            st.stop()
            
        spreadsheet_id = files[0]['id']
        
        # Obtener nombres de las pestañas
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

st.title("🏋️‍♂️ Planificador GRYMFIT")
st.write("Cargando tus datos...")
