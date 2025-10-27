import streamlit as st
from supabase import create_client
from datetime import date

st.set_page_config(page_title="Game Setup", page_icon="⚾")
st.markdown("<h1 style='text-align:center;'>Game Setup</h1>", unsafe_allow_html=True)

# Supabase connection
SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["key"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

st.title("⚾ Game Setup")
st.caption("Create a game and set up your lineup before tracking pitches.")

def create_game(home, away, gamedate):
    resp = supabase.table("Games").insert({
        "HomeTeam": home,
        "AwayTeam": away,
        "GameDate": str(gamedate)
    }).execute()
    return resp.data[0]["GameID"] if resp.data else None

home = st.text_input("Home Team")
away = st.text_input("Away Team")
gamedate = st.date_input("Game Date", value=date.today())

if st.button("Create Game"):
    gid = create_game(home, away, gamedate)
    if gid:
        st.session_state["selected_game_id"] = gid
        st.success(f"✅ Game created! Game ID: {gid}")
        st.info("When ready, click 'Start Game' below to move to pitch tracking.")
    else:
        st.error("Failed to create game. Check your Supabase connection.")

if st.button("▶️ Start Game"):
    if "selected_game_id" in st.session_state:
        st.switch_page("app.py")
    else:
        st.warning("Create a game first.")
