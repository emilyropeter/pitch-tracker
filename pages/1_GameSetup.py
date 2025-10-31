import streamlit as st
from supabase import create_client
from datetime import date

st.set_page_config(page_title="Game Setup")

# -----------------------------
# Supabase connection
# -----------------------------
SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["key"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# -----------------------------
# Helper functions
# -----------------------------
def ensure_player(name, team=None, throws=None, bats=None):
    """Return PlayerID for name; create if missing."""
    if not name.strip():
        return None
    r = supabase.table("Players").select("PlayerID").eq("Name", name).execute()
    if r.data:
        return r.data[0]["PlayerID"]
    payload = {"Name": name}
    if team:
        payload["Team"] = team
    if throws:
        payload["Throws"] = throws
    if bats:
        payload["Bats"] = bats
    created = supabase.table("Players").insert(payload).execute()
    return created.data[0]["PlayerID"] if created.data else None


def create_game(home, away, gamedate):
    resp = supabase.table("Games").insert({
        "HomeTeam": home,
        "AwayTeam": away,
        "GameDate": str(gamedate)
    }).execute()
    return resp.data[0]["GameID"] if resp.data else None


# -----------------------------
# Initialize session defaults
# -----------------------------
for key, default in {
    "lineup": [],
    "pitchers": [],
    "selected_game_id": None,
    "game_active": False
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


# -----------------------------
# 1 — Game Setup & Lineup
# -----------------------------
st.title("Game Setup")
st.caption("Create a new game, manage lineup, and add pitchers.")

with st.expander("1 — Game Setup & Lineup", expanded=True):
    col1, col2, col3 = st.columns([3, 3, 2])

    # ----------- Game Select/Create -----------
    with col1:
        games = supabase.table("Games").select(
            "GameID, GameDate, HomeTeam, AwayTeam"
        ).order("GameDate", desc=True).execute().data or []
        game_map = {f"{g['GameDate']} - {g['HomeTeam']} vs {g['AwayTeam']}": g["GameID"] for g in games}
        sel_game = st.selectbox("Select Game", ["-- Add New Game --"] + list(game_map.keys()))
        if sel_game == "-- Add New Game --":
            hom
