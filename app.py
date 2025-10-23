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
    try:
        # Ensure valid numeric types
        game_id = int(game_id) if game_id else None
        inning = int(inning) if inning else None

        # Minimal required insert — add only what’s definitely safe
        data = {
            "GameID": game_id,
            "Inning": inning,
            "RunsScored": 0,
            "EarnedRuns": 0
        }

        # Insert into Supabase
        resp = supabase.table("AtBats").insert(data).execute()

        if resp.data:
            return resp.data[0]["AtBatID"]
        else:
            st.error("Insert returned no data.")
            return None

    except Exception as e:
        st.error(f"Error creating at-bat: {str(e)}")
        return None

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
    if (balls, strikes) in [(2,0),(2,1)]:
        return "L"
    return None

# -----------------------
# Session State
# -----------------------
defaults = {
    "selected_game_id": None,
    "current_atbat_id": None,
    "balls": 0,
    "strikes": 0,
    "pitch_history": [],
    "last_pitch_summary": None,
    "last_saved_pitch_id": None
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# -----------------------
# Header
# -----------------------
st.title("⚾ Baseball Game Tracker")
st.caption("Track games, at-bats, and pitches easily with Supabase backend.")

# -----------------------
# 1 — Game Selection
# -----------------------
with st.expander("1 — Game Selection", expanded=True):
    games = supabase.table("Games").select("GameID, GameDate, HomeTeam, AwayTeam").order("GameDate", desc=True).execute().data or []
    game_map = {f"{g['GameDate']} - {g['HomeTeam']} vs {g['AwayTeam']}": g["GameID"] for g in games}

    selected_game_key = st.selectbox("Select Game", ["-- Add New Game --"] + list(game_map.keys()))

    if selected_game_key == "-- Add New Game --":
        home = st.text_input("Home Team")
        away = st.text_input("Away Team")
        gd = st.date_input("Game Date", date.today())
        if st.button("Save Game"):
            gid = create_game(home, away, gd)
            if gid:
                st.success("Game created. Refresh or reopen to select it.")
                st.rerun()
            else:
                st.error("Failed to create game.")
        st.stop()
    else:
        st.session_state["selected_game_id"] = game_map[selected_game_key]
        st.success(f"Selected: {selected_game_key}")

# -----------------------
# 2 — AtBat Setup
# -----------------------
st.header("2 — Start an AtBat")

if st.session_state["selected_game_id"]:
    inning_val = st.number_input("Inning", min_value=1, value=1)
    if st.button("Start New AtBat"):
        atbat_id = create_atbat(st.session_state["selected_game_id"], inning_val)
        if atbat_id:
            st.session_state["current_atbat_id"] = atbat_id
            st.session_state["balls"] = 0
            st.session_state["strikes"] = 0
            st.session_state["pitch_history"] = []
            st.success(f"AtBat {atbat_id} started.")
            st.rerun()
else:
    st.info("Select a game first.")

# -----------------------
# 3 — Pitch Entry
# -----------------------
st.header("3 — Pitch Entry")

if not st.session_state["current_atbat_id"]:
    st.info("Start an AtBat to enter pitches.")
else:
    atbat_id = st.session_state["current_atbat_id"]
    pno, poab = next_pitch_numbers_for(atbat_id)
    st.write(f"Next Pitch No: **{pno}**, Pitch of AB: **{poab}**")
    st.write(f"Count: **{st.session_state['balls']}-{st.session_state['strikes']}**")

    # Manual pitch entry form
    with st.form("manual_pitch_form"):
        m_ptype = st.selectbox("Pitch Type", ["Fastball", "Changeup", "Curveball", "Slider"])
        m_vel = st.number_input("Velocity (mph)", min_value=0.0, step=0.1)
        m_zone = st.selectbox("Zone (1–14 or None)", ["None"] + [str(i) for i in range(1, 15)])
        m_called = st.selectbox("Pitch Called", ["Ball Called", "Strike Called", "Strike Swing Miss", "Foul Ball", "In Play"])
        m_tagged = st.selectbox("Tagged Hit", ["None", "Bunt", "Flyball", "Groundball", "Linedrive"])
        m_hitdir = st.selectbox("Hit Direction", ["None", "Left Field", "Center Field", "Right Field"])
        submit_pitch = st.form_submit_button("Save Pitch")

    if submit_pitch:
        # Update count
        if m_called == "Ball Called":
            st.session_state["balls"] = min(4, st.session_state["balls"] + 1)
        elif m_called in ["Strike Called", "Strike Swing Miss"]:
            st.session_state["strikes"] = min(3, st.session_state["strikes"] + 1)
        elif m_called == "Foul Ball" and st.session_state["strikes"] < 2:
            st.session_state["strikes"] += 1

        wel_val = compute_wel(st.session_state["balls"], st.session_state["strikes"])
        zone_val = None if m_zone == "None" else int(m_zone)
        tagged_val = None if m_tagged == "None" else m_tagged
        hitdir_val = None if m_hitdir == "None" else m_hitdir

        pitch_data = {
            "AtBatID": atbat_id,
            "PitchNo": pno,
            "PitchOfAB": poab,
            "PitchType": m_ptype,
            "Velocity": float(m_vel) if m_vel else None,
            "Zone": zone_val,
            "PitchCalled": m_called,
            "WEL": wel_val,
            "Balls": st.session_state["balls"],
            "Strikes": st.session_state["strikes"],
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
                st.session_state["last_pitch_summary"] = (
                    f"{m_ptype} {m_vel} — {m_called} "
                    f"({st.session_state['balls']}-{st.session_state['strikes']})"
                )
                st.success("Pitch saved successfully!")
                st.experimental_rerun()
            else:
                st.error("Pitch not saved. Check your Supabase schema.")
        except Exception as e:
            st.error(f"Error inserting pitch: {e}")

# -----------------------
# 4 — Undo Last Pitch
# -----------------------
if st.session_state["last_pitch_summary"]:
    st.info("Last pitch: " + st.session_state["last_pitch_summary"])
    if st.button("Undo Last Pitch"):
        if st.session_state["pitch_history"]:
            last_pid = st.session_state["pitch_history"].pop()
            try:
                delete_last_pitch(last_pid)
                st.success("Last pitch removed.")
                st.experimental_rerun()
            except Exception as e:
                st.error("Undo failed: " + str(e))
        else:
            st.warning("No pitch to undo.")


