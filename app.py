import streamlit as st
from supabase import create_client, Client
import pandas as pd
import numpy as np
import datetime

# ----------------------------
#  SETUP
# ----------------------------
url = st.secrets["supabase"]["url"]
key = st.secrets["supabase"]["key"]
supabase: Client = create_client(url, key)

st.set_page_config(page_title="Pitch Tracker", layout="wide")

# ----------------------------
#  HELPER FUNCTIONS
# ----------------------------

def compute_wel(balls, strikes):
    """Compute WEL value based on balls/strikes count."""
    return round(1 - ((balls * 0.1) + (strikes * 0.15)), 3)

def next_pitch_numbers_for(atbat_id):
    """Get next PitchNo and PitchOfAB."""
    res = supabase.table("Pitches").select("PitchNo").order("PitchNo", desc=True).limit(1).execute()
    last_pitch_no = res.data[0]["PitchNo"] if res.data else 0
    poab_res = supabase.table("Pitches").select("PitchOfAB").eq("AtBatID", atbat_id).order("PitchOfAB", desc=True).limit(1).execute()
    last_poab = poab_res.data[0]["PitchOfAB"] if poab_res.data else 0
    return last_pitch_no + 1, last_poab + 1

def create_atbat(game_id, inning, order=None, leadoff=None, leadoff_on=None, play_result=None, runs_scored=0, earned_runs=0, korbb=None):
    payload = {
        "GameID": game_id,
        "Inning": inning,
        "RunsScored": runs_scored,
        "EarnedRuns": earned_runs
    }
    if order is not None:
        payload["BatterOrder"] = order
    if leadoff is not None:
        payload["LeadOff"] = leadoff
    if leadoff_on is not None:
        payload["LeadOffOn"] = leadoff_on
    if play_result:
        payload["PlayResult"] = play_result
    if korbb:
        payload["KorBB"] = korbb

    res = supabase.table("AtBats").insert(payload).execute()
    return res.data[0]["AtBatID"] if res.data else None

def clean_numeric(value):
    """Ensure numeric values are finite and JSON safe."""
    if isinstance(value, (int, float, np.number)):
        if np.isnan(value) or np.isinf(value):
            return None
        return float(value)
    return value

# ----------------------------
#  SESSION STATE INIT
# ----------------------------
if "balls" not in st.session_state:
    st.session_state["balls"] = 0
if "strikes" not in st.session_state:
    st.session_state["strikes"] = 0
if "pitch_history" not in st.session_state:
    st.session_state["pitch_history"] = []
if "last_saved_pitch_id" not in st.session_state:
    st.session_state["last_saved_pitch_id"] = None
if "last_pitch_summary" not in st.session_state:
    st.session_state["last_pitch_summary"] = ""

# ----------------------------
#  GAME + ATBAT SELECTION
# ----------------------------
st.header("⚾ Pitch Tracker")

games = supabase.table("Games").select("GameID, GameDate, Opponent").execute()
game_df = pd.DataFrame(games.data)
game_option = st.selectbox("Select Game", game_df["Opponent"] if not game_df.empty else ["None"])
selected_game = game_df.loc[game_df["Opponent"] == game_option, "GameID"].iloc[0] if not game_df.empty else None

atbats = supabase.table("AtBats").select("AtBatID, Inning, BatterOrder").eq("GameID", selected_game).execute()
atbat_df = pd.DataFrame(atbats.data)
atbat_option = st.selectbox("Select AtBat", atbat_df["AtBatID"] if not atbat_df.empty else ["None"])
atbat_id = int(atbat_option) if atbat_option != "None" else None

pno, poab = next_pitch_numbers_for(atbat_id) if atbat_id else (1, 1)

# ----------------------------
#  QUICK PITCH BUTTONS
# ----------------------------
st.subheader("Quick Pitch Entry")

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("Ball Called"):
        st.session_state["balls"] = min(4, st.session_state["balls"] + 1)
        supabase.table("Pitches").insert({
            "AtBatID": atbat_id, "PitchNo": pno, "PitchOfAB": poab,
            "PitchCalled": "Ball Called", "Balls": st.session_state["balls"],
            "Strikes": st.session_state["strikes"], "WEL": compute_wel(st.session_state["balls"], st.session_state["strikes"])
        }).execute()
        st.success("Ball recorded.")
        st.experimental_rerun()

with col2:
    if st.button("Strike Swing Miss"):
        st.session_state["strikes"] = min(3, st.session_state["strikes"] + 1)
        supabase.table("Pitches").insert({
            "AtBatID": atbat_id, "PitchNo": pno, "PitchOfAB": poab,
            "PitchCalled": "Strike Swing Miss", "Balls": st.session_state["balls"],
            "Strikes": st.session_state["strikes"], "WEL": compute_wel(st.session_state["balls"], st.session_state["strikes"])
        }).execute()
        st.success("Strike recorded.")
        st.experimental_rerun()

with col3:
    if st.button("Foul Ball"):
        if st.session_state["strikes"] < 2:
            st.session_state["strikes"] += 1
        supabase.table("Pitches").insert({
            "AtBatID": atbat_id, "PitchNo": pno, "PitchOfAB": poab,
            "PitchCalled": "Foul Ball", "Balls": st.session_state["balls"],
            "Strikes": st.session_state["strikes"], "WEL": compute_wel(st.session_state["balls"], st.session_state["strikes"])
        }).execute()
        st.success("Foul recorded.")
        st.experimental_rerun()

# ----------------------------
#  MANUAL PITCH ENTRY FORM
# ----------------------------
st.markdown("---")
st.markdown("### Manual Pitch Entry")

with st.form("manual_pitch_form"):
    m_ptype = st.selectbox("Pitch Type", ["Fastball","Changeup","Curveball","Slider"], key="m_ptype")
    m_vel = st.number_input("Velocity (mph)", min_value=0.0, step=0.1, key="m_vel")
    m_zone = st.selectbox("Zone (1-14 or None)", ["None"] + [str(i) for i in range(1,15)], key="m_zone")
    m_called = st.selectbox("Pitch Called", ["Ball Called","Strike Called","Strike Swing Miss","Foul Ball","In Play"], key="m_called")
    m_tagged = st.selectbox("Tagged Hit", ["None","Bunt","Flyball","Groundball","Linedrive"], key="m_tagged")
    m_hitdir = st.selectbox("Hit Direction", ["None","3-4 Hole","5-6 Hole","Center Field","Left Field","Right Field","Short Stop","Second Base","Third Base"], key="m_hitdir")
    submit_pitch = st.form_submit_button("Save Manual Pitch")

if submit_pitch:
    if m_called == "Ball Called":
        st.session_state["balls"] = min(4, st.session_state["balls"] + 1)
    elif m_called in ["Strike Called","Strike Swing Miss"]:
        st.session_state["strikes"] = min(3, st.session_state["strikes"] + 1)
    elif m_called == "Foul Ball" and st.session_state["strikes"] < 2:
        st.session_state["strikes"] += 1

    wel_val = compute_wel(st.session_state["balls"], st.session_state["strikes"])
    zone_val = None if m_zone == "None" else int(m_zone)
    tagged_val = None if m_tagged == "None" else m_tagged
    hitdir_val = None if m_hitdir == "None" else m_hitdir

    pitch_data = {
        "AtBatID": int(atbat_id),
        "PitchNo": int(pno),
        "PitchOfAB": int(poab),
        "PitchType": m_ptype,
        "Velocity": clean_numeric(m_vel),
        "Zone": zone_val,
        "PitchCalled": m_called,
        "WEL": wel_val,
        "Balls": int(st.session_state["balls"]),
        "Strikes": int(st.session_state["strikes"]),
        "TaggedHit": tagged_val,
        "HitDirection": hitdir_val,
        "KPI": None
    }

    try:
        resp = supabase.table("Pitches").insert(pitch_data).execute()
        if resp.data:
            pid = resp.data[0]["PitchID"]
            st.session_state["pitch_history"].append(pid)
            st.session_state["last_saved_pitch_id"] = pid
            st.session_state["last_pitch_summary"] = f"{m_ptype} {m_vel} — {m_called} ({st.session_state['balls']}-{st.session_state['strikes']})"
            st.success("Pitch saved successfully!")
            st.experimental_rerun()
    except Exception as e:
        st.error(f"Error saving pitch: {e}")

# ----------------------------
#  RUNNER EVENTS SECTION
# ----------------------------
st.markdown("---")
st.markdown("### Runner Events")

with st.form("runner_event_form"):
    base = st.selectbox("Base", ["1B","2B","3B","Home"])
    event = st.selectbox("Event", ["Steal","Pickoff","Advance","Out"])
    result = st.selectbox("Result", ["Safe","Out","Error"])
    submit_runner = st.form_submit_button("Save Runner Event")

if submit_runner:
    try:
        resp = supabase.table("RunnerEvents").insert({
            "AtBatID": int(atbat_id),
            "Base": base,
            "Event": event,
            "Result": result
        }).execute()
        st.success("Runner event saved successfully!")
        st.experimental_rerun()
    except Exception as e:
        st.error(f"Error saving runner event: {e}")

# ----------------------------
#  SUMMARY
# ----------------------------
st.markdown("---")
st.subheader("Session Summary")
st.write(f"Balls: {st.session_state['balls']}, Strikes: {st.session_state['strikes']}")
st.write(f"Last pitch: {st.session_state['last_pitch_summary']}")
