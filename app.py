# app.py — Main Baseball Game Tracker
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Game Setup", page_icon="⚾")
st.markdown("<h1 style='text-align:center;'>Game Setup</h1>", unsafe_allow_html=True)


# -----------------------------
# Supabase Connection
# -----------------------------
SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["key"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# -----------------------------
# Require Game Setup first
# -----------------------------
if "selected_game_id" not in st.session_state or not st.session_state["selected_game_id"]:
    st.warning("⚠️ Please go to the **Game Setup** page first to create and start a game.")
    st.stop()

# -----------------------------
# Page Header
# -----------------------------
st.title("⚾ Baseball Game Tracker")
st.caption("Track at-bats, pitches, and runner events for your active game.")

# Helper to add summary entries
def add_to_summary(line: str):
    if "event_log" not in st.session_state:
        st.session_state["event_log"] = []
    st.session_state["event_log"].insert(0, line)

# -----------------------------
# Step 2 — Select AtBat
# -----------------------------
st.header("2 — Select AtBat")

colB1, colB2, colB3 = st.columns([3,3,2])

# Batter select
with colB1:
    players = supabase.table("Players").select("PlayerID,Name").order("Name", asc=True).execute().data or []
    batter_names = [p["Name"] for p in players]
    batter_choice = st.selectbox("Select Batter", ["-- Select --"] + batter_names)
    if batter_choice != "-- Select --":
        batter_id = next((p["PlayerID"] for p in players if p["Name"] == batter_choice), None)
        st.session_state["current_batter_id"] = batter_id

# Pitcher select
with colB2:
    pitcher_names = [p["Name"] for p in players]
    pitcher_choice = st.selectbox("Select Pitcher", ["-- Select --"] + pitcher_names)
    if pitcher_choice != "-- Select --":
        pitcher_id = next((p["PlayerID"] for p in players if p["Name"] == pitcher_choice), None)
        st.session_state["current_pitcher_id"] = pitcher_id

# Inning + LeadOff
with colB3:
    inning_val = st.number_input("Inning", min_value=1, value=1)
    lead_off_sel = st.selectbox("LeadOff", ["Select", "Yes", "No"])
    if st.button("Start AtBat"):
        if not st.session_state.get("current_batter_id") or not st.session_state.get("current_pitcher_id"):
            st.error("Select both a batter and a pitcher.")
        else:
            lo_val = None if lead_off_sel == "Select" else (lead_off_sel == "Yes")
            payload = {
                "GameID": int(st.session_state["selected_game_id"]),
                "BatterID": int(st.session_state["current_batter_id"]),
                "PitcherID": int(st.session_state["current_pitcher_id"]),
                "Inning": int(inning_val),
                "LeadOff": lo_val,
                "RunsScored": 0,
                "EarnedRuns": 0
            }
            resp = supabase.table("AtBats").insert(payload).execute()
            if resp.data:
                st.session_state["current_atbat_id"] = resp.data[0]["AtBatID"]
                st.session_state["balls"] = 0
                st.session_state["strikes"] = 0
                st.success(f"AtBat started! ID: {resp.data[0]['AtBatID']}")
            else:
                st.error("Failed to create AtBat.")

# -----------------------------
# Step 3 — Quick Pitch Entry
# -----------------------------
if "current_atbat_id" not in st.session_state:
    st.info("Start an AtBat above before logging pitches.")
else:
    st.header("3 — Quick Pitch Entry")

    if "balls" not in st.session_state: st.session_state["balls"] = 0
    if "strikes" not in st.session_state: st.session_state["strikes"] = 0

    st.write(f"**Count:** {st.session_state['balls']}-{st.session_state['strikes']}")

    pt_cols = st.columns(5)
    pitch_types = ["Fastball", "Slider", "Curveball", "Changeup", "Cutter"]
    for i, t in enumerate(pitch_types):
        if pt_cols[i].button(t):
            st.session_state["quick_pitch_type"] = t

    pc_cols = st.columns(5)
    pitch_calls = ["Strike Called", "Strike Swing Miss", "Ball Called", "Foul Ball", "In Play"]
    for i, c in enumerate(pitch_calls):
        if pc_cols[i].button(c):
            st.session_state["quick_pitch_called"] = c

    velocity = st.number_input("Velocity (mph, optional)", min_value=0.0, step=0.1)
    zone = st.selectbox("Zone (optional)", ["None"] + [str(i) for i in range(1,15)])

    if st.button("Submit Pitch"):
        if not st.session_state.get("quick_pitch_type") or not st.session_state.get("quick_pitch_called"):
            st.warning("Select a pitch type and a call first.")
        else:
            called = st.session_state["quick_pitch_called"]
            if called == "Ball Called":
                st.session_state["balls"] = min(4, st.session_state["balls"] + 1)
            elif called in ["Strike Called", "Strike Swing Miss"]:
                st.session_state["strikes"] = min(3, st.session_state["strikes"] + 1)
            elif called == "Foul Ball" and st.session_state["strikes"] < 2:
                st.session_state["strikes"] += 1
            elif called == "In Play" and st.session_state["strikes"] < 3:
                st.session_state["strikes"] += 1

            wel = None
            b, s = st.session_state["balls"], st.session_state["strikes"]
            if (b, s) in [(0,0),(0,1),(1,0),(1,1)]:
                wel = "E"
            elif (b, s) in [(0,2),(1,2)]:
                wel = "W"
            elif (b, s) in [(2,0),(2,1)]:
                wel = "L"

            zone_val = None if zone == "None" else int(zone)

            payload = {
                "AtBatID": int(st.session_state["current_atbat_id"]),
                "PitchType": st.session_state["quick_pitch_type"],
                "Velocity": velocity or None,
                "Zone": zone_val,
                "PitchCalled": called,
                "Balls": b,
                "Strikes": s,
                "WEL": wel
            }
            res = supabase.table("Pitches").insert(payload).execute()
            if res.data:
                st.success(f"Pitch saved: {st.session_state['quick_pitch_type']} — {called}")
                add_to_summary(f"{st.session_state['quick_pitch_type']} {velocity} {called} ({b}-{s})")
                st.session_state["quick_pitch_type"] = None
                st.session_state["quick_pitch_called"] = None
            else:
                st.error("Failed to save pitch.")

# -----------------------------
# Step 4 — Finish AtBat
# -----------------------------
if st.session_state.get("current_atbat_id"):
    st.header("4 — Finish AtBat")
    play_results = [
        "1B", "2B", "3B", "HR", "Walk", "Intentional Walk",
        "Strikeout Looking", "Strikeout Swinging", "HitByPitch",
        "GroundOut", "FlyOut", "Error", "FC", "SAC", "SACFly"
    ]
    play = st.selectbox("Play Result", ["-- Select --"] + play_results)
    lead_off_on = st.selectbox("LeadOff On", ["Select", "Yes", "No"])
    runs = st.number_input("Runs Scored", min_value=0, value=0)
    er = st.number_input("Earned Runs", min_value=0, value=0)
    special = None
    if play in ["Walk", "Intentional Walk"]:
        special = st.selectbox("Special Walk Type", ["None", "4 Pitch Walk", "2 Strike Walk", "2 Out Walk"])
    if st.button("Finish AtBat"):
        upd = {
            "PlayResult": None if play == "-- Select --" else play,
            "RunsScored": runs,
            "EarnedRuns": er,
        }
        if lead_off_on != "Select":
            upd["LeadOffOn"] = (lead_off_on == "Yes")
        if special and special != "None":
            upd["KorBB"] = special
        supabase.table("AtBats").update(upd).eq("AtBatID", st.session_state["current_atbat_id"]).execute()
        add_to_summary(f"AtBat finished: {play} | Runs {runs} | ER {er}")
        st.session_state["current_atbat_id"] = None
        st.session_state["balls"] = 0
        st.session_state["strikes"] = 0
        st.success("AtBat completed.")

# -----------------------------
# Step 5 — Running Summary
# -----------------------------
st.markdown("---")
st.subheader("Running Summary (Session)")
if st.session_state.get("event_log"):
    for e in st.session_state["event_log"]:
        st.write("• " + e)
else:
    st.caption("No pitches or at-bats recorded yet.")

