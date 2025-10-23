import streamlit as st
from supabase import create_client
from datetime import date
import os

st.set_page_config(page_title="Baseball Game Tracker", layout="wide")

# -----------------------
# Supabase Connection
# -----------------------
try:
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
except KeyError:
    st.error("Missing Supabase credentials. Add them to your Streamlit secrets.")
    st.stop()

supabase = create_client(url, key)

# -----------------------
# Utilities
# -----------------------
def create_game(home, away, gamedate):
    """Create a new game."""
    resp = supabase.table("Games").insert({
        "HomeTeam": home,
        "AwayTeam": away,
        "GameDate": str(gamedate)
    }).execute()
    return resp.data[0]["GameID"] if resp.data else None

def create_atbat(game_id, inning):
    """Create a new AtBat row."""
    resp = supabase.table("AtBats").insert({
        "GameID": game_id,
        "Inning": inning
    }).execute()
    return resp.data[0]["AtBatID"] if resp.data else None

def delete_last_pitch(pitch_id):
    """Delete a pitch by ID."""
    supabase.table("Pitches").delete().eq("PitchID", pitch_id).execute()

def next_pitch_numbers_for(atbat_id):
    """Compute next pitch numbers."""
    res_global = supabase.table("Pitches").select("PitchNo").order("PitchNo", desc=True).limit(1).execute()
    next_pitch_no = res_global.data[0]["PitchNo"] + 1 if res_global.data else 1

    res_ab = supabase.table("Pitches").select("PitchOfAB").eq("AtBatID", atbat_id).order("PitchOfAB", desc=True).limit(1).execute()
    next_pitch_of_ab = res_ab.data[0]["PitchOfAB"] + 1 if res_ab.data else 1

    return next_pitch_no, next_pitch_of_ab

def compute_wel(balls, strikes):
    """Compute WEL (Win, Even, Lose)."""
    if (balls, strikes) in [(0,0),(0,1),(1,0),(1,1)]:
        return "E"
    if (balls, strikes) in [(0,2),(1,2)]:
        return "W"
    if (balls, strikes) in [(2,0),(2]()
