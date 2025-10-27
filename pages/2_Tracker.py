import streamlit as st
from supabase import create_client
from datetime import date

st.set_page_config(page_title="Tracker", page_icon="📊")

# ---------------------------------------------------------
# Supabase connection
# ---------------------------------------------------------
SUPABASE_URL = st.secrets["supabase"]["url"]
SUPABASE_KEY = st.secrets["supabase"]["key"]
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def ensure_player(name, team=None, throws=None, bats=None):
    if not name or str(name).strip() == "":
        return None
    r = supabase.table("Players").select("PlayerID").eq("Name", name).execute()
    if r.data:
        return r.data[0]["PlayerID"]
    payload = {"Name": name}
    if team: payload["Team"] = team
    if throws: payload["Throws"] = throws
    if bats: payload["Bats"] = bats
    created = supabase.table("Players").insert(payload).execute()
    return created.data[0]["PlayerID"] if created.data else None

def create_atbat(game_id, batter_id, pitcher_id, inning):
    payload = {"GameID": int(game_id), "BatterID": int(batter_id), "PitcherID": int(pitcher_id), "Inning": int(inning)}
    resp = supabase.table("AtBats").insert(payload).execute()
    return resp.data[0]["AtBatID"] if resp.data else None

def next_pitch_numbers_for(atbat_id):
    """Return (next global PitchNo, next PitchOfAB) with safe defaults."""
    try:
        r1 = supabase.table("Pitches").select("PitchNo").order("PitchNo", desc=True).limit(1).execute()
        last_global = r1.data[0]["PitchNo"] if r1.data and r1.data[0]["PitchNo"] is not None else 0
    except Exception:
        last_global = 0

    try:
        r2 = supabase.table("Pitches").select("PitchOfAB").eq("AtBatID", atbat_id).order("PitchOfAB", desc=True).limit(1).execute()
        last_poab = r2.data[0]["PitchOfAB"] if r2.data and r2.data[0]["PitchOfAB"] is not None else 0
    except Exception:
        last_poab = 0

    return (int(last_global) + 1, int(last_poab) + 1)

def compute_wel(balls, strikes):
    t = (balls, strikes)
    if t in [(0,0),(0,1),(1,0),(1,1)]: return "E"
    if t in [(0,2),(1,2)]: return "W"
    if t in [(2,0),(2,1)]: return "L"
    return None

def insert_pitch(atbat_id, pitch_no, pitch_of_ab, pitch_type, velocity, zone, pitch_called, balls, strikes, wel, tagged, hitdir, kpi):
    payload = {
        "AtBatID": int(atbat_id),
        "PitchNo": int(pitch_no),
        "PitchOfAB": int(pitch_of_ab),
        "PitchType": pitch_type,
        "Velocity": None if not velocity else float(velocity),
        "Zone": None if not zone else int(zone),
        "PitchCalled": pitch_called,
        "WEL": wel,
        "Balls": int(balls),
        "Strikes": int(strikes),
        "TaggedHit": tagged,
        "HitDirection": hitdir,
        "KPI": kpi
    }
    return supabase.table("Pitches").insert(payload).execute()

def add_to_summary(line: str):
    st.session_state["event_log"].insert(0, line)

# ---------------------------------------------------------
# Session defaults
# ---------------------------------------------------------
defaults = {
    "lineup": [],
    "pitchers": [],
    "selected_game_id": None,
    "current_batter_id": None,
    "current_pitcher_id": None,
    "current_atbat_id": None,
    "balls": 0,
    "strikes": 0,
    "pitch_history": [],
    "last_pitch_summary": None,
    "last_saved_pitch_id": None,
    "event_log": []
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ---------------------------------------------------------
# Ensure a game is active
# ---------------------------------------------------------
if not st.session_state.get("selected_game_id"):
    st.warning("Please go to the Game Setup page first to create and start a game.")
    st.stop()

st.title("📊 Tracker — Live Game View")

# ---------------------------------------------------------
# 1 — Select AtBat
# ---------------------------------------------------------
st.header("1 — Select AtBat")
col1, col2, col3 = st.columns([3,3,2])

with col1:
    lineup_names = [x["Name"] for x in st.session_state["lineup"]]
    batter_choice = st.selectbox("Select Batter", ["-- Select --"] + lineup_names)
    if batter_choice != "-- Select --":
        sel = next((x for x in st.session_state["lineup"] if x["Name"] == batter_choice), None)
        if sel:
            st.session_state["current_batter_id"] = sel["PlayerID"]
            st.write(f"Selected batter: {sel['Name']} (slot {sel['Order']})")

with col2:
    pitch_names = [x["Name"] for x in st.session_state["pitchers"]]
    pitcher_choice = st.selectbox("Select Pitcher", ["-- Select --"] + pitch_names)
    if pitcher_choice != "-- Select --":
        sp = next((x for x in st.session_state["pitchers"] if x["Name"] == pitcher_choice), None)
        if sp:
            st.session_state["current_pitcher_id"] = sp["PlayerID"]
            st.write(f"Selected pitcher: {sp['Name']}")

with col3:
    inning_val = st.number_input("Inning", min_value=1, value=1)
    if st.button("Start AtBat"):
        if not st.session_state["current_batter_id"] or not st.session_state["current_pitcher_id"]:
            st.error("Select batter and pitcher first.")
        else:
            atbat_id = create_atbat(
                st.session_state["selected_game_id"],
                st.session_state["current_batter_id"],
                st.session_state["current_pitcher_id"],
                inning_val
            )
            if atbat_id:
                st.session_state["current_atbat_id"] = atbat_id
                st.session_state["balls"] = 0
                st.session_state["strikes"] = 0
                st.session_state["pitch_history"] = []
                st.session_state["last_pitch_summary"] = None
                st.session_state["last_saved_pitch_id"] = None
                st.success(f"AtBat {atbat_id} created.")
                st.rerun()
            else:
                st.error("Failed to create AtBat.")

# ---------------------------------------------------------
# 2 — Pitch Entry
# ---------------------------------------------------------
if not st.session_state["current_atbat_id"]:
    st.info("Start an AtBat first.")
else:
    atbat_id = st.session_state["current_atbat_id"]
    pno, poab = next_pitch_numbers_for(atbat_id)
    st.subheader(f"Pitch #{pno} — Count: {st.session_state['balls']}-{st.session_state['strikes']}")

    st.markdown("**Pitch Type & Result**")
    pt_cols = st.columns(5)
    types = ["Fastball", "Slider", "Curveball", "Changeup", "Cutter"]
    for i, t in enumerate(types):
        if pt_cols[i].button(t):
            st.session_state["quick_pitch_type"] = t

    pc_cols = st.columns(5)
    calleds = ["Strike Called", "Strike Swing Miss", "Ball Called", "Foul Ball", "In Play"]
    for i, c in enumerate(calleds):
        if pc_cols[i].button(c):
            st.session_state["quick_pitch_called"] = c

    st.caption(f"Selected: {st.session_state.get('quick_pitch_type','—')} | {st.session_state.get('quick_pitch_called','—')}")

    if st.button("Submit Pitch"):
        if not st.session_state.get("quick_pitch_type") or not st.session_state.get("quick_pitch_called"):
            st.warning("Pick both type and result first.")
        else:
            called = st.session_state["quick_pitch_called"]
            if called == "Ball Called":
                st.session_state["balls"] = min(4, st.session_state["balls"] + 1)
            elif called in ["Strike Called", "Strike Swing Miss"]:
                st.session_state["strikes"] = min(3, st.session_state["strikes"] + 1)
            elif called == "Foul Ball" and st.session_state["strikes"] < 2:
                st.session_state["strikes"] += 1

            wel = compute_wel(st.session_state["balls"], st.session_state["strikes"])
            r = insert_pitch(atbat_id, pno, poab,
                             st.session_state["quick_pitch_type"], None, None,
                             called, st.session_state["balls"], st.session_state["strikes"],
                             wel, None, None, None)
            if r.data:
                pid = r.data[0]["PitchID"]
                st.session_state["pitch_history"].append(pid)
                st.session_state["last_saved_pitch_id"] = pid
                st.session_state["last_pitch_summary"] = f"{st.session_state['quick_pitch_type']} — {called} ({st.session_state['balls']}-{st.session_state['strikes']})"
                add_to_summary(st.session_state["last_pitch_summary"])
                st.success("Pitch saved.")
                st.session_state["quick_pitch_type"] = None
                st.session_state["quick_pitch_called"] = None
                st.rerun()
            else:
                st.error("Failed to save pitch.")

# ---------------------------------------------------------
# 3 — Finish AtBat
# ---------------------------------------------------------
st.header("3 — Finish AtBat")
if not st.session_state.get("current_atbat_id"):
    st.info("Start an AtBat before finishing one.")
else:
    play_result = st.selectbox("Play Result", [
        "-- Select --", "Single", "Double", "Triple", "Home Run",
        "Ground Out", "Fly Out", "Strikeout Looking", "Strikeout Swinging",
        "Walk", "Intentional Walk", "Hit by Pitch", "Error", "Other"
    ])
    leadoff_on = st.selectbox("Leadoff On", ["Select", "Yes", "No"])

    if st.button("Finish AtBat"):
        if play_result == "-- Select --" or leadoff_on == "Select":
            st.warning("Select both Play Result and Leadoff On.")
        else:
            st.success(f"AtBat finished: {play_result} | Leadoff On: {leadoff_on}")
            add_to_summary(f"AtBat Result: {play_result} | Leadoff On: {leadoff_on}")
            st.session_state["current_atbat_id"] = None
            st.session_state["balls"] = 0
            st.session_state["strikes"] = 0
            st.session_state["pitch_history"] = []

# ---------------------------------------------------------
# 5 — Runner Events (attach to last pitch)
# ---------------------------------------------------------
st.header("5 — Runner Events")
current_pid = st.session_state.get("last_saved_pitch_id") or (
    st.session_state["pitch_history"][-1] if st.session_state["pitch_history"] else None
)

if not current_pid:
    st.info("Log a pitch first to attach runner events.")
else:
    st.write(f"Attaching events to PitchID: {current_pid}")
    try:
        players = supabase.table("Players").select("PlayerID, Name").order("Name", "asc").execute().data or []
    except Exception as e:
        st.error(f"Could not load players: {e}")
        players = []

    if players:
        player_map = {p["Name"]: p["PlayerID"] for p in players}

        runner = st.selectbox("Runner", ["-- Select --"] + list(player_map.keys()))
        start_base = st.selectbox("Start Base", [1, 2, 3, 4])
        end_base = st.selectbox("End Base (0=None)", [0, 1, 2, 3, 4], format_func=lambda x: "None" if x == 0 else str(x))
        event_type = st.selectbox("Event Type", ["Stolen Base", "Caught Stealing", "Pickoff", "Out on Play", "Advanced on Hit", "Other"])
        out_recorded = st.selectbox("Out Recorded", ["No", "Yes"])

        if st.button("Save Runner Event"):
            if runner == "-- Select --":
                st.warning("Choose a runner.")
            else:
                payload = {
                    "PitchID": int(current_pid),
                    "RunnerID": player_map[runner],
                    "StartBase": int(start_base),
                    "EndBase": None if end_base == 0 else int(end_base),
                    "EventType": event_type,
                    "OutRecorded": (out_recorded == "Yes"),
                }
                try:
                    resp = supabase.table("RunnerEvents").insert(payload).execute()
                    if resp.data:
                        arrow = f"{start_base}→{end_base if end_base != 0 else '-'}"
                        add_to_summary(f"Runner {runner}: {event_type} | {arrow} | Out={payload['OutRecorded']}")
                        st.success("Runner event saved.")
                    else:
                        st.error("Failed to save runner event.")
                except Exception as e:
                    st.error(f"Insert failed: {e}")

# ---------------------------------------------------------
# 6 — Running Summary
# ---------------------------------------------------------
st.markdown("---")
st.subheader("Running Summary")
if st.session_state["event_log"]:
    for line in st.session_state["event_log"]:
        st.write("• " + line)
else:
    st.caption("No events yet. Pitch, record a runner event, or finish an at-bat to see entries here.")
