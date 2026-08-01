import streamlit as st
import pandas as pd
import plotly.express as px
from snowflake.snowpark import Session
import datetime
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization

# 4.1 — Configuração da página
st.set_page_config(page_title="COVID-19 Dashboard", page_icon="🦠", layout="wide")

# URL do CSV
url = 'https://raw.githubusercontent.com/owid/covid-19-data/master/public/data/owid-covid-data.csv'

# Parâmetros de conexão lendo de st.secrets
connection_parameters = {
    "user": st.secrets["snowflake"]["user"],
    "password": st.secrets["snowflake"]["password"],
    "account": st.secrets["snowflake"]["account"],
    "warehouse": st.secrets["snowflake"]["warehouse"],
    "database": "TEST_DB",
    "schema": "PUBLIC",
    "role": st.secrets["snowflake"]["role"]
}

st.sidebar.title("Carga e Gerenciamento")

@st.cache_resource(show_spinner="Conectando ao Snowflake...")
def get_snowflake_session():
    params = connection_parameters.copy()
    
    # Ler a chave privada (Key-Pair Auth)
    with open(".streamlit/rsa_key.p8", "rb") as key_file:
        p_key = serialization.load_pem_private_key(
            key_file.read(),
            password=None,
            backend=default_backend()
        )
        
    pkb = p_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption()
    )
    
    params["private_key"] = pkb
    if "password" in params:
        del params["password"]  # Não precisamos mais da senha
    
    session = Session.builder.configs(params).create()
    session.sql("CREATE DATABASE IF NOT EXISTS TEST_DB").collect()
    session.sql("USE DATABASE TEST_DB").collect()
    session.sql("CREATE SCHEMA IF NOT EXISTS PUBLIC").collect()
    session.sql("USE SCHEMA PUBLIC").collect()
    return session

if st.sidebar.button("■ Carregar Dados no Snowflake"):
    with st.spinner("Baixando e filtrando CSV (isso pode levar alguns minutos)..."):
        # Baixar CSV, filtrar e preparar
        df = pd.read_csv(url)
        paises = ['Brazil', 'United States', 'India', 'Germany', 'South Africa', 'Japan']
        df = df[df['location'].isin(paises)]
        df = df[df['date'] >= '2021-01-01']
        
        # Converter colunas para maiúsculas (padrão do Snowflake)
        df.columns = [str(c).upper() for c in df.columns]
        
    with st.spinner("Conectando ao Snowflake e gravando tabela..."):
        try:
            # Conectar e gravar usando a sessão em cache
            session = get_snowflake_session()
            
            session.write_pandas(df, "COVID_DATA", auto_create_table=True, overwrite=True)
            st.sidebar.success("Dados carregados com sucesso no Snowflake!")
        except Exception as e:
            st.sidebar.error(f"Erro ao carregar dados no Snowflake: {e}")


if st.sidebar.button("■ Carregar Dashboard"):
    with st.spinner("Lendo tabela do Snowflake..."):
        try:
            # Ler tabela com a sessão em cache
            session = get_snowflake_session()
            df_snow = session.table("COVID_DATA").to_pandas()
            
            # Salvar em st.session_state
            st.session_state['df_covid'] = df_snow
            st.sidebar.success("Dashboard carregado na sessão com sucesso!")
        except Exception as e:
            st.sidebar.error(f"Erro ao ler tabela do Snowflake: {e}")

# =========================================================================
# Etapa 5 — Conteúdo Principal e Visualizações
# =========================================================================

st.title("🦠 Dashboard COVID-19")
st.markdown("Analise os dados interativamente abaixo.")

if 'df_covid' in st.session_state:
    df_dashboard = st.session_state['df_covid'].copy()
    
    if 'DATE' in df_dashboard.columns:
        df_dashboard['DATE'] = pd.to_datetime(df_dashboard['DATE'])
        
    # --- FILTROS INTERATIVOS ---
    st.sidebar.markdown("---")
    st.sidebar.subheader("Filtros Interativos")
    
    # Filtro 1: Países (st.multiselect)
    paises_disponiveis = df_dashboard['LOCATION'].unique().tolist()
    paises_selecionados = st.sidebar.multiselect(
        "Selecione os países:", 
        options=paises_disponiveis, 
        default=paises_disponiveis
    )
    
    # Filtro 2: Período (st.slider)
    if not df_dashboard.empty and 'DATE' in df_dashboard.columns:
        min_date = df_dashboard['DATE'].min().date()
        max_date = df_dashboard['DATE'].max().date()
        date_range = st.sidebar.slider(
            "Selecione o período:", 
            min_value=min_date, 
            max_value=max_date, 
            value=(min_date, max_date)
        )
    else:
        date_range = None

    if paises_selecionados:
        # Aplicar filtros ao dataframe
        df_filtrado = df_dashboard[df_dashboard['LOCATION'].isin(paises_selecionados)]
        if date_range:
            df_filtrado = df_filtrado[
                (df_filtrado['DATE'].dt.date >= date_range[0]) & 
                (df_filtrado['DATE'].dt.date <= date_range[1])
            ]
            
        df_filtrado = df_filtrado.sort_values(by='DATE')
        
        # Para métricas acumulativas, agrupar e pegar o valor máximo do período
        df_max = df_filtrado.groupby('LOCATION').max(numeric_only=True).reset_index()

        # Criação de abas (st.tabs)
        tab1, tab2, tab3 = st.tabs(["📊 Visão Geral", "🗃️ Dados Brutos", "💻 Query SQL (Desafio)"])
        
        with tab1:
            # --- 3 KPIs / st.metric ---
            col1, col2, col3 = st.columns(3)
            
            total_casos = df_max['TOTAL_CASES'].sum() if 'TOTAL_CASES' in df_max.columns else 0
            total_obitos = df_max['TOTAL_DEATHS'].sum() if 'TOTAL_DEATHS' in df_max.columns else 0
            num_paises = len(paises_selecionados)
            
            def format_num(num):
                if pd.isna(num): return "0"
                return f"{int(num):,}".replace(",", ".")
                
            col1.metric("Total de Casos", format_num(total_casos))
            col2.metric("Total de Óbitos", format_num(total_obitos))
            col3.metric("Países Analisados", num_paises)
            
            st.markdown("---")
            
            # --- 4 Visualizações Obrigatórias ---
            
            # 1. Evolução de casos novos (Linha)
            st.subheader("1. Evolução de Casos Novos ao Longo do Tempo")
            if 'NEW_CASES' in df_filtrado.columns:
                fig1 = px.line(df_filtrado, x='DATE', y='NEW_CASES', color='LOCATION', 
                               title="Novos Casos Diários")
                st.plotly_chart(fig1, use_container_width=True)
                
            col_chart1, col_chart2 = st.columns(2)
            
            with col_chart1:
                # 2. Comparação do total de óbitos (Barras)
                st.subheader("2. Total de Óbitos Acumulados")
                if 'TOTAL_DEATHS' in df_max.columns:
                    fig2 = px.bar(df_max, x='LOCATION', y='TOTAL_DEATHS', color='LOCATION', 
                                  title="Óbitos por País")
                    st.plotly_chart(fig2, use_container_width=True)
            
            with col_chart2:
                # 3. Proporção de vacinados (1 dose) na data mais recente (Pizza)
                st.subheader("3. Proporção de Vacinados (1 dose)")
                if 'PEOPLE_VACCINATED' in df_max.columns:
                    # Filtra NaN para não quebrar o gráfico de pizza
                    df_pie = df_max.dropna(subset=['PEOPLE_VACCINATED'])
                    fig3 = px.pie(df_pie, names='LOCATION', values='PEOPLE_VACCINATED', hole=0.4, 
                                  title="Pessoas Vacinadas (Comparação)")
                    st.plotly_chart(fig3, use_container_width=True)
                else:
                    st.warning("Coluna 'PEOPLE_VACCINATED' não encontrada.")
            
            # 4. Relação população e total de casos (Dispersão)
            st.subheader("4. População vs Total de Casos")
            if 'POPULATION' in df_max.columns and 'TOTAL_CASES' in df_max.columns:
                fig4 = px.scatter(df_max, x='POPULATION', y='TOTAL_CASES', color='LOCATION', 
                                  size='POPULATION', hover_name='LOCATION',
                                  title="Relação entre População e Total de Casos Acumulados",
                                  labels={"POPULATION": "População", "TOTAL_CASES": "Total de Casos"})
                st.plotly_chart(fig4, use_container_width=True)
                
        with tab2:
            # --- Aba de Dados Brutos e Exportação ---
            st.subheader("Visualização dos Dados Brutos")
            st.dataframe(df_filtrado)
            
            # Botão de exportação
            csv_data = df_filtrado.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Exportar para CSV",
                data=csv_data,
                file_name='covid_dados_brutos.csv',
                mime='text/csv',
            )
            
        with tab3:
            # --- Desafio Opcional: Query SQL ---
            st.subheader("Executar Consultas SQL Direto no Snowflake")
            st.info("Digite uma query para buscar dados na tabela `COVID_DATA` armazenada no seu Snowflake.")
            
            user_query = st.text_area("Sua Query SQL:", value="SELECT * FROM COVID_DATA LIMIT 10;", height=150)
            
            if st.button("▶ Executar Query"):
                with st.spinner("Executando query no Snowflake..."):
                    try:
                        session = get_snowflake_session()
                        result_df = session.sql(user_query).to_pandas()
                        st.success("Query executada com sucesso!")
                        st.dataframe(result_df)
                    except Exception as e:
                        st.error(f"Erro ao executar query: {e}")

    else:
        st.warning("Selecione pelo menos um país na barra lateral para exibir os gráficos.")
else:
    st.info("👈 Utilize os botões na barra lateral para carregar os dados no Snowflake e gerar o Dashboard.")
