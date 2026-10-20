"""Run with: streamlit run app.py"""

from pathlib import Path

import streamlit as st
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
st.set_page_config(page_title="Syllagent", page_icon=":material/calendar_month:", layout="wide")

st.navigation([st.Page("syllabus_agent/page.py", title="Syllagent", icon=":material/calendar_month:")], position="hidden").run()
